"""캘린더 서비스 공용 타입 정의.

`market`은 거래소 세션 구분(KRX/NXT)이다(03-system-design.md §3-1-1).
`stock_master` 등의 상장시장 구분(KOSPI/KOSDAQ)과는 다른 축이므로
이 모듈에서 정의하는 Market 타입을 상장시장 값과 혼용하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Literal, Protocol

Market = Literal["KRX", "NXT"]

VALID_MARKETS: tuple[Market, ...] = ("KRX", "NXT")


@dataclass(frozen=True)
class CalendarRow:
    """reference.market_calendar 한 행에 대응하는 값 객체."""

    trade_date: date
    market: Market
    is_trading_day: bool
    session_close_at: time | None = None
    holiday_name: str | None = None
    source: str | None = None


class CalendarLookup(Protocol):
    """reference.market_calendar 조회 인터페이스.

    get_last_trading_day()가 실제 DB 구현(SQLAlchemy 등)에 결합되지 않도록
    분리한 추상화다. 실제 구현은 services/public_api/db 에 있다.
    """

    def get(self, trade_date: date, market: Market) -> CalendarRow | None: ...
