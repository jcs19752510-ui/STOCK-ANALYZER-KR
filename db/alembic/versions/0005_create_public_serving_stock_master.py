"""create public_serving.stock_master table + grants (REQ-001)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15

03-system-design.md §3-2 `public_serving.stock_master`, §3-1(스키마별 역할
매트릭스: `public_serving` 쓰기는 batch_worker, 읽기는 batch_worker/api_service
둘 다). `public_serving` 스키마 자체와 스키마 레벨 USAGE GRANT는 0003에서
이미 batch_worker/api_service 양쪽에 부여했으므로, 이 리비전은 새 테이블에
대한 테이블 단위 GRANT만 추가한다(DEF-003 교훈 — 테이블 생성과 GRANT를 같은
리비전에 포함해, 스키마는 있는데 권한이 없는 상태가 생기지 않게 한다).

`market`(상장시장 구분, KOSPI/KOSDAQ)은 §3-1-1에 따라 `raw_ohlcv`/
`market_calendar`의 `market`(거래소 세션 구분, KRX/NXT, `market_session`
ENUM)과 다른 축이므로 새 ENUM(`listed_market`)으로 분리한다 — 같은 이름의
ENUM을 재사용하면 두 축이 다시 뒤섞이는 Q1 재발 위험이 있다.

`updated_at` 컬럼은 설계서 §3-2의 `stock_master` 컬럼 목록에는 명시되어
있지 않으나, UNIT-01 DEF-004(updated_at 갱신 누락) 재발 방지를 위해 이번
유닛부터 마스터 성격의 테이블에 일관되게 추가한다(`reference.market_calendar`와
동일 패턴, `unit-03-note.md` 참조).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    listed_market_enum = postgresql.ENUM(
        "KOSPI", "KOSDAQ", name="listed_market", schema="public_serving"
    )
    listed_market_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "stock_master",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "market",
            postgresql.ENUM(
                "KOSPI",
                "KOSDAQ",
                name="listed_market",
                schema="public_serving",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("sector", sa.String(), nullable=True),
        # listing_date: 채택 데이터 소스(getStockPriceInfo 일별 시세 스냅샷)에서
        # 얻을 수 없어 nullable로 둔다(§8-2 항목8의 sector 처리 원칙과 동일,
        # unit-03-note.md "설계서 대비 편차" 참조).
        sa.Column("listing_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="public_serving",
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON public_serving.stock_master TO batch_worker")
    op.execute("GRANT SELECT ON public_serving.stock_master TO api_service")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public_serving.stock_master FROM api_service")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON public_serving.stock_master FROM batch_worker")

    op.drop_table("stock_master", schema="public_serving")

    postgresql.ENUM(
        "KOSPI", "KOSDAQ", name="listed_market", schema="public_serving"
    ).drop(op.get_bind(), checkfirst=True)
