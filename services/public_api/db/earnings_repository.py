"""`public_serving.corp_earnings` 조회 리포지토리 (DEC-041, UNIT-23). 읽기 전용(`api_service`)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.public_api.db.metrics_repository import StockRow
from shared.db_models.public_serving import CorpEarnings, StockMaster


@dataclass(frozen=True)
class EarningsRow:
    fiscal_year: int
    fs_div: str
    revenue: Decimal | None
    operating_income: Decimal | None
    net_income: Decimal | None


class StockEarningsRepository(Protocol):
    def get_stock(self, stock_code: str) -> StockRow | None: ...

    def get_earnings(self, stock_code: str) -> list[EarningsRow]:
        """연도 오름차순."""
        ...


class SqlStockEarningsRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_stock(self, stock_code: str) -> StockRow | None:
        row = self._session.get(StockMaster, stock_code)
        if row is None:
            return None
        return StockRow(stock_code=row.stock_code, name=row.name, market=row.market)

    def get_earnings(self, stock_code: str) -> list[EarningsRow]:
        rows = self._session.execute(
            select(CorpEarnings)
            .where(CorpEarnings.stock_code == stock_code)
            .order_by(CorpEarnings.fiscal_year.asc())
        ).scalars()
        return [
            EarningsRow(r.fiscal_year, r.fs_div, r.revenue, r.operating_income, r.net_income)
            for r in rows
        ]
