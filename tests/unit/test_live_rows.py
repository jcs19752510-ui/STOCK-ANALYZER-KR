"""`build_live_rows` 순수 함수 시험(DEC-089·090) — DB 없음. 판정이 아니라 "재계산 입력 행"이 맞는지 본다."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from services.derivation_batch.compute import (
    compute_pattern_metrics,
    compute_return_pct,
    rank_percentile,
)
from services.public_api.live_screen.rows import (
    FIXED_DAILY_COLUMNS,
    RECOMPUTED_COLUMNS,
    build_live_rows,
    compute_row_metrics,
    quote_is_usable,
)
from services.public_api.live_screen.types import DailyBar
from services.public_api.realtime.market import MarketQuote

NOW = 1_000_000.0
P = date(2026, 9, 30)  # 발행(수)
E1 = date(2026, 10, 1)  # 목
TODAY = date(2026, 10, 2)  # 금


def bars(n: int, end: date, start_price=1000, vol=100, step=1) -> list[DailyBar]:
    """`end`로 끝나는 평일 n개(오름차순). 종가는 start_price에서 step씩 오른다."""
    days: list[date] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    return [DailyBar(day, Decimal(start_price + i * step), Decimal(start_price + i * step), Decimal(start_price + i * step), Decimal(start_price + i * step), vol + i) for i, day in enumerate(days)]


def q(code: str, price: float, volume: int, age: float = 0.0) -> MarketQuote:
    return MarketQuote(code, price, 0, 0, volume, price, price, price, NOW - age)


def pub(code: str, **over) -> dict:
    row = {c: None for c in RECOMPUTED_COLUMNS} | {c: None for c in FIXED_DAILY_COLUMNS}
    row |= {"stock_code": code, "market": "KOSPI", "trade_date": P, "return_rank_pct": Decimal("50.0"),
            "per_raw": Decimal("10"), "market_cap_raw_krw": 5_000, "computed_at": "x", "batch_run_id": "y", "pattern_metrics_status": "OK"}
    return row | over


def run(rows, history, quotes, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("basis_date", P)
    kw.setdefault("expected_date", P)
    kw.setdefault("trading_today", True)
    return build_live_rows(rows, history, quotes, now_ts=NOW, **kw)


# ── quote_is_usable ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("quote", "usable"),
    [(None, False), (q("A", 100, 1), True), (q("A", 0, 1), False), (q("A", -1, 1), False), (q("A", 100, -1), False), (q("A", 100, 0), True),
     (q("A", 100, 1, age=300), True), (q("A", 100, 1, age=300.1), False)],
)
def test_quote_is_usable(quote, usable):
    assert quote_is_usable(quote, now_ts=NOW, stale_seconds=300) is usable


# ── gap 0: 시세 없는 종목은 발행 행 그대로 ──────────────────────────────────────────────
def test_no_gap_without_quote_keeps_published_row_and_does_not_mutate_input():
    row = pub("A", return_pct=Decimal("1.5"))
    snapshot = dict(row)
    res = run([row], {"A": bars(100, P)}, {})
    assert res.rows == [row] and res.rows[0] is not row and row == snapshot
    assert res.basis == {"A": "daily"} and res.meta["covered"] == 0 and res.meta["return_rank_policy"] == "daily"


def test_live_quote_recomputes_return_volume_and_marks_live():
    h = bars(100, P, start_price=1000, step=1)  # 마지막 종가 1099
    res = run([pub("A")], {"A": h}, {"A": q("A", 1209.0, 555)})
    r = res.rows[0]
    assert res.basis["A"] == "live"
    assert r["return_pct"] == compute_return_pct(Decimal("1209.0"), Decimal("1099"))
    assert r["volume_raw"] == 555  # 장중 누적 부분값
    assert r["per_raw"] == Decimal("10") and r["market_cap_raw_krw"] == 5_000  # 일봉 고정 열은 그대로
    assert r["pattern_metrics_status"] == "OK"


def test_recompute_equals_batch_functions_exactly():
    h = bars(100, P, start_price=2000, step=3, vol=1000)
    quote = q("A", 2400.0, 7000)
    r = run([pub("A")], {"A": h}, {"A": quote}).rows[0]
    closes = [Decimal("2400.0")] + [b.close for b in reversed(h)]
    volumes = [7000] + [b.volume for b in reversed(h)]
    expected = compute_row_metrics(closes, volumes)
    for col, val in expected.items():
        assert r[col] == val, col
    pat = compute_pattern_metrics(closes, volumes)
    assert r["ma60_gap_pct"] == pat.ma60_gap_pct and r["recent_surge_flag"] == pat.recent_surge_flag


def test_short_history_gives_insufficient_status_not_error():
    res = run([pub("A")], {"A": bars(30, P)}, {"A": q("A", 1100, 1)})
    r = res.rows[0]
    assert r["pattern_metrics_status"] == "INSUFFICIENT_HISTORY" and r["sideways_range_pct"] is None
    assert r["return_pct"] is not None  # 등락률은 이력이 짧아도 계산된다


def test_price_jump_gives_suspect_status():
    res = run([pub("A")], {"A": bars(100, P, start_price=1000, step=0)}, {"A": q("A", 2000.0, 1)})  # +100% 점프
    assert res.rows[0]["pattern_metrics_status"] == "SUSPECT_PRICE_JUMP"


def test_stale_quote_is_ignored():
    res = run([pub("A", return_pct=Decimal("7"))], {"A": bars(100, P)}, {"A": q("A", 5000, 1, age=301)})
    assert res.basis["A"] == "daily" and res.rows[0]["return_pct"] == Decimal("7") and res.meta["covered"] == 0


def test_today_not_trading_or_closed_ignores_quotes():
    h = {"A": bars(100, P)}
    not_trading = run([pub("A", return_pct=Decimal("7"))], h, {"A": q("A", 5000, 1)}, trading_today=False)
    assert not_trading.basis["A"] == "daily" and not_trading.rows[0]["return_pct"] == Decimal("7")
    closed = run([pub("A", return_pct=Decimal("7"))], h, {"A": q("A", 5000, 1)}, today=P, expected_date=P)  # E == 오늘(마감 뒤)
    assert closed.basis["A"] == "daily" and closed.rows[0]["return_pct"] == Decimal("7")


# ── 커버율·등락률 순위 정책 ─────────────────────────────────────────────────────────────
def test_return_rank_policy_by_coverage():
    codes = [f"S{i:02d}" for i in range(10)]
    rows = [pub(c) for c in codes]
    hist = {c: bars(100, P) for c in codes}
    quotes = {c: q(c, 1099 + 10 * (i + 1), 10) for i, c in enumerate(codes)}  # 모두 상승, 종목마다 다른 등락률
    full = run(rows, hist, quotes)
    assert full.meta["return_rank_policy"] == "live" and full.meta["coverage_ratio"] == 1.0
    by = {r["stock_code"]: r for r in full.rows}
    assert by["S09"]["return_rank_pct"] == Decimal("10.0") and by["S00"]["return_rank_pct"] == Decimal("100.0")  # 가장 많이 오른 종목이 상위
    assert "return_rank_pct" in full.meta["recomputed"]
    ninety = run(rows, hist, {c: quotes[c] for c in codes[:9]})  # 정확히 90% → live
    assert ninety.meta["return_rank_policy"] == "live"
    eighty = run(rows, hist, {c: quotes[c] for c in codes[:8]})
    assert eighty.meta["return_rank_policy"] == "daily" and "return_rank_pct" not in eighty.meta["recomputed"]
    assert {r["stock_code"]: r["return_rank_pct"] for r in eighty.rows}["S00"] == Decimal("50.0")  # 발행 값 유지


# ── 발행이 뒤처진 경우(DEC-090) ─────────────────────────────────────────────────────────
def gap_history(code: str, *, with_e1=True):
    base = bars(100, P, start_price=1000, step=1)
    if with_e1:
        base = base + [DailyBar(E1, Decimal(1200), Decimal(1200), Decimal(1200), Decimal(1200), 5000)]
    return {code: base}


def test_gap_recomputes_from_history_through_E_for_daily_rows():
    res = run([pub("A", return_pct=Decimal("99"))], gap_history("A"), {}, basis_date=P, expected_date=E1, today=TODAY)
    r = res.rows[0]
    assert res.basis["A"] == "daily"
    assert r["return_pct"] == compute_return_pct(Decimal(1200), Decimal(1099))  # E 기준(발행 P 값 99가 아님)
    assert r["volume_raw"] == 5000
    assert res.meta["return_rank_policy"] == "daily" and "return_rank_pct" in res.meta["recomputed"]


def test_gap_excludes_stocks_without_E_bar_and_reports_them():
    rows = [pub("A"), pub("B"), pub("C")]
    hist = gap_history("A") | gap_history("B", with_e1=False) | {"C": []}
    res = run(rows, hist, {}, basis_date=P, expected_date=E1)
    assert [r["stock_code"] for r in res.rows] == ["A"] and sorted(res.excluded) == ["B", "C"] and res.meta["excluded"] == 2


def test_gap_with_live_quote_appends_today_on_top_of_E():
    res = run([pub("A")], gap_history("A"), {"A": q("A", 1260.0, 9)}, basis_date=P, expected_date=E1, today=TODAY)
    assert res.basis["A"] == "live"
    assert res.rows[0]["return_pct"] == compute_return_pct(Decimal("1260.0"), Decimal(1200))


def test_gap_rank_among_daily_rows_uses_E_returns():
    codes = ["A", "B", "C"]
    hist = {}
    for i, c in enumerate(codes):
        h = bars(100, P, start_price=1000, step=0)
        hist[c] = h + [DailyBar(E1, Decimal(1000 + 10 * (i + 1)), Decimal(1), Decimal(1), Decimal(1000 + 10 * (i + 1)), 1)]
    res = run([pub(c) for c in codes], hist, {}, basis_date=P, expected_date=E1)
    ranks = {r["stock_code"]: r["return_rank_pct"] for r in res.rows}
    assert ranks == dict(zip(["C", "B", "A"], rank_percentile([("C", Decimal(3)), ("B", Decimal(2)), ("A", Decimal(1))], descending=True).values(), strict=True))


def test_history_with_duplicate_dates_prefers_first_value_and_ignores_future_bars():
    h = bars(100, P)
    dup = h + [DailyBar(P, Decimal(9999), Decimal(9999), Decimal(9999), Decimal(9999), 1), DailyBar(TODAY, Decimal(1), Decimal(1), Decimal(1), Decimal(1), 1)]
    a = run([pub("A")], {"A": dup}, {"A": q("A", 1110, 5)})
    b = run([pub("A")], {"A": h}, {"A": q("A", 1110, 5)})
    assert a.rows == b.rows  # 중복·미래 날짜는 영향 없음


def test_empty_inputs():
    res = run([], {}, {})
    assert res.rows == [] and res.meta["total"] == 0 and res.meta["coverage_ratio"] == 0.0


def test_meta_lists_recomputed_and_fixed_columns_and_partial_volume_flag():
    res = run([pub("A")], {"A": bars(100, P)}, {"A": q("A", 1100, 1)})
    assert set(RECOMPUTED_COLUMNS) <= set(res.meta["recomputed"]) and res.meta["fixed_daily"] == list(FIXED_DAILY_COLUMNS)
    assert res.meta["volume_partial"] is True and res.meta["compute_ms"] >= 0
    assert not (set(res.meta["recomputed"]) & set(FIXED_DAILY_COLUMNS))
