"""`GET /api/v1/screen/pattern` — 패턴 스크리닝 "급등 전 압축주" (REQ-032/034/035/036, 설계서 §5).

기존 `GET /screen`·`screen.py`는 바꾸지 않는다(additive only). 사용자는 임계값을 바꿀 수 없다 — 질의
파라미터로 받지 않고 서버 설정(`core/pattern_config.py`)만 쓴다. 조건 판정은 SQL 한 곳
(`db/pattern_repository.build_condition_exprs`)에서 하며 이 계층은 값을 다시 판정하지 않는다. 응답은
가격·원값 없이 비율·배수·불리언·일수와 조건별 충족/미충족/산정 불가(+사유)만 담는다.

점수·순위·충족 개수 정렬은 제공하지 않는다(REQ-034). 산정 불가 종목은 조용히 빼지 않는다:
`required`로 건 조건이 NULL이면 결과에서 제외되지만 `readiness`로 평가 가능 종목 수를 항상 공개하고,
전체가 미준비면 `PATTERN_DATA_NOT_READY`로 명시적으로 실패한다(REQ-035).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.public_api.core.pattern_config import PatternThresholds, load_pattern_thresholds
from services.public_api.data_freshness import build_staleness_note, resolve_session_close_at
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.pattern_repository import (
    CONDITION_IDS,
    METRIC_KEYS,
    SORT_COLUMN_MAP,
    PatternFilters,
    PatternRow,
    PatternScreenRepository,
    SqlPatternScreenRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import DataFreshness, Envelope, Meta
from services.public_api.schemas.pattern import (
    ConditionResult,
    PatternDefinition,
    PatternUniverse,
    PatternItem,
    PatternMetricsOut,
    PatternReadiness,
    PatternScreenData,
)
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day
from shared.calendar_service.types import CalendarLookup, Market
from shared.market_types import VALID_LISTED_MARKET_FILTERS, ListedMarketFilter
from shared.pattern_params import (
    PATTERN_STATUS_INSUFFICIENT_HISTORY,
    PATTERN_STATUS_SUSPECT_PRICE_JUMP,
)

router = APIRouter(tags=["screen"])

KST = ZoneInfo("Asia/Seoul")
DERIVATION_MARKET: Market = "KRX"  # MVP는 KRX 정규장만(DEC-010, screen.py와 동일)

SORT_BY_VALUES: tuple[str, ...] = tuple(SORT_COLUMN_MAP)
SORT_DIR_VALUES: tuple[str, ...] = ("asc", "desc")
DEFAULT_SORT_BY = "market_cap"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
DEFINITION_VERSION = "v1"
# `required` 원문 길이 상한: 가장 긴 유효 값은 "c1,c2,c3,c4,c5,c9"(17자). 이보다 길면 파싱하지 않고
# 즉시 거부한다(대량 입력으로 인한 비용 방지, TC-S02).
MAX_REQUIRED_LENGTH = len(",".join(CONDITION_IDS))

REASON_METRIC_UNAVAILABLE = "METRIC_UNAVAILABLE"

# 기동 시 한 번 읽고 검증한다 — 잘못된 `PATTERN_*` 설정이면 이 모듈을 import하는 순간(앱 기동)
# `ConfigError`로 실패한다(조용한 기본값 대체 금지, 설계서 §3-3).
_THRESHOLDS = load_pattern_thresholds()


def get_pattern_thresholds() -> PatternThresholds:
    """DI 지점 — 단위테스트가 설정을 오버라이드할 수 있게 분리."""
    return _THRESHOLDS


def get_pattern_repository(db: Session = Depends(get_db)) -> PatternScreenRepository:
    return SqlPatternScreenRepository(db)


def get_pattern_calendar_repository(db: Session = Depends(get_db)) -> CalendarLookup:
    return SqlCalendarRepository(db)


def _invalid(message: str) -> ApiError:
    return ApiError(status_code=400, code="INVALID_PARAMETER", message=message)


def parse_required(raw: str | None) -> list[str]:
    """`required` 파싱: 생략=6개 전부, 아니면 `c1,c2,c3,c4,c5,c9`의 비어있지 않은 부분집합.

    중복·미지 ID·공백·빈 토큰·대소문자 불일치는 모두 400. 반환은 정규 순서(입력 순서와 무관).
    """
    if raw is None:
        return list(CONDITION_IDS)
    if len(raw) > MAX_REQUIRED_LENGTH:
        raise _invalid(f"required가 너무 깁니다(최대 {MAX_REQUIRED_LENGTH}자).")
    tokens = raw.split(",")
    unknown = [t for t in tokens if t not in CONDITION_IDS]
    if unknown:
        raise _invalid(f"required는 {','.join(CONDITION_IDS)} 중 비어있지 않은 조합이어야 합니다.")
    if len(set(tokens)) != len(tokens):
        raise _invalid("required에 중복된 조건 ID가 있습니다.")
    return [cid for cid in CONDITION_IDS if cid in tokens]


def reason_for(met: bool | None, status: str | None) -> str | None:
    """산정 불가(`met=None`) 사유. 상태가 이력 부족·단절 의심이면 그 값, 그 외(상태 OK인데 개별 값이
    NULL이거나 구 배치 행)는 `METRIC_UNAVAILABLE`. 값이 있으면 사유 없음."""
    if met is not None:
        return None
    if status in (PATTERN_STATUS_INSUFFICIENT_HISTORY, PATTERN_STATUS_SUSPECT_PRICE_JUMP):
        return status
    return REASON_METRIC_UNAVAILABLE


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, Decimal | float) else None


def _item(row: PatternRow) -> PatternItem:
    m = row.metrics
    return PatternItem(
        stock_code=row.stock_code,
        name=row.name,
        market=row.market,
        conditions={
            cid: ConditionResult(met=row.conds[cid], reason=reason_for(row.conds[cid], row.status))
            for cid in CONDITION_IDS
        },
        metrics=PatternMetricsOut(
            **{
                key: (
                    _num(m[key])
                    if key not in ("ma60_cross_up_days", "recent_surge_flag")
                    else m[key]
                )
                for key in METRIC_KEYS
            }
        ),
        ma60_stage=row.stage,
    )


@router.get("/screen/pattern", response_model=Envelope[PatternScreenData])
def screen_pattern(
    market: str = Query("ALL", description="상장시장 구분(KOSPI|KOSDAQ|ALL)"),
    required: str | None = Query(
        None,
        description="필수로 적용할 조건(쉼표 구분, c1,c2,c3,c4,c5,c9의 부분집합). 생략 시 6개 전부",
    ),
    market_cap_min: int | None = Query(
        None, ge=0, description="시가총액 최소값(KRW 원, 필터 전용)"
    ),
    volume_min: int | None = Query(None, ge=0, description="거래량 최소값(주, 필터 전용)"),
    sort_by: str = Query(DEFAULT_SORT_BY, description="정렬 기준"),
    sort_dir: str = Query("desc", description="정렬 방향(asc|desc)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1),
    thresholds: PatternThresholds = Depends(get_pattern_thresholds),
    repository: PatternScreenRepository = Depends(get_pattern_repository),
    calendar: CalendarLookup = Depends(get_pattern_calendar_repository),
) -> Envelope[PatternScreenData]:
    if not thresholds.enabled:
        raise ApiError(
            status_code=404,
            code="FEATURE_DISABLED",
            message="이 기능은 현재 제공되지 않습니다.",
        )
    if market not in VALID_LISTED_MARKET_FILTERS:
        raise _invalid(f"market은 {VALID_LISTED_MARKET_FILTERS} 중 하나여야 합니다.")
    if sort_by not in SORT_BY_VALUES:
        raise _invalid(f"sort_by는 {SORT_BY_VALUES} 중 하나여야 합니다.")
    if sort_dir not in SORT_DIR_VALUES:
        raise _invalid(f"sort_dir은 {SORT_DIR_VALUES} 중 하나여야 합니다.")
    if page_size > MAX_PAGE_SIZE:
        raise _invalid(f"page_size는 {MAX_PAGE_SIZE}를 초과할 수 없습니다.")
    required_ids = parse_required(required)
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

    # `market` 필터 적용 후 집합 기준: 발행 거래일에 산정 가능(OK) 행이 0건이면 명시적으로 실패한다
    # (예: KOSDAQ만 미준비여도 그 요청은 424 — 부분 시장 준비 상태를 숨기지 않는다).
    total_rows, evaluated_rows = repository.readiness(
        published_trade_date, market_typed, thresholds
    )
    if evaluated_rows == 0:
        raise ApiError(
            status_code=424,
            code="PATTERN_DATA_NOT_READY",
            message="패턴 지표 산출에 필요한 시세 기간이 아직 부족합니다.",
        )

    filters = PatternFilters(
        trade_date=published_trade_date,
        market=market_typed,
        required=tuple(required_ids),
        market_cap_min=market_cap_min,
        volume_min=volume_min,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    result = repository.search(filters, thresholds)

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
    return Envelope[PatternScreenData](
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
        data=PatternScreenData(
            items=[_item(row) for row in result.items],
            total_count=result.total_count,
            page=page,
            definition=PatternDefinition(
                version=DEFINITION_VERSION,
                thresholds=thresholds.definition_thresholds(),
                calc=PatternThresholds.definition_calc(),
                universe=PatternUniverse(**thresholds.definition_universe()),
            ),
            readiness=PatternReadiness(
                evaluated_count=evaluated_rows,
                total_count=total_rows,
                ready_ratio=round(evaluated_rows / total_rows, 4),
            ),
        ),
    )
