"""로그인 회원 스키마(마이그레이션 0015)·DB 권한 경계·관리자 스크립트 임시 DB 통합 시험 (DEC-067).

실제 PostgreSQL에 `alembic upgrade head`를 적용한 임시 DB에서 확인한다. `auth_service` 역할과 접속 주소(`PUBLIC_API_AUTH_DATABASE_URL`)가
없으면 그 부분은 통과로 세지 않고 건너뛴다.
"""

# ruff: noqa: E501
from __future__ import annotations

import io
import os
import shlex
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from scripts import manage_users as mu
from shared.auth.passwords import hash_password, verify_password
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, run_alembic, temp_database

REPO_ROOT = Path(__file__).resolve().parents[2]
STRONG = "Tr0ub4dor&3-horse-staple"
STRONG2 = "Correct-Horse-Battery-9!"


def _auth_url(db: TempDb) -> URL:
    raw = os.environ.get("PUBLIC_API_AUTH_DATABASE_URL")
    if not raw:
        pytest.skip("PUBLIC_API_AUTH_DATABASE_URL 미설정 — auth_service 권한 시험을 건너뜀(통과로 세지 않음)")
    return make_url(raw).set(database=db.name)


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _engine(url: URL):
    return create_engine(TempDb.render(url))


def _run(url: URL, sql: str, **params):
    eng = _engine(url)
    try:
        with eng.begin() as conn:
            result = conn.execute(text(sql), params)
            return result.fetchall() if result.returns_rows else result.rowcount
    finally:
        eng.dispose()


def _denied(url: URL, sql: str, **params) -> bool:
    """권한 부족(InsufficientPrivilege)으로 거부되면 True. 다른 이유의 오류는 시험 실패."""
    try:
        _run(url, sql, **params)
    except (ProgrammingError, DBAPIError) as exc:
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        assert sqlstate == "42501", f"권한 거부가 아닌 오류: {sqlstate} {exc}"
        return True
    return False


@pytest.fixture()
def clean(db: TempDb):
    _run(db.migrator_url, "DELETE FROM auth.login_audit")
    _run(db.migrator_url, "DELETE FROM auth.app_users")
    yield


def _insert_user(db: TempDb, username="kim", name="김철수", password_hash="h"):
    _run(
        db.migrator_url,
        "INSERT INTO auth.app_users (username, display_name, password_hash) VALUES (:u, :n, :h)",
        u=username,
        n=name,
        h=password_hash,
    )


# ------------------------------------------------------------------ 구조·제약
def test_schema_and_tables_exist(db):
    rows = _run(
        db.migrator_url,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'auth' ORDER BY 1",
    )
    assert [r[0] for r in rows] == ["app_users", "login_audit"]
    assert _run(db.migrator_url, "SELECT count(*) FROM auth.app_users")[0][0] == 0
    cols = {r[0] for r in _run(db.migrator_url, "SELECT column_name FROM information_schema.columns WHERE table_schema='auth' AND table_name='app_users'")}
    assert {"user_id", "username", "display_name", "password_hash", "is_active", "failed_attempts", "lockout_level", "locked_until", "last_login_at"} <= cols
    assert "password" not in cols and "email" not in cols  # 원문·이메일은 저장하지 않는다


@pytest.mark.parametrize("username", ["Admin", "ab", "a b", "a" * 33, "_abc", "kim!", "김철수", ""])
def test_username_check_constraint_rejects(db, clean, username):
    with pytest.raises(IntegrityError):
        _insert_user(db, username=username)


def test_username_unique_and_valid_boundaries(db, clean):
    _insert_user(db, username="abc")
    _insert_user(db, username="a" * 32)
    with pytest.raises(IntegrityError):
        _insert_user(db, username="abc")


@pytest.mark.parametrize("name", ["", "가" * 41])
def test_display_name_length_constraint(db, clean, name):
    with pytest.raises(IntegrityError):
        _insert_user(db, name=name)


