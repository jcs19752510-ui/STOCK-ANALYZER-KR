"""실시간 서비스(시작 값 + 연결 + 허브 조합) 시험 — DEC-084."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import functools
from datetime import date

import pytest
from test_realtime_connection import Rig, approval_http, mock, run, settings, until  # noqa: F401

from services.public_api.intraday.kis_client import KisError
from services.public_api.realtime import protocol as p
from services.public_api.realtime.connection import CapacityError, KisWsManager
from services.public_api.realtime.service import RealtimeService, make_seed_fetcher
from services.public_api.schemas.intraday import MinuteBar, MinutesData, TickItem, TicksData


def seed_ok(code: str):
    bars = [
        {"time": "09:00", "open": 70000, "high": 70100, "low": 69900, "close": 70050, "volume": 600},
        {"time": "09:01", "open": 70050, "high": 70200, "low": 70000, "close": 70150, "volume": 400},
    ]
    ticks = [{"time": "09:01:50", "price": 70150, "change": 150, "change_pct": 0.21, "volume": 10, "strength": 100.0}]
    return bars, ticks, "20261006"


async def collect(sub, want: set[str], timeout: float = 5.0) -> dict:
    """원하는 이벤트 종류가 모두 모일 때까지 구독자 버퍼를 비우며 모은다(연결 상태 이벤트가 먼저 올 수 있다)."""
    got: dict = {}
    end = asyncio.get_running_loop().time() + timeout
    while not want <= got.keys():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError(f"이벤트가 모이지 않았습니다: {want - got.keys()}")
        got.update(dict(sub.drain()))
        await asyncio.sleep(0.01)
    return got


class ServiceRig:
    def __init__(self, seed=seed_ok, **kw):
        self.server = mock.MockKisWsServer()
        self.seed = seed
        self.kw = kw

    async def __aenter__(self):
        port = await self.server.start()
        factory = functools.partial(KisWsManager, grace=0.05, backoff_min=0.02, backoff_max=0.1, jitter=0.0, http_factory=approval_http(), **self.kw)
        self.svc = RealtimeService(settings(port), self.seed, manager_factory=factory)
        return self

    async def __aexit__(self, *exc):
        await self.svc.stop()
        await self.server.stop()


def test_열면_시작_값_스냅샷을_주고_실시간_체결이_분봉에_이어_붙는다() -> None:
    async def scenario() -> None:
        async with ServiceRig() as rig:
            sub, snap = await rig.svc.open("005930")
            assert snap["seeded"] is True and snap["business_date"] == "20261006"
            assert [b["time"] for b in snap["bars"]] == ["09:00", "09:01"] and snap["ticks"][0]["time"] == "09:01:50"
            await until(lambda: len(rig.server.subscriptions) == 2)
            # 시작 합계 1000. 첫 실시간 체결: 누적 1040, 체결량 30 → 기준선 1010(오차 이내) → 09:01 봉 거래량 400 + 40
            await rig.server.emit(p.TR_TRADE, mock.trade_values("005930", "090130", 70300, 30, 1040, prev_close=70000))
            events = await collect(sub, {"bar", "quote"})
            assert events["bar"]["time"] == "09:01" and events["bar"]["volume"] == 440 and events["bar"]["close"] == 70300
            assert events["quote"]["price"] == 70300 and events["quote"]["change"] == 300
            await rig.server.emit(p.TR_BOOK, mock.book_values("005930", "090131", 70300))
            book = (await collect(sub, {"book"}))["book"]
            assert book["asks"][0]["price"] == 70400 and book["bids"][0]["price"] == 70300 and len(book["asks"]) == 10
            await rig.svc.close(sub)

    run(scenario())


def test_같은_종목을_두_화면이_열어도_증권사_구독은_하나이고_둘_다_받는다() -> None:
    async def scenario() -> None:
        async with ServiceRig() as rig:
            a, _ = await rig.svc.open("005930")
            b, snap = await rig.svc.open("005930")
            assert snap["seeded"] is True
            await until(lambda: len(rig.server.subscriptions) == 2)
            await rig.server.emit(p.TR_TRADE, mock.trade_values("005930", "090130", 70300, 30, 1040))
            assert (await collect(a, {"tick"}))["tick"]["price"] == 70300
            assert (await collect(b, {"tick"}))["tick"]["price"] == 70300
            assert sum(1 for r in rig.server.received if r["tr_type"] == "1" and r["tr_id"] == p.TR_TRADE) == 1
            await rig.svc.close(a)
            await rig.svc.close(b)
            await until(lambda: not rig.server.subscriptions)  # 마지막 화면이 닫히면 유예 뒤 해지
            await until(lambda: not rig.svc.hub.has_state("005930"))  # 메모리 정리

    run(scenario())


def test_구독하지_않은_종목의_체결은_버린다() -> None:
    async def scenario() -> None:
        async with ServiceRig() as rig:
            sub, _ = await rig.svc.open("005930")
            rig.svc._on_data(p.DataFrame(tr_id=p.TR_TRADE, records=(dict(zip(p.TRADE_FIELDS, [str(v) for v in mock.record(p.TRADE_FIELDS, mock.trade_values("000660", "090130", 100000, 5, 500))], strict=True)),)))
            assert sub.drain() == [] and not rig.svc.hub.has_state("000660")
            await rig.svc.close(sub)

    run(scenario())


def test_시작_값_조회가_실패해도_실시간은_계속된다() -> None:
    def failing(code: str):
        raise KisError("UPSTREAM_UNAVAILABLE", "증권사 서버에 연결하지 못했습니다.")

    async def scenario() -> None:
        async with ServiceRig(seed=failing) as rig:
            sub, snap = await rig.svc.open("005930")
            assert snap["seeded"] is False and snap["bars"] == []
            await until(lambda: len(rig.server.subscriptions) == 2)
            await rig.server.emit(p.TR_TRADE, mock.trade_values("005930", "090130", 70300, 30, 1040))
            assert (await collect(sub, {"bar"}))["bar"]["volume"] == 30  # 기준선 = 누적 − 체결량
            await rig.svc.close(sub)

    run(scenario())


def test_종목_한도를_넘으면_열기를_거절하고_구독자를_남기지_않는다() -> None:
    async def scenario() -> None:
        async with ServiceRig() as rig:
            subs = [(await rig.svc.open(f"{i:06d}"))[0] for i in range(p.MAX_CODES)]
            with pytest.raises(CapacityError):
                await rig.svc.open("999999")
            assert rig.svc.hub.subscriber_count("999999") == 0 and not rig.svc.hub.has_state("999999")
            for s in subs:
                await rig.svc.close(s)

    run(scenario())


def test_연결_상태_변화를_화면에_알린다() -> None:
    async def scenario() -> None:
        async with ServiceRig() as rig:
            sub, snap = await rig.svc.open("005930")
            await until(lambda: len(rig.server.subscriptions) == 2)
            sub.drain()
            await rig.server.drop_all()
            await until(lambda: sub.wake.is_set())
            seen = [d["connection"] for e, d in sub.drain() if e == "status"]
            assert seen and seen[-1] in ("reconnecting", "connecting", "connected")
            await until(lambda: len(rig.server.subscriptions) == 2)  # 자동 복구
            await rig.svc.close(sub)

    run(scenario())


def test_시작_값_함수는_REST_결과를_그대로_옮긴다() -> None:
    class FakeIntraday:
        calls: list = []

        def minutes(self, code, interval, *, day, fallback_day):
            assert interval == 1 and day is None
            self.calls.append(fallback_day)
            if fallback_day is None:  # 오늘 분봉이 비어 있으면 직전 거래일로 다시 조회한다
                return MinutesData(stock_code=code, date=date(2026, 10, 6), interval=1, bars=[])
            return MinutesData(stock_code=code, date=fallback_day, interval=1, bars=[MinuteBar(time="09:00", open=1, high=2, low=1, close=2, volume=7)])

        def ticks(self, code, limit):
            assert limit == 120
            return TicksData(stock_code=code, ticks=[TickItem(time="09:00:01", price=2, change=1, change_pct=1.0, volume=3, strength=None)], truncated=False)

    fake = FakeIntraday()
    bars, ticks, d = make_seed_fetcher(fake, lambda: date(2026, 10, 2))("005930")
    assert fake.calls == [None, date(2026, 10, 2)]
    assert bars == [{"time": "09:00", "open": 1.0, "high": 2.0, "low": 1.0, "close": 2.0, "volume": 7}] and ticks[0]["price"] == 2 and d == "20261002"


def test_오늘_분봉이_있으면_직전_거래일_조회를_하지_않는다() -> None:
    class Today:
        def minutes(self, code, interval, *, day, fallback_day):
            return MinutesData(stock_code=code, date=date(2026, 10, 6), interval=1, bars=[MinuteBar(time="09:00", open=1, high=2, low=1, close=2, volume=7)])

        def ticks(self, code, limit):
            return TicksData(stock_code=code, ticks=[], truncated=False)

    def never() -> None:
        raise AssertionError("직전 거래일 조회(DB)를 하면 안 된다")

    bars, _, d = make_seed_fetcher(Today(), never)("005930")
    assert len(bars) == 1 and d == "20261006"


def test_체결_조회만_실패해도_분봉_시작_값은_쓴다() -> None:
    class Partial:
        def minutes(self, code, interval, *, day, fallback_day):
            return MinutesData(stock_code=code, date=date(2026, 10, 6), interval=1, bars=[MinuteBar(time="09:00", open=1, high=2, low=1, close=2, volume=7)])

        def ticks(self, code, limit):
            raise KisError("RATE_LIMITED", "한도")

    bars, ticks, _ = make_seed_fetcher(Partial(), lambda: None)("005930")
    assert len(bars) == 1 and ticks == []
