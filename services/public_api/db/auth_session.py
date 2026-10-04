"""회원 DB(`auth` 스키마) 접속 — 데이터 조회용 `api_service`와 **다른 전용 계정(`auth_service`)** (DEC-067, 설계서 §3).

공개 데이터 조회 연결(`session.py`)과 풀·주소를 분리해서, 데이터 조회 계정에는 회원 테이블 권한이 전혀 없다.
`PUBLIC_API_AUTH_DATABASE_URL`이 없으면 이 연결은 만들어지지 않고 로그인용 내부 경로는 404로 꺼진다.
"""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.public_api.core.config import (
    ConfigError,
    get_auth_database_url,
    get_db_connect_timeout_seconds,
    get_db_statement_timeout_ms,
)

# 비밀번호 검증(CPU)이 끝나기를 기다리며 트랜잭션을 열어 두는 일이 없게 하고, 혹시 남아도 10초 뒤 서버가 끊게 한다.
_IDLE_IN_TRANSACTION_MS = 10_000


@lru_cache(maxsize=1)
def get_auth_engine() -> Engine:
    url = get_auth_database_url()
    if url is None:
        raise ConfigError("환경변수 PUBLIC_API_AUTH_DATABASE_URL이 설정되지 않았습니다.")
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": get_db_connect_timeout_seconds(),
            "options": (
                f"-c statement_timeout={get_db_statement_timeout_ms()} "
                f"-c idle_in_transaction_session_timeout={_IDLE_IN_TRANSACTION_MS}"
            ),
        },
    )


@lru_cache(maxsize=1)
def get_auth_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_auth_engine(), autoflush=False, autocommit=False)


def get_auth_db() -> Iterator[Session]:
    session = get_auth_session_factory()()
    try:
        yield session
    finally:
        session.close()
