"""create public_serving.corp_earnings — 종목 상세 실적 탭용 연간 실적 (DEC-041, UNIT-23)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-02

DART 사업보고서(11011)에서 받은 연간 매출액·영업이익·당기순이익(원). 공시된 공개 재무 수치이며
`raw_internal`을 거치지 않고 `enrich_earnings.py`(batch_worker)가 직접 적재한다. `api_service`는
SELECT만 가능하다. 금액 컬럼은 전부 nullable — 찾지 못한 항목은 0이 아니라 NULL(지어내지 않음).
GRANT는 테이블 생성과 같은 리비전에 둔다(DEF-003 교훈). downgrade는 테이블만 제거한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corp_earnings",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("fiscal_year", sa.SmallInteger(), primary_key=True, nullable=False),
        sa.Column("fs_div", sa.String(length=3), nullable=False),  # CFS(연결) | OFS(개별)
        sa.Column("revenue", sa.Numeric(), nullable=True),
        sa.Column("operating_income", sa.Numeric(), nullable=True),
        sa.Column("net_income", sa.Numeric(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("fs_div IN ('CFS', 'OFS')", name="ck_corp_earnings_fs_div"),
        schema="public_serving",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON public_serving.corp_earnings TO batch_worker")
    op.execute("GRANT SELECT ON public_serving.corp_earnings TO api_service")


def downgrade() -> None:
    op.execute("REVOKE ALL ON public_serving.corp_earnings FROM api_service")
    op.execute("REVOKE ALL ON public_serving.corp_earnings FROM batch_worker")
    op.drop_table("corp_earnings", schema="public_serving")
