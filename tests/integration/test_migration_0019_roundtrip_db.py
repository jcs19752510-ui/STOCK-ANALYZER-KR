"""마이그레이션 0019(kis_daily_bar) 왕복: 되돌리기 후 재적용과 권한 유지(DEC-097)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tests.integration.pg_temp_db import TempDbUnavailable, run_alembic, temp_database

EXISTS = "select to_regclass('public_serving.kis_daily_bar') is not null"


def test_roundtrip_and_grants() -> None:
    try:
        ctx = temp_database()
        db = ctx.__enter__()
    except TempDbUnavailable as exc:
        pytest.skip(str(exc))
    try:
        engine = create_engine(db.migrator_url)
        with engine.connect() as c:
            assert c.execute(text(EXISTS)).scalar() is True  # temp_database가 head까지 적용
        down = run_alembic(db, "downgrade", "0018")
        assert down.returncode == 0, down.stderr[-500:]
        with engine.connect() as c:
            assert c.execute(text(EXISTS)).scalar() is False
        up = run_alembic(db, "upgrade", "head")
        assert up.returncode == 0, up.stderr[-500:]
        with engine.connect() as c:
            assert c.execute(text(EXISTS)).scalar() is True
            grants = {
                (r[0], r[1])
                for r in c.execute(
                    text(
                        "select grantee, privilege_type from information_schema.role_table_grants "
                        "where table_schema='public_serving' and table_name='kis_daily_bar'"
                    )
                )
            }
        assert ("api_service", "SELECT") in grants and ("api_service", "INSERT") not in grants
        assert {("batch_worker", p) for p in ("SELECT", "INSERT", "UPDATE", "DELETE")} <= grants
        engine.dispose()
    finally:
        ctx.__exit__(None, None, None)
