"""scripts/backfill_ohlcv.py 단위테스트 (REQ-031, 05-test-plan §4 TC-B01~B07).

DB·네트워크 없이 검증 가능한 순수 로직(대상 날짜 선택, 건너뜀 판정, 호출 상한/간격,
실패 정책, 상태 판정, 키 마스킹)만 다룬다. `upsert_ohlcv`(ON CONFLICT)·`batch_run`·
서킷브레이커 비오염·`--dry-run` 종단 동작은 PostgreSQL이 필요해
`tests/integration/test_backfill_ohlcv_db.py`(임시 DB)에서 검증한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from scripts.backfill_ohlcv import (
    BackfillError,
    BackfillReport,
    CallBudgetExceeded,
    ThrottledClient,
    build_summary,
    choose_target_dates,
    derive_status,
    estimate_calls,
    exit_code_for,
    mask_secrets,
    pages_per_date,
    run_backfill,
    split_existing,
)
from services.ingestion_batch.gov_data_client import (
    FetchResult,
    GovDataApiError,
    GovDataClientError,
    RawOhlcvRecord,
)


def _rec(code: str, d: date) -> RawOhlcvRecord:
    return RawOhlcvRecord(
        stock_code=code,
        trade_date=d,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=1000,
        trading_value=105000,
    )


class FakeInner:
    """GovDataPortalClient 대역 — fetch_ohlcv 호출을 기록한다."""

    def __init__(self, per_date_rows: dict[date, int] | None = None, *, page_size_rows=1000):
        self.per_date_rows = per_date_rows or {}
        self.calls: list[tuple[date, int]] = []
        self.errors: dict[date, Exception] = {}
        self._page = page_size_rows

    def fetch_ohlcv(self, trade_date: date, *, page_no: int = 1, num_of_rows: int = 1000):
        self.calls.append((trade_date, page_no))
        if trade_date in self.errors:
            raise self.errors[trade_date]
        total = self.per_date_rows.get(trade_date, 0)
        start = (page_no - 1) * num_of_rows
        n = max(0, min(num_of_rows, total - start))
        records = [_rec(f"{start + i:06d}", trade_date) for i in range(n)]
        return FetchResult(records=records, total_count=total)


def _days(n: int, end: date = date(2026, 10, 1)) -> list[date]:
    """end부터 과거로 n개의 평일(월~금)을 최신순으로 만든다."""
    out: list[date] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


# ── 대상 날짜 선택 ────────────────────────────────────────────────────────────
def test_choose_dates_takes_most_recent_n_newest_first():
    trading = _days(20)
    got = choose_target_dates(
        trading, days=5, date_from=None, date_to=None, last_closed_day=trading[0]
    )
    assert got == trading[:5]
    assert got == sorted(got, reverse=True)


def test_choose_dates_respects_to_and_from_range():
    trading = _days(20)
    got = choose_target_dates(
        trading,
        days=None,
        date_from=trading[10],
        date_to=trading[3],
        last_closed_day=trading[0],
    )
    assert got == trading[3:11]


def test_choose_dates_excludes_non_trading_days_by_construction():
    trading = [d for d in _days(20) if d != date(2026, 9, 30)]  # 9/30을 휴장으로 취급
    got = choose_target_dates(
        trading, days=30, date_from=None, date_to=None, last_closed_day=trading[0]
    )
    assert date(2026, 9, 30) not in got


def test_choose_dates_rejects_to_after_last_closed_day():
    trading = _days(10)
    with pytest.raises(BackfillError, match="마감"):
        choose_target_dates(
            trading,
            days=None,
            date_from=trading[5],
            date_to=trading[0] + timedelta(days=3),
            last_closed_day=trading[0],
        )


def test_choose_dates_rejects_days_together_with_from():
    trading = _days(10)
    with pytest.raises(BackfillError, match="동시"):
        choose_target_dates(
            trading, days=5, date_from=trading[5], date_to=None, last_closed_day=trading[0]
        )


def test_choose_dates_empty_result_is_an_error_not_silent():
    with pytest.raises(BackfillError, match="0건"):
        choose_target_dates(
            [], days=5, date_from=None, date_to=None, last_closed_day=date(2026, 10, 1)
        )


# ── 건너뜀 판정 (TC-B02) ─────────────────────────────────────────────────────
def test_split_existing_skips_dates_at_or_above_90_percent():
    dates = _days(3)
    counts = {dates[0]: 90, dates[1]: 89, dates[2]: 0}
    to_fetch, skipped = split_existing(dates, counts, active_count=100, ratio=0.9)
    assert skipped == [dates[0]]  # 정확히 90% = 충분(경계 포함)
    assert to_fetch == [dates[1], dates[2]]  # 89% = 부족, 0건 = 부족


def test_split_existing_requires_active_stock_count():
    with pytest.raises(BackfillError, match="종목"):
        split_existing(_days(2), {}, active_count=0, ratio=0.9)


# ── 호출 수 추정 (TC-B01 보조) ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ("rows", "pages"), [(1, 1), (1000, 1), (1001, 2), (2760, 3), (3000, 3), (3001, 4)]
)
def test_pages_per_date(rows, pages):
    assert pages_per_date(rows, page_size=1000) == pages


def test_estimate_calls():
    assert estimate_calls(105, 3) == 315
    assert estimate_calls(0, 3) == 0


# ── 호출 간격·상한 (TC-B07) ─────────────────────────────────────────────────
def test_throttled_client_sleeps_between_calls_only_not_before_first():
    inner = FakeInner({date(2026, 10, 1): 2500})
    sleeps: list[float] = []
    tc = ThrottledClient(inner, sleep_seconds=0.3, max_calls=None, sleep=sleeps.append)
    for page in (1, 2, 3):
        tc.fetch_ohlcv(date(2026, 10, 1), page_no=page, num_of_rows=1000)
    assert tc.calls == 3
    assert sleeps == [0.3, 0.3]


def test_throttled_client_blocks_call_beyond_max_calls_before_hitting_api():
    inner = FakeInner({date(2026, 10, 1): 10})
    tc = ThrottledClient(inner, sleep_seconds=0, max_calls=2, sleep=lambda s: None)
    tc.fetch_ohlcv(date(2026, 10, 1), page_no=1, num_of_rows=1000)
    tc.fetch_ohlcv(date(2026, 10, 1), page_no=1, num_of_rows=1000)
    with pytest.raises(CallBudgetExceeded):
        tc.fetch_ohlcv(date(2026, 10, 1), page_no=1, num_of_rows=1000)
    assert len(inner.calls) == 2  # 상한 초과 호출은 외부로 나가지 않았다
    assert tc.calls == 2


# ── 오케스트레이션: 정상/0건/실패/상한/재개 ───────────────────────────────────
def _persist_factory(store: dict[date, int]):
    def persist(d: date, records) -> int:
        store[d] = len(records)
        return len(records)

    return persist


def _run(dates, inner, *, max_calls=None, persist=None, store=None, max_consecutive=5):
    store = {} if store is None else store
    tc = ThrottledClient(inner, sleep_seconds=0, max_calls=max_calls, sleep=lambda s: None)
    report = run_backfill(
        dates,
        throttled=tc,
        persist_day=persist or _persist_factory(store),
        max_consecutive_failures=max_consecutive,
        log=lambda msg: None,
    )
    return report, store, inner


def test_run_backfill_happy_path_persists_each_date_with_all_pages():
    dates = _days(2)
    inner = FakeInner({dates[0]: 2500, dates[1]: 2500})
    report, store, _ = _run(dates, inner)
    assert store == {dates[0]: 2500, dates[1]: 2500}
    assert report.calls == 6  # 날짜당 3페이지
    assert report.failed == {} and report.empty_dates == [] and report.remaining == []
    assert derive_status(report) == ("SUCCESS", True)
    assert exit_code_for(report) == 0


def test_zero_rows_on_trading_day_is_warning_not_failure():
    dates = _days(2)
    inner = FakeInner({dates[1]: 100})  # 최신일은 0건(미배포)
    report, store, _ = _run(dates, inner)
    assert report.empty_dates == [dates[0]]
    assert report.failed == {}
    assert store == {dates[1]: 100}
    assert derive_status(report) == ("SUCCESS", True)
    assert "경고" in build_summary(report) or "0건" in build_summary(report)


def test_single_date_failure_is_recorded_and_run_continues():
    dates = _days(3)
    inner = FakeInner({d: 10 for d in dates})
    inner.errors[dates[1]] = GovDataClientError("3회 재시도 후에도 요청에 실패했습니다")
    report, store, _ = _run(dates, inner)
    assert list(report.failed) == [dates[1]]
    assert set(store) == {dates[0], dates[2]}
    assert derive_status(report) == ("PARTIAL", False)
    assert exit_code_for(report) == 1


def test_consecutive_failures_stop_the_run():
    dates = _days(6)
    inner = FakeInner({d: 10 for d in dates})
    for d in dates:
        inner.errors[d] = GovDataClientError("실패")
    report, store, _ = _run(dates, inner, max_consecutive=3)
    assert len(report.failed) == 3
    assert report.stopped_reason == "CONSECUTIVE_FAILURES"
    assert report.remaining == dates[3:]
    assert store == {}
    assert derive_status(report) == ("FAILED", False)


def test_gateway_api_error_is_fatal_and_stops_immediately():
    dates = _days(4)
    inner = FakeInner({d: 10 for d in dates})
    inner.errors[dates[1]] = GovDataApiError("게이트웨이 오류 code=22", retryable=False)
    report, store, inner = _run(dates, inner)
    assert report.stopped_reason == "API_ERROR"
    assert set(store) == {dates[0]}
    assert report.remaining == dates[2:]
    assert [c[0] for c in inner.calls].count(dates[2]) == 0  # 이후 날짜는 호출하지 않음
    assert derive_status(report) == ("PARTIAL", False)


def test_unexpected_exception_in_persist_is_fatal_and_reported():
    dates = _days(3)
    inner = FakeInner({d: 10 for d in dates})

    def boom(d, records):
        raise RuntimeError("DB 장애")

    report, store, _ = _run(dates, inner, persist=boom)
    assert report.stopped_reason == "UNEXPECTED"
    assert dates[0] in report.failed
    assert report.remaining == dates[1:]
    assert derive_status(report) == ("FAILED", False)
    assert exit_code_for(report) == 1


def test_max_calls_stops_cleanly_and_reports_remaining_dates():
    dates = _days(3)
    inner = FakeInner({d: 2500 for d in dates})  # 날짜당 3콜
    report, store, inner = _run(dates, inner, max_calls=4)
    # 1번째 날짜 3콜 완료, 2번째 날짜는 1콜 후 상한 도달 → 미완료 날짜는 저장하지 않는다.
    assert set(store) == {dates[0]}
    assert report.stopped_reason == "MAX_CALLS"
    assert report.remaining == dates[1:]
    assert report.calls == 4
    assert derive_status(report) == ("PARTIAL", True)
    assert exit_code_for(report) == 0  # 상한 도달은 깨끗한 종료(실패 아님)


def test_resume_after_interruption_only_fetches_unfinished_dates_without_duplicates():
    dates = _days(4)
    store: dict[date, int] = {}
    inner1 = FakeInner({d: 10 for d in dates})
    state = {"n": 0}

    def flaky(d, records):
        state["n"] += 1
        if state["n"] == 3:
            raise RuntimeError("중간 장애")
        store[d] = len(records)
        return len(records)

    r1, _, _ = _run(dates, inner1, persist=flaky)
    assert set(store) == set(dates[:2])
    assert dates[2] in r1.failed  # 저장에 실패한 날짜는 실패로 기록
    assert r1.remaining == dates[3:]  # 그 이후 날짜는 미처리로 보고

    # 재실행: 이미 저장된 날짜는 split_existing이 건너뛰므로 남은 날짜만 호출한다.
    counts = {d: store.get(d, 0) for d in dates}
    to_fetch, skipped = split_existing(dates, counts, active_count=10, ratio=0.9)
    assert skipped == dates[:2] and to_fetch == dates[2:]
    inner2 = FakeInner({d: 10 for d in dates})
    r2, _, inner2 = _run(to_fetch, inner2, store=store)
    assert {c[0] for c in inner2.calls} == set(dates[2:])
    assert set(store) == set(dates)
    assert derive_status(r2) == ("SUCCESS", True)


# ── 요약·키 마스킹 (TC-B05) ─────────────────────────────────────────────────
def test_summary_starts_with_backfill_prefix_for_breaker_exclusion():
    rep = BackfillReport()
    assert build_summary(rep).startswith("BACKFILL")
    rep.failed[date(2026, 9, 1)] = "x"
    assert build_summary(rep).startswith("BACKFILL")


def test_mask_secrets_removes_key_and_serviceKey_query_param():
    key = "abc/DEF+123=="
    text = (
        f"요청 실패 https://apis.data.go.kr/x?serviceKey={key}&basDt=20260901 "
        f"그리고 본문에 {key} 도 있음"
    )
    masked = mask_secrets(text, key)
    assert key not in masked
    assert "abc/DEF" not in masked
    assert "***" in masked


def test_mask_secrets_handles_url_encoded_key_and_empty_key():
    key = "abc/DEF+123=="
    from urllib.parse import quote

    assert quote(key, safe="") not in mask_secrets(f"k={quote(key, safe='')}", key)
    assert mask_secrets("정상 메시지", "") == "정상 메시지"
    assert mask_secrets("serviceKey=ZZZ&x=1", "") == "serviceKey=***&x=1"
