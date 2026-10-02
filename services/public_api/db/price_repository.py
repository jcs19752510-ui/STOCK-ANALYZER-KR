"""`public_serving.daily_prices` 조회 리포지토리 (DEC-041, UNIT-20). 읽기 전용(`api_service`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.public_api.db.metrics_repository import StockRow
from shared.db_models.public_serving import DailyPrice, StockMaster


@dataclass(frozen=True)
class PriceRow:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trading_value: int


@dataclass(frozen=True)
class QuoteRow:
    """목록용 시세 요약: 종목별 최신 종가와 직전 거래일 종가(없으면 None)."""

    stock_code: str
    trade_date: date
    close: Decimal
    prev_close: Decimal | None


class QuoteRepository(Protocol):
    def get_quotes(self, codes: list[str]) -> list[QuoteRow]:
        """요청한 종목 중 일봉이 있는 종목만 반환한다(순서는 호출자가 정한다)."""
        ...


class StockPriceRepository(Protocol):
    def get_stock(self, stock_code: str) -> StockRow | None: ...

    def get_prices(self, stock_code: str, days: int) -> list[PriceRow]:
        """최근 `days`개 거래일을 **오름차순**으로 반환한다."""
        ...


class SqlStockPriceRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_stock(self, stock_code: str) -> StockRow | None:
        row = self._session.get(StockMaster, stock_code)
        if row is None:
            return None
        return StockRow(stock_code=row.stock_code, name=row.name, market=row.market)

    def get_prices(self, stock_code: str, days: int) -> list[PriceRow]:
        rows = self._session.execute(
            select(DailyPrice)
            .where(DailyPrice.stock_code == stock_code)
            .order_by(DailyPrice.trade_date.desc())
            .limit(days)
        ).scalars()
        return [
            PriceRow(r.trade_date, r.open, r.high, r.low, r.close, r.volume, r.trading_value)
            for r in reversed(list(rows))
        ]


class SqlQuoteRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_quotes(self, codes: list[str]) -> list[QuoteRow]:
        ranked = (
            select(
                DailyPrice.stock_code,
                DailyPrice.trade_date,
                DailyPrice.close,
                func.row_number()
                .over(partition_by=DailyPrice.stock_code, order_by=DailyPrice.trade_date.desc())
                .label("rn"),
            )
            .where(DailyPrice.stock_code.in_(codes))
            .subquery()
        )
        rows = self._session.execute(
            select(ranked.c.stock_code, ranked.c.trade_date, ranked.c.close, ranked.c.rn)
            .where(ranked.c.rn <= 2)
            .order_by(ranked.c.stock_code, ranked.c.rn)
        ).all()
        latest: dict[str, QuoteRow] = {}
        for code, trade_date, close, rn in rows:
            if rn == 1:
                latest[code] = QuoteRow(code, trade_date, close, None)
            elif code in latest:
                cur = latest[code]
                latest[code] = QuoteRow(cur.stock_code, cur.trade_date, cur.close, close)
        return list(latest.values())
