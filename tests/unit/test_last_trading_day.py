from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from shared.calendar_service.last_trading_day import (
    CalendarDataError,
    CalendarScanLimitExceeded,
    get_last_trading_day,
)
from shared.calendar_service.types import CalendarRow

KST = ZoneInfo("Asia/Seoul")

TODAY = date(2026, 9, 14)  # 월요일, KRX/NXT 공통 거래일
PREV_TRADING_DAY = date(2026, 9, 11)  # 09-12/13 주말을 건너뛴 직전 거래일
KRX_CLOSE = time(15, 30)
NXT_CLOSE = time(20, 0)


class FakeCalendar:
    """CalendarLookup 프로토콜을 만족하는 테스트용 인메모리 캘린더."""

    def __init__(self, rows: dict[tuple[date, str], CalendarRow]):
        self._rows = rows

    def get(self, trade_date: date, market: str) -> CalendarRow | None:
        return self._rows.get((trade_date, market))


def _row(
    d: date,
    market: str,
    is_trading_day: bool,
    close: time | None = None,
):
    return CalendarRow(
        trade_date=d,
        market=market,
        is_trading_day=is_trading_day,
        session_close_at=close,
        holiday_name=None if is_trading_day else "휴장",
        source="test",
    )


@pytest.fixture
def week_calendar() -> FakeCalendar:
    """2026-09-11(금, 거래일) ~ 09-14(월, 거래일), 09-12/13(주말, 휴장) KRX+NXT."""
    rows: dict[tuple[date, str], CalendarRow] = {}
    for market, close in (("KRX", KRX_CLOSE), ("NXT", NXT_CLOSE)):
        rows[(date(2026, 9, 11), market)] = _row(date(2026, 9, 11), market, True, close)
        rows[(date(2026, 9, 12), market)] = _row(date(2026, 9, 12), market, False)
        rows[(date(2026, 9, 13), market)] = _row(date(2026, 9, 13), market, False)
        rows[(TODAY, market)] = _row(TODAY, market, True, close)
    return FakeCalendar(rows)


# --- 03-system-design.md §3-3 v4 "경계 시각별 기대 반환값 진리표" 그대로 재현 ---
# 전제: 2026-09-14(월)는 KRX/NXT 공통 거래일, KRX close=15:30, NXT close=20:00,
# 직전 영업일은 2026-09-11(금).
@pytest.mark.parametrize(
    "market, as_of_time, expected, table_row",
    [
        ("KRX", time(8, 59, 59), PREV_TRADING_DAY, 1),
        ("KRX", time(9, 0, 0), PREV_TRADING_DAY, 2),
        ("KRX", time(12, 0, 0), PREV_TRADING_DAY, 3),
        ("KRX", time(15, 29, 59), PREV_TRADING_DAY, 4),
        ("KRX", time(15, 30, 0), TODAY, 5),  # 마감 정각은 '이미 마감'으로 포함(>=)
        ("KRX", time(15, 30, 1), TODAY, 6),
        ("KRX", time(18, 0, 0), TODAY, 7),  # 시간외단일가(18:00)는 판단 기준 아님
        ("KRX", time(23, 59, 59), TODAY, 8),
        ("NXT", time(19, 59, 59), PREV_TRADING_DAY, 9),
        ("NXT", time(20, 0, 0), TODAY, 10),
        ("NXT", time(20, 0, 1), TODAY, 11),
    ],
)
def test_boundary_truth_table(week_calendar, market, as_of_time, expected, table_row):
    as_of = datetime.combine(TODAY, as_of_time, tzinfo=KST)

    result = get_last_trading_day(market, as_of, week_calendar)

    assert result == expected, f"진리표 #{table_row} 불일치"


def test_truth_table_row12_holiday_is_skipped_regardless_of_time(week_calendar):
    as_of = datetime(2026, 9, 13, 3, 0, tzinfo=KST)  # 일요일(휴장), 임의 시각

    result = get_last_trading_day("KRX", as_of, week_calendar)

    assert result == PREV_TRADING_DAY


