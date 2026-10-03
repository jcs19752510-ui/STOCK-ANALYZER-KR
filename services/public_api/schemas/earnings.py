"""`GET /api/v1/stocks/{code}/earnings` 응답 스키마 (DEC-041, UNIT-23).

DART 사업보고서의 연간 공시 수치(원)를 그대로 내려준다. 찾지 못한 항목은 null(0이 아님).
평가·점수·등급 같은 해석 필드는 없다.
"""

from __future__ import annotations

from pydantic import BaseModel


class EarningsYear(BaseModel):
    fiscal_year: int
    fs_div: str  # CFS(연결) | OFS(개별)
    revenue: float | None
    operating_income: float | None
    net_income: float | None


class StockEarningsData(BaseModel):
    stock_code: str
    name: str
    market: str
    earnings: list[EarningsYear]  # 연도 오름차순
