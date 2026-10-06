"""실시간 스트림 API(SSE) 시험 — 실제 uvicorn 서버 + 모의 증권사(REST·웹소켓)로 끝까지 검증한다 (DEC-084)."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import functools
import json
import sys
import threading
import types
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.requests import Request
from test_realtime_connection import mock, until  # noqa: F401

from services.public_api.api import local_intraday, local_realtime
from services.public_api.errors import ApiError
from services.public_api.intraday import config as cfg
from services.public_api.intraday.kis_client import KisClient
from services.public_api.realtime import protocol as p

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import mock_kis_server  # noqa: E402


class Stack:
    """모의 REST + 모의 웹소켓 + 실제 API 서버(uvicorn, 별도 스레드)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
        self.mp = monkeypatch
        self.env = env
        self.ws = mock.MockKisWsServer()

    async def __aenter__(self) -> Stack:
        self.rest = ThreadingHTTPServer(("127.0.0.1", 0), mock_kis_server.Handler)
        threading.Thread(target=self.rest.serve_forever, daemon=True).start()
        ws_port = await self.ws.start()
        base = {
            "LOCAL_INTRADAY_ENABLED": "true", "KIS_APP_KEY": "mock", "KIS_APP_SECRET": "mock", "KIS_ALLOW_CUSTOM_BASE_URL": "true",
            "KIS_BASE_URL": f"http://127.0.0.1:{self.rest.server_address[1]}", "KIS_WS_URL": f"ws://127.0.0.1:{ws_port}",
            "KIS_REALTIME_GRACE_SECONDS": "0.2", "KIS_TOKEN_CACHE_PATH": str(Path("/tmp/claude-0") / "rt-test-token.json"),
        }
        base.update(self.env)
        for k, v in base.items():
            self.mp.setenv(k, v)
        local_intraday.reset_intraday_service()
        local_realtime.reset_realtime_service()
        from services.public_api.main import app

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        await until(lambda: self.server.started, 10)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        return self

    async def __aexit__(self, *exc) -> None:
        self.server.should_exit = True
        await asyncio.to_thread(self.thread.join, 10)
        self.rest.shutdown()
        await self.ws.stop()
        local_intraday.reset_intraday_service()
        local_realtime.reset_realtime_service()


class SseReader:
    """SSE 응답을 이어서 읽는다(한 응답에서 여러 번 `until`을 부를 수 있다)."""

    def __init__(self, resp: httpx.Response) -> None:
        self._it = resp.aiter_text().__aiter__()
        self._buf = ""

    async def until(self, want: set[str], timeout: float = 8.0) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []

        async def read() -> None:
            while True:
                while "\n\n" in self._buf:
                    block, self._buf = self._buf.split("\n\n", 1)
                    name, data = None, None
                    for line in block.splitlines():
                        if line.startswith("event:"):
                            name = line[6:].strip()
                        elif line.startswith("data:"):
                            data = json.loads(line[5:].strip())
                    if name and data is not None:
                        out.append((name, data))
                if want <= {n for n, _ in out}:
                    return
                self._buf += await self._it.__anext__()

        await asyncio.wait_for(read(), timeout)
        return out


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 40))


def test_스트림은_스냅샷을_보내고_실시간_체결_호가를_밀어준다() -> None:
    async def scenario(mp) -> None:
        async with Stack(mp) as s, httpx.AsyncClient(base_url=s.url, timeout=None) as c:
            async with c.stream("GET", "/api/v1/local/stocks/005930/stream") as resp:
                assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
                assert "no-store" in resp.headers["cache-control"]
                reader = SseReader(resp)
                snap = dict(await reader.until({"snapshot"}))["snapshot"]
                assert snap["code"] == "005930" and snap["seeded"] is True and snap["bars"] and snap["ticks"]
                await until(lambda: len(s.ws.subscriptions) == 2)
                last_acml = max(t.get("acml_volume") or 0 for t in snap["ticks"])
                await s.ws.emit(p.TR_TRADE, mock.trade_values("005930", "153100", 91234, 17, 99_999_999, prev_close=90000))  # 모의 분봉이 15:30까지 있어 그 뒤 시각을 쓴다
                await s.ws.emit(p.TR_BOOK, mock.book_values("005930", "153100", 91234))
                got = dict(await reader.until({"tick", "quote", "book", "bar"}))
                assert got["quote"]["price"] == 91234 and got["quote"]["change"] == 1234 and got["tick"]["volume"] >= 1
                assert got["book"]["asks"][0]["price"] == 91234 + mock._tick_size(91234)
                assert got["bar"]["time"] == "15:31" and got["bar"]["close"] == 91234 and last_acml < 99_999_999

    run_with_mp(scenario)


