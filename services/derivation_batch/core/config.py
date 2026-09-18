"""Derivation Batch 환경설정 (REQ-002).

03-system-design.md §1-3: "/services/derivation_batch — raw_internal 읽기 +
public_serving/reference 쓰기 권한 DB 계정 사용" — Ingestion Batch와 동일한
`batch_worker` role을 쓰므로 같은 환경변수(`BATCH_DATABASE_URL`)를 그대로
재사용한다(`services/ingestion_batch/core/config.py`와 동일 패턴이나, §1-3
"각 서비스는 별도 배포 단위"를 지키기 위해 설정 모듈 자체는 공유하지 않고
이 서비스 전용으로 별도로 둔다 — `unit-02-note.md`의 calendar_lookup
중복과 같은 성격의 의도적 최소 중복).
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
    database_url = os.environ.get("BATCH_DATABASE_URL")
    if not database_url:
        raise ConfigError(
            "환경변수 BATCH_DATABASE_URL이 설정되지 않았습니다. "
            "(raw_internal 읽기 + public_serving 쓰기 권한이 있는 batch_worker 계정 "
            "접속 문자열 필요)"
        )
    return Settings(database_url=database_url)
