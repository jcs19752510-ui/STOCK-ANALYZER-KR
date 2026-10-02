"""KIS 클라이언트(토큰·재시도·한도·비밀 비노출)와 로컬 모드 API 접근 통제 테스트 (DEC-052).

실제 증권사 서버를 호출하지 않는다: `httpx.MockTransport`로 응답을 흉내 낸다.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from services.public_api.api import local_intraday
from services.public_api.db.session import get_db
from services.public_api.intraday import config as cfg
from services.public_api.intraday.kis_client import KisClient, KisError
from services.public_api.main import app
from services.public_api.rate_limit import reset_rate_limit_state

APP_KEY = "PSTESTKEY1234567890"
APP_SECRET = "SECRET-DO-NOT-LEAK-abcdefghijklmnopqrstuvwxyz"
BASE = "https://openapi.koreainvestment.com:9443"


def _settings(tmp_path: Path, **over):
    env = {
        cfg.ENABLED_ENV: "true",
        cfg.APP_KEY_ENV: APP_KEY,
        cfg.APP_SECRET_ENV: APP_SECRET,
        cfg.TOKEN_CACHE_ENV: str(tmp_path / "tok.json"),
        **over,
    }
    return cfg.get_settings(env)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _client(tmp_path, handler, clock=None, **over):
    clock = clock or Clock()
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return KisClient(_settings(tmp_path, **over), http, clock=clock, sleep=clock.sleep), clock


def _ok_token_handler(calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "0", "output2": [], "output1": {}})

    return handler


# ── 설정 ──────────────────────────────────────────────────────────────────────────────────
def test_disabled_by_default_and_requires_true():
    assert cfg.get_settings({}).enabled is False
    assert cfg.get_settings({cfg.ENABLED_ENV: "yes"}).enabled is False
    assert cfg.get_settings({cfg.ENABLED_ENV: " TRUE "}).enabled is True


def test_base_url_locked_to_real_domain_unless_explicit_override():
    with pytest.raises(cfg.IntradayConfigError):
        cfg.get_settings({cfg.ENABLED_ENV: "true", cfg.BASE_URL_ENV: "https://evil.example.com"})
    with pytest.raises(cfg.IntradayConfigError):  # http도 거부
        cfg.get_settings({cfg.ENABLED_ENV: "true", cfg.BASE_URL_ENV: "http://openapi.koreainvestment.com:9443"})
    ok = cfg.get_settings(
        {cfg.ENABLED_ENV: "true", cfg.BASE_URL_ENV: "http://127.0.0.1:9999", cfg.ALLOW_CUSTOM_BASE_ENV: "true"}
    )
    assert ok.base_url == "http://127.0.0.1:9999"
    assert cfg.get_settings({cfg.ENABLED_ENV: "true"}).base_url == BASE


def test_client_allowed_matrix():
    s = cfg.get_settings({cfg.ENABLED_ENV: "true"})
    assert cfg.client_allowed("127.0.0.1", s) and cfg.client_allowed("::1", s)
    for bad in ("192.168.0.5", "8.8.8.8", "testclient", "", None, "127.0.0.1.evil"):
        assert cfg.client_allowed(bad, s) is False, bad
    lan = cfg.get_settings({cfg.ENABLED_ENV: "true", cfg.ALLOWED_IPS_ENV: "127.0.0.1, 192.168.0.0/24"})
    assert cfg.client_allowed("192.168.0.77", lan) and not cfg.client_allowed("192.168.1.1", lan)
    with pytest.raises(cfg.IntradayConfigError):
        cfg.get_settings({cfg.ALLOWED_IPS_ENV: "not-an-ip"})


# ── 토큰·요청·재시도 ───────────────────────────────────────────────────────────────────────
def test_token_issued_once_cached_to_file_with_private_mode_and_reused(tmp_path):
    calls: list[httpx.Request] = []
    client, _ = _client(tmp_path, _ok_token_handler(calls))
    client.minute_today("005930", "100000")
    client.orderbook("005930")
    assert [c.url.path for c in calls].count("/oauth2/tokenP") == 1
    data_req = next(c for c in calls if c.url.path != "/oauth2/tokenP")
    assert data_req.headers["authorization"] == "Bearer tok-1"
    assert data_req.headers["tr_id"] == "FHKST03010200" and data_req.headers["custtype"] == "P"
    assert data_req.url.params["FID_INPUT_ISCD"] == "005930"
    cache = tmp_path / "tok.json"
    assert cache.exists()
    if os.name == "posix":
        assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert APP_SECRET not in cache.read_text(encoding="utf-8")  # 시크릿은 파일에 쓰지 않는다
    # 새 인스턴스(재시작)는 파일 캐시를 써서 토큰을 다시 받지 않는다
    calls2: list[httpx.Request] = []
    client2, _ = _client(tmp_path, _ok_token_handler(calls2))
    client2.orderbook("005930")
    assert "/oauth2/tokenP" not in [c.url.path for c in calls2]


def test_cached_token_ignored_when_app_key_changes(tmp_path):
    calls: list[httpx.Request] = []
    c1, _ = _client(tmp_path, _ok_token_handler(calls))
    c1.orderbook("005930")
    calls2: list[httpx.Request] = []
    http = httpx.Client(transport=httpx.MockTransport(_ok_token_handler(calls2)))
    other = cfg.get_settings(
        {cfg.ENABLED_ENV: "true", cfg.APP_KEY_ENV: "OTHER", cfg.APP_SECRET_ENV: "S2",
         cfg.TOKEN_CACHE_ENV: str(tmp_path / "tok.json")}
    )  # fmt: skip
    KisClient(other, http).orderbook("005930")
    assert "/oauth2/tokenP" in [c.url.path for c in calls2]


def test_expired_token_response_refreshes_once_and_retries(tmp_path):
    state = {"tokens": 0, "data": 0}

    def handler(req):
        if req.url.path == "/oauth2/tokenP":
            state["tokens"] += 1
            return httpx.Response(200, json={"access_token": f"tok-{state['tokens']}", "expires_in": 86400})
        state["data"] += 1
        if req.headers["authorization"] == "Bearer tok-1":
            return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token"})
        return httpx.Response(200, json={"rt_cd": "0", "output1": {"ok": 1}})

    client, _ = _client(tmp_path, handler)
    assert client.orderbook("005930")["output1"] == {"ok": 1}
    assert state == {"tokens": 2, "data": 2}


def test_rate_limit_response_retries_once_then_errors(tmp_path):
    n = {"data": 0}

    def handler(req):
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        n["data"] += 1
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과"})

    client, clock = _client(tmp_path, handler)
    with pytest.raises(KisError) as e:
        client.orderbook("005930")
    assert e.value.code == "RATE_LIMITED" and n["data"] == 2
    assert clock.t >= 1_000_001.0  # 재시도 전에 1초 대기


def test_throttle_spaces_requests(tmp_path):
    client, clock = _client(tmp_path, _ok_token_handler([]))
    start = clock.t
    for _ in range(5):
        client.orderbook("005930")
    assert clock.t - start >= 4 * 0.12 - 1e-6


def test_errors_never_leak_secrets_or_raw_body(tmp_path):
    def handler(req):
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "tok-LEAK-CHECK", "expires_in": 86400})
        return httpx.Response(
            200,
            json={"rt_cd": "1", "msg_cd": "X", "msg1": "오류 발생 " + "가" * 500, "echo": APP_SECRET},
        )

    client, _ = _client(tmp_path, handler)
    with pytest.raises(KisError) as e:
        client.orderbook("005930")
    text = f"{e.value.code} {e.value.message} {e.value!r}"
    for secret in (APP_KEY, APP_SECRET, "tok-LEAK-CHECK"):
        assert secret not in text
    assert len(e.value.message) < 200


def test_auth_failure_and_network_failure_codes(tmp_path):
    client, _ = _client(tmp_path, lambda req: httpx.Response(401, json={"error": "bad"}))
    with pytest.raises(KisError) as e:
        client.orderbook("005930")
    assert e.value.code == "AUTH_FAILED"

    def boom(req):
        raise httpx.ConnectError("down", request=req)

    client2, _ = _client(tmp_path / "x", boom)
    with pytest.raises(KisError) as e2:
        client2.orderbook("005930")
    assert e2.value.code == "UPSTREAM_UNAVAILABLE"
    assert "down" not in e2.value.message


def test_requires_keys():
    with pytest.raises(KisError) as e:
        KisClient(cfg.get_settings({cfg.ENABLED_ENV: "true"}))
    assert e.value.code == "NOT_CONFIGURED"


# ── API 접근 통제 ─────────────────────────────────────────────────────────────────────────
class _FakeSession:
    pass


@pytest.fixture
def api(tmp_path, monkeypatch):
    for k in (cfg.ENABLED_ENV, cfg.APP_KEY_ENV, cfg.APP_SECRET_ENV, cfg.ALLOWED_IPS_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(cfg.TOKEN_CACHE_ENV, str(tmp_path / "tok.json"))
    app.dependency_overrides[get_db] = lambda: _FakeSession()
    local_intraday.reset_intraday_service()
    reset_rate_limit_state()
    yield
    app.dependency_overrides.clear()
    local_intraday.reset_intraday_service()
    reset_rate_limit_state()


def _local(host="127.0.0.1"):
    return TestClient(app, client=(host, 50000), base_url="http://localhost")


PATHS = ("/api/v1/local/status", "/api/v1/local/stocks/005930/minutes",
         "/api/v1/local/stocks/005930/ticks", "/api/v1/local/stocks/005930/orderbook")  # fmt: skip


def test_all_endpoints_404_when_disabled_even_from_loopback(api):
    for path in PATHS:
        r = _local().get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "FEATURE_DISABLED", path


def test_enabled_but_non_allowed_ip_gets_same_404_not_403(api, monkeypatch):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    monkeypatch.setenv(cfg.APP_KEY_ENV, APP_KEY)
    monkeypatch.setenv(cfg.APP_SECRET_ENV, APP_SECRET)
    for host in ("192.168.0.9", "8.8.8.8"):
        for path in PATHS:
            r = _local(host).get(path)
            assert r.status_code == 404 and r.json()["error"]["code"] == "FEATURE_DISABLED"


def test_forwarded_header_cannot_spoof_allowed_ip(api, monkeypatch):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    r = _local("8.8.8.8").get(PATHS[0], headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"})
    assert r.status_code == 404


@pytest.mark.parametrize(
    "header",
    ["X-Forwarded-For", "X-Real-IP", "Forwarded", "Via", "CF-Connecting-IP", "CF-Ray", "X-Forwarded-Host"],
)
def test_proxied_or_tunneled_requests_are_refused_even_from_loopback(api, monkeypatch, header):
    """터널·리버스 프록시를 거치면 TCP 주소가 127.0.0.1로 보이므로, 프록시 헤더가 있으면 응답하지 않는다."""
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    r = _local().get(PATHS[0], headers={header: "203.0.113.9"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "FEATURE_DISABLED"


def test_public_host_header_is_refused_private_hosts_allowed(api, monkeypatch):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    for bad in ("stock.example.com", "abc.ngrok.io", "8.8.8.8:4001", "evil.com:80"):
        r = _local().get(PATHS[0], headers={"Host": bad})
        assert r.status_code == 404, bad
    for good in ("localhost:4001", "127.0.0.1:4001", "192.168.0.12:4001", "[::1]:4001", "localhost"):
        r = _local().get(PATHS[0], headers={"Host": good})
        assert r.status_code == 200, good


@pytest.mark.parametrize(
    "value,expected",
    [("localhost", True), ("LOCALHOST:8000", True), ("127.0.0.1", True), ("10.0.0.5:1", True),
     ("172.20.1.1", True), ("172.32.1.1", False), ("8.8.8.8", False), ("", False), (None, False),
     ("localhost.evil.com", False), ("[::1]:4001", True), ("[2606:4700::1111]:4001", False)],
)  # fmt: skip
def test_host_header_is_private(value, expected):
    assert cfg.host_header_is_private(value) is expected


def test_enabled_without_keys_is_503_not_configured(api, monkeypatch):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    r = _local().get(PATHS[3])
    assert r.status_code == 503 and r.json()["error"]["code"] == "LOCAL_INTRADAY_NOT_CONFIGURED"
    assert r.headers["cache-control"] == "no-store"


def test_misconfigured_base_url_is_503_without_leaking_values(api, monkeypatch):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    monkeypatch.setenv(cfg.BASE_URL_ENV, "https://evil.example.com/steal")
    r = _local().get(PATHS[0])
    assert r.status_code == 503 and r.json()["error"]["code"] == "LOCAL_INTRADAY_MISCONFIGURED"
    assert "evil.example.com" not in r.text


def test_hostile_codes_and_intervals_rejected_without_upstream_call(api, monkeypatch):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    monkeypatch.setenv(cfg.APP_KEY_ENV, APP_KEY)
    monkeypatch.setenv(cfg.APP_SECRET_ENV, APP_SECRET)

    class Boom:
        def __getattr__(self, name):
            raise AssertionError("증권사를 호출하면 안 된다")

    monkeypatch.setattr(local_intraday, "KisClient", lambda settings: Boom())
    c = _local()
    for code in ("1'; DROP TABLE x;--", "ABCDEFG", "../etc", "%00"):
        r = c.get(f"/api/v1/local/stocks/{code}/orderbook")
        assert r.status_code in (404, 422) and "DROP" not in r.text
    r = c.get("/api/v1/local/stocks/005930/minutes", params={"interval": 7})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PARAMETER"
    assert c.get("/api/v1/local/stocks/005930/ticks", params={"limit": 100000}).status_code == 400


def test_end_to_end_with_mock_kis_and_error_mapping(api, monkeypatch, tmp_path):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    monkeypatch.setenv(cfg.APP_KEY_ENV, APP_KEY)
    monkeypatch.setenv(cfg.APP_SECRET_ENV, APP_SECRET)
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        if req.url.path.endswith("inquire-asking-price-exp-ccn"):
            return httpx.Response(200, json={"rt_cd": "0", "output1": {
                "aspr_acpt_hour": "101500", "askp1": "1001", "askp_rsqn1": "7",
                "bidp1": "1000", "bidp_rsqn1": "9", "total_askp_rsqn": "70", "total_bidp_rsqn": "90"},
                "output2": {}})  # fmt: skip
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "E", "msg1": "거절"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        local_intraday, "KisClient", lambda settings: KisClient(settings, http, min_interval=0)
    )
    c = _local()
    assert c.get(PATHS[0]).json()["data"] == {"enabled": True, "provider": "KIS", "configured": True}
    book = c.get(PATHS[3]).json()["data"]
    assert book["asks"] == [{"price": 1001, "quantity": 7}] and book["time"] == "10:15:00"
    r = c.get(PATHS[2])  # 증권사가 거절 → 502 INTRADAY_UPSTREAM_ERROR, 비밀·원문 비노출
    assert r.status_code == 502 and r.json()["error"]["code"] == "INTRADAY_UPSTREAM_ERROR"
    for secret in (APP_KEY, APP_SECRET):
        assert secret not in r.text
    assert all(APP_SECRET not in json.dumps(dict(q.url.params)) for q in seen)  # 쿼리에 시크릿 없음


def test_local_paths_use_separate_rate_limit_bucket(api, monkeypatch):
    monkeypatch.setenv(cfg.ENABLED_ENV, "true")
    c = _local()
    for _ in range(100):  # 일반 한도(60)를 넘어도 로컬 경로는 별도 버킷이라 막히지 않는다
        assert c.get(PATHS[0]).status_code != 429
    # 일반 경로의 한도는 영향받지 않는다
    assert _local().get("/api/v1/health").status_code != 429