def test_counter_and_audit_constraints(db, clean):
    _insert_user(db)
    with pytest.raises(IntegrityError):
        _run(db.migrator_url, "UPDATE auth.app_users SET failed_attempts = -1")
    with pytest.raises(IntegrityError):
        _run(db.migrator_url, "INSERT INTO auth.login_audit (result) VALUES ('MAYBE')")
    with pytest.raises(IntegrityError):
        _run(db.migrator_url, "INSERT INTO auth.login_audit (result, username_attempted) VALUES ('FAIL', :u)", u="x" * 65)


def test_deleting_user_keeps_audit_rows_with_null_user(db, clean):
    _insert_user(db)
    uid = _run(db.migrator_url, "SELECT user_id FROM auth.app_users WHERE username='kim'")[0][0]
    _run(db.migrator_url, "INSERT INTO auth.login_audit (user_id, username_attempted, result) VALUES (:i, 'kim', 'SUCCESS')", i=uid)
    _run(db.migrator_url, "DELETE FROM auth.app_users WHERE username='kim'")
    rows = _run(db.migrator_url, "SELECT user_id, username_attempted FROM auth.login_audit")
    assert rows == [(None, "kim")]


# ------------------------------------------------------------------ 권한 경계(최소 권한)
def test_auth_service_can_do_only_what_the_design_allows(db, clean):
    url = _auth_url(db)
    _insert_user(db)
    assert _run(url, "SELECT username FROM auth.app_users") == [("kim",)]
    assert _run(url, "UPDATE auth.app_users SET failed_attempts = 3, lockout_level = 1, locked_until = now(), last_login_at = now(), updated_at = now()") == 1
    assert _run(url, "UPDATE auth.app_users SET password_hash = 'rehashed'") == 1  # 재해시 갱신용
    assert _run(url, "INSERT INTO auth.login_audit (username_attempted, result, client_ip) VALUES ('kim', 'FAIL', '203.0.113.x')") == 1
    # 허용하지 않은 것
    for sql in (
        "UPDATE auth.app_users SET username = 'other'",
        "UPDATE auth.app_users SET is_active = false",
        "UPDATE auth.app_users SET display_name = 'x'",
        "INSERT INTO auth.app_users (username, display_name, password_hash) VALUES ('new', 'n', 'h')",
        "DELETE FROM auth.app_users",
        "SELECT * FROM auth.login_audit",
        "UPDATE auth.login_audit SET result = 'SUCCESS'",
        "DELETE FROM auth.login_audit",
        "SELECT count(*) FROM public_serving.stock_master",
        "SELECT count(*) FROM raw_internal.raw_ohlcv",
        "SELECT count(*) FROM reference.market_calendar",
        "CREATE TABLE auth.evil (x int)",
        "CREATE TABLE public.evil (x int)",
    ):
        assert _denied(url, sql), f"auth_service에게 허용되면 안 되는 작업이 허용됨: {sql}"


@pytest.mark.parametrize("role_url_attr", ["api_url", "batch_url"])
def test_other_app_roles_have_no_access_to_auth_schema(db, clean, role_url_attr):
    url = getattr(db, role_url_attr)
    _insert_user(db)
    assert _denied(url, "SELECT * FROM auth.app_users")
    assert _denied(url, "SELECT password_hash FROM auth.app_users")
    assert _denied(url, "SELECT * FROM auth.login_audit")
    assert _denied(url, "INSERT INTO auth.login_audit (result) VALUES ('FAIL')")


def test_existing_api_service_access_is_unchanged(db):
    """기존 데이터 조회 권한(읽기 전용)은 이번 변경으로 달라지지 않았다."""
    assert _run(db.api_url, "SELECT count(*) FROM public_serving.stock_master")[0][0] == 0
    assert _denied(db.api_url, "SELECT count(*) FROM raw_internal.raw_ohlcv")
    assert _denied(db.api_url, "CREATE TABLE public.evil (x int)")


