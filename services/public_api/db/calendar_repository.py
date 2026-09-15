from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from shared.calendar_service.types import CalendarRow, Market
from shared.db_models.reference import MarketCalendar


class SqlCalendarRepository:
    """`shared.calendar_service.types.CalendarLookup` 프로토콜의 실제 구현.

    reference 스키마는 api_service 계정에 읽기 전용 GRANT만 있다(§3-1).
    """

    def __init__(self, session: Session):
        self._session = session

    def get(self, trade_date: date, market: Market) -> CalendarRow | None:
        row = self._session.get(MarketCalendar, {"trade_date": trade_date, "market": market})
        if row is None:
            return None
        return CalendarRow(
            trade_date=row.trade_date,
            market=row.market,
            is_trading_day=row.is_trading_day,
            session_close_at=row.session_close_at,
            holiday_name=row.holiday_name,
            source=row.source,
        )
