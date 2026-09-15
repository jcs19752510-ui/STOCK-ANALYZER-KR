from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class LastTradingDayData(BaseModel):
    trade_date: date
