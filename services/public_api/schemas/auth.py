"""로그인 내부 경로의 요청·응답 모델 (DEC-067). 비밀번호는 응답에 절대 포함하지 않는다."""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    remember: StrictBool = False  # "로그인 상태 유지"(30일). 기본은 8시간


class LoginData(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str  # user / admin
    session_id: str  # 서버 쪽 세션 목록의 id(쿠키에 담긴다)
    expires_in_seconds: int  # 이 세션의 절대 수명(남은 시간이 아니라 발급 시점 기준)


_UUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class SessionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(pattern=_UUID)
    session_id: str = Field(pattern=_UUID)


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(pattern=_UUID)
    session_id: str = Field(pattern=_UUID)


class LogoutData(BaseModel):
    revoked: bool  # 이 세션을 이번 요청으로 취소했으면 true(이미 취소·없음이면 false)


class SessionCheckData(BaseModel):
    active: bool
    username: str | None = None
    display_name: str | None = None
    role: str | None = None


class LogoutAllData(BaseModel):
    revoked_count: int  # 이번 요청으로 취소한 세션 수(현재 기기 포함)


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)
    website: str = Field(default="", max_length=200)  # 사람이 보지 못하게 숨긴 칸(봇 걸러내기). 채워져 있으면 접수한 척하고 버린다


class SignupData(BaseModel):
    status: str  # pending(승인 대기)


class AdminMember(BaseModel):
    username: str
    display_name: str
    role: str
    status: str  # pending / active / disabled
    created_at: str
    last_login_at: str | None
    locked: bool
    active_sessions: int


class AdminMembersData(BaseModel):
    items: list[AdminMember]
    total: int
    pending: int


class AdminActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "create", "approve", "reject", "enable", "disable", "set_role", "rename", "reset_password", "revoke_sessions", "delete"
    ]
    username: str = Field(min_length=1, max_length=64)
    role: Literal["user", "admin"] | None = None
    display_name: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=1024)


class AdminActionData(BaseModel):
    result: str
