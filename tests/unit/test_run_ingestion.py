"""services/ingestion_batch/run_ingestion.py 단위테스트 (REQ-011).

`resolve_target_trade_date()`는 DB 세션이 아니라 `CalendarLookup` 프로토콜만
받도록 설계해(shared.calendar_service.get_last_trading_day와 동일한 패턴),
실 DB 없이도 캘린더 계산 분기를 검증할 수 있다.

`run_once()`(raw_ohlcv upsert 포함)는 PostgreSQL 전용 `ON CONFLICT` 구문을
쓰므로 SQLite로 대체 검증할 수 없다 — unit-01-note.md와 동일한 이유로 이
부분은 로컬 Docker PostgreSQL로 수동 검증했다(unit-02-note.md §3 참조).
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from services.ingestion_batch.run_ingestion import (
    IngestionRunError,
    resolve_target_trade_date,
)
from shared.calendar_service.last_trading_day import CalendarDataError
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
    # 2026-09-14(월) 14:00 KST는 KRX 마감(15:30) 전이므로 직전 거래일(09-11)을 반환해야 한다.
    rows = {
        (date(2026, 9, 11), "KRX"): _row(date(2026, 9, 11), True, time(15, 30)),
        (date(2026, 9, 12), "KRX"): _row(date(2026, 9, 12), False),
        (date(2026, 9, 13), "KRX"): _row(date(2026, 9, 13), False),
        (date(2026, 9, 14), "KRX"): _row(date(2026, 9, 14), True, time(15, 30)),
    }
    calendar = FakeCalendar(rows)

    import services.ingestion_batch.run_ingestion as run_ingestion_module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 14, 0, tzinfo=KST)

    monkeypatch.setattr(run_ingestion_module, "datetime", _FixedDatetime)

    result = resolve_target_trade_date(calendar, override=None)
    assert result == date(2026, 9, 11)


def test_calendar_gap_raises_ingestion_run_error(monkeypatch):
    calendar = FakeCalendar({})  # 캘린더 데이터 전혀 없음

    import services.ingestion_batch.run_ingestion as run_ingestion_module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 14, 0, tzinfo=KST)

    monkeypatch.setattr(run_ingestion_module, "datetime", _FixedDatetime)

    with pytest.raises(IngestionRunError):
        resolve_target_trade_date(calendar, override=None)


def test_calendar_integrity_error_propagates(monkeypatch):
    """거래일인데 session_close_at이 없는 등 데이터 무결성 위반은 그대로 전파되어야 한다."""
    rows = {
        (date(2026, 9, 14), "KRX"): _row(date(2026, 9, 14), True, None),
    }
    calendar = FakeCalendar(rows)

    import services.ingestion_batch.run_ingestion as run_ingestion_module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 8, 0, tzinfo=KST)

    monkeypatch.setattr(run_ingestion_module, "datetime", _FixedDatetime)

    # candidate(09-14) == as_of.date()라 _already_closed가 session_close_at을
    # 실제로 비교하려 하지만 None이라 CalendarDataError를 던진다(데이터 무결성 위반).
    with pytest.raises(CalendarDataError):
        resolve_target_trade_date(calendar, override=None)
