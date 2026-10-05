"""소유자 전용 투자자별 순매수 API (DEC-068).

`GET /api/v1/internal/owner/stocks/{code}/investor` — 소유자 PC가 증권사에서 받아 적재한 값만 내려준다.
세 겹으로 막는다: ① 내부 토큰(웹 서버만 호출) ② 웹이 전달한 로그인 아이디(`X-Auth-Username`)가 API의
`PUBLIC_API_OWNER_USERNAME`(쉼표로 여러 명 가능)에 있을 때만 ③ 소유자 설정이 없으면 404로 존재를 숨긴다.
소유자 외 회원은 403. 값이 없으면 빈 목록(0으로 채우지 않는다).
"""

# ruff: noqa: E501
from __future__ import annotations

import hmac
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from services.public_api.api.common import require_stock_code
from services.public_api.db.investor_flow_repository import (
    InvestorFlowRepository,
    SqlInvestorFlowRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import Envelope, Meta
from services.public_api.schemas.intraday import InvestorData

KST = ZoneInfo("Asia/Seoul")
OWNER_ENV = "PUBLIC_API_OWNER_USERNAME"


def owner_usernames() -> list[str]:
    """`PUBLIC_API_OWNER_USERNAME`은 쉼표로 여러 아이디를 둘 수 있다(예: `jcs1973,jcs1975`). 공백·대소문자는 무시한다."""
    return [u for u in (x.strip().lower() for x in os.environ.get(OWNER_ENV, "").split(",")) if u]


def require_owner(request: Request, response: Response) -> None:
    owners = owner_usernames()
    token = os.environ.get("PUBLIC_API_INTERNAL_TOKEN", "").strip()
    if not owners or not token:
        raise ApiError(status_code=404, code="FEATURE_DISABLED", message="이 기능은 현재 제공되지 않습니다.")
    provided = request.headers.get("x-internal-token", "")
    if not provided or not hmac.compare_digest(provided.encode("utf-8"), token.encode("utf-8")):
        raise ApiError(status_code=401, code="AUTH_REQUIRED", message="인증이 필요합니다.")
    username = request.headers.get("x-auth-username", "").strip().lower()
    matched = False
    for owner in owners:  # 전부 비교한다(일치하는 순간 멈추지 않아 비교 시간이 아이디 위치에 좌우되지 않는다)
        matched |= hmac.compare_digest(username.encode("utf-8"), owner.encode("utf-8"))
    if not username or not matched:
        raise ApiError(status_code=403, code="FORBIDDEN", message="접근 권한이 없습니다.")
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/internal/owner", tags=["owner-investor"], dependencies=[Depends(require_owner)])


def get_investor_repository(db: Session = Depends(get_db)) -> InvestorFlowRepository:
    return SqlInvestorFlowRepository(db)


@router.get("/stocks/{code}/investor", response_model=Envelope[InvestorData])
def get_owner_investor(
    code: str,
    repository: InvestorFlowRepository = Depends(get_investor_repository),
) -> Envelope[InvestorData]:
    stock = repository.get_stock(require_stock_code(code))
    if stock is None:
        raise ApiError(status_code=404, code="STOCK_NOT_FOUND", message="종목을 찾을 수 없습니다.")
    return Envelope[InvestorData](
        meta=Meta(generated_at=datetime.now(KST)),
        data=InvestorData(stock_code=stock.stock_code, rows=repository.get_days(stock.stock_code), source="KIS(소유자 PC 수집)"),
    )
