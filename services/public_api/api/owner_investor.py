"""관리자 전용 투자자별 순매수 API (DEC-068 → DEC-074로 권한 기준을 DB의 관리자 권한으로 변경).

`GET /api/v1/internal/admin/stocks/{code}/investor` — 관리자 PC가 증권사에서 받아 적재한 값만 내려준다.
두 겹으로 막는다: ① 내부 토큰(웹 서버만 호출) ② 매 호출마다 DB에서 "유효한 세션 + 활성 + 관리자" 확인(`current_admin`). 관리자가 아니면 403.
값이 없으면 빈 목록(0으로 채우지 않는다).
"""

# ruff: noqa: E501
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from services.public_api.api.common import require_stock_code
from services.public_api.api.internal_admin import current_admin
from services.public_api.api.internal_auth import require_internal_call
from services.public_api.db.investor_flow_repository import (
    InvestorFlowRepository,
    SqlInvestorFlowRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import Envelope, Meta
from services.public_api.schemas.intraday import InvestorData

KST = ZoneInfo("Asia/Seoul")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/internal/admin",
    tags=["admin-investor"],
    dependencies=[Depends(require_internal_call), Depends(current_admin), Depends(_no_store)],
)


def get_investor_repository(db: Session = Depends(get_db)) -> InvestorFlowRepository:
    return SqlInvestorFlowRepository(db)


@router.get("/stocks/{code}/investor", response_model=Envelope[InvestorData])
def get_admin_investor(
    code: str,
    repository: InvestorFlowRepository = Depends(get_investor_repository),
) -> Envelope[InvestorData]:
    stock = repository.get_stock(require_stock_code(code))
    if stock is None:
        raise ApiError(status_code=404, code="STOCK_NOT_FOUND", message="종목을 찾을 수 없습니다.")
    return Envelope[InvestorData](
        meta=Meta(generated_at=datetime.now(KST)),
        data=InvestorData(stock_code=stock.stock_code, rows=repository.get_days(stock.stock_code), source="KIS(관리자 PC 수집)"),
    )
