"""`CalendarLookup` SQL 구현 (Ingestion Batch 전용 사본).

`services/public_api/db/calendar_repository.py`의 `SqlCalendarRepository`와
로직이 동일하다. 03-system-design.md §1-3(서비스별 독립 배포 단위, 서로 다른
컨테이너 이미지)을 지키기 위해 서비스 간 코드 import를 만들지 않고 의도적으로
작게 중복시켰다 — public_api가 죽거나 재배포되어도 ingestion_batch 이미지가
영향받지 않아야 하고, 반대도 마찬가지다. 두 사본이 갈라지면(로직 변경 시 한쪽만
수정) 문제가 될 수 있으므로, 이 로직이 세 번째로 필요해지면(UNIT-06~08의
Derivation Batch 등) `shared/calendar_service/`로 승격하는 것을 권고한다
(unit-02-note.md §2 참조 — 이번 유닛 범위에서는 UNIT-01 산출물을 건드리지
않기 위해 승격하지 않았다).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from shared.calendar_service.types import CalendarRow, Market
from shared.db_models.reference import MarketCalendar


class SqlCalendarRepository:
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
