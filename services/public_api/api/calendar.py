from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.calendar import LastTradingDayData
from services.public_api.schemas.envelope import DataFreshness, Envelope, Meta
from shared.calendar_service import (
    VALID_MARKETS,
    CalendarIntegrityError,
    get_last_trading_day,
)
from shared.calendar_service.types import CalendarLookup, Market

router = APIRouter(prefix="/calendar", tags=["calendar"])

KST = ZoneInfo("Asia/Seoul")


def get_calendar_repository(db: Session = Depends(get_db)) -> CalendarLookup:
    """DI 지점을 분리해, 단위테스트가 실제 DB 없이 이 의존성만 오버라이드할 수 있게 한다."""
    return SqlCalendarRepository(db)


@router.get("/last-trading-day", response_model=Envelope[LastTradingDayData])
def last_trading_day(
    market: str = Query(..., description="거래소 세션 구분 (KRX|NXT)"),
    as_of: datetime | None = Query(
        None, description="기준 시각(ISO 8601), 생략 시 서버 현재시각(KST)"
    ),
    repository: CalendarLookup = Depends(get_calendar_repository),
) -> Envelope[LastTradingDayData]:
    if market not in VALID_MARKETS:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"market은 {VALID_MARKETS} 중 하나여야 합니다: {market!r}",
        )
    market_typed: Market = market  # type: ignore[assignment]

    as_of_dt = as_of if as_of is not None else datetime.now(KST)
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=KST)

    try:
        trade_date = get_last_trading_day(market_typed, as_of_dt, repository)
    except CalendarIntegrityError as exc:
        # CalendarScanLimitExceeded/CalendarDataError 공통: 캘린더 데이터가
        # 존재하지만 신뢰할 수 없는 상태 — "캘린더 미확인"(424)과 구분되는
        # 서비스 이상(503)으로 처리한다.
        raise ApiError(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="캘린더 데이터 이상으로 직전 거래일을 계산할 수 없습니다.",
        ) from exc

    if trade_date is None:
        raise ApiError(
            status_code=424,
            code="CALENDAR_NOT_CONFIRMED",
            message="휴장일 캘린더가 아직 갱신되지 않아 직전 거래일을 계산할 수 없습니다.",
        )

    calendar_row = repository.get(trade_date=trade_date, market=market_typed)
    session_close_at = None
    if calendar_row is not None and calendar_row.session_close_at is not None:
        session_close_at = datetime.combine(
            trade_date, calendar_row.session_close_at, tzinfo=KST
        )

    generated_at = datetime.now(KST)
    return Envelope[LastTradingDayData](
        meta=Meta(
            data_freshness=DataFreshness(
                market=market_typed,
                trade_date=trade_date,
                session_close_at=session_close_at,
                generated_at=generated_at,
                is_latest_trading_day=True,
                expected_last_trading_day=trade_date,
                staleness_note=None,
            ),
            generated_at=generated_at,
        ),
        data=LastTradingDayData(trade_date=trade_date),
    )
