"""create public_serving.kis_daily_bar — 증권사(KIS) 일봉 보충 캐시 (DEC-097, 본인 PC 전용)

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-07

발행 일봉(공공데이터)이 직전 거래일보다 뒤처졌을 때 장중 재계산이 쓰는 증권사 일봉을 **소유자 PC**의 수집 스크립트
(`collect_kis_daily_bars.py`, batch_worker)가 적재해 두는 임시 캐시다. 서버를 다시 켜도 2,700여 종목을 다시 조회하지 않기 위함이다.
- 확정 값이 아니다: 발행 포인터·`daily_prices`·`raw_ohlcv`를 건드리지 않는다. 발행 거래일 이하의 행은 공공데이터가 대신하므로 수집 스크립트가 지운다.
- 본인 PC 전용(재배포 아님). `api_service`는 SELECT만 가능하다. GRANT는 같은 리비전에 둔다(DEF-003 교훈).
"""

# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kis_daily_bar",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="public_serving",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public_serving.kis_daily_bar TO batch_worker")
    op.execute("GRANT SELECT ON public_serving.kis_daily_bar TO api_service")


def downgrade() -> None:
    op.execute("REVOKE ALL ON public_serving.kis_daily_bar FROM api_service")
    op.execute("REVOKE ALL ON public_serving.kis_daily_bar FROM batch_worker")
    op.drop_table("kis_daily_bar", schema="public_serving")
