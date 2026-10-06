"""일봉 보충(DEC-090)·스냅샷 저장소·서비스 시험 — DB·증권사 없이 가짜 주입으로 끝까지."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from services.public_api.live_screen.fill import (
    REASON_MISMATCH,
    REASON_MISSING_DATES,
    REASON_NO_ANCHOR,
    REASON_OK,
    BaseFiller,
    validate_fill,
)
from services.public_api.live_screen.rows import LiveRowsResult
from services.public_api.live_screen.service import (
    LiveScreenError,
    LiveScreenService,
    PublishedContext,
    QuoteState,
    ServiceDeps,
)
from services.public_api.live_screen.snapshot import SnapshotStore
from services.public_api.live_screen.types import DailyBar
from services.public_api.realtime.market import MarketQuote

P, E1, E2 = date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)


def bar(d: date, close: int, vol: int = 10) -> DailyBar:
    c = Decimal(close)
    return DailyBar(d, c, c, c, c, vol)


# ── validate_fill ──────────────────────────────────────────────────────────────────────
def test_validate_fill_ok_returns_only_needed_dates_sorted():
    kis = [bar(E2, 12), bar(P, 10), bar(E1, 11), bar(date(2026, 9, 29), 9)]
    bars, reason = validate_fill(kis, bar(P, 10), [E2, E1])
    assert reason == REASON_OK and [b.trade_date for b in bars] == [E1, E2]


@pytest.mark.parametrize(
    ("kis", "reason"),
    [
        ([bar(E1, 11)], REASON_NO_ANCHOR),  # P 행 없음
        ([bar(P, 11), bar(E1, 11)], REASON_MISMATCH),  # P 종가가 발행과 다름(수정주가 어긋남)
        ([bar(P, 10)], REASON_MISSING_DATES),  # 필요한 날 없음
        ([], REASON_NO_ANCHOR),
    ],
)
def test_validate_fill_rejects(kis, reason):
    assert validate_fill(kis, bar(P, 10), [E1]) == (None, reason)


def test_validate_fill_requires_every_needed_date():
    assert validate_fill([bar(P, 10), bar(E2, 12)], bar(P, 10), [E1, E2])[1] == REASON_MISSING_DATES


# ── BaseFiller ─────────────────────────────────────────────────────────────────────────
def anchors(n: int) -> dict[str, DailyBar]:
    return {f"S{i:03d}": bar(P, 100 + i) for i in range(n)}


def run_fill(fetch, anc, needed=(E1,), **kw):
    async def go():
        f = BaseFiller(fetch, retry_delay=0.0, sleep=lambda s: asyncio.sleep(0), **kw)
        st = f.ensure((P, E1), list(needed), anc)
        await f.wait()
        return f, st

    return asyncio.run(go())


def good_fetch(anc):
    return lambda code: [anc[code], bar(E1, int(anc[code].close) + 1)]


def test_filler_fills_all_and_counts():
    anc = anchors(25)
    f, st = run_fill(good_fetch(anc), anc)
    assert st.state == "ready" and st.total == 25 and st.attempted == 25 and st.filled == 25 and f.fetch_calls == 25
    assert set(f.bars()) == set(anc) and f.bars()["S000"][0].trade_date == E1 and st.ratio == 1.0


def test_filler_mixed_outcomes_and_retries_exhaust():
    anc = anchors(12)
    calls: dict[str, int] = {}

    def fetch(code):
        calls[code] = calls.get(code, 0) + 1
        if code == "S001":
            raise RuntimeError("down")  # 항상 실패 → max_attempts(3) 소진
        if code == "S002" and calls[code] < 2:
            raise RuntimeError("blip")  # 한 번 실패 후 성공
        if code == "S003":
            return [bar(P, 1), bar(E1, 2)]  # 교차검증 불일치
        if code == "S004":
            return [anc[code]]  # 필요한 날 없음
        return [anc[code], bar(E1, 1)]

    f, st = run_fill(fetch, anc)
    assert calls["S001"] == 3 and calls["S002"] == 2
    assert (st.filled, st.mismatched, st.missing, st.failed) == (9, 1, 1, 1) and st.attempted == 12
    assert "S001" not in f.bars() and "S002" in f.bars() and st.reasons == {"failed": 1, REASON_MISMATCH: 1, REASON_MISSING_DATES: 1}


def cached_bars(anc, code):
    return [anc[code], bar(E1, int(anc[code].close) + 1)]


def test_filler_cache_fills_without_kis_calls():
    anc = anchors(10)
    loaded = []

    def loader(p, e):
        loaded.append((p, e))
        return {c: cached_bars(anc, c) for c in anc}

    def no_fetch(code):
        raise AssertionError("KIS must not be called")

    f, st = run_fill(no_fetch, anc, cache_loader=loader)
    assert loaded == [(P, E1)]
    assert st.state == "ready" and st.filled == 10 and st.from_cache == 10 and st.attempted == 10
    assert f.fetch_calls == 0 and set(f.bars()) == set(anc)


def test_filler_partial_cache_falls_back_to_kis_for_rest():
    anc = anchors(10)
    kis_called = []

    def fetch(code):
        kis_called.append(code)
        return cached_bars(anc, code)

    f, st = run_fill(fetch, anc, cache_loader=lambda p, e: {c: cached_bars(anc, c) for c in list(anc)[:6]})
    assert st.filled == 10 and st.from_cache == 6 and f.fetch_calls == 4 and len(kis_called) == 4
    assert not set(kis_called) & set(list(anc)[:6])


def test_filler_cache_mismatch_or_missing_dates_fall_back_to_kis():
    anc = anchors(4)
    cache = {
        "S000": [bar(P, 1), bar(E1, 2)],  # 앵커 종가 불일치
        "S001": [anc["S001"]],  # 필요한 날 없음
        "S002": [],  # 빈 목록
        # S003: 캐시 없음
    }
    f, st = run_fill(good_fetch(anc), anc, cache_loader=lambda p, e: cache)
    assert st.filled == 4 and st.from_cache == 0 and f.fetch_calls == 4 and st.mismatched == 0


def test_filler_cache_loader_exception_falls_back_to_kis():
    anc = anchors(5)

    def boom(p, e):
        raise RuntimeError("db down")

    f, st = run_fill(good_fetch(anc), anc, cache_loader=boom)
    assert st.state == "ready" and st.filled == 5 and st.from_cache == 0 and f.fetch_calls == 5


def test_filler_same_key_is_idempotent_and_new_key_restarts():
    anc = anchors(5)

    async def go():
        f = BaseFiller(good_fetch(anc), retry_delay=0.0, sleep=lambda s: asyncio.sleep(0))
        a = f.ensure((P, E1), [E1], anc)
        await f.wait()
        b = f.ensure((P, E1), [E1], anc)
        assert a is b and f.fetch_calls == 5  # 같은 (P,E)는 다시 부르지 않는다
        c = f.ensure((P, E2), [E1, E2], {k: v for k, v in anc.items()})
        assert c is not a and f.bars() == {}  # 새 key는 비우고 새로 시작
        await f.close()
        return f

    asyncio.run(go())


def test_filler_empty_anchors_is_ready_immediately_and_close_cancels():
    async def go():
        f = BaseFiller(lambda c: [], retry_delay=0.0)
        st = f.ensure((P, E1), [E1], {})
        assert st.state == "ready" and st.total == 0 and st.ratio == 1.0
        slow = BaseFiller(lambda c: __import__("time").sleep(0.2) or [], workers=1)
        slow.ensure((P, E1), [E1], anchors(50))
        await asyncio.sleep(0.05)
        await slow.close()
        assert slow.status().state == "running"  # 취소되어 끝나지 않음(진행 상태를 거짓으로 ready로 바꾸지 않는다)

    asyncio.run(go())


# ── SnapshotStore ──────────────────────────────────────────────────────────────────────
def test_snapshot_store_keeps_five_latest_and_reuse_window():
    t = [100.0]
    store = SnapshotStore(clock=lambda: t[0])
    ids = []
    for i in range(7):
        t[0] += 1
        ids.append(store.add(LiveRowsResult([], {}), {"i": i}, P).snapshot_id)
    assert len(store) == 5 and store.get(ids[0]) is None and store.get(ids[1]) is None and store.get(ids[2]) is not None
    t[0] += 1  # 마지막 스냅샷이 1초 전
    assert store.latest().snapshot_id == ids[-1] and store.latest(max_age=0.5) is None
    assert store.latest(max_age=1.5).snapshot_id == ids[-1]
    assert store.previous(ids[-1]).snapshot_id == ids[-2] and store.previous(ids[2]) is None


def test_snapshot_payload_built_once():
    store = SnapshotStore()
    snap = store.add(LiveRowsResult([], {}), {}, P)
    calls = []
    assert snap.payload(lambda: calls.append(1) or "x") == "x" and snap.payload(lambda: calls.append(1) or "y") == "x" and len(calls) == 1


# ── LiveScreenService ──────────────────────────────────────────────────────────────────
def pub_row(code: str) -> dict:
    return {"stock_code": code, "market": "KOSPI", "trade_date": P, "return_pct": None, "return_rank_pct": None, "pattern_metrics_status": "OK"}


def history_for(codes) -> dict[str, list[DailyBar]]:
    out = {}
    for code in codes:
        days = []
        d = P
        while len(days) < 100:
            if d.weekday() < 5:
                days.append(d)
            d = date.fromordinal(d.toordinal() - 1)
        out[code] = [bar(day, 1000 + i) for i, day in enumerate(reversed(days))]
    return out


class Rig:
    def __init__(self, *, expected=P, today=E1, trading=True, needed=(), quotes=None, codes=("A", "B"), **kw):
        self.t = [1000.0]
        self.ctx_loads = 0
        self.codes = list(codes)
        self.expected, self.today, self.trading, self.needed = expected, today, trading, list(needed)
        self.quotes = quotes if quotes is not None else {}
        self.stale = False
        self.hist_loads = 0

        def load_context():
            self.ctx_loads += 1
            return PublishedContext(P, self.expected, self.today, self.trading, self.needed, [pub_row(c) for c in self.codes])

        def load_history(d):
            self.hist_loads += 1
            return history_for(self.codes)

        async def quote_state():
            return QuoteState(dict(self.quotes), self.stale, True, len(self.codes))

        self.filler = kw.pop("filler", None)
        self.deps = ServiceDeps(load_context, load_history, quote_state, self.filler, clock=lambda: self.t[0], **kw)
        self.svc = LiveScreenService(self.deps)

    def quote(self, code, price, volume=1):
        self.quotes[code] = MarketQuote(code, price, 0, 0, volume, price, price, price, self.t[0])


def test_service_reuses_within_min_interval_and_recomputes_after_and_single_flight():
    r = Rig(min_interval=5.0)
    r.quote("A", 1200.0)

    async def go():
        a, b, c = await asyncio.gather(r.svc.acquire(None), r.svc.acquire(None), r.svc.acquire(None))
        assert a.snapshot_id == b.snapshot_id == c.snapshot_id and r.svc.computes_total == 1  # 동시 요청도 계산 1번
        r.t[0] += 4.9
        assert (await r.svc.acquire(None)).snapshot_id == a.snapshot_id
        r.t[0] += 0.2
        d = await r.svc.acquire(None)
        assert d.snapshot_id != a.snapshot_id and r.svc.computes_total == 2
        forced = await r.svc.recompute()
        assert forced.snapshot_id != d.snapshot_id and r.svc.computes_total == 3
        assert r.hist_loads == 1  # 이력은 발행일이 같으면 다시 읽지 않는다

    asyncio.run(go())


def test_service_snapshot_id_lookup_and_expired():
    r = Rig()
    r.quote("A", 1200.0)

    async def go():
        s = await r.svc.acquire(None)
        assert (await r.svc.acquire(s.snapshot_id)).snapshot_id == s.snapshot_id
        with pytest.raises(LiveScreenError) as ei:
            await r.svc.acquire("f" * 32)
        assert ei.value.status_code == 410 and ei.value.code == "SNAPSHOT_EXPIRED"

    asyncio.run(go())


def test_service_info_meta_fields():
    r = Rig(quotes={})
    r.quote("A", 1100.0)
    r.stale = True
    info = asyncio.run(r.svc.acquire(None)).info
    assert info["basis_trade_date"] == "2026-09-30" and info["expected_trade_date"] == "2026-09-30" and info["today"] == "2026-10-01"
    assert info["quotes_covered"] == 1 and info["quotes_total"] == 2 and info["stale"] is True and info["volume_partial"] is True
    assert info["refresh_seconds"] >= 5 and info["base_fill"]["state"] == "none" and info["oldest_quote_age_seconds"] == 0.0
    assert info["return_rank_policy"] == "daily"


def test_service_quotes_not_ready_when_live_applies_but_not_when_closed():
    r = Rig()
    with pytest.raises(LiveScreenError) as ei:
        asyncio.run(r.svc.acquire(None))
    assert ei.value.status_code == 503 and ei.value.code == "LIVE_QUOTES_NOT_READY"
    closed = Rig(expected=E1, today=E1, needed=[E1], filler=None)
    # 발행이 뒤처졌는데 보충기가 없으면 거부
    with pytest.raises(LiveScreenError) as ei2:
        asyncio.run(closed.svc.acquire(None))
    assert ei2.value.code == "LIVE_BASE_STALE"
    ok = Rig(expected=P, today=P)  # 마감 뒤(E=오늘): 시세 없이도 발행 값
    assert asyncio.run(ok.svc.acquire(None)).info["quotes_covered"] == 0


def test_service_gap_over_limit_is_stale_without_touching_history_or_filler():
    r = Rig(expected=date(2026, 10, 8), today=date(2026, 10, 9), needed=[date(2026, 10, d) for d in (1, 2, 5, 6, 7, 8)])
    with pytest.raises(LiveScreenError) as ei:
        asyncio.run(r.svc.acquire(None))
    assert ei.value.status_code == 409 and ei.value.code == "LIVE_BASE_STALE" and r.hist_loads == 0
    five = Rig(expected=date(2026, 10, 7), today=date(2026, 10, 8), needed=[date(2026, 10, d) for d in (1, 2, 5, 6, 7)], filler=BaseFiller(lambda c: []))
    with pytest.raises(LiveScreenError) as ei5:  # 5거래일은 허용 범위 — 보충 진행(503)이지 STALE이 아니다
        asyncio.run(five.svc.acquire(None))
    assert ei5.value.code == "LIVE_BASE_FILLING"


def test_service_filling_blocks_below_90_percent_then_serves():
    codes = [f"S{i:02d}" for i in range(10)]
    holder = {}

    def fetch(code):
        return [bar(P, 1000 + 99), bar(E1, 1200)] if code != "S09" else [bar(P, 1), bar(E1, 1)]  # 마지막 종목은 교차검증 불일치

    # 발행 마지막 종가 = history_for의 마지막 값(1099)
    filler = BaseFiller(fetch, retry_delay=0.0, sleep=lambda s: asyncio.sleep(0), workers=1)
    r = Rig(expected=E1, today=E2, needed=[E1], codes=codes, filler=filler, quotes={})
    r.quote("S00", 1300.0)

    async def go():
        with pytest.raises(LiveScreenError) as ei:
            await r.svc.acquire(None)
        assert ei.value.code == "LIVE_BASE_FILLING" and ei.value.details["total"] == 10 and ei.value.details["gap_days"] == 1
        await filler.wait()
        snap = await r.svc.acquire(None)
        bf = snap.info["base_fill"]
        assert bf["state"] == "ready" and bf["filled"] == 9 and bf["mismatched"] == 1 and bf["excluded"] == 1 and bf["pending"] == 0
        assert "S09" not in snap.result.basis and snap.result.basis["S00"] == "live" and snap.result.basis["S01"] == "daily"
        holder["ok"] = True

    asyncio.run(go())
    assert holder["ok"]
