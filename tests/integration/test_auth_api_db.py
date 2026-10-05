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


def _add_user(db: TempDb, username: str, name: str = "김철수", *, active: bool = True, password_hash: str = HASH, role: str = "user", pending: bool = False):
    """시험용 회원. 기본은 승인된 일반 회원(active면 활성, 아니면 사용 중지). pending=True면 승인 대기."""
    _admin(
        db,
        "INSERT INTO auth.app_users (username, display_name, password_hash, is_active, approved_at, role) "
        "VALUES (:u, :n, :h, :a, CASE WHEN :p THEN NULL ELSE now() END, :r)",
        u=username,
        n=name,
        h=password_hash,
        a=active and not pending,
        p=pending,
        r=role,
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
    _admin(db, "DELETE FROM auth.admin_audit")
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
    assert set(data) == {"user_id", "username", "display_name", "role", "session_id", "expires_in_seconds"}  # 해시·상태 등은 응답에 없다
    assert data["expires_in_seconds"] == 8 * 3600
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
    _add_user(db, "lock")
    _admin(db, "UPDATE auth.app_users SET locked_until = now() + interval '1 hour' WHERE username='lock'")
    cases = [
        ("kim", "wrong-password-xyz"),  # 비밀번호 틀림
        ("nobody", GOOD),  # 없는 아이디
        ("Ab", GOOD),  # 형식이 틀린 아이디
        ("lock", GOOD),  # 잠김 + 맞는 비밀번호
        ("' OR '1'='1", GOOD),
        ("kim; DROP TABLE auth.app_users;--", GOOD),
    ]
    shapes = [_error_shape(_login(api, u, p)) for u, p in cases]
    assert all(s == shapes[0] for s in shapes), shapes
    assert shapes[0] == (401, "INVALID_CREDENTIALS", GENERIC_MESSAGE, None)
    # 이유는 기록에만 남는다
    assert [a[1] for a in _audit(db)] == ["FAIL", "FAIL", "FAIL", "LOCKED", "FAIL", "FAIL"]
    assert _admin(db, "SELECT count(*) FROM auth.app_users")[0][0] == 2  # 주입 시도가 아무 영향도 주지 않았다


def test_unknown_inactive_and_locked_still_do_a_full_cost_hash(db, api, monkeypatch):
    _add_user(db, "kim")
    _add_user(db, "off", active=False)
    _add_user(db, "lock")
    _admin(db, "UPDATE auth.app_users SET locked_until = now() + interval '1 hour' WHERE username='lock'")
    calls = {"dummy": 0, "verify": 0}
    real_dummy, real_verify = auth_service.dummy_verify, auth_service.verify_password
    monkeypatch.setattr(auth_service, "dummy_verify", lambda p: (calls.__setitem__("dummy", calls["dummy"] + 1), real_dummy(p))[1])
    monkeypatch.setattr(auth_service, "verify_password", lambda h, p: (calls.__setitem__("verify", calls["verify"] + 1), real_verify(h, p))[1])
    for user in ("nobody", "lock"):  # 없는 아이디·잠긴 계정: 비밀번호를 보지 않고 같은 비용의 더미 계산
        _login(api, user, GOOD)
    assert calls == {"dummy": 2, "verify": 0}
    _login(api, "off", GOOD)  # 사용 중지(DEC-074): 실제 비밀번호 검증과 같은 비용(맞으면 이유를 알려 준다)
    assert calls == {"dummy": 2, "verify": 1}
    _login(api, "kim", "wrong-password-xyz")
    assert calls["verify"] == 2


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
    assert api.post("/api/v1/internal/auth/session-check", json={"user_id": "11111111-1111-4111-8111-111111111111", "session_id": "11111111-1111-4111-8111-111111111111"}).status_code == 401
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
    sid = _admin(db, "INSERT INTO auth.user_sessions (user_id, remember, expires_at) VALUES (CAST(:u AS uuid), false, now() + interval '8 hours') RETURNING session_id::text", u=uid)[0][0]
    off_sid = _admin(db, "INSERT INTO auth.user_sessions (user_id, remember, expires_at) VALUES (CAST(:u AS uuid), false, now() + interval '8 hours') RETURNING session_id::text", u=off)[0][0]
    ok = api.post("/api/v1/internal/auth/session-check", json={"user_id": uid, "session_id": sid}, headers=h).json()["data"]
    assert ok == {"active": True, "username": "kim", "display_name": "김철수", "role": "user"}
    for gone, gsid in ((off, off_sid), ("99999999-9999-4999-8999-999999999999", sid)):
        assert api.post("/api/v1/internal/auth/session-check", json={"user_id": gone, "session_id": gsid}, headers=h).json()["data"] == {"active": False, "username": None, "display_name": None, "role": None}
    for bad in ({"user_id": "x", "session_id": sid}, {"user_id": uid, "session_id": sid, "extra": 1}, {"user_id": uid}, {}):
        assert api.post("/api/v1/internal/auth/session-check", json=bad, headers=h).status_code == 400


def test_existing_data_api_paths_are_unaffected_by_the_new_router(db, api):
    assert api.get("/api/v1/live").status_code == 200
    assert api.get("/openapi.json").status_code == 200  # 스위치가 꺼진 기본 상태(로컬)에서는 문서가 그대로 있다


# ------------------------------------------------------------------ 서버 쪽 세션·로그인 상태 유지 30일 (DEC-070)
H = {"X-Internal-Token": TOKEN}
CHECK = "/api/v1/internal/auth/session-check"
LOGOUT = "/api/v1/internal/auth/logout"


def _login_data(api, remember=None, username="kim", password=GOOD):
    body = {"username": username, "password": password}
    if remember is not None:
        body["remember"] = remember
    r = api.post("/api/v1/internal/auth/login", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _check(api, uid, sid):
    return api.post(CHECK, json={"user_id": uid, "session_id": sid}, headers=H).json()["data"]["active"]


def _sess_row(db, sid):
    return _admin(db, "SELECT remember, EXTRACT(EPOCH FROM (expires_at - created_at))::int, last_check_at IS NOT NULL, revoked_at IS NOT NULL FROM auth.user_sessions WHERE session_id = CAST(:s AS uuid)", s=sid)[0]


def test_login_creates_server_session_with_8h_default_and_30d_when_remembered(db, api):
    _add_user(db, "kim")
    d8 = _login_data(api)
    d30 = _login_data(api, remember=True)
    dfalse = _login_data(api, remember=False)
    assert d8["expires_in_seconds"] == 8 * 3600 and dfalse["expires_in_seconds"] == 8 * 3600
    assert d30["expires_in_seconds"] == 30 * 24 * 3600
    assert len({d8["session_id"], d30["session_id"], dfalse["session_id"]}) == 3
    assert _sess_row(db, d8["session_id"])[:2] == (False, 8 * 3600)
    assert _sess_row(db, d30["session_id"])[:2] == (True, 30 * 24 * 3600)


def test_failed_login_creates_no_session(db, api):
    _add_user(db, "kim")
    assert _login(api, "kim", "wrong-password-xyz").status_code == 401
    api.post("/api/v1/internal/auth/login", json={"username": "kim", "password": GOOD, "remember": True}, headers={**H, "X-End-User-IP": "203.0.113.5"})
    assert _admin(db, "SELECT count(*) FROM auth.user_sessions")[0][0] == 1  # 성공한 한 건만


def test_remember_must_be_a_real_boolean_and_lifetime_cannot_be_chosen_by_caller(db, api):
    _add_user(db, "kim")
    for bad in ("true", "yes", 1, 0, "30d", None, [True], {"days": 3650}):
        r = api.post("/api/v1/internal/auth/login", json={"username": "kim", "password": GOOD, "remember": bad}, headers=H)
        assert r.status_code == 400, bad
    for extra in ({"expires_in": 99999999}, {"days": 3650}, {"session_id": "11111111-1111-4111-8111-111111111111"}):
        r = api.post("/api/v1/internal/auth/login", json={"username": "kim", "password": GOOD, **extra}, headers=H)
        assert r.status_code == 400, extra
    assert _admin(db, "SELECT count(*) FROM auth.user_sessions")[0][0] == 0


def test_session_check_requires_a_live_session_of_the_same_user(db, api):
    _add_user(db, "kim")
    _add_user(db, "lee", "이영희")
    kim = _login_data(api)
    lee = _login_data(api, username="lee")
    assert _check(api, kim["user_id"], kim["session_id"]) is True
    assert _sess_row(db, kim["session_id"])[2] is True  # 확인 시각 기록
    assert _check(api, kim["user_id"], lee["session_id"]) is False  # 남의 세션 id를 내 id로 제시
    assert _check(api, lee["user_id"], kim["session_id"]) is False
    assert _check(api, kim["user_id"], "99999999-9999-4999-8999-999999999999") is False  # 없는 세션
    assert _check(api, kim["user_id"], kim["session_id"].upper()) is True  # UUID 대소문자 무관


def test_session_check_rejects_revoked_expired_and_disabled(db, api):
    _add_user(db, "kim")
    d = _login_data(api, remember=True)
    uid, sid = d["user_id"], d["session_id"]
    # 만료(절대 만료: 지난 뒤에는 다시 확인해도 통과하지 않는다)
    _admin(db, "UPDATE auth.user_sessions SET created_at = now() - interval '31 days', expires_at = now() - interval '1 day' WHERE session_id = CAST(:s AS uuid)", s=sid)
    assert _check(api, uid, sid) is False
    d2 = _login_data(api, remember=True)
    assert _check(api, uid, d2["session_id"]) is True
    _admin(db, "UPDATE auth.app_users SET is_active = false WHERE username = 'kim'")  # 회원 비활성
    assert _check(api, uid, d2["session_id"]) is False
    _admin(db, "UPDATE auth.app_users SET is_active = true WHERE username = 'kim'")
    assert _check(api, uid, d2["session_id"]) is True  # 다시 활성이면 세션은 살아 있다(취소한 것이 아니므로)
    _admin(db, "UPDATE auth.user_sessions SET revoked_at = now() WHERE session_id = CAST(:s AS uuid)", s=d2["session_id"])
    assert _check(api, uid, d2["session_id"]) is False


def test_logout_revokes_only_this_session_and_is_idempotent(db, api):
    _add_user(db, "kim")
    _add_user(db, "lee", "이영희")
    a = _login_data(api, remember=True)  # 집 PC
    b = _login_data(api, remember=True)  # 다른 기기
    other = _login_data(api, username="lee")
    r = api.post(LOGOUT, json={"user_id": a["user_id"], "session_id": a["session_id"]}, headers=H)
    assert r.status_code == 200 and r.json()["data"] == {"revoked": True}
    assert _check(api, a["user_id"], a["session_id"]) is False  # 훔친 쿠키도 5분 안에 거부
    assert _check(api, b["user_id"], b["session_id"]) is True  # 다른 기기 세션은 그대로
    assert _check(api, other["user_id"], other["session_id"]) is True
    assert api.post(LOGOUT, json={"user_id": a["user_id"], "session_id": a["session_id"]}, headers=H).json()["data"] == {"revoked": False}
    # 남의 세션을 내 id로 로그아웃시킬 수 없다
    assert api.post(LOGOUT, json={"user_id": a["user_id"], "session_id": other["session_id"]}, headers=H).json()["data"] == {"revoked": False}
    assert _check(api, other["user_id"], other["session_id"]) is True
    for bad in ({"user_id": a["user_id"]}, {"session_id": a["session_id"]}, {"user_id": "x", "session_id": "y"}, {}):
        assert api.post(LOGOUT, json=bad, headers=H).status_code == 400
    assert api.post(LOGOUT, json={"user_id": a["user_id"], "session_id": a["session_id"]}).status_code == 401  # 내부 토큰 필수


def test_auth_service_cannot_extend_reassign_or_delete_sessions(db, api):
    _add_user(db, "kim")
    d = _login_data(api, remember=True)
    auth_url = make_url(os.environ["PUBLIC_API_AUTH_DATABASE_URL"]).set(database=db.name)
    eng = create_engine(TempDb.render(auth_url))
    try:
        for sql in (
            "UPDATE auth.user_sessions SET expires_at = expires_at + interval '1 year'",
            "UPDATE auth.user_sessions SET user_id = gen_random_uuid()",
            "UPDATE auth.user_sessions SET remember = false",
            "DELETE FROM auth.user_sessions",
        ):
            with eng.connect() as c, pytest.raises(Exception, match="permission denied"):
                c.execute(text(sql))
        with eng.begin() as c:  # 허용된 두 열은 가능
            c.execute(text("UPDATE auth.user_sessions SET last_check_at = now()"))
    finally:
        eng.dispose()
    assert _sess_row(db, d["session_id"])[1] == 30 * 24 * 3600


def test_session_expiry_constraint_blocks_lifetimes_beyond_31_days(db, api):
    _add_user(db, "kim")
    uid = _admin(db, "SELECT user_id::text FROM auth.app_users WHERE username='kim'")[0][0]
    for expr in ("now() + interval '32 days'", "now() - interval '1 hour'"):
        with pytest.raises(Exception, match="ck_user_sessions_expiry"):
            _admin(db, f"INSERT INTO auth.user_sessions (user_id, remember, expires_at) VALUES (CAST(:u AS uuid), true, {expr})", u=uid)


def test_deleting_member_removes_sessions(db, api):
    _add_user(db, "kim")
    _login_data(api, remember=True)
    assert _admin(db, "SELECT count(*) FROM auth.user_sessions")[0][0] == 1
    _admin(db, "DELETE FROM auth.app_users WHERE username = 'kim'")
    assert _admin(db, "SELECT count(*) FROM auth.user_sessions")[0][0] == 0


# ------------------------------------------------------------------ 모든 기기에서 로그아웃 (DEC-071)
LOGOUT_ALL = "/api/v1/internal/auth/logout-all"


def test_logout_all_revokes_every_session_of_the_member_only(db, api):
    _add_user(db, "kim")
    _add_user(db, "lee", "이영희")
    a = _login_data(api, remember=True)
    b = _login_data(api, remember=True)
    c = _login_data(api)  # 8시간 세션도 포함
    other = _login_data(api, username="lee", remember=True)
    r = api.post(LOGOUT_ALL, json={"user_id": a["user_id"], "session_id": a["session_id"]}, headers=H)
    assert r.status_code == 200 and r.json()["data"] == {"revoked_count": 3}
    for s in (a, b, c):
        assert _check(api, s["user_id"], s["session_id"]) is False
        assert _sess_row(db, s["session_id"])[3] is True
    assert _check(api, other["user_id"], other["session_id"]) is True  # 다른 회원은 그대로
    # 새로 로그인하면 다시 쓸 수 있다
    again = _login_data(api, remember=True)
    assert _check(api, again["user_id"], again["session_id"]) is True


def test_logout_all_needs_a_live_session_of_that_member(db, api):
    _add_user(db, "kim")
    _add_user(db, "lee", "이영희")
    a = _login_data(api, remember=True)
    b = _login_data(api, remember=True)
    lee = _login_data(api, username="lee")
    # 남의 세션 id를 내 id로 제시 → 거부, 아무것도 취소되지 않는다
    r = api.post(LOGOUT_ALL, json={"user_id": a["user_id"], "session_id": lee["session_id"]}, headers=H)
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_SESSION"
    assert _check(api, a["user_id"], a["session_id"]) is True and _check(api, lee["user_id"], lee["session_id"]) is True
    # 없는 세션
    assert api.post(LOGOUT_ALL, json={"user_id": a["user_id"], "session_id": "99999999-9999-4999-8999-999999999999"}, headers=H).status_code == 401
    # 이미 취소된 세션(로그아웃된 쿠키)으로는 다른 기기를 끊지 못한다
    api.post(LOGOUT, json={"user_id": a["user_id"], "session_id": a["session_id"]}, headers=H)
    assert api.post(LOGOUT_ALL, json={"user_id": a["user_id"], "session_id": a["session_id"]}, headers=H).status_code == 401
    assert _check(api, b["user_id"], b["session_id"]) is True
    # 만료된 세션·비활성 회원
    _admin(db, "UPDATE auth.user_sessions SET created_at = now() - interval '31 days', expires_at = now() - interval '1 day' WHERE session_id = CAST(:s AS uuid)", s=b["session_id"])
    assert api.post(LOGOUT_ALL, json={"user_id": b["user_id"], "session_id": b["session_id"]}, headers=H).status_code == 401
    c = _login_data(api)
    _admin(db, "UPDATE auth.app_users SET is_active = false WHERE username = 'kim'")
    assert api.post(LOGOUT_ALL, json={"user_id": c["user_id"], "session_id": c["session_id"]}, headers=H).status_code == 401


def test_logout_all_validation_and_internal_token(db, api):
    _add_user(db, "kim")
    a = _login_data(api)
    body = {"user_id": a["user_id"], "session_id": a["session_id"]}
    assert api.post(LOGOUT_ALL, json=body).status_code == 401  # 내부 토큰 필수
    assert api.post(LOGOUT_ALL, json=body, headers={"X-Internal-Token": "wrong"}).status_code == 401
    for bad in ({}, {"user_id": a["user_id"]}, {"session_id": a["session_id"]}, {**body, "extra": 1}, {"user_id": "x", "session_id": "y"}):
        assert api.post(LOGOUT_ALL, json=bad, headers=H).status_code == 400, bad
    assert _check(api, a["user_id"], a["session_id"]) is True  # 거부된 요청은 아무것도 바꾸지 않는다


# ------------------------------------------------------------------ 회원가입 신청(승인 대기) (DEC-074)
SIGNUP = "/api/v1/internal/auth/signup"
GOODPW2 = "Qw8!rT5zLp"


def _signup(api, username="newbie", name="신입", password=GOODPW2, ip=None, token=TOKEN, **extra):
    headers = {"X-Internal-Token": token} if token else {}
    if ip:
        headers["X-End-User-IP"] = ip
    body = {"username": username, "display_name": name, "password": password, **extra}
    return api.post(SIGNUP, json=body, headers=headers)


def _urow(db, username):
    rows = _admin(db, "SELECT role, is_active, approved_at IS NOT NULL, password_hash FROM auth.app_users WHERE username = :u", u=username)
    return rows[0] if rows else None


@pytest.fixture(autouse=True)
def _reset_signup_throttle(monkeypatch):
    from services.public_api.auth import throttle as th

    monkeypatch.setenv("PUBLIC_API_SIGNUP_PER_10MIN", "600")  # 시험이 많이 가입해도 막히지 않게(제한 시험만 낮춘다)
    monkeypatch.setenv("PUBLIC_API_SIGNUP_GLOBAL_PER_HOUR", "10000")
    th.reset_signup_throttle()
    yield
    th.reset_signup_throttle()


def test_signup_creates_a_pending_user_who_cannot_log_in_yet(db, api):
    r = _signup(api)
    assert r.status_code == 200 and r.json()["data"] == {"status": "pending"}
    role, active, approved, h = _urow(db, "newbie")
    assert (role, active, approved) == ("user", False, False)  # 일반 권한, 비활성, 미승인
    assert h.startswith("$argon2id$") and GOODPW2 not in h and GOODPW2 not in r.text
    # 비밀번호가 맞으면 본인에게만 "승인 대기"를 알려 준다. 틀리면 평범한 실패와 같다.
    ok = _login(api, "newbie", GOODPW2)
    assert ok.status_code == 403 and ok.json()["error"]["code"] == "PENDING_APPROVAL"
    bad = _login(api, "newbie", "wrong-password-xyz")
    assert _error_shape(bad) == (401, "INVALID_CREDENTIALS", GENERIC_MESSAGE, None)
    assert [a[1] for a in _audit(db)] == ["PENDING", "FAIL"]
    assert _admin(db, "SELECT count(*) FROM auth.user_sessions")[0][0] == 0  # 세션이 만들어지지 않는다


def test_pending_user_cannot_use_an_existing_session_id_or_anything_else(db, api):
    _signup(api)
    uid = _admin(db, "SELECT user_id::text FROM auth.app_users WHERE username='newbie'")[0][0]
    # 승인 전에는 (우회로) 세션을 만들 수도 없고, 만들어 둔 것이 있어도 확인에서 거부된다
    sid = _admin(db, "INSERT INTO auth.user_sessions (user_id, remember, expires_at) VALUES (CAST(:u AS uuid), false, now() + interval '8 hours') RETURNING session_id::text", u=uid)[0][0]
    assert _check(api, uid, sid) is False


def test_signup_validation_rejects_bad_input_and_creates_nothing(db, api):
    bad = [
        dict(username="ab"), dict(username="Has Space"), dict(username="한글아이디"), dict(username="x" * 33),
        dict(password="short7!"), dict(password="12345678"), dict(password="password"), dict(password="aaaaaaaa"),
        dict(username="kimkim", password="kimkim"), dict(name=""), dict(name="가" * 41), dict(name="이\x00름"),
    ]
    for kw in bad:
        r = _signup(api, **kw)
        assert r.status_code in (400,), kw
    for extra in ({"role": "admin"}, {"is_active": True}, {"approved_at": "2026-01-01"}, {"user_id": "x"}):
        assert _signup(api, **extra).status_code == 400, extra  # 권한·활성·승인은 신청으로 정할 수 없다
    assert _admin(db, "SELECT count(*) FROM auth.app_users")[0][0] == 0
    assert api.post(SIGNUP, json={"username": "newbie"}, headers=H).status_code == 400


def test_signup_duplicate_username_is_rejected_case_insensitively_and_keeps_the_first(db, api):
    assert _signup(api, "newbie", password=GOODPW2).status_code == 200
    first_hash = _urow(db, "newbie")[3]
    r = _signup(api, " NewBie ", password="Another-pass-77")
    assert r.status_code == 409 and r.json()["error"]["code"] == "USERNAME_TAKEN"
    assert _urow(db, "newbie")[3] == first_hash
    _add_user(db, "kim")  # 이미 승인된 회원 아이디도 마찬가지
    assert _signup(api, "kim").status_code == 409


def test_signup_honeypot_pretends_success_but_creates_nothing(db, api):
    r = _signup(api, website="http://spam.example")
    assert r.status_code == 200 and r.json()["data"] == {"status": "pending"}
    assert _admin(db, "SELECT count(*) FROM auth.app_users")[0][0] == 0


def test_signup_requires_internal_token_and_is_rate_limited(db, api, monkeypatch):
    assert _signup(api, token=None).status_code == 401
    assert _signup(api, token="wrong").status_code == 401
    monkeypatch.setenv("PUBLIC_API_SIGNUP_PER_10MIN", "3")
    codes = [_signup(api, f"user{i}x", ip="203.0.113.9").status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]
    r = _signup(api, "other1x", ip="203.0.113.9")
    assert r.json()["error"]["code"] == "SIGNUP_RATE_LIMITED"
    assert _signup(api, "other2x", ip="203.0.113.10").status_code == 200  # 다른 접속 주소는 독립
    from services.public_api.auth import throttle as th

    th.reset_signup_throttle()
    monkeypatch.setenv("PUBLIC_API_SIGNUP_GLOBAL_PER_HOUR", "2")
    assert [_signup(api, f"glob{i}x", ip=f"198.51.100.{i}").status_code for i in range(3)] == [200, 200, 429]  # 서버 전체 상한


def test_signup_closes_when_too_many_requests_are_waiting(db, api, monkeypatch):
    monkeypatch.setattr(auth_service, "MAX_PENDING_SIGNUPS", 2)
    assert _signup(api, "wait1x").status_code == 200
    assert _signup(api, "wait2x").status_code == 200
    r = _signup(api, "wait3x")
    assert r.status_code == 503 and r.json()["error"]["code"] == "SIGNUP_CLOSED"
    _add_user(db, "kim")  # 승인된 회원은 대기 수에 포함되지 않는다
    assert _admin(db, "SELECT count(*) FROM auth.app_users")[0][0] == 3


# ------------------------------------------------------------------ 관리자 회원 관리 (DEC-074)
ADMIN_LIST = "/api/v1/internal/admin/members"
ADMIN_ACT = "/api/v1/internal/admin/action"


def _login_hdr(api, username, password=GOOD):
    d = _login_data(api, username=username, password=password)
    return {"X-Internal-Token": TOKEN, "X-Auth-User": d["user_id"], "X-Auth-Session": d["session_id"]}, d


def _act(api, h, action, username, **kw):
    return api.post(ADMIN_ACT, json={"action": action, "username": username, **kw}, headers=h)


def _two_admins(db, api):
    _add_user(db, "boss", "관리자", role="admin")
    _add_user(db, "chief", "부관리자", role="admin")
    hb, db_ = _login_hdr(api, "boss")
    hc, dc = _login_hdr(api, "chief")
    return (hb, db_), (hc, dc)


def test_admin_endpoints_reject_everyone_but_active_admins_with_a_live_session(db, api):
    _add_user(db, "boss", "관리자", role="admin")
    _add_user(db, "plain", "일반")
    hb, db_ = _login_hdr(api, "boss")
    hp, _dp = _login_hdr(api, "plain")
    assert api.get(ADMIN_LIST, headers=hb).status_code == 200
    assert api.get(ADMIN_LIST, headers=hp).status_code == 403  # 일반 사용자
    assert _act(api, hp, "delete", "boss").status_code == 403
    assert api.get(ADMIN_LIST, headers={"X-Internal-Token": TOKEN}).status_code == 403  # 로그인 정보 없음
    assert api.get(ADMIN_LIST, headers={k: v for k, v in hb.items() if k != "X-Internal-Token"}).status_code == 401  # 내부 토큰 없음
    assert api.get(ADMIN_LIST, headers={**hb, "X-Auth-Session": hp["X-Auth-Session"]}).status_code == 403  # 남의 세션
    # 권한·상태가 DB에서 바뀌면 같은 세션도 바로 거부(쿠키·웹 말을 믿지 않는다)
    _admin(db, "UPDATE auth.app_users SET role = 'user' WHERE username='boss'")
    assert api.get(ADMIN_LIST, headers=hb).status_code == 403
    _admin(db, "UPDATE auth.app_users SET role = 'admin' WHERE username='boss'")
    assert api.get(ADMIN_LIST, headers=hb).status_code == 200
    api.post(LOGOUT, json={"user_id": db_["user_id"], "session_id": db_["session_id"]}, headers=H)
    assert api.get(ADMIN_LIST, headers=hb).status_code == 403  # 로그아웃한 세션
    assert _admin(db, "SELECT count(*) FROM auth.app_users")[0][0] == 2  # 거부된 요청은 아무것도 바꾸지 않았다


def test_admin_list_shows_statuses_pending_first_and_no_secrets(db, api):
    _add_user(db, "boss", "관리자", role="admin")
    _add_user(db, "plain", "일반")
    _add_user(db, "off", "중지", active=False)
    _signup(api, "newbie")
    hb, _ = _login_hdr(api, "boss")
    r = api.get(ADMIN_LIST, headers=hb)
    data = r.json()["data"]
    assert data["total"] == 4 and data["pending"] == 1
    assert [(m["username"], m["status"], m["role"]) for m in data["items"]] == [
        ("newbie", "pending", "user"), ("boss", "active", "admin"), ("off", "disabled", "user"), ("plain", "active", "user"),
    ] or [m["username"] for m in data["items"]][0] == "newbie"
    assert all(set(m) == {"username", "display_name", "role", "status", "created_at", "last_login_at", "locked", "active_sessions"} for m in data["items"])
    assert "argon2" not in r.text and "password" not in r.text
    assert next(m for m in data["items"] if m["username"] == "boss")["active_sessions"] == 1


def test_admin_approves_a_signup_then_the_user_can_log_in_and_reject_deletes(db, api):
    _add_user(db, "boss", "관리자", role="admin")
    _signup(api, "newbie")
    _signup(api, "spammer")
    hb, _ = _login_hdr(api, "boss")
    assert _act(api, hb, "approve", "newbie").json()["data"] == {"result": "approved"}
    assert _urow(db, "newbie")[:3] == ("user", True, True)
    d = _login_data(api, username="newbie", password=GOODPW2)
    assert d["role"] == "user"
    assert _act(api, hb, "approve", "newbie").status_code == 409  # 이미 승인됨
    assert _act(api, hb, "reject", "newbie").status_code == 409  # 승인된 회원은 거절이 아니라 삭제
    assert _act(api, hb, "reject", "spammer").json()["data"] == {"result": "rejected"}
    assert _urow(db, "spammer") is None
    assert _act(api, hb, "approve", "nobody").status_code == 404
    actions = [r[0] for r in _admin(db, "SELECT action FROM auth.admin_audit ORDER BY audit_id")]
    assert actions == ["approve", "reject"]


def test_admin_create_edit_role_disable_enable_and_delete(db, api):
    _add_user(db, "boss", "관리자", role="admin")
    hb, _ = _login_hdr(api, "boss")
    r = _act(api, hb, "create", "made1", display_name="만든이", password=GOODPW2, role="user")
    assert r.status_code == 200 and r.json()["data"] == {"result": "created"}
    assert _urow(db, "made1")[:3] == ("user", True, True)
    assert _login_data(api, username="made1", password=GOODPW2)["role"] == "user"  # 바로 로그인 가능
    assert _act(api, hb, "create", "made1", display_name="x", password=GOODPW2, role="user").status_code == 409
    assert _act(api, hb, "create", "made2", display_name="x", password="weak", role="user").status_code == 400
    assert _act(api, hb, "create", "made2", display_name="x", password=GOODPW2, role="root").status_code == 400
    assert _act(api, hb, "create", "made2", display_name="x", password=GOODPW2).status_code == 400  # 권한 필수
    assert _act(api, hb, "rename", "made1", display_name="새이름").json()["data"] == {"result": "renamed"}
    assert _admin(db, "SELECT display_name FROM auth.app_users WHERE username='made1'")[0][0] == "새이름"
    assert _act(api, hb, "rename", "made1", display_name="").status_code == 400
    assert _act(api, hb, "set_role", "made1", role="admin").json()["data"] == {"result": "role_changed"}
    assert _login_data(api, username="made1", password=GOODPW2)["role"] == "admin"
    assert _act(api, hb, "set_role", "made1", role="admin").status_code == 409  # 같은 권한
    assert _act(api, hb, "set_role", "made1", role="user").status_code == 200
    d = _login_data(api, username="made1", password=GOODPW2)
    assert _check(api, d["user_id"], d["session_id"]) is True
    assert _act(api, hb, "disable", "made1").json()["data"] == {"result": "disabled"}
    assert _check(api, d["user_id"], d["session_id"]) is False  # 비활성화하면 로그인 중인 기기도 끊김
    r = _login(api, "made1", GOODPW2)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"
    assert _act(api, hb, "enable", "made1").status_code == 200
    assert _check(api, d["user_id"], d["session_id"]) is False  # 다시 켜도 이전 로그인은 되살아나지 않는다
    assert _login(api, "made1", GOODPW2).status_code == 200
    assert _act(api, hb, "delete", "made1").json()["data"] == {"result": "deleted"}
    assert _urow(db, "made1") is None
    assert _admin(db, "SELECT count(*) FROM auth.user_sessions WHERE user_id NOT IN (SELECT user_id FROM auth.app_users)")[0][0] == 0


def test_admin_reset_password_enforces_policy_clears_lock_and_ends_sessions(db, api):
    _add_user(db, "boss", "관리자", role="admin")
    _add_user(db, "plain", "일반")
    hb, _ = _login_hdr(api, "boss")
    d = _login_data(api, username="plain")
    for _ in range(5):
        _login(api, "plain", "wrong-password-xyz")
    assert _login(api, "plain", GOOD).status_code == 401  # 잠김
    assert _act(api, hb, "reset_password", "plain", password="123").status_code == 400  # 정책 위반은 거부, 상태 불변
    assert _act(api, hb, "reset_password", "plain").status_code == 400
    assert _check(api, d["user_id"], d["session_id"]) is True
    r = _act(api, hb, "reset_password", "plain", password=GOODPW2)
    assert r.json()["data"] == {"result": "password_reset"} and GOODPW2 not in r.text
    assert _check(api, d["user_id"], d["session_id"]) is False  # 기존 로그인은 모두 끊김
    assert _login(api, "plain", GOOD).status_code == 401  # 옛 비밀번호 거부
    assert _login(api, "plain", GOODPW2).status_code == 200  # 잠금이 풀리고 새 비밀번호 사용 가능
    audit = _admin(db, "SELECT action, detail FROM auth.admin_audit ORDER BY audit_id")
    assert audit == [("reset_password", None)]  # 비밀번호·해시는 기록하지 않는다


def test_admin_cannot_lock_themselves_out_or_remove_the_last_admin(db, api):
    (hb, db_), (hc, dc) = _two_admins(db, api)
    for action, kw in (("disable", {}), ("delete", {}), ("set_role", {"role": "user"})):
        r = _act(api, hb, action, "boss", **kw)
        assert r.status_code == 409 and r.json()["error"]["code"] == "SELF_PROTECTED", action
    assert _urow(db, "boss")[:2] == ("admin", True)
    assert _act(api, hb, "rename", "boss", display_name="내이름").status_code == 200  # 이름 수정은 본인도 가능
    assert _act(api, hc, "set_role", "boss", role="user").status_code == 200  # 다른 관리자가 강등
    # boss는 이제 일반 사용자: 관리자 기능 불가, chief가 유일한 관리자 → chief 본인은 자신을 없앨 수 없다
    assert api.get(ADMIN_LIST, headers=hb).status_code == 403
    assert _act(api, hc, "disable", "chief").json()["error"]["code"] == "SELF_PROTECTED"
    assert _admin(db, "SELECT count(*) FROM auth.app_users WHERE role='admin' AND is_active")[0][0] == 1


def test_two_admins_cannot_remove_each_other_at_the_same_time(db, api):
    (hb, _db), (hc, _dc) = _two_admins(db, api)
    results = {}

    def go(name, h, target):
        results[name] = _act(api, h, "disable", target).status_code

    t1 = threading.Thread(target=go, args=("b", hb, "chief"))
    t2 = threading.Thread(target=go, args=("c", hc, "boss"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert _admin(db, "SELECT count(*) FROM auth.app_users WHERE role='admin' AND is_active")[0][0] >= 1, results
    assert sorted(results.values()) != [200, 200], results  # 둘 다 성공하면 관리자가 0명이 된다


def test_admin_action_input_validation_and_audit_trail(db, api):
    _add_user(db, "boss", "관리자", role="admin")
    _add_user(db, "plain", "일반")
    hb, d = _login_hdr(api, "boss")
    for body in (
        {"action": "explode", "username": "plain"}, {"action": "delete"}, {"username": "plain"},
        {"action": "delete", "username": "plain", "extra": 1}, {"action": "delete", "username": "x"},
        {"action": "set_role", "username": "plain", "role": "superuser"}, {"action": "rename", "username": "plain", "display_name": "가" * 101},
    ):
        assert api.post(ADMIN_ACT, json=body, headers=hb).status_code == 400, body
    assert _act(api, hb, "disable", "nobody").status_code == 404
    assert _urow(db, "plain")[:2] == ("user", True)  # 잘못된 요청은 아무것도 바꾸지 않았다
    assert _act(api, hb, "revoke_sessions", "plain").json()["data"] == {"result": "sessions_revoked"}
    assert _act(api, hb, "disable", "plain").status_code == 200
    rows = _admin(db, "SELECT actor_username, action, target_username FROM auth.admin_audit ORDER BY audit_id")
    assert rows == [("boss", "revoke_sessions", "plain"), ("boss", "disable", "plain")]
    assert d["user_id"]  # keep


def test_admin_delete_removes_audit_actor_link_without_losing_the_record(db, api):
    (hb, _), (hc, _dc) = _two_admins(db, api)
    _act(api, hb, "rename", "chief", display_name="바뀜")
    assert _act(api, hc, "delete", "boss").status_code == 200
    rows = _admin(db, "SELECT actor_user_id IS NULL, actor_username, action FROM auth.admin_audit ORDER BY audit_id")
    assert rows == [(True, "boss", "rename"), (False, "chief", "delete")]  # 삭제된 행위자의 id는 비워지지만 기록(이름·행동)은 남는다
