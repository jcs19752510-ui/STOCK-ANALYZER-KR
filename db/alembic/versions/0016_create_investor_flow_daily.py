"""create public_serving.investor_flow_daily — 종목별 일별 투자자 순매수 (DEC-068, 소유자 전용 표시)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-05

증권사(한국투자증권) 조회 값을 **소유자 PC**의 수집 스크립트(`collect_investor_flow.py`, batch_worker)가 적재한다.
증권사 앱키는 PC에만 있고 서버에는 없다. 이 테이블은 소유자 계정에게만 API가 내려준다(재배포 아님, DEC-068).
`api_service`는 SELECT만 가능하다. 값이 없는 항목은 0이 아니라 NULL(지어내지 않음). 단위는 증권사 원본:
수량=주, 거래대금=백만원. GRANT는 같은 리비전에 둔다(DEF-003 교훈).
"""

# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investor_flow_daily",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("personal_quantity", sa.BigInteger(), nullable=True),
        sa.Column("foreign_quantity", sa.BigInteger(), nullable=True),
        sa.Column("institution_quantity", sa.BigInteger(), nullable=True),
        sa.Column("personal_amount_million", sa.BigInteger(), nullable=True),
        sa.Column("foreign_amount_million", sa.BigInteger(), nullable=True),
        sa.Column("institution_amount_million", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="public_serving",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON public_serving.investor_flow_daily TO batch_worker")
    op.execute("GRANT SELECT ON public_serving.investor_flow_daily TO api_service")


def downgrade() -> None:
    op.execute("REVOKE ALL ON public_serving.investor_flow_daily FROM api_service")
    op.execute("REVOKE ALL ON public_serving.investor_flow_daily FROM batch_worker")
    op.drop_table("investor_flow_daily", schema="public_serving")
