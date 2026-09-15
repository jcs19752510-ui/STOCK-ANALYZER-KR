from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# alembic.ini가 repo 루트에 있고 이 파일은 db/alembic/ 아래 있으므로,
# shared.db_models를 import 하려면 repo 루트를 sys.path에 추가해야 한다.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.db_models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "환경변수 ALEMBIC_DATABASE_URL이 설정되지 않았습니다. "
            "마이그레이션은 DDL 권한이 있는 계정(batch_worker 등)으로만 실행해야 하며, "
            "public_api의 읽기 전용 계정 URL을 재사용하지 않습니다(03-system-design.md §1-1)."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_database_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
