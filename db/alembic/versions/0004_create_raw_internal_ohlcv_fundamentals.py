"""create raw_internal schema, raw_ohlcv/raw_fundamentals tables + grants (REQ-011)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15

03-system-design.md §3-2 `raw_internal.raw_ohlcv`/`raw_fundamentals`,
§1-1(1차/2차 방어 — 스키마 분리 + DB 권한 분리): `raw_internal`은
`batch_worker`만 접근 가능하고 `api_service`는 어떤 권한도 갖지 않는다
(DEF-003 교훈 적용 — 스키마/테이블 생성과 GRANT를 같은 리비전에 포함).

`raw_ohlcv.market`은 `reference.market_session` ENUM을 그대로 재사용한다
(§3-1-1 — 거래소 세션 구분 KRX/NXT는 reference.market_calendar와 동일 개념).
새 ENUM을 만들지 않으므로 이 리비전은 0001을 논리적으로 의존하지만, 리비전
체인상으로는 0003을 통해 이미 그 이후에 위치한다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = ("raw_internal",)
depends_on: str | Sequence[str] | None = None

_market_session_enum_ref = postgresql.ENUM(
    "KRX", "NXT", name="market_session", schema="reference", create_type=False
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_internal")

    op.create_table(
        "raw_ohlcv",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("market", _market_session_enum_ref, primary_key=True, nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.BigInteger(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "source_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public_serving.batch_run.batch_run_id"),
            nullable=False,
        ),
        schema="raw_internal",
    )

    op.create_table(
        "raw_fundamentals",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("per", sa.Numeric(), nullable=True),
        sa.Column("pbr", sa.Numeric(), nullable=True),
        sa.Column("market_cap", sa.BigInteger(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "source_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public_serving.batch_run.batch_run_id"),
            nullable=False,
        ),
        schema="raw_internal",
    )

    op.execute("GRANT USAGE ON SCHEMA raw_internal TO batch_worker")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON raw_internal.raw_ohlcv TO batch_worker"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON raw_internal.raw_fundamentals TO batch_worker"
    )
    # api_service에는 어떤 권한도 부여하지 않는다(§1-1 2차 방어). 기본적으로
    # PostgreSQL은 새 스키마/테이블에 PUBLIC 권한을 자동 부여하지 않으므로
    # 이 REVOKE는 이미 보장된 상태를 명시적으로 재확인하는 방어적 문서화다
    # (DEF-003 재발 방지 관점에서, "권한이 없어야 한다"는 의도를 코드로도 남긴다).
    op.execute("REVOKE ALL ON SCHEMA raw_internal FROM api_service")
    op.execute("REVOKE ALL ON raw_internal.raw_ohlcv FROM api_service")
    op.execute("REVOKE ALL ON raw_internal.raw_fundamentals FROM api_service")


def downgrade() -> None:
    op.execute("REVOKE ALL ON raw_internal.raw_fundamentals FROM batch_worker")
    op.execute("REVOKE ALL ON raw_internal.raw_ohlcv FROM batch_worker")
    op.execute("REVOKE USAGE ON SCHEMA raw_internal FROM batch_worker")

    op.drop_table("raw_fundamentals", schema="raw_internal")
    op.drop_table("raw_ohlcv", schema="raw_internal")

    op.execute("DROP SCHEMA IF EXISTS raw_internal CASCADE")
