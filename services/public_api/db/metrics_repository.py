"""`public_serving.stock_master`/`derived_metrics_daily`/`current_published_batch`
조회 리포지토리 (REQ-002).

`api_service`는 `public_serving`에 읽기전용 GRANT만 있다(§3-1). 이 모듈은
조회만 수행하며 쓰기 경로가 없다 — Derivation Batch(쓰기)는
`services/derivation_batch/repository.py`가 별도로 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db_models.public_serving import CurrentPublishedBatch, DerivedMetricsDaily, StockMaster


@dataclass(frozen=True)
class StockRow:
    stock_code: str
    name: str
    market: str


@dataclass(frozen=True)
class DerivedMetricsRow:
    return_pct: Decimal | None
    return_rank_pct: Decimal | None
    ma5_gap_pct: Decimal | None
    ma20_gap_pct: Decimal | None
    volume_anomaly_score: Decimal | None
    per_percentile: Decimal | None
    pbr_percentile: Decimal | None
    market_cap_percentile: Decimal | None


class StockMetricsRepository(Protocol):
    def get_stock(self, stock_code: str) -> StockRow | None: ...

    def get_current_published_trade_date(self, market: str) -> date | None: ...

    def get_metrics(self, stock_code: str, trade_date: date) -> DerivedMetricsRow | None: ...


class SqlStockMetricsRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_stock(self, stock_code: str) -> StockRow | None:
        row = self._session.get(StockMaster, stock_code)
        if row is None:
            return None
        return StockRow(stock_code=row.stock_code, name=row.name, market=row.market)

    def get_current_published_trade_date(self, market: str) -> date | None:
        row = self._session.get(CurrentPublishedBatch, market)
        return row.trade_date if row is not None else None

    def get_metrics(self, stock_code: str, trade_date: date) -> DerivedMetricsRow | None:
        stmt = select(DerivedMetricsDaily).where(
            DerivedMetricsDaily.stock_code == stock_code,
            DerivedMetricsDaily.trade_date == trade_date,
        )
        row = self._session.execute(stmt).scalars().first()
        if row is None:
            return None
        return DerivedMetricsRow(
            return_pct=row.return_pct,
            return_rank_pct=row.return_rank_pct,
            ma5_gap_pct=row.ma5_gap_pct,
            ma20_gap_pct=row.ma20_gap_pct,
            volume_anomaly_score=row.volume_anomaly_score,
            per_percentile=row.per_percentile,
            pbr_percentile=row.pbr_percentile,
            market_cap_percentile=row.market_cap_percentile,
        )


__all__ = [
    "DerivedMetricsRow",
    "SqlStockMetricsRepository",
    "StockMetricsRepository",
    "StockRow",
]
