from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.public_api.data_freshness import build_staleness_note, resolve_session_close_at
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.screen_repository import (
    ScreenFilters,
    ScreenRepository,
    ScreenRow,
    SqlScreenRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import DataFreshness, Envelope, Meta
from services.public_api.schemas.screen import ScreenData, ScreenResultItem
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day
from shared.calendar_service.types import CalendarLookup, Market
from shared.market_types import VALID_LISTED_MARKET_FILTERS, ListedMarketFilter

router = APIRouter(tags=["screen"])

KST = ZoneInfo("Asia/Seoul")

# derived_metrics_daily는 Ingestion/Derivation Batch가 다루는 거래소 세션
# (§3-1-1)을 그대로 물려받는다. MVP는 KRX 정규장만 다룬다(DEC-010,
# services/public_api/api/metrics.py와 동일).
DERIVATION_MARKET: Market = "KRX"

# 03-system-design.md §4-2 `GET /screen` 허용값.
SORT_BY_VALUES: tuple[str, ...] = ("return_pct", "market_cap", "per", "pbr", "volume_anomaly_score")
SORT_DIR_VALUES: tuple[str, ...] = ("asc", "desc")
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def get_screen_repository(db: Session = Depends(get_db)) -> ScreenRepository:
    """DI 지점을 분리해, 단위테스트가 실제 DB 없이 이 의존성만 오버라이드할 수 있게 한다."""
    return SqlScreenRepository(db)


def get_calendar_repository(db: Session = Depends(get_db)) -> CalendarLookup:
    return SqlCalendarRepository(db)


def _to_float(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


def _require_range_order(
    min_value: float | None, max_value: float | None, *, field_name: str
) -> None:
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"{field_name}_min은 {field_name}_max보다 클 수 없습니다.",
        )


def _resolve_matched_metric_keys(filters: ScreenFilters) -> list[str]:
    """`matched_metrics` = (a) 실제 값이 지정된 필터 조건의 지표 ∪ (b) `sort_by`
    지표(DEC-013). `volume_min`(거래량)은 필터로는 동작하지만, 원본 거래량
    노출 금지 원칙(§4-3)과 이에 대응하는 가공(percentile) 컬럼이 설계서에
    정의되어 있지 않아 이 화이트리스트에 포함하지 않는다(필터 전용,
    `unit-07-note.md` §2 참조) — PER/PBR/시가총액과 달리 대응 표시값이
    없는 필터라서 표시 대상에서 제외하는 것이지, 필터 자체가 동작하지
    않는다는 뜻은 아니다.
    """
    keys: set[str] = set()
    if filters.market_cap_min is not None or filters.market_cap_max is not None:
        keys.add("market_cap")
    if filters.return_pct_min is not None or filters.return_pct_max is not None:
        keys.add("return_pct")
    if filters.per_max is not None:
        keys.add("per")
    if filters.pbr_max is not None:
        keys.add("pbr")
    keys.add(filters.sort_by)
    return sorted(keys)


def _build_matched_metrics(row: ScreenRow, keys: list[str]) -> dict[str, float | None]:
    value_by_key: dict[str, float | None] = {
        "return_pct": _to_float(row.return_pct),
        "market_cap": _to_float(row.market_cap_percentile),
        "per": _to_float(row.per_percentile),
        "pbr": _to_float(row.pbr_percentile),
        "volume_anomaly_score": _to_float(row.volume_anomaly_score),
    }
    return {key: value_by_key[key] for key in keys}


@router.get("/screen", response_model=Envelope[ScreenData])
def screen_stocks(
    market: str = Query(
        "ALL", description="상장시장 구분(KOSPI|KOSDAQ|ALL), 생략 시 기본값 ALL"
    ),
    market_cap_min: int | None = Query(None, ge=0, description="시가총액 최소값(KRW 원 단위 정수)"),
    market_cap_max: int | None = Query(None, ge=0, description="시가총액 최대값(KRW 원 단위 정수)"),
    volume_min: int | None = Query(None, ge=0, description="거래량 최소값(주)"),
    return_pct_min: float | None = Query(None, description="등락률 최소값(%)"),
    return_pct_max: float | None = Query(None, description="등락률 최대값(%)"),
    per_max: float | None = Query(None, description="PER 최대값(배)"),
    pbr_max: float | None = Query(None, description="PBR 최대값(배)"),
    sort_by: str = Query("return_pct", description="정렬 기준"),
    sort_dir: str = Query("desc", description="정렬 방향(asc|desc)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1),
    repository: ScreenRepository = Depends(get_screen_repository),
    calendar: CalendarLookup = Depends(get_calendar_repository),
) -> Envelope[ScreenData]:
    if market not in VALID_LISTED_MARKET_FILTERS:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"market은 {VALID_LISTED_MARKET_FILTERS} 중 하나여야 합니다: {market!r}",
        )
    if sort_by not in SORT_BY_VALUES:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"sort_by는 {SORT_BY_VALUES} 중 하나여야 합니다: {sort_by!r}",
        )
    if sort_dir not in SORT_DIR_VALUES:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"sort_dir은 {SORT_DIR_VALUES} 중 하나여야 합니다: {sort_dir!r}",
        )
    if page_size > MAX_PAGE_SIZE:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"page_size는 {MAX_PAGE_SIZE}를 초과할 수 없습니다: {page_size}",
        )
    _require_range_order(market_cap_min, market_cap_max, field_name="market_cap")
    _require_range_order(return_pct_min, return_pct_max, field_name="return_pct")

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

    published_trade_date = repository.get_current_published_trade_date(DERIVATION_MARKET)
    if published_trade_date is None:
        raise ApiError(
            status_code=503,
            code="DATA_PIPELINE_STALE",
            message="표시할 데이터가 아직 없습니다. 서비스 데이터 준비 중입니다.",
        )

    filters = ScreenFilters(
        trade_date=published_trade_date,
        market=market_typed,
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        volume_min=volume_min,
        return_pct_min=return_pct_min,
        return_pct_max=return_pct_max,
        per_max=per_max,
        pbr_max=pbr_max,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    result = repository.search(filters)
    matched_keys = _resolve_matched_metric_keys(filters)

    items = [
        ScreenResultItem(
            stock_code=row.stock_code,
            name=row.name,
            market=row.market,
            matched_metrics=_build_matched_metrics(row, matched_keys),
        )
        for row in result.items
    ]

    session_close_at = resolve_session_close_at(
        calendar, DERIVATION_MARKET, trade_date=published_trade_date, tzinfo=KST
    )
    is_latest = published_trade_date == expected_trade_date
    staleness_note = None
    if not is_latest:
        staleness_note = build_staleness_note(
            calendar, DERIVATION_MARKET, resolved=published_trade_date, expected=expected_trade_date
        )

    generated_at = datetime.now(KST)
    return Envelope[ScreenData](
        meta=Meta(
            data_freshness=DataFreshness(
                market=DERIVATION_MARKET,
                trade_date=published_trade_date,
                session_close_at=session_close_at,
                generated_at=generated_at,
                is_latest_trading_day=is_latest,
                expected_last_trading_day=expected_trade_date,
                staleness_note=staleness_note,
            ),
            generated_at=generated_at,
        ),
        data=ScreenData(items=items, total_count=result.total_count, page=page),
    )
