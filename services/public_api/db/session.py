from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.public_api.core.config import get_settings

# 03-system-design.md §5-4(Must): "DB 커넥션 풀 고갈/쿼리 타임아웃 등 일시적
# 인프라 장애... 쿼리 타임아웃 5초, 초과 시 503 SERVICE_UNAVAILABLE 반환".
# DEF-FS-01/REQ-025(08~09단계)가 실측한 근본 원인은 connect_timeout 미설정
# 으로 DB가 무응답일 때 연결 시도가 OS/드라이버 기본값(60~90초)까지 스레드를
# 점유하는 것이었다. connect_timeout(연결 자체)과 statement_timeout(연결 이후
# 쿼리 실행)을 모두 짧게 고정해, 어느 단계에서 DB가 응답하지 않아도 수 초
# 내에 명시적 예외(OperationalError 등)로 실패하도록 한다. 두 값 모두
# main.py의 요청 타임아웃(4.5초)보다 작게 잡아, 정상적인 DB 장애 시나리오는
# 애플리케이션 레벨 백업 타임아웃에 기대지 않고도 자체적으로 §5-4의 "5초
# 이내" 목표를 만족한다.
_CONNECT_TIMEOUT_SECONDS = 3
_STATEMENT_TIMEOUT_MS = 3000


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": _CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}",
        },
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