def test_check_command_passes_on_correct_setup(db, capsys):
    _auth_url(db)  # 없으면 건너뜀
    eng = _engine(db.migrator_url)
    try:
        assert mu.main(["check"], engine=eng) == 0
    finally:
        eng.dispose()
    out = capsys.readouterr().out
    assert "FAIL" not in out and out.count("OK") >= 10


def test_check_command_detects_a_privilege_violation(db, capsys):
    _auth_url(db)
    _run(db.migrator_url, "GRANT DELETE ON auth.app_users TO auth_service")
    eng = _engine(db.migrator_url)
    try:
        assert mu.main(["check"], engine=eng) == 1
    finally:
        eng.dispose()
        _run(db.migrator_url, "REVOKE DELETE ON auth.app_users FROM auth_service")
    out = capsys.readouterr().out
    assert "FAIL" in out and "app_users DELETE" in out


# ------------------------------------------------------------------ 마이그레이션 되돌리기·역할 없음
def test_downgrade_and_upgrade_cycle(db):
    assert run_alembic(db, "downgrade", "0014").returncode == 0
    assert _run(db.migrator_url, "SELECT count(*) FROM information_schema.schemata WHERE schema_name='auth'")[0][0] == 0
    assert _run(db.migrator_url, "SELECT count(*) FROM public_serving.stock_master")[0][0] == 0  # 기존 스키마는 그대로
    assert run_alembic(db, "upgrade", "head").returncode == 0
    assert _run(db.migrator_url, "SELECT count(*) FROM information_schema.tables WHERE table_schema='auth'")[0][0] == 2


def _admin_psql(*extra: str) -> list[str]:
    custom = os.environ.get("TEST_PG_ADMIN_PSQL", "").strip()
    if not custom:
        pytest.skip("TEST_PG_ADMIN_PSQL 미설정")
    return [*shlex.split(custom), *extra]


def test_migration_succeeds_without_auth_service_role_then_setup_sql_applies_grants(capsys):
    """PC 로컬 DB처럼 `auth_service`가 없어도 마이그레이션이 실패하지 않아야 하고, 이후 neon-auth-setup.sql이 권한을 채운다."""
    _auth_url_probe = os.environ.get("PUBLIC_API_AUTH_DATABASE_URL")
    if not _auth_url_probe:
        pytest.skip("PUBLIC_API_AUTH_DATABASE_URL 미설정")
    renamed = False
    try:
        subprocess.run(_admin_psql("-v", "ON_ERROR_STOP=1", "-c", "ALTER ROLE auth_service RENAME TO auth_service_tmp"), check=True, capture_output=True, text=True)
        renamed = True
        with temp_database() as tdb:  # 내부에서 alembic upgrade head 실행 — 역할이 없어도 성공해야 한다
            assert _run(tdb.migrator_url, "SELECT count(*) FROM information_schema.tables WHERE table_schema='auth'")[0][0] == 2
            acl = _run(tdb.migrator_url, "SELECT relacl::text FROM pg_class WHERE oid = 'auth.app_users'::regclass")[0][0]
            assert acl is None or "auth_service" not in acl
            # 역할을 되돌리고(다시 만든 것과 같음) 설정 SQL을 실행한다
            subprocess.run(_admin_psql("-v", "ON_ERROR_STOP=1", "-c", "ALTER ROLE auth_service_tmp RENAME TO auth_service"), check=True, capture_output=True, text=True)
            renamed = False
            setup = subprocess.run(
                _admin_psql("-d", tdb.name, "-v", "ON_ERROR_STOP=1", "-v", "auth=authpw", "-f", str(REPO_ROOT / "deploy/render/neon-auth-setup.sql")),
                capture_output=True, text=True,
            )
            assert setup.returncode == 0, setup.stderr[-400:]
            eng = _engine(tdb.migrator_url)
            try:
                assert mu.main(["check"], engine=eng) == 0
            finally:
                eng.dispose()
            # 설정 SQL은 여러 번 실행해도 안전하다
            again = subprocess.run(
                _admin_psql("-d", tdb.name, "-v", "ON_ERROR_STOP=1", "-v", "auth=authpw", "-f", str(REPO_ROOT / "deploy/render/neon-auth-setup.sql")),
                capture_output=True, text=True,
            )
            assert again.returncode == 0, again.stderr[-400:]
    finally:
        if renamed:
            subprocess.run(_admin_psql("-c", "ALTER ROLE auth_service_tmp RENAME TO auth_service"), capture_output=True, text=True)


