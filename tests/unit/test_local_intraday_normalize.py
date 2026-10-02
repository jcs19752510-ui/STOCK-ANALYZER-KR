"""개인 로컬 모드 장중 시세 정규화·집계·페이징 단위 테스트(DEC-052). 네트워크 없음."""

from __future__ import annotations

from datetime import date

import pytest

from services.public_api.intraday.kis_client import KisError
from services.public_api.intraday.normalize import (
    aggregate_minutes,
    hhmmss,
    minus_one_minute,
    normalize_minute_rows,
    normalize_orderbook,
    normalize_ticks,
    signed,
)
from services.public_api.intraday.service import IntradayService


def _row(day: str, hhmm: str, o, h, lo, c, v):
    return {
        "stck_bsop_date": day, "stck_cntg_hour": hhmm + "00",
        "stck_oprc": str(o), "stck_hgpr": str(h), "stck_lwpr": str(lo),
        "stck_prpr": str(c), "cntg_vol": str(v),
    }  # fmt: skip


def test_hhmmss_and_minus_one_minute():
    assert hhmmss("093005") == "09:30:05"
    assert hhmmss("9305") is None and hhmmss("25:00:00") is None and hhmmss("") is None
    assert minus_one_minute("090500") == "090400"
    assert minus_one_minute("090000") == "085900"
    assert minus_one_minute("000030") == "000000"


@pytest.mark.parametrize(
    "value,sign,expected",
    [
        (50.0, "5", -50.0), (50.0, "4", -50.0), (50.0, "2", 50.0),
        (50.0, "1", 50.0), (0.0, "3", 0.0), (None, "2", None),
    ],  # fmt: skip
)
def test_signed_follows_kis_sign_code(value, sign, expected):
    assert signed(value, sign) == expected


def test_minute_rows_filter_date_drop_bad_rows_and_never_zero_fill():
    rows = [
        _row("20261002", "0900", 100, 101, 99, 100, 10),
        _row("20261001", "1530", 90, 91, 89, 90, 5),  # 다른 날짜
        {**_row("20261002", "0901", 1, 2, 3, 4, 5), "stck_oprc": ""},  # 시가 결측
        {**_row("20261002", "0902", 1, 2, 3, 4, 5), "cntg_vol": "abc"},  # 거래량 비정상
        {**_row("20261002", "0903", 1, 2, 3, 4, 5), "stck_cntg_hour": "99"},  # 시각 비정상
        _row("20261002", "0904", 100, 103, 100, 102, 7),
    ]
    out = normalize_minute_rows(rows, "20261002")
    assert sorted(out) == ["090000", "090400"]
    assert out["090400"].close == 102 and out["090400"].time == "09:04"


