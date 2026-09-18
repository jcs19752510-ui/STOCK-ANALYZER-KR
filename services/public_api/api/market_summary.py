from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.public_api.data_freshness import build_staleness_note, resolve_session_close_at
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.market_summary_repository import (
    MarketSummaryRepository,
    MarketSummaryRow,
    SqlMarketSummaryRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import DataFreshness, Envelope, Meta
from services.public_api.schemas.market_summary import (
    MarketSummaryData,
    MarketSummaryItem,
    SectorSummary,
)
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day
from shared.calendar_service.types import CalendarLookup, Market
from shared.market_types import (
    VALID_LISTED_MARKET_FILTERS,
    VALID_LISTED_MARKETS,
    ListedMarketFilter,
)

router = APIRouter(tags=["market-summary"])

KST = ZoneInfo("Asia/Seoul")

# market_summary_daily는 Ingestion/Derivation Batch가 다루는 거래소 세션
# (§3-1-1)을 그대로 물려받아 신선도를 판단한다. MVP는 KRX 정규장만 다룬다
# (DEC-010, services/public_api/api/screen.py·metrics.py와 동일).
DERIVATION_MARKET: Market = "KRX"


def get_market_summary_repository(db: Session = Depends(get_db)) -> MarketSummaryRepository:
    """DI 지점을 분리해, 단위테스트가 실제 DB 없이 이 의존성만 오버라이드할 수 있게 한다."""
    return SqlMarketSummaryRepository(db)


def get_calendar_repository(db: Session = Depends(get_db)) -> CalendarLookup:
    return SqlCalendarRepository(db)


def _to_item(row: MarketSummaryRow) -> MarketSummaryItem:
    return MarketSummaryItem(
        market=row.market,
        advancers_count=row.advancers_count,
        decliners_count=row.decliners_count,
        unchanged_count=row.unchanged_count,
        top_sectors_by_value=[
            SectorSummary(sector=s.sector, trading_value_krw=s.trading_value_krw)
            for s in row.top_sectors_by_value
        ],
        total_trading_value_krw=row.total_trading_value_krw,
    )


def _require_summary(
    repository: MarketSummaryRepository, trade_date: date_type, market: str
) -> MarketSummaryItem:
    """발행된(`current_published_batch`) 거래일인데 그 (trade_date, market)의
    `market_summary_daily` 행이 없으면, 이는 개별 종목 결측(정상적으로
    발생 가능, §3-2 결측치 처리 원칙)과 달리 **배치 파이프라인 정합성
    이상**이다 — Derivation Batch가 `derived_metrics_daily`와 같은 실행에서
    KOSPI/KOSDAQ/ALL 3행을 항상 함께 쓰기 때문이다(services/derivation_batch/
    run_derivation.py). 상승/하락 0건 등 실제 값처럼 보이는 0으로 조용히
    채우면 "데이터가 없다"를 "오늘은 변동이 없었다"로 오인시킬 위험이 있어
    (REQ-006 투명성 원칙 위반), 명시적으로 503을 반환한다.
    """
    row = repository.get_summary(trade_date, market)
    if row is None:
        raise ApiError(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message=(
                f"{trade_date} {market} 시장 동향 요약 데이터를 찾을 수 없습니다. "
                "배치 파이프라인 이상일 수 있습니다."
            ),
        )
    return _to_item(row)


@router.get("/market-summary", response_model=Envelope[MarketSummaryData])
def get_market_summary(
    date: date_type | None = Query(None, description="조회 거래일(YYYY-MM-DD), 생략 시 최신"),
    market: str = Query(
        "ALL", description="상장시장 구분(KOSPI|KOSDAQ|ALL), 생략 시 기본값 ALL"
    ),
    repository: MarketSummaryRepository = Depends(get_market_summary_repository),
    calendar: CalendarLookup = Depends(get_calendar_repository),
) -> Envelope[MarketSummaryData]:
    if market not in VALID_LISTED_MARKET_FILTERS:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"market은 {VALID_LISTED_MARKET_FILTERS} 중 하나여야 합니다: {market!r}",
        )
    market_typed: ListedMarketFilter = market  # type: ignore[assignment]

    now = datetime.now(KST)
    try:
        expected_trade_date = get_last_trading_day(DERIVATION_MARKET, now, calendar)
    except CalendarIntegrityError as exc:
        raise ApiError(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="캘린더 데이터 이상으로 데이터 신선도를 판단할 수 없습니다.",
        ) from exc

    if expected_trade_date is None:
        raise ApiError(
            status_code=424,
            code="CALENDAR_NOT_CONFIRMED",
            message="휴장일 캘린더가 아직 갱신되지 않아 직전 거래일을 계산할 수 없습니다.",
        )

    if date is not None:
        resolved_trade_date = date
    else:
        published = repository.get_current_published_trade_date(DERIVATION_MARKET)
        if published is None:
            raise ApiError(
                status_code=503,
                code="DATA_PIPELINE_STALE",
                message="표시할 데이터가 아직 없습니다. 서비스 데이터 준비 중입니다.",
            )
        resolved_trade_date = published

    main_item = _require_summary(repository, resolved_trade_date, market_typed)

    by_market: list[MarketSummaryItem] | None = None
    if market_typed == "ALL":
        by_market = [
            _require_summary(repository, resolved_trade_date, sub_market)
            for sub_market in VALID_LISTED_MARKETS
        ]

    session_close_at = resolve_session_close_at(
        calendar, DERIVATION_MARKET, trade_date=resolved_trade_date, tzinfo=KST
    )
    is_latest = resolved_trade_date == expected_trade_date
    staleness_note = None
    if not is_latest:
        staleness_note = build_staleness_note(
            calendar, DERIVATION_MARKET, resolved=resolved_trade_date, expected=expected_trade_date
        )

    generated_at = datetime.now(KST)
    return Envelope[MarketSummaryData](
        meta=Meta(
            data_freshness=DataFreshness(
                market=DERIVATION_MARKET,
                trade_date=resolved_trade_date,
                session_close_at=session_close_at,
                generated_at=generated_at,
                is_latest_trading_day=is_latest,
                expected_last_trading_day=expected_trade_date,
                staleness_note=staleness_note,
            ),
            generated_at=generated_at,
        ),
        data=MarketSummaryData(
            market=main_item.market,
            advancers_count=main_item.advancers_count,
            decliners_count=main_item.decliners_count,
            unchanged_count=main_item.unchanged_count,
            top_sectors_by_value=main_item.top_sectors_by_value,
            total_trading_value_krw=main_item.total_trading_value_krw,
            by_market=by_market,
        ),
    )
