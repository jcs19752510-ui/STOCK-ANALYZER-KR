"""`public_serving.market_summary_daily` 조회 리포지토리 (REQ-004).

`api_service`는 `public_serving`에 읽기전용 GRANT만 있다(03-system-design.md
§3-1). 이 모듈은 조회만 수행하며 쓰기 경로가 없다 — Derivation Batch(쓰기)는
`services/derivation_batch/repository.py`가 별도로 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

from shared.db_models.public_serving import CurrentPublishedBatch, MarketSummaryDaily
from shared.market_types import ListedMarketFilter


@dataclass(frozen=True)
class SectorSummaryRow:
    sector: str
    trading_value_krw: int


@dataclass(frozen=True)
class MarketSummaryRow:
    market: str
    advancers_count: int
    decliners_count: int
    unchanged_count: int
    top_sectors_by_value: list[SectorSummaryRow]
    total_trading_value_krw: int


class MarketSummaryRepository(Protocol):
    def get_current_published_trade_date(self, market: str) -> date | None: ...

    def get_summary(
        self, trade_date: date, market: ListedMarketFilter
    ) -> MarketSummaryRow | None: ...


class SqlMarketSummaryRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_current_published_trade_date(self, market: str) -> date | None:
        row = self._session.get(CurrentPublishedBatch, market)
        return row.trade_date if row is not None else None

    def get_summary(
        self, trade_date: date, market: ListedMarketFilter
    ) -> MarketSummaryRow | None:
        row = self._session.get(MarketSummaryDaily, (trade_date, market))
        if row is None:
            return None
        return MarketSummaryRow(
            market=row.market,
            advancers_count=row.advancers_count,
            decliners_count=row.decliners_count,
            unchanged_count=row.unchanged_count,
            top_sectors_by_value=[
                SectorSummaryRow(
                    sector=item["sector"], trading_value_krw=item["trading_value_krw"]
                )
                for item in row.top_sectors_by_value
            ],
            total_trading_value_krw=row.total_trading_value_krw,
        )


__all__ = [
    "MarketSummaryRepository",
    "MarketSummaryRow",
    "SectorSummaryRow",
    "SqlMarketSummaryRepository",
]
