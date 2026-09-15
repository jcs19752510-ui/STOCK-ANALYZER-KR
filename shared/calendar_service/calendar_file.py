"""연간 캘린더 데이터 파일(YAML) 파싱 + 행 생성 (REQ-012).

`scripts/load_calendar.py`가 사용하는 순수 로직(DB 접근 없음)만 여기 둔다.
DB 연결이 없어도 단위테스트가 가능하도록 분리했다.

YAML 형식 예시는 `data/calendar/2026.example.yaml` 참조.

REQ-012 "하드코딩 금지"는 "연도별로 바뀌는 휴장일/특수개장일 목록을 코드에
박아넣지 않는다"는 뜻이다. 요일 기반 기본 규칙(평일=거래일, 주말=휴장)은
연도가 바뀌어도 변하지 않는 보편적 사실이라 이 모듈의 로직으로 둔다 — 실제
매년 바뀌는 것은 공휴일/임시휴장/특수개장일 목록뿐이며, 그 목록은 전부 이
파일이 읽는 YAML 데이터에서 온다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from shared.calendar_service.types import VALID_MARKETS, Market


class CalendarFileError(ValueError):
    """YAML 캘린더 파일 형식/내용 오류. 조용히 넘어가지 않고 항상 예외로 알린다."""


@dataclass(frozen=True)
class CalendarRowInput:
    trade_date: date
    market: Market
    is_trading_day: bool
    session_close_at: time | None
    holiday_name: str | None
    source: str


def _parse_time(value: str, *, context: str) -> time:
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise CalendarFileError(f"{context}: 시각 형식이 올바르지 않습니다: {value!r}")


def _parse_date(value: Any, *, context: str, year: int) -> date:
    if isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CalendarFileError(f"{context}: 날짜 형식이 올바르지 않습니다: {value!r}") from exc
    else:
        raise CalendarFileError(f"{context}: 날짜 값이 올바르지 않습니다: {value!r}")

    if parsed.year != year:
        raise CalendarFileError(
            f"{context}: 날짜 {parsed}가 파일의 대상 연도({year})와 일치하지 않습니다."
        )
    return parsed


def _all_dates_in_year(year: int) -> list[date]:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def build_calendar_rows(raw: dict[str, Any]) -> list[CalendarRowInput]:
    """파싱된 YAML dict에서 (연도 x 시장) 전체 날짜의 캘린더 행을 생성한다.

    필수 필드 누락, 알 수 없는 market, 대상 연도를 벗어난 날짜 등은 전부
    CalendarFileError로 명시적으로 실패시킨다(조용한 무시/기본값 대체 금지).
    """
    if "year" not in raw:
        raise CalendarFileError("최상위 필드 'year'가 없습니다.")
    if "source" not in raw or not raw["source"]:
        raise CalendarFileError("최상위 필드 'source'가 없습니다(근거 출처 기록 필수, §3-2).")
    if "markets" not in raw or not raw["markets"]:
        raise CalendarFileError("최상위 필드 'markets'가 없습니다.")

    year = raw["year"]
    source = raw["source"]
    markets: dict[str, Any] = raw["markets"]

    unknown_markets = set(markets) - set(VALID_MARKETS)
    if unknown_markets:
        raise CalendarFileError(f"알 수 없는 market 키: {unknown_markets}")

    rows: list[CalendarRowInput] = []

    for market_name, market_conf in markets.items():
        market: Market = market_name  # type: ignore[assignment]
        if "default_close_time" not in market_conf:
            raise CalendarFileError(f"markets.{market_name}: 'default_close_time'이 없습니다.")
        default_close_time = _parse_time(
            market_conf["default_close_time"], context=f"markets.{market_name}.default_close_time"
        )

        holidays: dict[date, str] = {}
        for entry in market_conf.get("holidays", []) or []:
            if "date" not in entry or "name" not in entry:
                raise CalendarFileError(
                    f"markets.{market_name}.holidays: 'date'/'name' 필드가 모두 필요합니다: {entry}"
                )
            holiday_date = _parse_date(
                entry["date"], context=f"markets.{market_name}.holidays", year=year
            )
            if holiday_date in holidays:
                raise CalendarFileError(
                    f"markets.{market_name}.holidays: 날짜 중복: {holiday_date}"
                )
            holidays[holiday_date] = entry["name"]

        special_trading_days: dict[date, time] = {}
        for entry in market_conf.get("special_trading_days", []) or []:
            if "date" not in entry:
                raise CalendarFileError(
                    f"markets.{market_name}.special_trading_days: 'date' 필드가 필요합니다: {entry}"
                )
            special_date = _parse_date(
                entry["date"],
                context=f"markets.{market_name}.special_trading_days",
                year=year,
            )
            if special_date in holidays:
                raise CalendarFileError(
                    f"markets.{market_name}: {special_date}가 holidays와 "
                    "special_trading_days 양쪽에 모두 존재합니다."
                )
            close_time = (
                _parse_time(
                    entry["close_time"],
                    context=f"markets.{market_name}.special_trading_days",
                )
                if "close_time" in entry
                else default_close_time
            )
            special_trading_days[special_date] = close_time

        for trade_date in _all_dates_in_year(year):
            if trade_date in holidays:
                rows.append(
                    CalendarRowInput(
                        trade_date=trade_date,
                        market=market,
                        is_trading_day=False,
                        session_close_at=None,
                        holiday_name=holidays[trade_date],
                        source=source,
                    )
                )
                continue

            if trade_date in special_trading_days:
                rows.append(
                    CalendarRowInput(
                        trade_date=trade_date,
                        market=market,
                        is_trading_day=True,
                        session_close_at=special_trading_days[trade_date],
                        holiday_name=None,
                        source=source,
                    )
                )
                continue

            is_weekday = trade_date.weekday() < 5
            rows.append(
                CalendarRowInput(
                    trade_date=trade_date,
                    market=market,
                    is_trading_day=is_weekday,
                    session_close_at=default_close_time if is_weekday else None,
                    holiday_name=None,
                    source=source,
                )
            )

    return rows