def test_truth_table_row13_calendar_gap_returns_none():
    calendar = FakeCalendar({})  # 해당 연도 데이터 자체가 없는 상황

    result = get_last_trading_day("KRX", datetime(2027, 1, 5, 12, 0, tzinfo=KST), calendar)

    assert result is None


def test_past_date_is_always_closed_regardless_of_close_time():
    # candidate가 오늘보다 이전이면 _already_closed()는 시각을 비교하지 않고 항상 True.
    # "오늘"(2026-09-11)은 휴장으로 둬서 역순 탐색이 어제(과거 거래일)까지 가도록 하고,
    # as_of 시각을 자정 직후(00:00:00)로 아주 이르게 줘도 과거 날짜는 무조건 마감으로
    # 취급되는지 확인한다.
    today = date(2026, 9, 11)
    past = date(2026, 9, 10)
    calendar = FakeCalendar(
        {
            (today, "KRX"): _row(today, "KRX", False),
            (past, "KRX"): _row(past, "KRX", True, KRX_CLOSE),
        }
    )

    result = get_last_trading_day(
        "KRX", datetime(2026, 9, 11, 0, 0, 0, tzinfo=KST), calendar
    )

    assert result == past


def test_skips_consecutive_holidays():
    # 추석 연휴 등 연휴가 이어질 때 자동으로 역순 탐색되는지 확인
    rows = {}
    rows[(date(2026, 9, 28), "KRX")] = _row(date(2026, 9, 28), "KRX", True, KRX_CLOSE)  # 월
    for d in (date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)):
        rows[(d, "KRX")] = _row(d, "KRX", False)
    rows[(date(2026, 10, 2), "KRX")] = _row(date(2026, 10, 2), "KRX", False)
    calendar = FakeCalendar(rows)
    as_of = datetime(2026, 10, 2, 12, 0, tzinfo=KST)

    result = get_last_trading_day("KRX", as_of, calendar)

    assert result == date(2026, 9, 28)


def test_short_circuit_prevents_crash_on_holiday_with_null_close_time():
    # 휴장일 행은 session_close_at=None일 수 있다. is_trading_day=False일 때
    # _already_closed()가 호출되지 않아야 None과 시각을 비교하는 크래시가 안 난다
    # (03-system-design.md §3-3 "구현 시 필수 주의사항" 2번, 단락 평가 순서).
    d = date(2026, 9, 14)
    calendar = FakeCalendar({(d, "KRX"): _row(d, "KRX", False, close=None)})

    result = get_last_trading_day("KRX", datetime(2026, 9, 14, 12, 0, tzinfo=KST), calendar)

    assert result is None  # 캘린더에 09-13 이전 데이터가 없어 공백으로 처리됨


def test_calendar_data_error_when_trading_day_missing_close_time():
    # is_trading_day=True인데 session_close_at이 비어 있는 것은 데이터 무결성 위반.
    d = date(2026, 9, 14)
    calendar = FakeCalendar({(d, "KRX"): _row(d, "KRX", True, close=None)})

    with pytest.raises(CalendarDataError):
        get_last_trading_day("KRX", datetime(2026, 9, 14, 12, 0, tzinfo=KST), calendar)


def test_returns_none_on_calendar_gap():
    calendar = FakeCalendar({})

    result = get_last_trading_day("KRX", datetime(2027, 1, 5, 12, 0, tzinfo=KST), calendar)

    assert result is None


def test_raises_when_scan_limit_exceeded():
    start = date(2026, 1, 1)
    rows = {
        (start - timedelta(days=i), "KRX"): _row(start - timedelta(days=i), "KRX", False)
        for i in range(-2, 500)
    }
    calendar = FakeCalendar(rows)
    as_of = datetime(2026, 1, 1, 12, 0, tzinfo=KST)

    with pytest.raises(CalendarScanLimitExceeded):
        get_last_trading_day("KRX", as_of, calendar)


def test_unknown_market_raises_value_error():
    calendar = FakeCalendar({})
    as_of = datetime(2026, 9, 14, 12, 0, tzinfo=KST)

    with pytest.raises(ValueError):
        get_last_trading_day("XYZ", as_of, calendar)  # type: ignore[arg-type]
