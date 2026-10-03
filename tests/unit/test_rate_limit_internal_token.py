"""프론트 서버 내부 호출의 최종 사용자 IP 식별(DEC-045, R1) 단위 테스트.

TestClient의 TCP peer는 항상 같은 주소("testclient")라, 헤더가 키를 바꾸는지로 신뢰 경계를 검증한다.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from services.public_api.rate_limit import RateLimitMiddleware, reset_rate_limit_state

TOKEN = "s3cret-internal-token"


async def _ok(request):
    return PlainTextResponse("ok")


def _client(limit: int = 3, internal_limit: int = 10) -> TestClient:
    app = Starlette(routes=[Route("/ping", _ok)])
    app.add_middleware(
        RateLimitMiddleware, limit=limit, window_seconds=60, internal_limit=internal_limit
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_rate_limit_state()
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", TOKEN)
    yield
    reset_rate_limit_state()


def _hdr(ip: str | None, token: str | None = TOKEN) -> dict[str, str]:
    h: dict[str, str] = {}
    if token is not None:
        h["X-Internal-Token"] = token
    if ip is not None:
        h["X-End-User-IP"] = ip
    return h


def test_valid_token_counts_each_end_user_separately():
    client = _client(limit=3)
    for _ in range(3):
        assert client.get("/ping", headers=_hdr("203.0.113.1")).status_code == 200
    assert client.get("/ping", headers=_hdr("203.0.113.1")).status_code == 429
    # 다른 방문자는 같은 서버 IP에서 와도 독립 예산
    assert client.get("/ping", headers=_hdr("203.0.113.2")).status_code == 200


def test_ip_header_without_token_is_ignored_spoof_proof():
    client = _client(limit=3)
    for i in range(3):
        assert client.get("/ping", headers=_hdr(f"198.51.100.{i}", token=None)).status_code == 200
    # 매번 다른 IP를 주장해도 peer 기준 하나로 집계 → 4번째 차단
    assert client.get("/ping", headers=_hdr("198.51.100.99", token=None)).status_code == 429


def test_wrong_token_is_ignored():
    client = _client(limit=2)
    for i in range(2):
        resp = client.get("/ping", headers=_hdr(f"198.51.100.{i}", token="wrong"))
        assert resp.status_code == 200
    blocked = client.get("/ping", headers=_hdr("198.51.100.50", token="wrong"))
    assert blocked.status_code == 429


def test_feature_off_when_env_token_unset(monkeypatch):
    monkeypatch.delenv("PUBLIC_API_INTERNAL_TOKEN", raising=False)
    client = _client(limit=2)
    for i in range(2):
        assert client.get("/ping", headers=_hdr(f"198.51.100.{i}", token="")).status_code == 200
    assert client.get("/ping", headers=_hdr("198.51.100.9", token="")).status_code == 429


@pytest.mark.parametrize("bad_ip", [None, "", "not-an-ip", "999.1.1.1", "1.2.3.4, 5.6.7.8"])
def test_valid_token_without_valid_ip_uses_shared_fallback_bucket(bad_ip):
    client = _client(limit=3, internal_limit=5)
    for _ in range(5):
        assert client.get("/ping", headers=_hdr(bad_ip)).status_code == 200
    assert client.get("/ping", headers=_hdr(bad_ip)).status_code == 429


def test_fallback_bucket_does_not_consume_end_user_budget():
    client = _client(limit=3, internal_limit=2)
    for _ in range(2):
        client.get("/ping", headers=_hdr(None))
    assert client.get("/ping", headers=_hdr(None)).status_code == 429
    assert client.get("/ping", headers=_hdr("203.0.113.1")).status_code == 200


def test_ipv6_end_user_supported():
    client = _client(limit=1)
    assert client.get("/ping", headers=_hdr("2001:db8::1")).status_code == 200
    assert client.get("/ping", headers=_hdr("2001:db8::1")).status_code == 429
    assert client.get("/ping", headers=_hdr("2001:db8::2")).status_code == 200
