# ruff: noqa: E501
"""내부 토큰 강제·회원별 호출 한도·로그인 시도 제한·접속 주소 가리기 단위 시험 (DEC-067). DB 불필요."""

from __future__ import annotations

import importlib

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from services.public_api.auth import throttle
from services.public_api.auth.service import mask_ip
from services.public_api.core import config
from services.public_api.middleware import InternalTokenMiddleware
from services.public_api.rate_limit import RateLimitMiddleware, reset_rate_limit_state

TOKEN = "t" * 40


async def _ok(request):
    return PlainTextResponse("ok")


def _app_with_middleware() -> TestClient:
    app = Starlette(routes=[Route("/api/v1/live", _ok), Route("/api/v1/stocks", _ok), Route("/docs", _ok), Route("/anything", _ok)])
    app.add_middleware(InternalTokenMiddleware)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", TOKEN)
    reset_rate_limit_state()
    throttle.reset_login_throttle()
    yield
    reset_rate_limit_state()
    throttle.reset_login_throttle()


# ------------------------------------------------------------------ 내부 토큰 미들웨어
def test_only_live_is_open_without_token():
    c = _app_with_middleware()
    assert c.get("/api/v1/live").status_code == 200
    for path in ("/api/v1/stocks", "/docs", "/anything", "/openapi.json", "/", "/api/v1/live/extra", "/api/v1/LIVE"):
        r = c.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_correct_token_passes_wrong_or_missing_fails():
    c = _app_with_middleware()
    assert c.get("/api/v1/stocks", headers={"X-Internal-Token": TOKEN}).status_code == 200
    for bad in ("", "x", TOKEN + "x", TOKEN[:-1], TOKEN.upper(), " " + TOKEN):
        assert c.get("/api/v1/stocks", headers={"X-Internal-Token": bad}).status_code == 401, repr(bad)


def test_401_body_is_identical_for_all_failures_and_reveals_nothing():
    c = _app_with_middleware()
    bodies = []
    for headers in ({}, {"X-Internal-Token": "wrong"}, {"X-Internal-Token": TOKEN[:-1]}):
        r = c.get("/api/v1/stocks", headers=headers)
        j = r.json()
        j["meta"].pop("generated_at")
        bodies.append((r.status_code, j))
    assert all(b == bodies[0] for b in bodies)
    assert TOKEN not in str(bodies)


