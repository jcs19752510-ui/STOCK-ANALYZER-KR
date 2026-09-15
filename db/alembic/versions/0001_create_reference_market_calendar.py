"""create reference schema and market_calendar table (REQ-005, REQ-012)

Revision ID: 0001
Revises:
Create Date: 2026-09-14

03-system-design.md §3-2 `reference.market_calendar`, §3-5(스키마별 독립
Alembic 리비전 네임스페이스 원칙 — 이 리비전은 `reference` 스키마 전용이다).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("reference",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reference")

    # postgresql.ENUM을 명시적으로 한 번만 생성하고, 아래 create_table에서는
    # create_type=False로 참조해야 한다 - 그렇지 않으면 create_table이 같은
    # 타입을 다시 생성하려 시도해 "type already exists" 오류가 난다.
    market_session_enum = postgresql.ENUM(
        "KRX", "NXT", name="market_session", schema="reference"
    )
    market_session_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "market_calendar",
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column(
            "market",
            postgresql.ENUM(
                "KRX",
                "NXT",
                name="market_session",
                schema="reference",
                create_type=False,
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False),
        sa.Column("session_close_at", sa.Time(), nullable=True),
        sa.Column("holiday_name", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="reference",
    )


def downgrade() -> None:
    op.drop_table("market_calendar", schema="reference")

    market_session_enum = postgresql.ENUM(
        "KRX", "NXT", name="market_session", schema="reference"
    )
    market_session_enum.drop(op.get_bind(), checkfirst=True)

    op.execute("DROP SCHEMA IF EXISTS reference CASCADE")
