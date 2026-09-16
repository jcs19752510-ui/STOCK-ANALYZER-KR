from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.public_api.data_freshness import build_staleness_note, resolve_session_close_at
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.metrics_repository import (
    SqlStockMetricsRepository,
    StockMetricsRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import DataFreshness, Envelope, Meta
from services.public_api.schemas.metrics import StockMetricsData
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day
from shared.calendar_service.types import CalendarLookup, Market

router = APIRouter(tags=["metrics"])

KST = ZoneInfo("Asia/Seoul")

# derived_metrics_daily는 Ingestion Batch가 다루는 거래소 세션(§3-1-1)을
# 그대로 물려받는다. MVP는 KRX 정규장만 다룬다(DEC-010, run_ingestion.py와 동일).
DERIVATION_MARKET: Market = "KRX"


def get_stock_metrics_repository(db: Session = Depends(get_db)) -> StockMetricsRepository:
    """DI 지점을 분리해, 단위테스트가 실제 DB 없이 이 의존성만 오버라이드할 수 있게 한다."""
    return SqlStockMetricsRepository(db)


def get_calendar_repository(db: Session = Depends(get_db)) -> CalendarLookup:
    return SqlCalendarRepository(db)


def _to_float(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


@router.get("/stocks/{code}/metrics", response_model=Envelope[StockMetricsData])
def get_stock_metrics(
    code: str,
    date: date_type | None = Query(None, description="조회 거래일(YYYY-MM-DD), 생략 시 최신"),
    repository: StockMetricsRepository = Depends(get_stock_metrics_repository),
    calendar: CalendarLookup = Depends(get_calendar_repository),
) -> Envelope[StockMetricsData]:
    stock = repository.get_stock(code)
    if stock is None:
        raise ApiError(
            status_code=404,
            code="STOCK_NOT_FOUND",
            message=f"종목코드 {code!r}를 찾을 수 없습니다.",
        )

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

    # 종목은 존재하지만 이 거래일의 파생 지표 행이 없는 경우(신규 상장·거래정지 등
    # Derivation Batch가 그날 이 종목을 처리하지 못한 경우)를 별도 에러 코드로
    # 다루지 않는다 — 03-system-design.md §3-2 결측치 처리 원칙("계산 불가능한
    # 필드는 null, 0/대체값 금지")을 행 단위 결측으로 그대로 확장해, 전 지표
    # 필드를 null로 채운 응답을 반환한다(04-ux-design.md §2-4 "데이터 부족"
    # 카드 표시로 자연스럽게 이어짐). 상세 근거는 `unit-06-note.md` §2 참조.
    metrics = repository.get_metrics(code, resolved_trade_date)

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
    data = StockMetricsData(
        stock_code=stock.stock_code,
        name=stock.name,
        market=stock.market,
        return_pct=_to_float(metrics.return_pct if metrics else None),
        return_rank_pct=_to_float(metrics.return_rank_pct if metrics else None),
        ma5_gap_pct=_to_float(metrics.ma5_gap_pct if metrics else None),
        ma20_gap_pct=_to_float(metrics.ma20_gap_pct if metrics else None),
        volume_anomaly_score=_to_float(metrics.volume_anomaly_score if metrics else None),
        per_percentile=_to_float(metrics.per_percentile if metrics else None),
        pbr_percentile=_to_float(metrics.pbr_percentile if metrics else None),
        market_cap_percentile=_to_float(metrics.market_cap_percentile if metrics else None),
    )

    return Envelope[StockMetricsData](
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
        data=data,
    )
