"""로그인 내부 경로의 요청·응답 모델 (DEC-067). 비밀번호는 응답에 절대 포함하지 않는다."""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class LoginData(BaseModel):
    user_id: str
    username: str
    display_name: str


class SessionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class SessionCheckData(BaseModel):
    active: bool
    username: str | None = None
    display_name: str | None = None


class MemberItem(BaseModel):
    username: str
    display_name: str


class MembersData(BaseModel):
    items: list[MemberItem]
    total: int
