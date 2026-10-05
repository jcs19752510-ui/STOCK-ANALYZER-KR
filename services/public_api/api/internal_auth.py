"""웹 서버 전용 로그인 내부 경로 (DEC-067). 브라우저는 이 경로를 직접 부를 수 없다(내부 토큰이 없다).

- `POST /api/v1/internal/auth/login` : 아이디·비밀번호 확인. 실패는 이유와 관계없이 같은 401.
- `POST /api/v1/internal/auth/session-check` : 이 세션이 취소·만료되지 않았고 회원이 아직 활성인지(웹이 5분마다 확인).
- `POST /api/v1/internal/auth/logout` : 이 세션 하나를 서버에서 취소(DEC-070).
- `POST /api/v1/internal/auth/logout-all` : 이 회원의 모든 세션 취소(DEC-071). 요청한 세션이 살아 있을 때만.
- `POST /api/v1/internal/auth/signup` : 회원가입 신청(승인 대기 계정 생성, DEC-074).

모든 경로는 **강제 스위치와 무관하게** 항상 내부 토큰을 요구한다(로컬에서 스위치가 꺼져 있어도 열려 있지 않다).
회원 DB 주소(`PUBLIC_API_AUTH_DATABASE_URL`)나 토큰이 설정되지 않으면 404로 존재 자체를 숨긴다.
"""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import hmac
import ipaddress
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from services.public_api.auth.service import (
    SignupError,
    authenticate,
    check_session_user,
    create_session,
    revoke_all_sessions,
    revoke_session,
    signup,
)
from services.public_api.auth.throttle import allow_login_attempt, allow_signup_attempt
from services.public_api.core.config import get_auth_database_url
from services.public_api.db.auth_session import get_auth_db
from services.public_api.errors import ApiError
from services.public_api.schemas.auth import (
    LoginData,
    LoginRequest,
    LogoutAllData,
    LogoutData,
    LogoutRequest,
    SessionCheckData,
    SessionCheckRequest,
    SignupData,
    SignupRequest,
)
from services.public_api.schemas.envelope import Envelope, Meta

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)

_INVALID_CREDENTIALS = "아이디 또는 비밀번호가 올바르지 않습니다."


def require_internal_call(request: Request, response: Response) -> None:
    expected = os.environ.get("PUBLIC_API_INTERNAL_TOKEN", "").strip()
    if get_auth_database_url() is None or not expected:
        raise ApiError(status_code=404, code="FEATURE_DISABLED", message="이 기능은 현재 제공되지 않습니다.")
    provided = request.headers.get("x-internal-token", "")
    if not provided or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise ApiError(status_code=401, code="AUTH_REQUIRED", message="인증이 필요합니다.")
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/internal", tags=["internal-auth"], dependencies=[Depends(require_internal_call)])


def _client_ip(request: Request) -> str | None:
    """웹 서버가 전달한 방문자 주소. 토큰이 검증된 요청에서만 이 함수가 불리므로 신뢰한다. 형식이 틀리면 없는 것으로 본다."""
    raw = request.headers.get("x-end-user-ip", "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _meta() -> Meta:
    return Meta(generated_at=datetime.now(KST))


@router.post("/auth/login", response_model=Envelope[LoginData])
def login(body: LoginRequest, request: Request, db: Session = Depends(get_auth_db)) -> Envelope[LoginData]:
    ip = _client_ip(request)
    if not allow_login_attempt(ip):
        raise ApiError(
            status_code=429,
            code="LOGIN_RATE_LIMITED",
            message="로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        )
    outcome = authenticate(db, body.username, body.password, ip)
    if outcome.state == "pending":  # 비밀번호가 맞은 본인에게만 알려 준다
        raise ApiError(status_code=403, code="PENDING_APPROVAL", message="관리자 승인 대기 중입니다. 승인된 뒤에 로그인할 수 있습니다.")
    if outcome.state == "disabled":
        raise ApiError(status_code=403, code="ACCOUNT_DISABLED", message="사용이 중지된 계정입니다. 관리자에게 문의해 주세요.")
    if not outcome.ok or outcome.user is None:
        raise ApiError(status_code=401, code="INVALID_CREDENTIALS", message=_INVALID_CREDENTIALS)
    user = outcome.user
    session_id, expires_in = create_session(db, user.user_id, body.remember)
    return Envelope[LoginData](
        meta=_meta(),
        data=LoginData(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            session_id=session_id,
            expires_in_seconds=expires_in,
        ),
    )


@router.post("/auth/session-check", response_model=Envelope[SessionCheckData])
def session_check(body: SessionCheckRequest, db: Session = Depends(get_auth_db)) -> Envelope[SessionCheckData]:
    user = check_session_user(db, body.user_id, body.session_id)
    data = (
        SessionCheckData(active=True, username=user.username, display_name=user.display_name, role=user.role)
        if user
        else SessionCheckData(active=False)
    )
    return Envelope[SessionCheckData](meta=_meta(), data=data)


@router.post("/auth/logout", response_model=Envelope[LogoutData])
def logout(body: LogoutRequest, db: Session = Depends(get_auth_db)) -> Envelope[LogoutData]:
    return Envelope[LogoutData](meta=_meta(), data=LogoutData(revoked=revoke_session(db, body.user_id, body.session_id)))


@router.post("/auth/logout-all", response_model=Envelope[LogoutAllData])
def logout_all(body: LogoutRequest, db: Session = Depends(get_auth_db)) -> Envelope[LogoutAllData]:
    count = revoke_all_sessions(db, body.user_id, body.session_id)
    if count is None:  # 이미 취소·만료된 세션이거나 남의 세션: 아무것도 하지 않는다
        raise ApiError(status_code=401, code="INVALID_SESSION", message="유효한 로그인이 아닙니다.")
    return Envelope[LogoutAllData](meta=_meta(), data=LogoutAllData(revoked_count=count))


@router.post("/auth/signup", response_model=Envelope[SignupData])
def signup_request(body: SignupRequest, request: Request, db: Session = Depends(get_auth_db)) -> Envelope[SignupData]:
    """회원가입 신청(DEC-074). 승인 대기 계정만 만들고 로그인은 관리자 승인 뒤에 가능하다."""
    if not allow_signup_attempt(_client_ip(request)):
        raise ApiError(status_code=429, code="SIGNUP_RATE_LIMITED", message="가입 신청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
    if body.website.strip():  # 숨긴 칸이 채워짐 = 봇. 접수한 것처럼 응답하고 아무것도 만들지 않는다.
        return Envelope[SignupData](meta=_meta(), data=SignupData(status="pending"))
    try:
        signup(db, body.username, body.display_name, body.password)
    except SignupError as exc:
        raise ApiError(status_code=exc.status, code=exc.code, message=exc.message) from exc
    return Envelope[SignupData](meta=_meta(), data=SignupData(status="pending"))