def run_with_mp(scenario) -> None:
    mp = pytest.MonkeyPatch()
    try:
        run(scenario(mp))
    finally:
        mp.undo()


def test_화면을_닫으면_유예_뒤_증권사_구독이_해지된다() -> None:
    async def scenario(mp) -> None:
        async with Stack(mp) as s, httpx.AsyncClient(base_url=s.url, timeout=None) as c:
            async with c.stream("GET", "/api/v1/local/stocks/005930/stream") as resp:
                await SseReader(resp).until({"snapshot"})
                await until(lambda: len(s.ws.subscriptions) == 2)
            # 연결을 닫음 → 서버가 감지해 구독자를 정리하고 0.2초 유예 뒤 증권사 구독을 해지한다
            await until(lambda: not s.ws.subscriptions, 10)
            assert any(r["tr_type"] == "2" for r in s.ws.received)

    run_with_mp(scenario)


def test_동시_종목_한도를_넘으면_429() -> None:
    async def scenario(mp) -> None:
        # 시작 값 조회의 호출 간격(실서버용 0.12초)을 시험에서만 없앤다 — 종목 20개를 여는 데 걸리는 시간을 줄이기 위해
        mp.setattr(local_intraday, "KisClient", functools.partial(KisClient, min_interval=0.0))
        async with Stack(mp) as s, httpx.AsyncClient(base_url=s.url, timeout=None) as c:
            opened = []
            try:
                for i in range(p.MAX_CODES):
                    cm = c.stream("GET", f"/api/v1/local/stocks/{i:06d}/stream")
                    resp = await cm.__aenter__()
                    opened.append((cm, resp))
                    assert resp.status_code == 200
                over = await c.get("/api/v1/local/stocks/999999/stream")
                assert over.status_code == 429 and over.json()["error"]["code"] == "REALTIME_CAPACITY"
                status = (await c.get("/api/v1/local/realtime/status")).json()["data"]
                assert status["configured"] is True and len(status["codes"]) == p.MAX_CODES and status["capacity"] == p.MAX_CODES
            finally:
                for cm, _ in opened:
                    await cm.__aexit__(None, None, None)

    run_with_mp(scenario)


def test_접근_통제는_존재를_드러내지_않는다() -> None:
    async def scenario(mp) -> None:
        async with Stack(mp) as s, httpx.AsyncClient(base_url=s.url, timeout=10) as c:
            path = "/api/v1/local/stocks/005930/stream"
            # 공개 도메인 Host
            assert (await c.get(path, headers={"Host": "stock.example.com"})).status_code == 404
            # 프록시·터널이 붙이는 헤더
            for h in ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded"):
                assert (await c.get(path, headers={h: "1.2.3.4"})).status_code == 404, h
            # 잘못된 종목코드
            assert (await c.get("/api/v1/local/stocks/ABC/stream")).status_code in (400, 404, 422)
            assert s.ws.connect_count == 0  # 거절된 요청은 증권사에 연결하지 않는다

    run_with_mp(scenario)


