"""장중 재계산이 공유하는 값 타입(의존성 없음 — 순환 import 방지용)."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class DailyBar:
    """일봉 한 줄. 지표 계산에는 종가·거래량만 쓰지만 고가·저가·시가도 보관한다(보충 교차검증·표시용)."""

    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
