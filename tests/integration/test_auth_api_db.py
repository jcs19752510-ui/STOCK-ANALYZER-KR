# ruff: noqa: E501
"""로그인 내부 API(웹 서버 전용) 실제 PostgreSQL 통합 시험 (DEC-067, 설계서 §4·§7).

임시 DB(`alembic upgrade head` 적용)에서 `auth_service` 계정으로 실제 인증 로직·잠금·기록·권한을 확인한다.
`PUBLIC_API_AUTH_DATABASE_URL`이 없으면 건너뛴다(통과로 세지 않음).
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from services.public_api.auth import service as auth_service
from services.public_api.auth import throttle
from services.public_api.auth.service import authenticate
from services.public_api.db.auth_session import get_auth_db
from services.public_api.rate_limit import reset_rate_limit_state
from shared.auth.passwords import hash_password, needs_rehash, verify_password
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

TOKEN = "k" * 48
GOOD = "Tr0ub4dor&3-horse-staple"
HASH = hash_password(GOOD)
GENERIC_MESSAGE = "아이디 또는 비밀번호가 올바르지 않습니다."


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    if not os.environ.get("PUBLIC_API_AUTH_DATABASE_URL"):
        pytest.skip("PUBLIC_API_AUTH_DATABASE_URL 미설정 — 건너뜀(통과로 세지 않음)")
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _admin(db: TempDb, sql: str, **params):
    eng = create_engine(TempDb.render(db.migrator_url))
    try:
        with eng.begin() as conn:
            result = conn.execute(text(sql), params)
            return result.fetchall() if result.returns_rows else result.rowcount
    finally:
        eng.dispose()


def _add_user(db: TempDb, username: str, name: str = "김철수", *, active: bool = True, password_hash: str = HASH):
    _admin(
        db,
        "INSERT INTO auth.app_users (username, display_name, password_hash, is_active) VALUES (:u, :n, :h, :a)",
        u=username,
        n=name,
        h=password_hash,
        a=active,
    )


def _row(db: TempDb, username: str):
    return _admin(
        db,
        "SELECT failed_attempts, lockout_level, locked_until IS NOT NULL, last_login_at IS NOT NULL, password_hash, "
        "COALESCE(EXTRACT(EPOCH FROM (locked_until - now())), 0) FROM auth.app_users WHERE username = :u",
        u=username,
    )[0]


def _audit(db: TempDb):
    return _admin(db, "SELECT username_attempted, result, client_ip, user_id IS NOT NULL FROM auth.login_audit ORDER BY audit_id")


@pytest.fixture()
def api(db: TempDb, monkeypatch) -> Iterator[TestClient]:
    from services.public_api.main import app

    auth_url = make_url(os.environ["PUBLIC_API_AUTH_DATABASE_URL"]).set(database=db.name)
    engine = create_engine(TempDb.render(auth_url), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override() -> Iterator:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_auth_db] = override
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv("PUBLIC_API_AUTH_DATABASE_URL", TempDb.render(auth_url))
    monkeypatch.setenv("PUBLIC_API_LOGIN_RATE_PER_MINUTE", "600")
    monkeypatch.setenv("PUBLIC_API_LOGIN_GLOBAL_PER_MINUTE", "3000")
    reset_rate_limit_state()
    throttle.reset_login_throttle()
    _admin(db, "DELETE FROM auth.login_audit")
    _admin(db, "DELETE FROM auth.app_users")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_auth_db, None)
        engine.dispose()
        reset_rate_limit_state()
        throttle.reset_login_throttle()


def _login(client: TestClient, username: str, password: str, *, ip: str | None = None, token: str | None = TOKEN):
    headers = {}
    if token is not None:
        headers["X-Internal-Token"] = token
    if ip:
        headers["X-End-User-IP"] = ip
    return client.post("/api/v1/internal/auth/login", json={"username": username, "password": password}, headers=headers)


def _error_shape(response):
    body = response.json()
    return response.status_code, body["error"]["code"], body["error"]["message"], body["data"]


# ------------------------------------------------------------------ 로그인 성공
def test_login_success_returns_member_info_and_records_it(db, api):
    _add_user(db, "kim", "김철수")
    r = _login(api, " KIM ", GOOD, ip="203.0.113.77")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["username"] == "kim" and data["display_name"] == "김철수" and len(data["user_id"]) == 36
    assert set(data) == {"user_id", "username", "display_name"}  # 해시·상태 등은 응답에 없다
    assert GOOD not in r.text and HASH not in r.text
    failed, level, locked, logged_in, _hash, _secs = _row(db, "kim")
    assert (failed, level, locked, logged_in) == (0, 0, False, True)
    assert _audit(db) == [("kim", "SUCCESS", "203.0.113.x", True)]  # 접속 주소는 마지막 옥텟이 가려진다
    assert r.headers["cache-control"] == "no-store"


def test_audit_ip_is_null_for_missing_or_invalid_header(db, api):
    _add_user(db, "kim")
    _login(api, "kim", GOOD)
    _login(api, "kim", GOOD, ip="not-an-ip")
    assert [row[2] for row in _audit(db)] == [None, None]


# ------------------------------------------------------------------ 실패는 모두 같은 모양
def test_all_failure_reasons_look_identical_to_the_caller(db, api):
    _add_user(db, "kim")
    _add_user(db, "off", active=False)
    _add_user(db, "lock")
    _admin(db, "UPDATE auth.app_users SET locked_until = now() + interval '1 hour' WHERE username='lock'")
    cases = [
        ("kim", "wrong-password-xyz"),  # 비밀번호 틀림
        ("nobody", GOOD),  # 없는 아이디
        ("Ab", GOOD),  # 형식이 틀린 아이디
        ("off", GOOD),  # 비활성 + 맞는 비밀번호
        ("lock", GOOD),  # 잠김 + 맞는 비밀번호
        ("' OR '1'='1", GOOD),
        ("kim; DROP TABLE auth.app_users;--", GOOD),
    ]
    shapes = [_error_shape(_login(api, u, p)) for u, p in cases]
    assert all(s == shapes[0] for s in shapes), shapes
    assert shapes[0] == (401, "INVALID_CREDENTIALS", GENERIC_MESSAGE, None)
    # 이유는 기록에만 남는다
    assert [a[1] for a in _audit(db)] == ["FAIL", "FAIL", "FAIL", "INACTIVE", "LOCKED", "FAIL", "FAIL"]
    assert _admin(db, "SELECT count(*) FROM auth.app_users")[0][0] == 3  # 주입 시도가 아무 영향도 주지 않았다


def test_unknown_inactive_and_locked_still_do_a_full_cost_hash(db, api, monkeypatch):
    _add_user(db, "kim")
    _add_user(db, "off", active=False)
    _add_user(db, "lock")
    _admin(db, "UPDATE auth.app_users SET locked_until = now() + interval '1 hour' WHERE username='lock'")
    calls = {"dummy": 0, "verify": 0}
    real_dummy, real_verify = auth_service.dummy_verify, auth_service.verify_password
    monkeypatch.setattr(auth_service, "dummy_verify", lambda p: (calls.__setitem__("dummy", calls["dummy"] + 1), real_dummy(p))[1])
    monkeypatch.setattr(auth_service, "verify_password", lambda h, p: (calls.__setitem__("verify", calls["verify"] + 1), real_verify(h, p))[1])
    for user in ("nobody", "off", "lock"):
        _login(api, user, GOOD)
    assert calls == {"dummy": 3, "verify": 0}
    _login(api, "kim", "wrong-password-xyz")
    assert calls["verify"] == 1


# ------------------------------------------------------------------ 잠금
def test_five_failures_lock_the_account_even_for_the_right_password(db, api):
    _add_user(db, "kim")
    for _ in range(4):
        assert _login(api, "kim", "wrong-password-xyz").status_code == 401
    failed, level, locked, _l, _h, _s = _row(db, "kim")
    assert (failed, level, locked) == (4, 0, False)
    assert _login(api, "kim", "wrong-password-xyz").status_code == 401  # 5번째 → 잠김
    failed, level, locked, _l, _h, secs = _row(db, "kim")
    assert (failed, level, locked) == (0, 1, True) and 14 * 60 < secs <= 15 * 60
    assert _login(api, "kim", GOOD).status_code == 401  # 잠긴 동안은 맞는 비밀번호도 거부
    assert _audit(db)[-1][1] == "LOCKED"
    assert _row(db, "kim")[3] is False  # 마지막 로그인 시각이 갱신되지 않았다


def test_lock_expires_then_login_works_and_resets_the_level(db, api):
    _add_user(db, "kim")
    _admin(db, "UPDATE auth.app_users SET failed_attempts = 0, lockout_level = 2, locked_until = now() - interval '1 second' WHERE username='kim'")
    assert _login(api, "kim", GOOD).status_code == 200
    failed, level, locked, logged_in, _h, _s = _row(db, "kim")
    assert (failed, level, locked, logged_in) == (0, 0, False, True)


@pytest.mark.parametrize("level,expected_minutes", [(0, 15), (1, 30), (2, 60), (5, 480), (7, 1440), (12, 1440)])
def test_lock_duration_doubles_and_is_capped_at_24_hours(db, api, level, expected_minutes):
    _add_user(db, "kim")
    _admin(db, "UPDATE auth.app_users SET failed_attempts = 4, lockout_level = :l WHERE username='kim'", l=level)
    assert _login(api, "kim", "wrong-password-xyz").status_code == 401
    secs = _row(db, "kim")[5]
    assert (expected_minutes - 1) * 60 < secs <= expected_minutes * 60 + 1, (level, secs)
    assert _row(db, "kim")[1] == level + 1


def test_success_resets_the_failure_counter(db, api):
    _add_user(db, "kim")
    for _ in range(3):
        _login(api, "kim", "wrong-password-xyz")
    assert _row(db, "kim")[0] == 3
    assert _login(api, "kim", GOOD).status_code == 200
    assert _row(db, "kim")[0] == 0


def test_account_locked_while_password_is_being_checked_cannot_log_in(db, api, monkeypatch):
    """검증(느린 계산) 중에 잠긴 계정이 맞는 비밀번호로 통과하는 경주 상태를 막는다."""
    _add_user(db, "kim")
    real_verify = auth_service.verify_password

    def verify_then_lock(h, p):
        ok = real_verify(h, p)
        _admin(db, "UPDATE auth.app_users SET locked_until = now() + interval '1 hour' WHERE username='kim'")
        return ok

    monkeypatch.setattr(auth_service, "verify_password", verify_then_lock)
    r = _login(api, "kim", GOOD)
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert _audit(db)[-1][1] == "LOCKED" and _row(db, "kim")[3] is False


def test_account_disabled_while_password_is_being_checked_cannot_log_in(db, api, monkeypatch):
    _add_user(db, "kim")
    real_verify = auth_service.verify_password

    def verify_then_disable(h, p):
        ok = real_verify(h, p)
        _admin(db, "UPDATE auth.app_users SET is_active = false WHERE username='kim'")
        return ok

    monkeypatch.setattr(auth_service, "verify_password", verify_then_disable)
    assert _login(api, "kim", GOOD).status_code == 401


def test_parallel_wrong_attempts_keep_the_counters_consistent(db, api):
    """동시에 틀려도 실패 횟수가 유실되지 않는다: 잠금 단계×5 + 현재 횟수 = 기록된 실패 횟수."""
    _add_user(db, "kim")
    auth_url = make_url(os.environ["PUBLIC_API_AUTH_DATABASE_URL"]).set(database=db.name)
    engine = create_engine(TempDb.render(auth_url), pool_size=8)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    barrier = threading.Barrier(8)

    def attempt(_i):
        s = factory()
        try:
            barrier.wait(timeout=10)
            return authenticate(s, "kim", "wrong-password-xyz", None).ok
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    engine.dispose()
    assert results == [False] * 8
    failed, level, locked, _l, _h, _s = _row(db, "kim")
    recorded = _admin(db, "SELECT count(*) FROM auth.login_audit WHERE result = 'FAIL'")[0][0]
    assert level * 5 + failed == recorded
    assert locked is (level > 0)


# ------------------------------------------------------------------ 해시 갱신·비밀 비노출
def test_old_parameter_hash_is_upgraded_on_successful_login(db, api):
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID).hash(GOOD)
    _add_user(db, "kim", password_hash=old)
    assert needs_rehash(old)
    assert _login(api, "kim", GOOD).status_code == 200
    new = _row(db, "kim")[4]
    assert new != old and not needs_rehash(new) and verify_password(new, GOOD)


def test_policy_tightening_does_not_lock_out_existing_members(db, api):
    """정책보다 약해도(예: 11자) 이미 만든 비밀번호로 로그인은 되어야 한다(새 비밀번호를 받는 경로만 정책을 검사한다)."""
    weak_but_valid_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID).hash("short-pw1")
    _add_user(db, "kim", password_hash=weak_but_valid_hash)
    assert _login(api, "kim", "short-pw1").status_code == 200


def test_passwords_and_hashes_never_appear_in_logs_or_audit(db, api, caplog):
    _add_user(db, "kim")
    caplog.set_level(logging.DEBUG)
    secret_wrong = "Wr0ng-Secret-Pass-123"
    _login(api, "kim", secret_wrong)
    _login(api, "kim", GOOD)
    _login(api, "nobody", secret_wrong)
    blob = caplog.text + str(_audit(db))
    for secret in (secret_wrong, GOOD, HASH, TOKEN):
        assert secret not in blob


def test_validation_errors_do_not_echo_the_submitted_values(db, api):
    secret = "Echo-Me-Please-123456" + "x" * 1100
    r = api.post("/api/v1/internal/auth/login", json={"username": "kim", "password": secret}, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 400 and secret[:20] not in r.text  # 앱 공통 검증 오류 처리(400 INVALID_PARAMETER)
    for body in ({}, {"username": "kim"}, {"username": "", "password": "x"}, {"username": "kim", "password": "x", "extra": 1}, {"username": "k" * 65, "password": "x"}):
        r = api.post("/api/v1/internal/auth/login", json=body, headers={"X-Internal-Token": TOKEN})
        assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PARAMETER", body


# ------------------------------------------------------------------ 내부 토큰(스위치와 무관하게 항상)
def test_internal_endpoints_always_require_the_token(db, api):
    _add_user(db, "kim")
    for token in (None, "", "wrong", TOKEN[:-1], TOKEN + "x"):
        r = _login(api, "kim", GOOD, token=token)
        assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED", token
    assert api.get("/api/v1/internal/members").status_code == 401
    assert api.post("/api/v1/internal/auth/session-check", json={"user_id": "11111111-1111-4111-8111-111111111111"}).status_code == 401
    assert _audit(db) == []  # 토큰이 틀린 호출은 인증 로직에 닿지도 않는다


def test_internal_endpoints_are_disabled_when_not_configured(db, api, monkeypatch):
    monkeypatch.delenv("PUBLIC_API_AUTH_DATABASE_URL")
    r = _login(api, "kim", GOOD)
    assert r.status_code == 404 and r.json()["error"]["code"] == "FEATURE_DISABLED"
    monkeypatch.setenv("PUBLIC_API_AUTH_DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:1/z")
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", "")
    assert api.get("/api/v1/internal/members").status_code == 404


# ------------------------------------------------------------------ 로그인 시도 제한
def test_login_rate_limit_applies_before_any_credential_check(db, api, monkeypatch):
    _add_user(db, "kim")
    monkeypatch.setenv("PUBLIC_API_LOGIN_RATE_PER_MINUTE", "3")
    codes = [_login(api, "kim", "wrong-password-xyz", ip="203.0.113.9").status_code for _ in range(3)]
    assert codes == [401, 401, 401]
    r = _login(api, "kim", GOOD, ip="203.0.113.9")  # 맞는 비밀번호여도 제한이 먼저
    assert r.status_code == 429 and r.json()["error"]["code"] == "LOGIN_RATE_LIMITED"
    assert len(_audit(db)) == 3  # 제한된 시도는 인증하지 않았으므로 기록도 늘지 않는다
    assert _login(api, "kim", GOOD, ip="203.0.113.10").status_code == 200  # 다른 접속 주소는 독립


# ------------------------------------------------------------------ 세션 확인·회원 목록
def test_session_check_reports_active_state(db, api):
    _add_user(db, "kim", "김철수")
    _add_user(db, "off", "비활성", active=False)
    uid = _admin(db, "SELECT user_id::text FROM auth.app_users WHERE username='kim'")[0][0]
    off = _admin(db, "SELECT user_id::text FROM auth.app_users WHERE username='off'")[0][0]
    h = {"X-Internal-Token": TOKEN}
    ok = api.post("/api/v1/internal/auth/session-check", json={"user_id": uid}, headers=h).json()["data"]
    assert ok == {"active": True, "username": "kim", "display_name": "김철수"}
    for gone in (off, "99999999-9999-4999-8999-999999999999"):
        assert api.post("/api/v1/internal/auth/session-check", json={"user_id": gone}, headers=h).json()["data"] == {"active": False, "username": None, "display_name": None}
    for bad in ({"user_id": "x"}, {"user_id": uid, "extra": 1}, {}):
        assert api.post("/api/v1/internal/auth/session-check", json=bad, headers=h).status_code == 400


def test_members_lists_only_active_members_with_id_and_name_only(db, api):
    _add_user(db, "lee", "이영희")
    _add_user(db, "kim", "김철수")
    _add_user(db, "off", "퇴사자", active=False)
    _add_user(db, "evil", "<script>alert(1)</script>")
    r = api.get("/api/v1/internal/members", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    assert [m["username"] for m in data["items"]] == ["evil", "kim", "lee"]  # 이름 순
    assert all(set(m) == {"username", "display_name"} for m in data["items"])
    assert "off" not in r.text and "퇴사자" not in r.text and "argon2" not in r.text
    assert data["items"][0]["display_name"] == "<script>alert(1)</script>"  # 서버는 원문 그대로, 화면이 이스케이프한다


def test_members_empty_list(db, api):
    r = api.get("/api/v1/internal/members", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200 and r.json()["data"] == {"items": [], "total": 0}


def test_existing_data_api_paths_are_unaffected_by_the_new_router(db, api):
    assert api.get("/api/v1/live").status_code == 200
    assert api.get("/openapi.json").status_code == 200  # 스위치가 꺼진 기본 상태(로컬)에서는 문서가 그대로 있다
