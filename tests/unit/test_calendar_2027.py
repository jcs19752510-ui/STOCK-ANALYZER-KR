"""2027 캘린더 파일 점검(DEC-093) — 형식·날짜 규칙·개수. 공식 공고 대조는 사용자 몫(파일 머리말 참고)."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.load_calendar import load_yaml_file
from shared.calendar_service.calendar_file import build_calendar_rows

CAL_DIR = Path(__file__).resolve().parents[2] / "data" / "calendar"
FILES = sorted(p for p in CAL_DIR.glob("20[0-9][0-9].yaml"))


def weekdays(year: int) -> int:
    d, n = date(year, 1, 1), 0
    while d.year == year:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_calendar_file_parses_and_is_consistent(path):
    year = int(path.stem)
    rows = build_calendar_rows(load_yaml_file(path))
    krx = [r for r in rows if r.market == "KRX"]
    nxt = [r for r in rows if r.market == "NXT"]
    assert len(krx) == len(nxt) == (366 if year % 4 == 0 else 365)
    assert {r.trade_date.year for r in rows} == {year}
    # 토·일은 항상 비거래일, 휴장일은 모두 평일, KRX·NXT 휴장일이 같다
    assert all(not r.is_trading_day for r in krx if r.trade_date.weekday() >= 5)
    assert {r.trade_date for r in krx if not r.is_trading_day} == {r.trade_date for r in nxt if not r.is_trading_day}
    assert all(r.session_close_at is not None for r in krx if r.is_trading_day)


def test_2027_expected_trading_days_and_key_dates():
    rows = {r.trade_date: r for r in build_calendar_rows(load_yaml_file(CAL_DIR / "2027.yaml")) if r.market == "KRX"}
    trading = sum(r.is_trading_day for r in rows.values())
    holidays_on_weekdays = 14
    assert trading == weekdays(2027) - holidays_on_weekdays == 247
    closed = {date(2027, 1, 1), date(2027, 2, 5), date(2027, 2, 8), date(2027, 3, 1), date(2027, 5, 5), date(2027, 5, 13), date(2027, 8, 16),
              date(2027, 9, 14), date(2027, 9, 15), date(2027, 9, 16), date(2027, 10, 4), date(2027, 10, 11), date(2027, 12, 27), date(2027, 12, 31)}
    assert {d for d, r in rows.items() if not r.is_trading_day and d.weekday() < 5} == closed
    # 대체공휴일 규칙 점검: 원래 공휴일이 주말이면 다음 평일이 휴장, 현충일(6/6 일요일)은 대체 없음
    assert rows[date(2027, 6, 7)].is_trading_day and rows[date(2027, 8, 17)].is_trading_day
    assert date(2027, 2, 6).weekday() == 5 and date(2027, 8, 15).weekday() == 6 and date(2027, 10, 3).weekday() == 6 and date(2027, 10, 9).weekday() == 5 and date(2027, 12, 25).weekday() == 5
