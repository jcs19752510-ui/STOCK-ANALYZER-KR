"""Public API 환경설정.

03-system-design.md §1-1 3차 방어(프로세스/배포 분리) 원칙에 따라, 이 서비스는
`api_service` DB 계정 접속 정보만 환경변수로 받는다. `raw_internal` 자격증명은
이 서비스에 주입되지 않으며, 코드에서도 참조하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """필수 환경변수가 없을 때 명시적으로 발생시키는 예외(조용한 기본값 대체 금지)."""


@dataclass(frozen=True)
class Settings:
    database_url: str


def get_settings() -> Settings:
    database_url = os.environ.get("PUBLIC_API_DATABASE_URL")
    if not database_url:
        raise ConfigError(
            "환경변수 PUBLIC_API_DATABASE_URL이 설정되지 않았습니다. "
            "예: postgresql+psycopg://api_service:***@localhost:5432/stock_screener"
        )
    return Settings(database_url=database_url)