# ------------------------------------------------------------------ 관리자 스크립트
@pytest.fixture()
def cli(db, clean, monkeypatch, capsys):
    eng = _engine(db.migrator_url)

    def run(*argv: str, stdin: str | None = None, typed: str | None = None) -> tuple[int, str, str]:
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        if typed is not None:
            monkeypatch.setattr("builtins.input", lambda _prompt="": typed)
        code = mu.main(list(argv), engine=eng)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    yield run
    eng.dispose()


def _row(db: TempDb, username: str):
    rows = _run(db.migrator_url, "SELECT password_hash, is_active, failed_attempts, lockout_level, locked_until, display_name FROM auth.app_users WHERE username = :u", u=username)
    return rows[0] if rows else None


def test_cli_add_stores_argon2id_hash_and_never_echoes_secrets(db, cli):
    code, out, err = cli("add", "Kim", "--name", "김철수", "--password-stdin", stdin=STRONG + "\n")
    assert code == 0 and "kim" in out
    stored = _row(db, "kim")
    assert stored[0].startswith("$argon2id$") and verify_password(stored[0], STRONG)
    assert stored[1] is True and stored[5] == "김철수"
    assert STRONG not in out + err and stored[0] not in out + err


def test_cli_add_duplicate_fails_without_changing_the_first(db, cli):
    assert cli("add", "kim", "--name", "김", "--password-stdin", stdin=STRONG + "\n")[0] == 0
    first = _row(db, "kim")[0]
    code, _out, err = cli("add", "KIM", "--name", "다른 사람", "--password-stdin", stdin=STRONG2 + "\n")
    assert code == 1 and "이미 있는 아이디" in err
    assert _row(db, "kim")[0] == first


@pytest.mark.parametrize("password", ["short", "password1234", "123456789012", "kim.chulsoo.2026"])
def test_cli_rejects_weak_passwords_and_inserts_nothing(db, cli, password):
    code, out, err = cli("add", "kim.chulsoo.2026", "--name", "김", "--password-stdin", stdin=password + "\n")
    assert code == 1 and "[규칙 위반]" in err
    assert _row(db, "kim.chulsoo.2026") is None
    assert password not in out + err


def test_cli_rejects_bad_username_and_name(db, cli):
    assert cli("add", "Ab", "--name", "김", "--password-stdin", stdin=STRONG + "\n")[0] == 1
    assert cli("add", "kim", "--name", "   ", "--password-stdin", stdin=STRONG + "\n")[0] == 1
    assert _run(db.migrator_url, "SELECT count(*) FROM auth.app_users")[0][0] == 0


def test_cli_set_password_changes_hash_and_clears_lock(db, cli):
    cli("add", "kim", "--name", "김", "--password-stdin", stdin=STRONG + "\n")
    _run(db.migrator_url, "UPDATE auth.app_users SET failed_attempts = 5, lockout_level = 2, locked_until = now() + interval '1 hour'")
    old = _row(db, "kim")[0]
    code, _o, _e = cli("set-password", "kim", "--password-stdin", stdin=STRONG2 + "\n")
    assert code == 0
    row = _row(db, "kim")
    assert row[0] != old and verify_password(row[0], STRONG2) and not verify_password(row[0], STRONG)
    assert row[2] == 0 and row[3] == 0 and row[4] is None
    assert cli("set-password", "nobody", "--password-stdin", stdin=STRONG2 + "\n")[0] == 1


