"""`public_serving.derived_metrics_daily` 조건 스크리닝 리포지토리 (REQ-003).

`api_service`는 `public_serving`에 읽기전용 GRANT만 있다(03-system-design.md
§3-1). 이 모듈은 조회만 수행하며 쓰기 경로가 없다.

`derived_metrics_daily`에는 원본 시세 컬럼(open/high/low/close)이 애초에
존재하지 않고(§4-3), `per_raw`/`pbr_raw`/`market_cap_raw_krw`/`volume_raw`는
DB 컬럼으로는 존재하되 이 리포지토리가 반환하는 `ScreenRow`에도, 상위
`services/public_api/schemas/screen.py` 응답 스키마에도 포함하지 않는다
(§4-3 화이트리스트 원칙, 필터링에만 사용).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from shared.db_models.public_serving import CurrentPublishedBatch, DerivedMetricsDaily, StockMaster
from shared.market_types import ListedMarketFilter

# `sort_by` 허용값(03-system-design.md §4-2)과 실제 정렬 대상 컬럼의 매핑.
# "서버 내부 정렬은 원시값 컬럼을 기준으로 수행한다"(§4-2 v3 신규 설명) —
# percentile 컬럼이 아니라 `*_raw` 컬럼에 이미 인덱스가 걸려 있어 이쪽을 쓴다.
SORT_COLUMN_MAP = {
    "return_pct": DerivedMetricsDaily.return_pct,
    "market_cap": DerivedMetricsDaily.market_cap_raw_krw,
    "per": DerivedMetricsDaily.per_raw,
    "pbr": DerivedMetricsDaily.pbr_raw,
    "volume_anomaly_score": DerivedMetricsDaily.volume_anomaly_score,
}


@dataclass(frozen=True)
class ScreenFilters:
    trade_date: date
    market: ListedMarketFilter
    market_cap_min: int | None
    market_cap_max: int | None
    volume_min: int | None
    return_pct_min: float | None
    return_pct_max: float | None
    per_max: float | None
    pbr_max: float | None
    sort_by: str
    sort_dir: str
    page: int
    page_size: int


@dataclass(frozen=True)
class ScreenRow:
    stock_code: str
    name: str
    market: str
    return_pct: Decimal | None
    per_percentile: Decimal | None
    pbr_percentile: Decimal | None
    market_cap_percentile: Decimal | None
    volume_anomaly_score: Decimal | None


@dataclass(frozen=True)
class ScreenQueryResult:
    items: list[ScreenRow]
    total_count: int


class ScreenRepository(Protocol):
    def get_current_published_trade_date(self, market: str) -> date | None: ...

    def search(self, filters: ScreenFilters) -> ScreenQueryResult: ...


def _apply_filters(stmt: Select, filters: ScreenFilters) -> Select:
    """`null` 지표를 조건으로 건 경우 자동 제외(§3-2 결측치 처리 원칙) —
    SQL의 `NULL 비교는 항상 알 수 없음(false 취급)` 표준 동작을 그대로
    활용한다(별도 `IS NOT NULL` 분기 불필요)."""
    stmt = stmt.where(DerivedMetricsDaily.trade_date == filters.trade_date)
    if filters.market != "ALL":
        stmt = stmt.where(DerivedMetricsDaily.market == filters.market)
    if filters.market_cap_min is not None:
        stmt = stmt.where(DerivedMetricsDaily.market_cap_raw_krw >= filters.market_cap_min)
    if filters.market_cap_max is not None:
        stmt = stmt.where(DerivedMetricsDaily.market_cap_raw_krw <= filters.market_cap_max)
    if filters.volume_min is not None:
        stmt = stmt.where(DerivedMetricsDaily.volume_raw >= filters.volume_min)
    if filters.return_pct_min is not None:
        stmt = stmt.where(DerivedMetricsDaily.return_pct >= filters.return_pct_min)
    if filters.return_pct_max is not None:
        stmt = stmt.where(DerivedMetricsDaily.return_pct <= filters.return_pct_max)
    if filters.per_max is not None:
        stmt = stmt.where(DerivedMetricsDaily.per_raw <= filters.per_max)
    if filters.pbr_max is not None:
        stmt = stmt.where(DerivedMetricsDaily.pbr_raw <= filters.pbr_max)
    return stmt


class SqlScreenRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_current_published_trade_date(self, market: str) -> date | None:
        row = self._session.get(CurrentPublishedBatch, market)
        return row.trade_date if row is not None else None

    def search(self, filters: ScreenFilters) -> ScreenQueryResult:
        filtered = _apply_filters(select(DerivedMetricsDaily), filters)

        count_stmt = select(func.count()).select_from(filtered.subquery())
        total_count = self._session.execute(count_stmt).scalar_one()

        sort_column = SORT_COLUMN_MAP[filters.sort_by]
        order = sort_column.desc() if filters.sort_dir == "desc" else sort_column.asc()

        # 동률 처리는 stock_code 오름차순을 2차 정렬 키로 고정한다(§4-2 v3 신규
        # 설명 — 페이지네이션 결과가 매번 동일하게 결정론적으로 나오도록).
        page_stmt = (
            filtered.join(StockMaster, StockMaster.stock_code == DerivedMetricsDaily.stock_code)
            .add_columns(StockMaster.name)
            .order_by(order, DerivedMetricsDaily.stock_code.asc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        rows = self._session.execute(page_stmt).all()
        items = [
            ScreenRow(
                stock_code=metrics.stock_code,
                name=name,
                market=metrics.market,
                return_pct=metrics.return_pct,
                per_percentile=metrics.per_percentile,
                pbr_percentile=metrics.pbr_percentile,
                market_cap_percentile=metrics.market_cap_percentile,
                volume_anomaly_score=metrics.volume_anomaly_score,
            )
            for metrics, name in rows
        ]
        return ScreenQueryResult(items=items, total_count=total_count)


__all__ = [
    "SORT_COLUMN_MAP",
    "ScreenFilters",
    "ScreenQueryResult",
    "ScreenRepository",
    "ScreenRow",
    "SqlScreenRepository",
]
