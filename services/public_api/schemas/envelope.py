"""공통 응답 envelope (03-system-design.md §4-1).

REQ-007(면책 문구 상시 노출)을 위해 `disclaimer` 원문은 이 모듈 한 곳에서만
관리한다(§6-4: "문구 원문은 백엔드 상수 1곳에서 관리").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

DISCLAIMER_TEXT = (
    "이 서비스는 투자자문업 등록 사업자가 아니며, 제공되는 정보는 투자 조언이 "
    "아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다."
)

DataT = TypeVar("DataT")


class DataFreshness(BaseModel):
    market: str
    trade_date: date
    session_close_at: datetime | None = None
    generated_at: datetime
    is_latest_trading_day: bool
    expected_last_trading_day: date
    staleness_note: str | None = None


class Meta(BaseModel):
    data_freshness: DataFreshness | None = None
    disclaimer: str = DISCLAIMER_TEXT
    generated_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str


class Envelope(BaseModel, Generic[DataT]):
    meta: Meta
    data: DataT | None = None
    error: ErrorDetail | None = None


__all__ = [
    "DISCLAIMER_TEXT",
    "DataFreshness",
    "Envelope",
    "ErrorDetail",
    "Meta",
]
