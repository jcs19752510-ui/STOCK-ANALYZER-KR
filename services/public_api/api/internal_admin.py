"""관리자 전용 내부 경로 (DEC-074). 웹 서버가 관리자 화면을 위해서만 부른다.

- `GET  /api/v1/internal/admin/members` : 모든 회원(승인 대기·활성·사용 중지) 목록.
- `POST /api/v1/internal/admin/action`  : 추가·승인·거절·활성/비활성·권한 변경·이름 수정·비밀번호 초기화·세션 취소·삭제.

두 겹으로 막는다: ① 내부 토큰(웹 서버만 호출) ② **매 호출마다 DB에서** "요청한 세션이 유효하고 회원이 활성이며 권한이 관리자"인지 확인
(`X-Auth-User`·`X-Auth-Session` 헤더의 값으로 조회하며, 웹 서버가 말한 권한이나 쿠키 속 권한을 믿지 않는다). 아니면 403.
"""

# ruff: noqa: E501
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from services.public_api.api.internal_auth import require_internal_call
from services.public_api.auth.admin import AdminError, list_members, perform
from services.public_api.auth.service import AuthUser, require_admin
from services.public_api.db.auth_session import get_auth_db
from services.public_api.errors import ApiError
from services.public_api.schemas.auth import (
    AdminActionData,
    AdminActionRequest,
    AdminMember,
    AdminMembersData,
)
from services.public_api.schemas.envelope import Envelope, Meta
from shared.auth.passwords import PolicyError

KST = ZoneInfo("Asia/Seoul")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def current_admin(request: Request, db: Session = Depends(get_auth_db)) -> AuthUser:
    uid = request.headers.get("x-auth-user", "").strip()
    sid = request.headers.get("x-auth-session", "").strip()
    if not _UUID.fullmatch(uid) or not _UUID.fullmatch(sid):
        raise ApiError(status_code=403, code="FORBIDDEN", message="접근 권한이 없습니다.")
    admin = require_admin(db, uid, sid)
    if admin is None:
        raise ApiError(status_code=403, code="FORBIDDEN", message="접근 권한이 없습니다.")
    return admin


router = APIRouter(prefix="/internal/admin", tags=["internal-admin"], dependencies=[Depends(require_internal_call)])


def _meta() -> Meta:
    return Meta(generated_at=datetime.now(KST))


@router.get("/members", response_model=Envelope[AdminMembersData])
def admin_members(admin: AuthUser = Depends(current_admin), db: Session = Depends(get_auth_db)) -> Envelope[AdminMembersData]:
    rows = list_members(db)
    items = [AdminMember(**r.__dict__) for r in rows]
    return Envelope[AdminMembersData](
        meta=_meta(),
        data=AdminMembersData(items=items, total=len(items), pending=sum(1 for r in rows if r.status == "pending")),
    )


@router.post("/action", response_model=Envelope[AdminActionData])
def admin_action(
    body: AdminActionRequest, admin: AuthUser = Depends(current_admin), db: Session = Depends(get_auth_db)
) -> Envelope[AdminActionData]:
    try:
        result = perform(
            db,
            admin,
            body.action,
            body.username,
            role=body.role,
            display_name=body.display_name,
            password=body.password,
        )
    except AdminError as exc:
        raise ApiError(status_code=exc.status, code=exc.code, message=exc.message) from exc
    except PolicyError as exc:  # 방어: perform이 이미 AdminError로 바꾸지만 누락 대비
        raise ApiError(status_code=400, code="INVALID_INPUT", message=" ".join(exc.messages)) from exc
    return Envelope[AdminActionData](meta=_meta(), data=AdminActionData(result=result))