def test_기능이_꺼져_있으면_404_앱키가_없으면_503() -> None:
    async def off(mp) -> None:
        async with Stack(mp, LOCAL_INTRADAY_ENABLED="false") as s, httpx.AsyncClient(base_url=s.url, timeout=10) as c:
            assert (await c.get("/api/v1/local/stocks/005930/stream")).status_code == 404
            assert (await c.get("/api/v1/local/realtime/status")).status_code == 404

    async def nokey(mp) -> None:
        async with Stack(mp, KIS_APP_KEY="", KIS_APP_SECRET="") as s, httpx.AsyncClient(base_url=s.url, timeout=10) as c:
            r = await c.get("/api/v1/local/stocks/005930/stream")
            assert r.status_code == 503 and r.json()["error"]["code"] == "LOCAL_INTRADAY_NOT_CONFIGURED"

    run_with_mp(off)
    run_with_mp(nokey)


# ── 소유자(관리자) 확인: 로그인을 켠 환경 ───────────────────────────────────────
UID = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"


def fake_request(headers: dict[str, str]) -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()], "method": "GET", "path": "/", "query_string": b""})


SETTINGS = cfg.IntradaySettings(enabled=True, app_key="k", app_secret="s", base_url="http://x", allowed_networks=(), token_cache_path=Path("x"))


def test_로그인을_끈_환경에서는_소유자_확인을_건너뛴다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_realtime, "internal_token_enforced", lambda: False)
    assert local_realtime.require_owner(fake_request({}), SETTINGS) is SETTINGS


def test_로그인을_켠_환경에서는_관리자_세션만_통과한다(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.public_api.auth import service as auth_service

    monkeypatch.setattr(local_realtime, "internal_token_enforced", lambda: True)
    closed: list[bool] = []
    session = types.SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(local_realtime, "get_auth_session_factory", lambda: (lambda: session))
    seen: list[tuple] = []

    def fake_require_admin(sess, uid, sid):
        seen.append((uid, sid))
        return object() if uid == UID else None

    monkeypatch.setattr(auth_service, "require_admin", fake_require_admin)
    ok = fake_request({"x-auth-user": UID, "x-auth-session": SID})
    assert local_realtime.require_owner(ok, SETTINGS) is SETTINGS and seen == [(UID, SID)] and closed == [True]  # DB 연결을 바로 반납
    for headers in ({}, {"x-auth-user": "not-uuid", "x-auth-session": SID}, {"x-auth-user": UID}):  # 헤더가 없거나 형식이 틀리면 DB도 보지 않고 거부
        with pytest.raises(ApiError) as exc:
            local_realtime.require_owner(fake_request(headers), SETTINGS)
        assert exc.value.status_code == 403
    other = fake_request({"x-auth-user": "33333333-3333-4333-8333-333333333333", "x-auth-session": SID})  # 관리자가 아닌 회원
    with pytest.raises(ApiError) as exc:
        local_realtime.require_owner(other, SETTINGS)
    assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


def test_스트림이_이어지는_동안_권한이_사라지면_end로_끝낸다() -> None:
    from services.public_api.auth import service as auth_service

    async def scenario(mp) -> None:
        state = {"admin": True}
        mp.setattr(local_realtime, "internal_token_enforced", lambda: True)
        mp.setattr(local_realtime, "get_auth_session_factory", lambda: (lambda: types.SimpleNamespace(close=lambda: None)))
        mp.setattr(auth_service, "require_admin", lambda sess, uid, sid: object() if state["admin"] else None)
        mp.setattr(local_realtime, "RECHECK_SECONDS", 0.3)
        headers = {"x-auth-user": UID, "x-auth-session": SID}
        async with Stack(mp) as s, httpx.AsyncClient(base_url=s.url, timeout=None) as c:
            async with c.stream("GET", "/api/v1/local/stocks/005930/stream", headers=headers) as resp:
                assert resp.status_code == 200
                reader = SseReader(resp)
                await reader.until({"snapshot"})
                state["admin"] = False  # 관리자 권한 회수(또는 로그아웃·사용 중지)
                got = await reader.until({"end"}, timeout=5)
                assert dict(got)["end"] == {"reason": "forbidden"}
            await until(lambda: not s.ws.subscriptions, 10)  # 끝난 스트림은 구독도 정리한다
            denied = await c.get("/api/v1/local/stocks/005930/stream", headers=headers)  # 이제 새 연결도 거부
            assert denied.status_code == 403

    run_with_mp(scenario)
