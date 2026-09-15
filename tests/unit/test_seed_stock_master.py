"""scripts/seed_stock_master.py 단위테스트 (REQ-001).

`upsert_stock_master()`는 PostgreSQL 전용 `ON CONFLICT` 구문을 쓰므로
SQLite로 대체 검증할 수 없다 — unit-01/02-note.md와 동일한 이유로 이 부분은
로컬 Docker PostgreSQL로 수동 검증했다(unit-03-note.md §7 참조). 이 파일은
DB 세션 없이 검증 가능한 순수 로직(거래일 계산 재사용, 페이지네이션)만
다룬다.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from scripts.seed_stock_master import (
    MAX_PAGES,
    PAGE_SIZE,
    SeedStockMasterError,
    fetch_all_records,
    resolve_target_trade_date,
)
from services.ingestion_batch.gov_data_client import (
    StockMasterFetchResult,
    StockMasterSnapshotRecord,
)
from shared.calendar_service.types import CalendarRow

KST = ZoneInfo("Asia/Seoul")


class FakeCalendar:
    def __init__(self, rows: dict[tuple[date, str], CalendarRow]):
        self._rows = rows

    def get(self, trade_date: date, market: str) -> CalendarRow | None:
        return self._rows.get((trade_date, market))


def _row(d: date, is_trading_day: bool, close: time | None = None) -> CalendarRow:
    return CalendarRow(
        trade_date=d,
        market="KRX",
        is_trading_day=is_trading_day,
        session_close_at=close,
        holiday_name=None if is_trading_day else "휴장",
        source="test",
    )


def test_override_short_circuits_calendar_lookup():
    calendar = FakeCalendar({})  # 비어 있어도 override가 있으면 조회하지 않아야 함
    result = resolve_target_trade_date(calendar, override=date(2026, 9, 1))
    assert result == date(2026, 9, 1)


def test_no_override_uses_calendar(monkeypatch):
    rows = {
        (date(2026, 9, 11), "KRX"): _row(date(2026, 9, 11), True, time(15, 30)),
        (date(2026, 9, 12), "KRX"): _row(date(2026, 9, 12), False),
        (date(2026, 9, 13), "KRX"): _row(date(2026, 9, 13), False),
        (date(2026, 9, 14), "KRX"): _row(date(2026, 9, 14), True, time(15, 30)),
    }
    calendar = FakeCalendar(rows)

    import scripts.seed_stock_master as module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 14, 0, tzinfo=KST)

    monkeypatch.setattr(module, "datetime", _FixedDatetime)

    result = resolve_target_trade_date(calendar, override=None)
    assert result == date(2026, 9, 11)


def test_calendar_gap_raises_seed_error(monkeypatch):
    calendar = FakeCalendar({})  # 캘린더 데이터 전혀 없음

    import scripts.seed_stock_master as module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 14, 0, tzinfo=KST)

    monkeypatch.setattr(module, "datetime", _FixedDatetime)

    with pytest.raises(SeedStockMasterError):
        resolve_target_trade_date(calendar, override=None)


class FakeGovClient:
    def __init__(self, pages: dict[int, StockMasterFetchResult]):
        self._pages = pages
        self.calls: list[int] = []

    def fetch_stock_master_snapshot(
        self, trade_date: date, *, page_no: int, num_of_rows: int
    ) -> StockMasterFetchResult:
        self.calls.append(page_no)
        return self._pages[page_no]


def _record(code: str = "005930") -> StockMasterSnapshotRecord:
    return StockMasterSnapshotRecord(stock_code=code, name="테스트", market="KOSPI")


def test_fetch_all_records_single_page():
    client = FakeGovClient({1: StockMasterFetchResult(records=[_record()], total_count=1)})

    records = fetch_all_records(client, date(2026, 9, 11))

    assert len(records) == 1
    assert client.calls == [1]  # 1페이지로 충분하면 추가 호출하지 않는다


def test_fetch_all_records_multiple_pages():
    total = PAGE_SIZE + 10
    page1_records = [_record(str(i).zfill(6)) for i in range(PAGE_SIZE)]
    page2_records = [_record(str(i).zfill(6)) for i in range(PAGE_SIZE, total)]
    client = FakeGovClient(
        {
            1: StockMasterFetchResult(records=page1_records, total_count=total),
            2: StockMasterFetchResult(records=page2_records, total_count=total),
        }
    )

    records = fetch_all_records(client, date(2026, 9, 11))

    assert len(records) == total
    assert client.calls == [1, 2]


def test_fetch_all_records_hits_max_pages_raises():
    huge_total = PAGE_SIZE * (MAX_PAGES + 5)
    pages = {
        page_no: StockMasterFetchResult(records=[_record()], total_count=huge_total)
        for page_no in range(1, MAX_PAGES + 1)
    }
    client = FakeGovClient(pages)

    with pytest.raises(SeedStockMasterError):
        fetch_all_records(client, date(2026, 9, 11))
