from __future__ import annotations

from pydantic import BaseModel


class ScreenResultItem(BaseModel):
    """`GET /api/v1/screen` 결과 1건(REQ-003, 03-system-design.md §4-2).

    `matched_metrics`는 (a) 실제 값이 지정된 필터 조건의 지표 ∪ (b) `sort_by`로
    지정된 지표만 포함하는 화이트리스트 딕셔너리다(DEC-013). 원본 시세
    원문(OHLCV)이나 PER/PBR/시가총액 원시값은 이 안에도, 이 스키마 어디에도
    존재하지 않는다(§4-3) — 화면은 이 값을 그대로 문장으로 표시한다.
    """

    stock_code: str
    name: str
    market: str
    matched_metrics: dict[str, float | None]


class ScreenData(BaseModel):
    items: list[ScreenResultItem]
    total_count: int
    page: int
