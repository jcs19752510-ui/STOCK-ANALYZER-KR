"""종목 연간 실적 API (DEC-041, UNIT-23) — 종목 상세 실적 탭용(DART 공시 수치)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from services.public_api.api.common import require_stock_code
from services.public_api.db.earnings_repository import (
    SqlStockEarningsRepository,
    StockEarningsRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.earnings import EarningsYear, StockEarningsData
from services.public_api.schemas.envelope import Envelope, Meta

router = APIRouter(tags=["earnings"])

KST = ZoneInfo("Asia/Seoul")


def get_earnings_repository(db: Session = Depends(get_db)) -> StockEarningsRepository:
    return SqlStockEarningsRepository(db)


def _num(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


@router.get("/stocks/{code}/earnings", response_model=Envelope[StockEarningsData])
def get_stock_earnings(
    code: str,
    repository: StockEarningsRepository = Depends(get_earnings_repository),
) -> Envelope[StockEarningsData]:
    stock = repository.get_stock(require_stock_code(code))
    if stock is None:
        raise ApiError(status_code=404, code="STOCK_NOT_FOUND", message="종목을 찾을 수 없습니다.")
    rows = repository.get_earnings(code)
    return Envelope[StockEarningsData](
        meta=Meta(generated_at=datetime.now(KST)),
        data=StockEarningsData(
            stock_code=stock.stock_code,
            name=stock.name,
            market=stock.market,
            earnings=[
                EarningsYear(
                    fiscal_year=r.fiscal_year,
                    fs_div=r.fs_div,
                    revenue=_num(r.revenue),
                    operating_income=_num(r.operating_income),
                    net_income=_num(r.net_income),
                )
                for r in rows
            ],
        ),
    )
