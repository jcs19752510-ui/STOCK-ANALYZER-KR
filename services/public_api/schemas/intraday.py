"""개인 로컬 모드 장중 시세 응답 스키마 (DEC-052). 증권사 응답을 이 형태로 정규화해 내려준다."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class MinuteBar(BaseModel):
    time: str  # "HH:MM" (봉 시작 시각)
    open: float
    high: float
    low: float
    close: float
    volume: int


class MinutesData(BaseModel):
    stock_code: str
    date: date
    interval: int  # 분
    bars: list[MinuteBar]  # 시간 오름차순
    source: str = "KIS"


class TickItem(BaseModel):
    time: str  # "HH:MM:SS"
    price: float
    change: float | None  # 전일 대비(하락은 음수)
    change_pct: float | None
    volume: int  # 체결량
    strength: float | None  # 당일 체결강도


class TicksData(BaseModel):
    stock_code: str
    ticks: list[TickItem]  # 최근 체결이 앞
    truncated: bool  # 요청 건수만큼 모으지 못했으면 true
    source: str = "KIS"


class BookLevel(BaseModel):
    price: float
    quantity: int


class ExpectedExecution(BaseModel):
    price: float
    change: float | None
    change_pct: float | None
    volume: int | None


class OrderBookData(BaseModel):
    stock_code: str
    time: str | None  # 호가 접수 시각 "HH:MM:SS"
    asks: list[BookLevel]  # 매도호가 1단계(가장 낮은 가격)부터
    bids: list[BookLevel]  # 매수호가 1단계(가장 높은 가격)부터
    total_ask_quantity: int
    total_bid_quantity: int
    expected: ExpectedExecution | None  # 장 시작 전·마감 동시호가 예상체결
    source: str = "KIS"


class LocalStatus(BaseModel):
    enabled: bool
    provider: str = "KIS"
    configured: bool