def test_cli_disable_enable_unlock(db, cli):
    cli("add", "kim", "--name", "김", "--password-stdin", stdin=STRONG + "\n")
    assert cli("disable", "kim")[0] == 0 and _row(db, "kim")[1] is False
    _run(db.migrator_url, "UPDATE auth.app_users SET failed_attempts = 4, locked_until = now() + interval '1 hour'")
    assert cli("enable", "kim")[0] == 0
    row = _row(db, "kim")
    assert row[1] is True and row[2] == 0 and row[4] is None
    _run(db.migrator_url, "UPDATE auth.app_users SET failed_attempts = 4, lockout_level = 1, locked_until = now() + interval '1 hour'")
    assert cli("unlock", "kim")[0] == 0 and _row(db, "kim")[4] is None
    assert cli("disable", "nobody")[0] == 1


def test_cli_delete_needs_confirmation(db, cli):
    cli("add", "kim", "--name", "김", "--password-stdin", stdin=STRONG + "\n")
    code, _o, err = cli("delete", "kim", typed="lee")
    assert code == 1 and _row(db, "kim") is not None
    assert cli("delete", "kim", typed="KIM")[0] == 0 and _row(db, "kim") is None
    cli("add", "park", "--name", "박", "--password-stdin", stdin=STRONG + "\n")
    assert cli("delete", "park", "--yes")[0] == 0 and _row(db, "park") is None


def test_cli_list_and_audit_never_show_hashes(db, cli):
    cli("add", "kim", "--name", "김철수", "--password-stdin", stdin=STRONG + "\n")
    cli("add", "lee", "--name", "이영희", "--password-stdin", stdin=STRONG2 + "\n")
    cli("disable", "lee")
    code, out, _e = cli("list")
    assert code == 0 and "kim" in out and "김철수" in out and "비활성" in out and "총 2명" in out
    assert "$argon2" not in out and STRONG not in out
    _run(db.migrator_url, "INSERT INTO auth.login_audit (username_attempted, result, client_ip) VALUES ('kim', 'FAIL', '203.0.113.x')")
    code, out, _e = cli("audit", "--limit", "5")
    assert code == 0 and "FAIL" in out and "203.0.113.x" in out


def test_cli_purge_audit_deletes_only_old_rows(db, cli):
    _run(db.migrator_url, "INSERT INTO auth.login_audit (username_attempted, result, occurred_at) VALUES ('old', 'FAIL', now() - interval '91 days')")
    _run(db.migrator_url, "INSERT INTO auth.login_audit (username_attempted, result, occurred_at) VALUES ('edge', 'FAIL', now() - interval '89 days')")
    _run(db.migrator_url, "INSERT INTO auth.login_audit (username_attempted, result) VALUES ('new', 'SUCCESS')")
    assert cli("purge-audit", "--days", "0")[0] == 1
    code, out, _e = cli("purge-audit")
    assert code == 0 and "1건" in out
    code, out, _e = cli("audit", "--limit", "10")
    assert "old" not in out and "edge" in out and "new" in out


def test_cli_db_errors_do_not_leak_connection_strings(monkeypatch, capsys):
    bad = create_engine("postgresql+psycopg://user:SuperSecretPw@127.0.0.1:1/nodb", connect_args={"connect_timeout": 1})
    code = mu.main(["list"], engine=bad)
    out = capsys.readouterr()
    bad.dispose()
    assert code == 1 and "SuperSecretPw" not in out.out + out.err and "[DB 오류]" in out.err


def test_cli_requires_connection_setting(monkeypatch, capsys):
    monkeypatch.delenv(mu.URL_ENV, raising=False)
    monkeypatch.delenv(mu.FALLBACK_URL_ENV, raising=False)
    with pytest.raises(SystemExit) as exc:
        mu.main(["list"])
    assert "설정 오류" in str(exc.value)


def test_hash_helper_matches_cli_policy():
    """CLI와 서버가 같은 규칙(shared.auth.passwords)을 쓴다."""
    assert verify_password(hash_password(STRONG), STRONG)
