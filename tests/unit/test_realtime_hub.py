"""실시간 허브(최신 상태·1분봉·구독자 버퍼) 시험 — DEC-084."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio

from services.public_api.realtime import hub as h
from services.public_api.realtime import protocol as p
from services.public_api.schemas.intraday import BookLevel, OrderBookData


def trade(time: str = "09:30:01", price: float = 70500, volume: int = 30, acml: int | None = 1000, date: str | None = "20261006") -> p.Trade:
    return p.Trade(
        code="005930", time=time, price=price, change=500, change_pct=0.7, open=70000, high=70600, low=69900, ask1=price + 100, bid1=price,
        volume=volume, acml_volume=acml, acml_value=(acml or 0) * 70000, strength=100.0, side="1", business_date=date, halted=False, vi_price=None,
    )


def bar(t: str, o: float, hi: float, lo: float, c: float, v: int) -> dict:
    return {"time": t, "open": o, "high": hi, "low": lo, "close": c, "volume": v}


def test_체결_하나가_틱_분봉_시세_이벤트를_만든다() -> None:
    st = h.CodeState("005930")
    events = st.apply_trade(trade())
    assert [e for e, _ in events] == ["tick", "bar", "quote"]
    tick, b, quote = (d for _, d in events)
    assert tick["price"] == 70500 and tick["volume"] == 30 and tick["time"] == "09:30:01"
    assert b == {"time": "09:30", "open": 70500, "high": 70500, "low": 70500, "close": 70500, "volume": 30}
    assert quote["price"] == 70500 and quote["acml_volume"] == 1000 and quote["halted"] is False


def test_분봉_거래량은_누적_거래량_차이로_만든다() -> None:
    st = h.CodeState("005930")
    st.apply_trade(trade("09:30:01", 70500, 30, 1000))
    st.apply_trade(trade("09:30:20", 70700, 10, 1010))
    # 사이의 체결(누적 1010→1050 중 일부)이 누락돼도 누적이 맞도록 다음 체결에 합산된다
    events = st.apply_trade(trade("09:30:40", 70400, 5, 1050))
    b = dict(events)["bar"]
    assert (b["open"], b["high"], b["low"], b["close"], b["volume"]) == (70500, 70700, 70400, 70400, 30 + 10 + 40)
    nxt = dict(st.apply_trade(trade("09:31:05", 70450, 20, 1070)))["bar"]
    assert nxt["time"] == "09:31" and nxt["open"] == 70450 and nxt["volume"] == 20


def test_같은_체결과_오래된_체결은_무시한다() -> None:
    st = h.CodeState("005930")
    assert st.apply_trade(trade("09:30:01", 70500, 30, 1000))
    assert st.apply_trade(trade("09:30:01", 70500, 30, 1000)) == []  # 완전히 같은 체결(재전송)
    assert st.apply_trade(trade("09:30:00", 70400, 5, 990)) == []  # 누적이 더 작은 늦은 체결
    assert len(st.ticks) == 1


def test_시작_값과_이어_붙이기_기준선이_맞으면_시작_합계를_쓴다() -> None:
    st = h.CodeState("005930")
    st.seed([bar("09:00", 70000, 70100, 69900, 70050, 600), bar("09:01", 70050, 70200, 70000, 70150, 400)], [])
    assert st.seed_total == 1000
    # 첫 실시간 체결의 누적 1040, 체결량 30 → 기준선 1010 ≈ 시작 합계 1000(오차 이내) → 그 사이 놓친 10도 이번 봉에 합산
    b = dict(st.apply_trade(trade("09:01:30", 70300, 30, 1040)))["bar"]
    assert b["time"] == "09:01" and b["volume"] == 400 + 40 and b["high"] == 70300 and b["close"] == 70300
    assert st.covered == 1040


def test_시작_값과_크게_어긋나면_첫_체결의_기준선을_쓴다() -> None:
    st = h.CodeState("005930")
    st.seed([bar("09:00", 70000, 70100, 69900, 70050, 100)], [])  # 시작 합계 100, 실제 누적은 훨씬 큼(시간외·NXT 거래량 등)
    b = dict(st.apply_trade(trade("09:01:30", 70300, 30, 900_000)))["bar"]
    assert b["volume"] == 30  # 기준선 = 누적 − 이번 체결량 → 이번 체결량만 더한다(거래량 폭증 방지)


def test_시작_값_없이도_동작한다() -> None:
    st = h.CodeState("005930")
    assert st.seeded is False
    b = dict(st.apply_trade(trade(volume=30, acml=5000)))["bar"]
    assert b["volume"] == 30


def test_누적_거래량이_없으면_체결량을_쓴다() -> None:
    st = h.CodeState("005930")
    st.apply_trade(trade("09:30:01", 70500, 30, None))
    b = dict(st.apply_trade(trade("09:30:02", 70600, 20, None)))["bar"]
    assert b["volume"] == 50


def test_새_거래일이면_어제_값을_버린다() -> None:
    st = h.CodeState("005930")
    st.seed([bar("15:29", 70000, 70100, 69900, 70050, 600)], [{"time": "15:29:59", "price": 70050, "change": 0, "change_pct": 0, "volume": 1, "strength": 100.0}])
    st.business_date = "20261002"
    events = st.apply_trade(trade("09:00:01", 71000, 10, 10, date="20261006"))
    assert st.business_date == "20261006" and st.live_date == "20261006" and list(st.bars) == ["09:00"] and len(st.ticks) == 1
    # 구독자에게는 개별 이벤트가 아니라 새 날 상태 전체(snapshot) 하나로 알린다
    assert [e for e, _ in events] == ["snapshot"]
    snap = dict(events)["snapshot"]
    assert snap["business_date"] == "20261006" and [b["time"] for b in snap["bars"]] == ["09:00"] and snap["bars"][0]["volume"] == 10 and snap["quote"]["price"] == 71000
    assert len(snap["ticks"]) == 1


def test_거래일_변경_스냅샷은_구독자_버퍼에서_이전_날_이벤트보다_앞서고_이전_날_대기분을_버린다() -> None:
    async def scenario() -> None:
        sub = h.Subscriber("005930")
        sub.push("tick", {"time": "15:29:59"})
        sub.push("bar", {"time": "15:29"})
        sub.push("quote", {"price": 1})
        sub.push("book", {"x": 1})
        sub.push("status", {"connection": "connected"})
        sub.push("snapshot", {"business_date": "20261007"})
        sub.push("tick", {"time": "09:00:01"})  # 새 날 체결은 스냅샷 뒤에 그대로 온다
        out = sub.drain()
        assert [e for e, _ in out] == ["snapshot", "tick", "status"]
        assert out[1][1]["time"] == "09:00:01"

    asyncio.run(scenario())


def test_첫_체결로_날짜를_알기_전에는_live_date가_비어_있다() -> None:
    st = h.CodeState("005930")
    st.seed([bar("09:00", 1, 2, 1, 2, 7)], [])
    assert st.live_date is None and st.business_date is None
    st.apply_trade(trade())
    assert st.live_date == "20261006"


def test_이미_실시간을_받은_뒤_시작_값은_합치고_첫_현재가는_실시간이_없을_때만_쓴다() -> None:
    st = h.CodeState("005930")
    st.apply_trade(trade("09:01:05", 70900, 25, 1025))
    live = dict(st.bars["09:01"])
    live_quote = dict(st.quote)
    ticks_before = list(st.ticks)
    st.seed([bar("09:00", 1, 2, 1, 2, 600), bar("09:01", 1, 2, 1, 2, 999)], [{"time": "09:00:30", "price": 1}], {"price": 123, "time": ""})
    assert st.bars["09:01"] == live and st.bars["09:00"]["volume"] == 600 and list(st.bars) == ["09:00", "09:01"]
    assert st.quote == live_quote and list(st.ticks) == ticks_before and st.seeded is True
    fresh = h.CodeState("005930")
    fresh.seed([], [], {"price": 123, "time": ""})
    assert fresh.quote["price"] == 123 and fresh.snapshot()["quote"]["price"] == 123


def test_늦게_온_이전_분_체결이_종가를_되돌리지_않는다() -> None:
    st = h.CodeState("005930")
    st.apply_trade(trade("09:30:50", 70500, 30, 1000))
    st.apply_trade(trade("09:31:05", 70700, 10, 1010))
    events = dict(st.apply_trade(trade("09:30:58", 70600, 5, 1015)))  # 09:30 봉에 늦게 도착
    assert st.bars["09:31"]["close"] == 70700
    assert events["bar"]["time"] == "09:30" and events["bar"]["close"] == 70500 and events["bar"]["high"] == 70600


def test_호가는_같으면_다시_보내지_않는다() -> None:
    st = h.CodeState("005930")
    book = OrderBookData(stock_code="005930", time="09:30:01", asks=[BookLevel(price=70600, quantity=10)], bids=[BookLevel(price=70500, quantity=20)], total_ask_quantity=10, total_bid_quantity=20, expected=None)
    assert [e for e, _ in st.apply_book(book)] == ["book"]
    assert st.apply_book(book) == []


def test_스냅샷() -> None:
    st = h.CodeState("005930")
    for i in range(150):
        st.apply_trade(trade(f"09:{30 + i // 60:02d}:{i % 60:02d}", 70000 + i, 1, 1000 + i))
    snap = st.snapshot()
    assert len(snap["ticks"]) == h.SNAPSHOT_TICKS and snap["ticks"][0]["price"] == 70149  # 최신이 앞
    assert [b["time"] for b in snap["bars"]] == sorted(b["time"] for b in snap["bars"])
    assert snap["business_date"] == "20261006" and snap["seeded"] is False


def test_구독자_버퍼는_최신값만_남긴다() -> None:
    async def scenario() -> None:
        sub = h.Subscriber("005930")
        sub.push("quote", {"price": 1})
        sub.push("quote", {"price": 2})
        sub.push("book", {"x": 1})
        sub.push("bar", {"time": "09:30", "close": 1})
        sub.push("bar", {"time": "09:30", "close": 2})
        sub.push("bar", {"time": "09:31", "close": 3})
        for i in range(3):
            sub.push("tick", {"n": i})
        out = sub.drain()
        assert [e for e, _ in out][:3] == ["tick", "tick", "tick"]  # 체결은 순서대로 모두
        assert [d["close"] for e, d in out if e == "bar"] == [2, 3]  # 같은 분봉은 최신 것만
        assert dict(out)["quote"] == {"price": 2}
        assert sub.drain() == [] and not sub.wake.is_set()

    asyncio.run(scenario())


def test_구독자_체결_버퍼는_상한이_있다() -> None:
    async def scenario() -> None:
        sub = h.Subscriber("005930")
        for i in range(h.SUBSCRIBER_TICK_BUFFER + 100):
            sub.push("tick", {"n": i})
        out = sub.drain()
        assert len(out) == h.SUBSCRIBER_TICK_BUFFER and out[-1][1]["n"] == h.SUBSCRIBER_TICK_BUFFER + 99  # 오래된 것부터 버린다

    asyncio.run(scenario())


def test_허브_발행과_정리() -> None:
    async def scenario() -> None:
        hub = h.RealtimeHub()
        hub.state("005930")
        a, b = hub.subscribe("005930"), hub.subscribe("005930")
        hub.publish("005930", [("quote", {"price": 1})])
        assert a.drain() and b.drain()
        hub.broadcast("status", {"connection": "reconnecting"})
        assert dict(a.drain())["status"]["connection"] == "reconnecting"
        hub.unsubscribe(a)
        a.push("quote", {"price": 9})  # 닫힌 구독자는 받지 않는다
        assert a.drain() == [] and hub.subscriber_count("005930") == 1
        hub.drop_state("005930")  # 구독자가 남아 있으면 상태를 지우지 않는다
        assert hub.has_state("005930")
        hub.unsubscribe(b)
        hub.drop_state("005930")
        assert not hub.has_state("005930") and hub.subscriber_count() == 0

    asyncio.run(scenario())
