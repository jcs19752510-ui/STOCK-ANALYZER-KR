from datetime import date, time

import pytest

from shared.calendar_service.calendar_file import CalendarFileError, build_calendar_rows

MINIMAL_VALID = {
    "year": 2026,
    "source": "테스트 출처",
    "markets": {
        "KRX": {
            "default_close_time": "15:30:00",
            "holidays": [{"date": "2026-01-01", "name": "신정"}],
            "special_trading_days": [],
        }
    },
}


def test_full_year_generated_for_each_market():
    rows = build_calendar_rows(MINIMAL_VALID)

    assert len(rows) == 365  # 2026년은 평년
    assert all(r.market == "KRX" for r in rows)
    assert all(r.source == "테스트 출처" for r in rows)


def test_weekday_is_trading_day_by_default():
    rows = {r.trade_date: r for r in build_calendar_rows(MINIMAL_VALID)}

    monday = rows[date(2026, 9, 14)]
    saturday = rows[date(2026, 9, 12)]

    assert monday.is_trading_day is True
    assert monday.session_close_at == time(15, 30)
    assert saturday.is_trading_day is False
    assert saturday.session_close_at is None


def test_holiday_overrides_weekday_to_non_trading():
    rows = {r.trade_date: r for r in build_calendar_rows(MINIMAL_VALID)}

    new_years_day = rows[date(2026, 1, 1)]  # 2026-01-01은 목요일(평일)이지만 신정 휴장

    assert new_years_day.is_trading_day is False
    assert new_years_day.holiday_name == "신정"


def test_special_trading_day_overrides_weekend_to_trading():
    raw = {
        "year": 2026,
        "source": "테스트 출처",
        "markets": {
            "KRX": {
                "default_close_time": "15:30:00",
                "holidays": [],
                "special_trading_days": [{"date": "2026-09-13", "close_time": "13:00:00"}],
            }
        },
    }
    rows = {r.trade_date: r for r in build_calendar_rows(raw)}

    special_day = rows[date(2026, 9, 13)]  # 일요일

    assert special_day.is_trading_day is True
    assert special_day.session_close_at == time(13, 0)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"year": 2026},
        {"year": 2026, "source": "x"},
        {
            "year": 2026,
            "source": "x",
            "markets": {"BAD_MARKET": {"default_close_time": "15:30:00"}},
        },
    ],
)
def test_missing_or_invalid_fields_raise_explicit_error(raw):
    with pytest.raises(CalendarFileError):
        build_calendar_rows(raw)


def test_holiday_date_outside_target_year_raises():
    raw = {
        "year": 2026,
        "source": "x",
        "markets": {
            "KRX": {
                "default_close_time": "15:30:00",
                "holidays": [{"date": "2027-01-01", "name": "신정"}],
            }
        },
    }
    with pytest.raises(CalendarFileError):
        build_calendar_rows(raw)


def test_holiday_and_special_trading_day_conflict_raises():
    raw = {
        "year": 2026,
        "source": "x",
        "markets": {
            "KRX": {
                "default_close_time": "15:30:00",
                "holidays": [{"date": "2026-01-01", "name": "신정"}],
                "special_trading_days": [{"date": "2026-01-01"}],
            }
        },
    }
    with pytest.raises(CalendarFileError):
        build_calendar_rows(raw)
