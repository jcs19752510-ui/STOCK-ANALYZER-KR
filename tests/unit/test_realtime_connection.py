"""실시간 연결 관리자 시험 — 실제 웹소켓(모의 증권사 서버)으로 연결·구독·재연결·해지를 검증한다 (DEC-084)."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from services.public_api.intraday.config import IntradaySettings
from services.public_api.realtime import protocol as p
from services.public_api.realtime.connection import CapacityError, KisWsManager

_spec = importlib.util.spec_from_file_location("mock_kis_ws_server", Path(__file__).resolve().parents[2] / "scripts" / "mock_kis_ws_server.py")
mock = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["mock_kis_ws_server"] = mock
_spec.loader.exec_module(mock)  # type: ignore[union-attr]


def settings(port: int) -> IntradaySettings:
    return IntradaySettings(
        enabled=True, app_key="APPKEY", app_secret="APPSECRET", base_url="http://mock", allowed_networks=(),
        token_cache_path=Path("unused"), ws_url=f"ws://127.0.0.1:{port}",
    )


def approval_http(key: str = "mock-approval", status: int = 200, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(json.loads(request.content))
        return httpx.Response(status, json={"approval_key": key} if status == 200 else {"error": "x"})

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def until(pred, timeout: float = 5.0) -> None:
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("조건이 시간 안에 충족되지 않았습니다")
        await asyncio.sleep(0.01)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


class Rig:
    def __init__(self, **mgr_kwargs):
        self.frames: list[p.DataFrame] = []
        self.states: list[tuple[str, str | None]] = []
        self.mgr_kwargs = mgr_kwargs
        self.server = mock.MockKisWsServer()
        self.http_calls: list = []

    async def __aenter__(self):
        port = await self.server.start()
        kwargs = {"grace": 0.05, "backoff_min": 0.02, "backoff_max": 0.1, "jitter": 0.0, "http_factory": approval_http(calls=self.http_calls)}
        kwargs.update(self.mgr_kwargs)
        self.mgr = KisWsManager(settings(port), self.frames.append, lambda s, d: self.states.append((s, d)), **kwargs)
        self.mgr.start()
        return self

    async def __aexit__(self, *exc):
        await self.mgr.stop()
        await self.server.stop()


def test_연결하면_체결과_호가를_구독하고_데이터를_받는다() -> None:
    async def scenario() -> None:
        async with Rig() as rig:
            rig.mgr.add("005930")
            await until(lambda: rig.server.subscriptions == {(p.TR_TRADE, "005930"), (p.TR_BOOK, "005930")})
            assert rig.mgr.state == "connected"
            assert {r["tr_id"] for r in rig.server.received} == {p.TR_TRADE, p.TR_BOOK}
            assert all(r["custtype"] == "P" and r["tr_type"] == "1" for r in rig.server.received)
            await rig.server.emit(p.TR_TRADE, mock.trade_values("005930", "093001", 70500, 30, 1000))
            await until(lambda: rig.frames)
            trade = p.parse_trade(rig.frames[0].records[0])
            assert trade is not None and trade.price == 70500 and trade.code == "005930"
            # 접속키 발급 요청은 공식 필드 이름으로 한 번만
            assert rig.http_calls == [{"grant_type": "client_credentials", "appkey": "APPKEY", "secretkey": "APPSECRET"}]

    run(scenario())


def test_종목이_없으면_연결하지_않는다() -> None:
    async def scenario() -> None:
        async with Rig() as rig:
            await asyncio.sleep(0.15)
            assert rig.mgr.state == "idle" and rig.server.connect_count == 0 and rig.http_calls == []

    run(scenario())


def test_연결된_뒤_종목을_더하고_빼면_구독이_따라온다() -> None:
    async def scenario() -> None:
        async with Rig() as rig:
            rig.mgr.add("005930")
            await until(lambda: rig.mgr.state == "connected")
            rig.mgr.add("000660")
            await until(lambda: (p.TR_TRADE, "000660") in rig.server.subscriptions and (p.TR_BOOK, "000660") in rig.server.subscriptions)
            rig.mgr.remove("000660")  # 해지는 유예(0.05초) 뒤
            assert (p.TR_TRADE, "000660") in rig.server.subscriptions
            await until(lambda: (p.TR_TRADE, "000660") not in rig.server.subscriptions)
            assert (p.TR_TRADE, "005930") in rig.server.subscriptions
            assert any(r["tr_type"] == "2" and r["tr_key"] == "000660" for r in rig.server.received)

    run(scenario())


def test_같은_종목을_여러_번_열어도_구독은_하나이고_마지막이_닫혀야_해지된다() -> None:
    async def scenario() -> None:
        async with Rig() as rig:
            rig.mgr.add("005930")
            rig.mgr.add("005930")
            await until(lambda: rig.mgr.state == "connected")
            await until(lambda: len(rig.server.subscriptions) == 2)
            assert sum(1 for r in rig.server.received if r["tr_type"] == "1" and r["tr_id"] == p.TR_TRADE) == 1
            rig.mgr.remove("005930")
            await asyncio.sleep(0.2)
            assert (p.TR_TRADE, "005930") in rig.server.subscriptions  # 아직 한 화면이 보고 있다
            rig.mgr.remove("005930")
            await until(lambda: not rig.server.subscriptions)

    run(scenario())


def test_해지_유예_중에_다시_열면_구독을_유지한다() -> None:
    async def scenario() -> None:
        async with Rig(grace=0.3) as rig:
            rig.mgr.add("005930")
            await until(lambda: len(rig.server.subscriptions) == 2)
            rig.mgr.remove("005930")
            rig.mgr.add("005930")  # 새로고침처럼 곧바로 다시 연다
            await asyncio.sleep(0.5)
            assert len(rig.server.subscriptions) == 2
            assert not any(r["tr_type"] == "2" for r in rig.server.received)

    run(scenario())


def test_종목_한도를_넘으면_거절한다() -> None:
    async def scenario() -> None:
        async with Rig() as rig:
            for i in range(p.MAX_CODES):
                rig.mgr.add(f"{i:06d}")
            with pytest.raises(CapacityError):
                rig.mgr.add("999999")
            assert "999999" not in rig.mgr.codes
            # 해지 대기 중인 종목이 있으면 그 자리를 쓴다
            rig.mgr.remove("000000")
            rig.mgr.add("999999")
            assert "999999" in rig.mgr.codes and "000000" not in rig.mgr.codes

    run(scenario())


def test_연결이_끊기면_다시_연결하고_구독을_복구한다() -> None:
    async def scenario() -> None:
        async with Rig() as rig:
            rig.mgr.add("005930")
            await until(lambda: len(rig.server.subscriptions) == 2)
            await rig.server.drop_all()
            await until(lambda: rig.mgr.state == "reconnecting" or rig.server.connect_count >= 2)
            await until(lambda: rig.server.connect_count >= 2 and len(rig.server.subscriptions) == 2)
            assert rig.mgr.state == "connected"
            await rig.server.emit(p.TR_TRADE, mock.trade_values("005930", "093002", 70600, 10, 1010))
            await until(lambda: rig.frames)

    run(scenario())


def test_접속키_발급이_실패하면_다시_시도한다() -> None:
    async def scenario() -> None:
        async with Rig(http_factory=approval_http(status=401)) as rig:
            rig.mgr.add("005930")
            await until(lambda: rig.mgr.last_error is not None and "AUTH_FAILED" in rig.mgr.last_error)
            assert rig.server.connect_count == 0 and rig.mgr.state in ("reconnecting", "connecting")
            assert "APPSECRET" not in (rig.mgr.last_error or "")

    run(scenario())


def test_잘못된_접속키_응답이면_접속키를_버리고_다시_연결한다() -> None:
    async def scenario() -> None:
        calls: list = []
        async with Rig(http_factory=approval_http(key="WRONG", calls=calls)) as rig:
            rig.mgr.add("005930")
            await until(lambda: rig.mgr.last_error is not None and "OPSP0011" in rig.mgr.last_error)
            # 무효한 키를 계속 쓰지 않는다: 거절 뒤 다시 연결할 때마다 접속키를 새로 받는다
            await until(lambda: len(calls) >= 3 and rig.server.connect_count >= 3)

    run(scenario())


class FakeWs:
    def __init__(self, items):
        self.items = list(items)
        self.pongs: list = []

    async def recv(self):
        if not self.items:
            await asyncio.sleep(10)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def pong(self, data):
        self.pongs.append(data)


def test_PINGPONG에는_같은_내용으로_pong을_보낸다() -> None:
    async def scenario() -> None:
        mgr = KisWsManager(settings(1), lambda f: None, watchdog=0.05)
        ping = json.dumps({"header": {"tr_id": "PINGPONG", "datetime": "20261006101010"}})
        ws = FakeWs([ping, ping])
        with pytest.raises(TimeoutError):  # 더 올 것이 없으면 무수신 감시(0.05초)가 끝낸다
            await mgr._reader(ws)
        assert ws.pongs == [ping, ping]

    run(scenario())


def test_일정_시간_아무것도_못_받으면_재연결하도록_예외로_끝난다() -> None:
    async def scenario() -> None:
        mgr = KisWsManager(settings(1), lambda f: None, watchdog=0.05)
        with pytest.raises(TimeoutError):
            await mgr._reader(FakeWs([]))

    run(scenario())


def test_데이터_처리가_실패해도_연결은_유지한다() -> None:
    async def scenario() -> None:
        calls = []

        def boom(frame) -> None:
            calls.append(frame)
            raise ValueError("처리 실패")

        mgr = KisWsManager(settings(1), boom, watchdog=0.05)
        good = "0|H0UNCNT0|001|" + "^".join(["x"] * len(p.TRADE_FIELDS))
        with pytest.raises(TimeoutError):
            await mgr._reader(FakeWs([good, good]))
        assert len(calls) == 2  # 첫 건 실패 뒤에도 다음 건을 계속 받았다

    run(scenario())


def test_구독_오류_응답은_기록하되_연결은_끊지_않는다() -> None:
    async def scenario() -> None:
        mgr = KisWsManager(settings(1), lambda f: None, watchdog=0.05)
        err = json.dumps({"header": {"tr_id": "H0UNCNT0", "tr_key": "005930"}, "body": {"rt_cd": "1", "msg_cd": "OPSP0008", "msg1": "MAX SUBSCRIBE OVER"}})
        with pytest.raises(TimeoutError):
            await mgr._reader(FakeWs([err]))
        assert mgr.last_error == "OPSP0008: MAX SUBSCRIBE OVER"

    run(scenario())
