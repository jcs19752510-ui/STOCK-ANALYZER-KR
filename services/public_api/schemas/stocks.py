from __future__ import annotations

from pydantic import BaseModel


class StockSearchItem(BaseModel):
    """`GET /api/v1/stocks` 응답 항목(REQ-001, 03-system-design.md §4-2).

    `market`은 상장시장 구분(KOSPI/KOSDAQ, §3-1-1)이다. 원본 시세 필드
    (open/high/low/close/volume)는 `stock_master`에 애초에 존재하지 않으므로
    이 스키마에도 나타날 수 없다(§4-3 데이터 가공 원칙과 무관 — 이 테이블은
    처음부터 시세 데이터를 다루지 않는다).
    """

    stock_code: str
    name: str
    market: str
