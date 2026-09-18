"""create public_serving.market_summary_daily table + grants (REQ-004)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-17

03-system-design.md §3-2 `public_serving.market_summary_daily`(REQ-004
산출물, 원본 시세 컬럼 없음 — §4-3 데이터 가공 원칙). `market` ENUM은
상장시장 구분(KOSPI/KOSDAQ) + `ALL`(전체 통합, DEC-016) 3값이며, 기존
`listed_market` ENUM(0005, KOSPI/KOSDAQ 2값)을 재사용하지 않고 별도 ENUM
으로 분리한다 — 재사용하면 `stock_master`/`derived_metrics_daily`가 절대
가질 수 없는 `ALL` 값이 그 ENUM에 섞여 들어가, §3-1-1이 확립한 "같은
이름의 ENUM을 재사용할 때는 반드시 표에 추가하고 어느 축인지 명시" 원칙과
상충한다.

DEF-003 교훈(unit-01-test.md) 적용 — 테이블 생성과 GRANT를 같은 리비전에
포함해, 스키마는 있는데 권한이 없는 상태가 생기지 않게 한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    market_summary_market_enum = postgresql.ENUM(
        "KOSPI", "KOSDAQ", "ALL", name="market_summary_market", schema="public_serving"
    )
    market_summary_market_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "market_summary_daily",
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column(
            "market",
            postgresql.ENUM(
                "KOSPI",
                "KOSDAQ",
                "ALL",
                name="market_summary_market",
                schema="public_serving",
                create_type=False,
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("advancers_count", sa.Integer(), nullable=False),
        sa.Column("decliners_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column(
            "top_sectors_by_value",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("total_trading_value_krw", sa.BigInteger(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "batch_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public_serving.batch_run.batch_run_id"),
            nullable=False,
        ),
        schema="public_serving",
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON public_serving.market_summary_daily TO batch_worker"
    )
    op.execute("GRANT SELECT ON public_serving.market_summary_daily TO api_service")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public_serving.market_summary_daily FROM api_service")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON public_serving.market_summary_daily FROM batch_worker"
    )

    op.drop_table("market_summary_daily", schema="public_serving")

    postgresql.ENUM(
        "KOSPI", "KOSDAQ", "ALL", name="market_summary_market", schema="public_serving"
    ).drop(op.get_bind(), checkfirst=True)
