"""임시 PostgreSQL DB 생성/삭제 헬퍼 (05-test-plan §1, 규칙 K).

개발 DB(`stock_screener`)에는 합성 데이터를 넣지 않는다. 대신 로컬 Docker 컨테이너
(`stock-screener-pg`)의 슈퍼유저(`postgres`)로 `stock_screener_test_<난수>` DB를 만들고,
`alembic upgrade head`로 실제 스키마·권한(GRANT)을 그대로 적용한 뒤, **try/finally로
반드시 DROP**한다(정상 종료·테스트 실패·예외 모두 동일하게 정리).

접속 문자열은 `.env`의 `ALEMBIC_DATABASE_URL`(migrator)·`BATCH_DATABASE_URL`(batch_worker)에서
데이터베이스 이름만 임시 DB로 바꿔 쓴다. 비밀번호는 어디에도 출력하지 않는다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL, make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "stock-screener-pg"
TEMP_DB_PREFIX = "stock_screener_test_"


class TempDbUnavailable(RuntimeError):
    """Docker 컨테이너/접속 정보 부재 — 호출자가 skip 사유로 사용한다."""


@dataclass(frozen=True)
class TempDb:
    name: str
    migrator_url: URL  # DDL/시드용(슈퍼유저급)
    batch_url: URL  # batch_worker — 스크립트가 실제로 쓰는 역할

    @staticmethod
    def render(url: URL) -> str:
        return url.render_as_string(hide_password=False)


def _read_env_file_value(key: str) -> str | None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def _base_url(key: str) -> URL:
    raw = os.environ.get(key) or _read_env_file_value(key)
    if not raw:
        raise TempDbUnavailable(f"{key}를 환경변수/.env에서 찾을 수 없습니다.")
    return make_url(raw)


def _psql(sql: str) -> None:
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql 실행 실패: {proc.stderr.strip()[:300]}")


@contextmanager
def temp_database() -> Iterator[TempDb]:
    try:
        migrator = _base_url("ALEMBIC_DATABASE_URL")
        batch = _base_url("BATCH_DATABASE_URL")
        probe = subprocess.run(
            ["docker", "exec", CONTAINER, "pg_isready"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise TempDbUnavailable(f"docker 사용 불가: {exc}") from exc
    if probe.returncode != 0:
        raise TempDbUnavailable("stock-screener-pg 컨테이너가 응답하지 않습니다.")

    name = f"{TEMP_DB_PREFIX}{uuid.uuid4().hex[:10]}"
    created = False
    try:
        _psql(f'CREATE DATABASE "{name}"')
        created = True
        env = {**os.environ, "ALEMBIC_DATABASE_URL": TempDb.render(migrator.set(database=name))}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"alembic upgrade head 실패: {result.stderr.strip()[-500:]}")
        yield TempDb(
            name=name,
            migrator_url=migrator.set(database=name),
            batch_url=batch.set(database=name),
        )
    finally:
        if created:
            _psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def leftover_temp_databases() -> list[str]:
    """정리 누락 점검용 — 남아 있는 임시 DB 이름 목록."""
    proc = subprocess.run(
        [
            "docker", "exec", CONTAINER, "psql", "-U", "postgres", "-At", "-c",
            f"SELECT datname FROM pg_database WHERE datname LIKE '{TEMP_DB_PREFIX}%'",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]
