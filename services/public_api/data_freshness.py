"""`meta.data_freshness` 구성 공통 헬퍼 (REQ-006, 03-system-design.md §3-4).

UNIT-06(`GET /stocks/{code}/metrics`)이 실 데이터를 반환하는 첫 엔드포인트라
이 헬퍼를 여기서 처음 만든다. UNIT-07/08도 동일한 "요청한 거래일이 최신인지,
아니면 며칠 지연됐는지" 판단이 필요하므로 재사용 가능하게 분리해 둔다(계산
로직 이원화 방지 — §3-4 "프론트엔드가 판단하지 않는다"는 원칙을 백엔드
내부에서도 한 곳에서만 계산하는 것으로 확장 적용).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import tzinfo as TzInfo

from shared.calendar_service.types import CalendarLookup, Market

# staleness_note에 정확한 지연 영업일수를 넣기 위해 하루씩 스캔하되, 비정상적으로
# 큰 간격(캘린더 데이터 이상 등)에서 무한정 스캔하지 않도록 방어적 상한을 둔다.
# 이 상한을 넘으면 정확한 숫자 대신 일반 문구로 대체한다(추측으로 숫자를 지어내지 않음).
MAX_LAG_SCAN_DAYS = 60


def count_trading_days_strictly_after(
    calendar: CalendarLookup, market: Market, *, start_exclusive: date, end_inclusive: date
) -> int | None:
    """`(start_exclusive, end_inclusive]` 구간의 거래일 수. 스캔 상한 초과 시 None."""
    if start_exclusive >= end_inclusive:
        return 0
    count = 0
    cursor = start_exclusive + timedelta(days=1)
    scanned = 0
    while cursor <= end_inclusive:
        row = calendar.get(trade_date=cursor, market=market)
        if row is not None and row.is_trading_day:
            count += 1
        cursor += timedelta(days=1)
        scanned += 1
        if scanned > MAX_LAG_SCAN_DAYS:
            return None
    return count


def build_staleness_note(
    calendar: CalendarLookup, market: Market, *, resolved: date, expected: date
) -> str:
    """지연 경고 문구(04-ux-design.md §2-1 "예상보다 N영업일 지연된 데이터입니다")."""
    lag = count_trading_days_strictly_after(
        calendar, market, start_exclusive=resolved, end_inclusive=expected
    )
    if lag is None or lag <= 0:
        return "예상보다 지연된 데이터입니다"
    return f"예상보다 {lag}영업일 지연된 데이터입니다"


def resolve_session_close_at(
    calendar: CalendarLookup, market: Market, *, trade_date: date, tzinfo: TzInfo
) -> datetime | None:
    row = calendar.get(trade_date=trade_date, market=market)
    if row is None or row.session_close_at is None:
        return None
    return datetime.combine(trade_date, row.session_close_at, tzinfo=tzinfo)


__all__ = [
    "MAX_LAG_SCAN_DAYS",
    "build_staleness_note",
    "count_trading_days_strictly_after",
    "resolve_session_close_at",
]
