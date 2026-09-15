"""`public_serving.stock_master` 검색 리포지토리 (REQ-001).

`api_service`는 `public_serving`에 읽기전용 GRANT만 있다(03-system-design.md
§3-1). 이 모듈은 조회만 수행하며 쓰기 경로가 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from shared.db_models.public_serving import StockMaster
from shared.market_types import ListedMarketFilter

# 공개 무인증 검색 엔드포인트가 응답 크기 상한 없이 대량 결과를 반환하지
# 않도록 하는 내부 안전장치다. API 요청 파라미터로 노출하지 않는다(설계서
# §4-2가 `/stocks`에 페이지네이션 파라미터를 정의하지 않았으므로, 이를 새
# 계약으로 추가하는 대신 구현 내부 상수로만 둔다 — unit-03-note.md 참조).
MAX_SEARCH_RESULTS = 100


@dataclass(frozen=True)
class StockSearchResultRow:
    stock_code: str
    name: str
    market: str


class StockSearchRepository(Protocol):
    def search(self, *, query: str, market: ListedMarketFilter) -> list[StockSearchResultRow]: ...


class SqlStockSearchRepository:
    def __init__(self, session: Session):
        self._session = session

    def search(self, *, query: str, market: ListedMarketFilter) -> list[StockSearchResultRow]:
        """종목명/코드 부분일치(대소문자 무시) 검색.

        상장폐지 등으로 `is_active=false`인 종목은 검색 결과에서 제외한다
        (REQ-001이 "코스피/코스닥 상장 종목명·코드 검색"으로 범위를 한정하고
        있어, 더 이상 상장되어 있지 않은 종목은 검색 대상이 아니라고 판단했다
        — unit-03-note.md "설계서 대비 편차" 참조).
        """
        pattern = f"%{query}%"
        stmt = select(StockMaster).where(
            StockMaster.is_active.is_(True),
            or_(StockMaster.name.ilike(pattern), StockMaster.stock_code.ilike(pattern)),
        )
        if market != "ALL":
            stmt = stmt.where(StockMaster.market == market)
        stmt = stmt.order_by(StockMaster.stock_code.asc()).limit(MAX_SEARCH_RESULTS)

        rows = self._session.execute(stmt).scalars().all()
        return [
            StockSearchResultRow(stock_code=row.stock_code, name=row.name, market=row.market)
            for row in rows
        ]
