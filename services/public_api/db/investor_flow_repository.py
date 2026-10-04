"""`public_serving.investor_flow_daily` 조회 리포지토리 (DEC-068). 읽기 전용(`api_service`)."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.public_api.db.metrics_repository import StockRow
from services.public_api.schemas.intraday import InvestorDay
from shared.db_models.public_serving import InvestorFlowDaily, StockMaster

MAX_DAYS = 30


class InvestorFlowRepository(Protocol):
    def get_stock(self, stock_code: str) -> StockRow | None: ...

    def get_days(self, stock_code: str) -> list[InvestorDay]:
        """최근 거래일이 앞."""
        ...


class SqlInvestorFlowRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_stock(self, stock_code: str) -> StockRow | None:
        row = self._session.get(StockMaster, stock_code)
        if row is None:
            return None
        return StockRow(stock_code=row.stock_code, name=row.name, market=row.market)

    def get_days(self, stock_code: str) -> list[InvestorDay]:
        rows = self._session.execute(
            select(InvestorFlowDaily)
            .where(InvestorFlowDaily.stock_code == stock_code)
            .order_by(InvestorFlowDaily.trade_date.desc())
            .limit(MAX_DAYS)
        ).scalars()
        return [
            InvestorDay(
                date=r.trade_date,
                personal_quantity=r.personal_quantity,
                foreign_quantity=r.foreign_quantity,
                institution_quantity=r.institution_quantity,
                personal_amount_million=r.personal_amount_million,
                foreign_amount_million=r.foreign_amount_million,
                institution_amount_million=r.institution_amount_million,
            )
            for r in rows
        ]
