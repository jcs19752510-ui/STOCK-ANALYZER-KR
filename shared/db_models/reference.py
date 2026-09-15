"""`reference` 스키마 모델 (REQ-005, REQ-012).

03-system-design.md §3-2 `reference.market_calendar` 정의를 그대로 반영한다.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from shared.calendar_service.types import Market
from shared.db_models.base import Base

market_session_enum = Enum(
    "KRX",
    "NXT",
    name="market_session",
    schema="reference",
    create_constraint=True,
    validate_strings=True,
)


class MarketCalendar(Base):
    """거래소 세션(KRX/NXT) 단위 휴장일/영업일 캘린더."""

    __tablename__ = "market_calendar"
    __table_args__ = {"schema": "reference"}

    trade_date: Mapped[date] = mapped_column(primary_key=True)
    market: Mapped[Market] = mapped_column(market_session_enum, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(nullable=False)
    session_close_at: Mapped[time | None] = mapped_column(nullable=True)
    holiday_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
