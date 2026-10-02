"""create public_serving.daily_prices — 종목 상세 차트용 공개 일봉 (DEC-041, UNIT-19)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-02

사용자 결정(DEC-041)으로 종목 상세 화면에 일 단위 시세(캔들·거래량·일자별 표)를 노출한다.
`raw_internal`에 대한 `api_service` 권한 차단(0004, 2차 방어)은 **풀지 않는다.** 대신 공개 전용
복사본 테이블을 두고 Derivation Batch가 `raw_ohlcv`(KRX 세션)에서 복사한다.
`api_service`는 이 테이블 SELECT만 가능하다.

PK는 (stock_code, trade_date) — 시장 세션은 KRX만 복사하므로 PK에 넣지 않는다(MVP, DEC-010).
GRANT는 테이블 생성과 같은 리비전에 둔다(DEF-003 교훈).
downgrade는 테이블만 제거한다(데이터는 배치 재실행으로 복원 가능).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_prices",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="public_serving",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON public_serving.daily_prices TO batch_worker")
    op.execute("GRANT SELECT ON public_serving.daily_prices TO api_service")


def downgrade() -> None:
    op.execute("REVOKE ALL ON public_serving.daily_prices FROM api_service")
    op.execute("REVOKE ALL ON public_serving.daily_prices FROM batch_worker")
    op.drop_table("daily_prices", schema="public_serving")
