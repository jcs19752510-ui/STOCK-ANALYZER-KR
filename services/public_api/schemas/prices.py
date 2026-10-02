"""`GET /api/v1/stocks/{code}/prices` 응답 스키마 (DEC-041, UNIT-20).

종목 상세 차트·일자별 시세용 **일 단위 종가 기준** 시세다. 실시간·호가가 아니다. 이 엔드포인트는
신규이며 기존 `/screen`·`/screen/pattern`·`/stocks/{code}/metrics`의 원값 비노출 계약은 그대로다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class PricePoint(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    trading_value: int
    # 직전 거래일(응답 안의 바로 앞 행) 종가 대비. 첫 행은 비교 대상이 없어 null.
    change: float | None
    change_pct: float | None


class StockPricesData(BaseModel):
    stock_code: str
    name: str
    market: str
    prices: list[PricePoint]  # 거래일 오름차순


class QuoteItem(BaseModel):
    stock_code: str
    trade_date: date
    close: float
    change: float | None
    change_pct: float | None


class QuotesData(BaseModel):
    quotes: list[QuoteItem]  # 요청 순서, 일봉이 없는 종목은 생략