def test_empty_expected_token_rejects_everything_fail_closed(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", "")
    c = _app_with_middleware()
    assert c.get("/api/v1/stocks").status_code == 401
    assert c.get("/api/v1/stocks", headers={"X-Internal-Token": ""}).status_code == 401
    assert c.get("/api/v1/live").status_code == 200  # 헬스체크는 항상 열려 있다


def test_non_ascii_token_header_does_not_crash():
    c = _app_with_middleware()
    r = c.get("/api/v1/stocks", headers={"X-Internal-Token": "토큰".encode()})
    assert r.status_code == 401


# ------------------------------------------------------------------ 설정 검증(기동 거부)
def test_enforcement_flag_parsing(monkeypatch):
    for value, expected in (("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True), ("false", False), ("", False), ("0", False), ("no", False)):
        monkeypatch.setenv("PUBLIC_API_REQUIRE_INTERNAL_TOKEN", value)
        assert config.internal_token_enforced() is expected, value
    monkeypatch.delenv("PUBLIC_API_REQUIRE_INTERNAL_TOKEN")
    assert config.internal_token_enforced() is False


def test_validate_auth_config_refuses_weak_token_only_when_enforced(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_REQUIRE_INTERNAL_TOKEN", "true")
    for weak in ("", "short", "x" * 31):
        monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", weak)
        with pytest.raises(config.ConfigError):
            config.validate_auth_config()
    monkeypatch.delenv("PUBLIC_API_INTERNAL_TOKEN")
    with pytest.raises(config.ConfigError):
        config.validate_auth_config()
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", "x" * 32)
    config.validate_auth_config()  # 통과
    monkeypatch.setenv("PUBLIC_API_REQUIRE_INTERNAL_TOKEN", "false")
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", "")
    config.validate_auth_config()  # 스위치가 꺼져 있으면 검사하지 않는다(로컬)


# ------------------------------------------------------------------ 실제 앱(스위치 켠 상태)
@pytest.fixture()
def enforced_app(monkeypatch):
    import services.public_api.main as main

    monkeypatch.setenv("PUBLIC_API_REQUIRE_INTERNAL_TOKEN", "true")
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", TOKEN)
    reloaded = importlib.reload(main)
    try:
        yield reloaded.app
    finally:
        monkeypatch.undo()
        importlib.reload(main)  # 이후 시험이 기본 설정의 앱을 보게 되돌린다


def test_real_app_enforced_hides_docs_and_blocks_data_without_token(enforced_app):
    c = TestClient(enforced_app)
    assert c.get("/api/v1/live").status_code == 200
    for path in ("/api/v1/stocks?query=a", "/api/v1/market-summary", "/api/v1/screen", "/api/v1/stocks/005930/prices", "/api/v1/internal/members", "/api/v1/health"):
        assert c.get(path).status_code == 401, path
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 401, path  # 토큰 없이는 존재 여부도 알 수 없다
        assert c.get(path, headers={"X-Internal-Token": TOKEN}).status_code == 404, path  # 토큰이 있어도 문서 경로 자체가 없다
    assert "x-content-type-options" in {k.lower() for k in c.get("/api/v1/stocks").headers}  # 401에도 보안 헤더


def test_real_app_default_keeps_docs_and_open_data_paths(monkeypatch):
    monkeypatch.delenv("PUBLIC_API_REQUIRE_INTERNAL_TOKEN", raising=False)
    import services.public_api.main as main

    app = importlib.reload(main).app
    c = TestClient(app)
    assert c.get("/openapi.json").status_code == 200  # 로컬 개발 동작 불변
    assert c.get("/api/v1/live").status_code == 200


def test_real_app_refuses_to_start_with_weak_token(monkeypatch):
    import services.public_api.main as main

    monkeypatch.setenv("PUBLIC_API_REQUIRE_INTERNAL_TOKEN", "true")
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", "short")
    with pytest.raises(config.ConfigError):
        importlib.reload(main)
    monkeypatch.undo()
    importlib.reload(main)


# ------------------------------------------------------------------ 회원별 호출 한도(X-Auth-User)
def _limited(limit=3) -> TestClient:
    app = Starlette(routes=[Route("/ping", _ok)])
    app.add_middleware(RateLimitMiddleware, limit=limit, window_seconds=60, internal_limit=50)
    return TestClient(app)


U1 = "11111111-1111-4111-8111-111111111111"
U2 = "22222222-2222-4222-8222-222222222222"


def _h(user=None, ip=None, token=TOKEN):
    h = {}
    if token is not None:
        h["X-Internal-Token"] = token
    if user:
        h["X-Auth-User"] = user
    if ip:
        h["X-End-User-IP"] = ip
    return h


def test_each_member_has_an_independent_budget():
    c = _limited(3)
    for _ in range(3):
        assert c.get("/ping", headers=_h(user=U1)).status_code == 200
    assert c.get("/ping", headers=_h(user=U1)).status_code == 429
    assert c.get("/ping", headers=_h(user=U2)).status_code == 200


def test_member_header_is_ignored_without_valid_token_spoof_proof():
    c = _limited(3)
    for i in range(3):
        assert c.get("/ping", headers=_h(user=f"{i}{U1[1:]}", token=None)).status_code == 200
    assert c.get("/ping", headers=_h(user="3" + U1[1:], token=None)).status_code == 429  # 같은 peer 버킷
    assert c.get("/ping", headers=_h(user="4" + U1[1:], token="wrong")).status_code == 429


def test_invalid_member_id_falls_back_and_user_has_priority_over_ip():
    c = _limited(2)
    for _ in range(2):
        c.get("/ping", headers=_h(user="not-a-uuid", ip="203.0.113.5"))
    assert c.get("/ping", headers=_h(user="not-a-uuid", ip="203.0.113.5")).status_code == 429  # IP 키로 셈
    # 회원 id가 있으면 IP와 무관하게 그 회원 키
    c2 = _limited(2)
    for ip in ("203.0.113.1", "203.0.113.2"):
        assert c2.get("/ping", headers=_h(user=U1, ip=ip)).status_code == 200
    assert c2.get("/ping", headers=_h(user=U1, ip="203.0.113.3")).status_code == 429


# ------------------------------------------------------------------ 로그인 시도 제한
def test_login_throttle_per_key_and_global(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_LOGIN_RATE_PER_MINUTE", "3")
    monkeypatch.setenv("PUBLIC_API_LOGIN_GLOBAL_PER_MINUTE", "5")
    t = 1000.0
    assert [throttle.allow_login_attempt("a", now=t) for _ in range(4)] == [True, True, True, False]
    assert throttle.allow_login_attempt("b", now=t) is True
    assert throttle.allow_login_attempt("c", now=t) is True  # 전체 5번째
    assert throttle.allow_login_attempt("d", now=t) is False  # 전체 상한
    assert throttle.allow_login_attempt("a", now=t + 61) is True  # 1분 뒤 창이 새로 시작


def test_login_throttle_unknown_client_shares_one_key(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_LOGIN_RATE_PER_MINUTE", "2")
    assert [throttle.allow_login_attempt(None, now=5.0) for _ in range(3)] == [True, True, False]
    assert throttle.allow_login_attempt("1.2.3.4", now=5.0) is True


@pytest.mark.parametrize("name,value", [("PUBLIC_API_LOGIN_RATE_PER_MINUTE", "0"), ("PUBLIC_API_LOGIN_RATE_PER_MINUTE", "x"), ("PUBLIC_API_LOGIN_GLOBAL_PER_MINUTE", "99999")])
def test_login_throttle_config_errors_are_explicit(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(config.ConfigError):
        config.get_login_rate_limits()


# ------------------------------------------------------------------ 기록용 접속 주소 가리기
@pytest.mark.parametrize(
    "raw,expected",
    [("203.0.113.77", "203.0.113.x"), ("2001:db8:1234:5678::1", "2001:0db8:1234::x"), ("::1", "0000:0000:0000::x"), (None, None), ("", None), ("not-an-ip", None), ("203.0.113", None), ("1.2.3.4; DROP TABLE", None)],
)
def test_mask_ip(raw, expected):
    assert mask_ip(raw) == expected