def test_aggregate_minutes_buckets_from_nine_and_ohlcv_rules():
    rows = [
        _row("20261002", "0900", 100, 105, 99, 102, 10),
        _row("20261002", "0901", 102, 110, 101, 108, 20),
        _row("20261002", "0904", 108, 109, 95, 96, 30),
        _row("20261002", "0905", 96, 97, 90, 91, 40),  # 다음 5분 구간
    ]
    one = aggregate_minutes(normalize_minute_rows(rows, "20261002"), 1)
    assert [b.time for b in one] == ["09:00", "09:01", "09:04", "09:05"]
    five = aggregate_minutes(normalize_minute_rows(rows, "20261002"), 5)
    assert [b.time for b in five] == ["09:00", "09:05"]
    first = five[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (100, 110, 95, 96, 60)


def test_ticks_sign_and_drop_invalid():
    rows = [
        {"stck_cntg_hour": "100005", "stck_prpr": "1,000", "prdy_vrss": "20", "prdy_vrss_sign": "5",
         "cntg_vol": "3", "tday_rltv": "101.5", "prdy_ctrt": "-1.96"},
        {"stck_cntg_hour": "100004", "stck_prpr": "", "cntg_vol": "1"},  # 가격 결측
        {"stck_cntg_hour": "100003", "stck_prpr": "1020", "prdy_vrss": "0", "prdy_vrss_sign": "3",
         "cntg_vol": "2", "tday_rltv": "", "prdy_ctrt": "0"},
    ]  # fmt: skip
    t = normalize_ticks(rows)
    assert len(t) == 2
    assert (t[0].time, t[0].price, t[0].change, t[0].change_pct) == ("10:00:05", 1000, -20, -1.96)
    assert t[0].strength == 101.5 and t[1].strength is None and t[1].change == 0


def test_orderbook_levels_totals_and_expected():
    o1 = {"aspr_acpt_hour": "100001", "total_askp_rsqn": "500", "total_bidp_rsqn": "700"}
    for i in range(1, 11):
        o1[f"askp{i}"], o1[f"askp_rsqn{i}"] = str(1000 + i), str(10 * i)
        o1[f"bidp{i}"], o1[f"bidp_rsqn{i}"] = str(1000 - i), str(5 * i)
    o1["askp10"] = "0"  # 호가 없는 단계는 제외
    o2 = {"antc_cnpr": "1005", "antc_cntg_vrss": "5", "antc_cntg_vrss_sign": "2",
          "antc_cntg_prdy_ctrt": "0.50", "antc_vol": "1234"}  # fmt: skip
    book = normalize_orderbook("005930", o1, o2)
    assert [a.price for a in book.asks][:3] == [1001, 1002, 1003] and len(book.asks) == 9
    assert [b.price for b in book.bids][:2] == [999, 998] and len(book.bids) == 10
    assert book.total_ask_quantity == 500 and book.total_bid_quantity == 700
    assert book.time == "10:00:01"
    assert book.expected and book.expected.price == 1005 and book.expected.volume == 1234
    empty = normalize_orderbook("005930", None, None)
    assert empty.asks == [] and empty.expected is None and empty.total_ask_quantity == 0


class FakeKis:
    """KIS 응답 모양을 흉내 내는 가짜 클라이언트(페이지 크기 30/120, 최근→과거 순)."""

    def __init__(
        self, minute_rows, past_rows=None, ccnl=None, conclusions=None, fail_conclusion=False
    ):
        self.minute_rows = minute_rows  # 1분봉 전체(과거→최근)
        self.past_rows = past_rows or []
        self.ccnl = ccnl or []
        self.conclusions = conclusions or []
        self.fail_conclusion = fail_conclusion
        self.calls: list[tuple] = []

    @staticmethod
    def _page(rows, hhmmss, size):
        eligible = [r for r in rows if r["stck_cntg_hour"] <= hhmmss]
        return list(reversed(eligible))[:size]

    def minute_today(self, code, hhmmss):
        self.calls.append(("today", hhmmss))
        return {"output2": self._page(self.minute_rows, hhmmss, 30)}

    def minute_past(self, code, yyyymmdd, hhmmss):
        self.calls.append(("past", yyyymmdd, hhmmss))
        rows = [r for r in self.past_rows if r["stck_bsop_date"] == yyyymmdd]
        return {"output2": self._page(rows, hhmmss, 120)}

    def orderbook(self, code):
        book = {"askp1": "101", "askp_rsqn1": "5", "bidp1": "100", "bidp_rsqn1": "6"}
        return {"output1": book, "output2": {}}

    def recent_ccnl(self, code):
        return {"output": self.ccnl[:30]}

    def conclusion_before(self, code, hhmmss):
        self.calls.append(("concl", hhmmss))
        if self.fail_conclusion:
            raise KisError("UPSTREAM_ERROR", "x")
        eligible = [r for r in self.conclusions if r["stck_cntg_hour"] <= hhmmss]
        return {"output2": eligible[:30]}


def _day_rows(day: str, start_min=540, end_min=930):
    rows = []
    for m in range(start_min, end_min + 1):
        hh, mm = divmod(m, 60)
        c = 1000 + (m % 17)
        rows.append(_row(day, f"{hh:02d}{mm:02d}", c, c + 2, c - 2, c + 1, 10 + (m % 5)))
    return rows


class FixedClock:
    # 2026-10-02 11:00 KST
    def __call__(self):
        from datetime import datetime, timedelta, timezone
        return datetime(2026, 10, 2, 11, 0, tzinfo=timezone(timedelta(hours=9))).timestamp()


def test_today_minutes_page_back_to_open_and_cache_hit():
    fake = FakeKis(_day_rows("20261002", 540, 660))  # 09:00~11:00까지 존재
    svc = IntradayService(fake, clock=FixedClock())
    out = svc.minutes("005930", 1, day=None, fallback_day=date(2026, 10, 1))
    assert out.date == date(2026, 10, 2) and len(out.bars) == 121
    assert out.bars[0].time == "09:00" and out.bars[-1].time == "11:00"
    n_calls = len(fake.calls)
    assert n_calls <= 14  # 121건 / 30건 = 5쪽 안팎
    svc.minutes("005930", 1, day=None, fallback_day=date(2026, 10, 1))
    assert len(fake.calls) == n_calls  # TTL 캐시: 증권사를 다시 부르지 않는다
    five = svc.minutes("005930", 5, day=None, fallback_day=date(2026, 10, 1))
    assert five.bars[0].time == "09:00" and len(five.bars) == 25


def test_empty_today_falls_back_to_previous_trading_day_via_past_endpoint():
    fake = FakeKis([], past_rows=_day_rows("20261001"))
    svc = IntradayService(fake, clock=FixedClock())
    out = svc.minutes("005930", 10, day=None, fallback_day=date(2026, 10, 1))
    assert out.date == date(2026, 10, 1) and out.bars
    assert any(c[0] == "past" and c[1] == "20261001" for c in fake.calls)
    # 날짜를 명시하면 폴백 없이 그 날짜(과거 엔드포인트)만 조회
    fake2 = FakeKis([], past_rows=_day_rows("20260930"))
    svc2 = IntradayService(fake2, clock=FixedClock())
    out2 = svc2.minutes("005930", 5, day=date(2026, 9, 30), fallback_day=None)
    assert out2.date == date(2026, 9, 30) and out2.bars


def test_invalid_interval_rejected_and_page_cap_prevents_runaway():
    svc = IntradayService(FakeKis([]), clock=FixedClock())
    with pytest.raises(KisError) as e:
        svc.minutes("005930", 7, day=None, fallback_day=None)
    assert e.value.code == "INVALID_INTERVAL"

    class Endless(FakeKis):  # 항상 새 시각의 행을 돌려줘도 페이지 상한에서 멈춘다
        def __init__(self):
            super().__init__([])
            self.n = 0

        def minute_today(self, code, hhmmss):
            self.n += 1
            self.calls.append(("today", hhmmss))
            hh = 15 - self.n // 60
            mm = 59 - self.n % 60
            return {"output2": [_row("20261002", f"{max(hh, 10):02d}{mm:02d}", 1, 2, 1, 2, 1)]}

    e2 = Endless()
    IntradayService(e2, clock=FixedClock()).minutes("005930", 1, day=None, fallback_day=None)
    assert len(e2.calls) <= 14


def _tick(hhmmss, price, vol=1):
    return {
        "stck_cntg_hour": hhmmss, "stck_prpr": str(price), "prdy_vrss": "0",
        "prdy_vrss_sign": "3", "cntg_vol": str(vol), "tday_rltv": "100", "prdy_ctrt": "0",
    }  # fmt: skip


def test_ticks_page_older_and_dedupe_same_second():
    # 최근 → 과거 순으로 70건(10:00:10 ... 같은 초에 2건씩)
    base = [(f"1000{59 - i // 2:02d}", 1000 + i) for i in range(70)]  # 같은 초 2건씩
    allrows = [_tick(t, p) for t, p in base]
    fake = FakeKis([], ccnl=allrows, conclusions=allrows)
    svc = IntradayService(fake, clock=FixedClock())
    out = svc.ticks("005930", 60)
    assert len(out.ticks) == 60 and out.truncated is False
    times = [t.time for t in out.ticks]
    assert times == sorted(times, reverse=True)  # 최근이 앞
    # 같은 (시각,가격) 쌍이 중복 없이 모였는지(가격이 전부 다르므로 가격 중복 = 중복 수집)
    prices = [t.price for t in out.ticks]
    assert len(set(prices)) == len(prices)


def test_ticks_partial_when_history_endpoint_fails():
    rows = [_tick(f"1000{59 - i:02d}", 1000 + i) for i in range(30)]
    svc = IntradayService(FakeKis([], ccnl=rows, fail_conclusion=True), clock=FixedClock())
    out = svc.ticks("005930", 100)
    assert len(out.ticks) == 30 and out.truncated is True
