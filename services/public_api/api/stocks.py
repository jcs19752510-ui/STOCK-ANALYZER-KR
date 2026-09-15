from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.public_api.db.session import get_db
from services.public_api.db.stock_repository import (
    SqlStockSearchRepository,
    StockSearchRepository,
)
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import Envelope, Meta
from services.public_api.schemas.stocks import StockSearchItem
from shared.market_types import VALID_LISTED_MARKET_FILTERS, ListedMarketFilter

router = APIRouter(tags=["stocks"])

KST = ZoneInfo("Asia/Seoul")


def get_stock_search_repository(db: Session = Depends(get_db)) -> StockSearchRepository:
    """DI 지점을 분리해, 단위테스트가 실제 DB 없이 이 의존성만 오버라이드할 수 있게 한다."""
    return SqlStockSearchRepository(db)


@router.get("/stocks", response_model=Envelope[list[StockSearchItem]])
def search_stocks(
    query: str = Query(..., description="종목명/코드 부분일치 검색어(빈 값 불가)"),
    market: str = Query(
        "ALL", description="상장시장 구분(KOSPI|KOSDAQ|ALL), 생략 시 기본값 ALL"
    ),
    repository: StockSearchRepository = Depends(get_stock_search_repository),
) -> Envelope[list[StockSearchItem]]:
    if not query.strip():
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message="query는 빈 값일 수 없습니다.",
        )
    if market not in VALID_LISTED_MARKET_FILTERS:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"market은 {VALID_LISTED_MARKET_FILTERS} 중 하나여야 합니다: {market!r}",
        )
    market_typed: ListedMarketFilter = market  # type: ignore[assignment]

    rows = repository.search(query=query.strip(), market=market_typed)

    return Envelope[list[StockSearchItem]](
        meta=Meta(generated_at=datetime.now(KST)),
        data=[
            StockSearchItem(stock_code=row.stock_code, name=row.name, market=row.market)
            for row in rows
        ],
    )
