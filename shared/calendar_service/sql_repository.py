"""`CalendarLookup` 프로토콜의 SQL 구현 (승격, UNIT-06).

이전까지 `services/public_api/db/calendar_repository.py`와
`services/ingestion_batch/calendar_lookup.py`에 100% 동일한 로직이
의도적으로 중복되어 있었다(§1-3 "서비스별 독립 배포 단위" 원칙 준수 목적,
`unit-02-note.md` §2-3 참조). 그 노트는 "이 로직이 세 번째로 필요해지면
(UNIT-06~08의 Derivation Batch 등) `shared/calendar_service/`로 승격하는
것을 권고한다"고 명시했다 — 이번 유닛(UNIT-06, Derivation Batch)이 바로 그
세 번째 필요 시점이므로, 새 사본을 또 만드는 대신 이 시점에 승격한다.

`reference` 스키마는 원본(raw) 데이터가 아니므로(§1-3 "raw 데이터 모델
코드 없음"과 무관), 이 조회 구현을 `shared/`에 두는 것은 설계 원칙과
상충하지 않는다 — `shared/db_models/reference.py`도 이미 여기 있다.

기존 두 모듈(`services/public_api/db/calendar_repository.py`,
`services/ingestion_batch/calendar_lookup.py`)은 이 모듈을 재노출(re-export)
하는 얇은 래퍼로 남겨, 기존 import 경로(및 그 경로를 참조하는 테스트)를
깨지 않는다.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from shared.calendar_service.types import CalendarRow, Market
from shared.db_models.reference import MarketCalendar


class SqlCalendarRepository:
    """`reference.market_calendar` 조회. 읽기 전용(GRANT는 §3-1 참조)."""

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
