"""create public_serving.derived_metrics_daily/current_published_batch + grants (REQ-002)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-16

03-system-design.md §3-2 `public_serving.derived_metrics_daily`(REQ-002 산출물,
원본 시세 컬럼 없음 — §4-3 데이터 가공 원칙 1차 방어)와
`public_serving.current_published_batch`(REQ-002/003/004 공용 "현재 서빙 중"
포인터, §5-3 롤백/무결성). §3-1(스키마별 역할 매트릭스: `public_serving` 쓰기는
batch_worker, 읽기는 batch_worker/api_service 둘 다) 그대로 적용.

DEF-003 교훈(unit-01-test.md) 적용 — 테이블 생성과 GRANT를 같은 리비전에 포함.

`derived_metrics_daily.market`은 **상장시장 구분**(KOSPI/KOSDAQ, §3-1-1)이라
`stock_master`와 같은 `listed_market` ENUM(0005, create_type=False)을
재사용한다. `current_published_batch.market`은 이 리비전이 직접 확정한
설계 공백 보완 사항이다 — 설계서 §3-2 표는 이 컬럼이 어느 축(상장시장 vs
거래소 세션)인지 명시하지 않았다. `meta.data_freshness.market`(§3-4)이
거래소 세션 구분이고 이 포인터가 "그 세션 배치가 어디까지 발행됐는지"를
가리키므로, `reference.market_session` ENUM(KRX/NXT, 0001, create_type=False)을
재사용하기로 확정했다(근거는 `unit-06-note.md` §2 참조).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_listed_market_enum_ref = postgresql.ENUM(
    "KOSPI", "KOSDAQ", name="listed_market", schema="public_serving", create_type=False
)
_market_session_enum_ref = postgresql.ENUM(
    "KRX", "NXT", name="market_session", schema="reference", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "derived_metrics_daily",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("trade_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("market", _listed_market_enum_ref, primary_key=True, nullable=False),
        sa.Column("return_pct", sa.Numeric(), nullable=True),
        sa.Column("return_rank_pct", sa.Numeric(), nullable=True),
        sa.Column("ma5_gap_pct", sa.Numeric(), nullable=True),
        sa.Column("ma20_gap_pct", sa.Numeric(), nullable=True),
        sa.Column("volume_anomaly_score", sa.Numeric(), nullable=True),
        sa.Column("per_raw", sa.Numeric(), nullable=True),
        sa.Column("pbr_raw", sa.Numeric(), nullable=True),
        sa.Column("market_cap_raw_krw", sa.BigInteger(), nullable=True),
        sa.Column("per_percentile", sa.Numeric(), nullable=True),
        sa.Column("pbr_percentile", sa.Numeric(), nullable=True),
        sa.Column("market_cap_percentile", sa.Numeric(), nullable=True),
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

    op.create_table(
        "current_published_batch",
        sa.Column("market", _market_session_enum_ref, primary_key=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column(
            "batch_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public_serving.batch_run.batch_run_id"),
            nullable=False,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="public_serving",
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON public_serving.derived_metrics_daily TO batch_worker"
    )
    op.execute("GRANT SELECT ON public_serving.derived_metrics_daily TO api_service")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON public_serving.current_published_batch TO batch_worker"
    )
    op.execute("GRANT SELECT ON public_serving.current_published_batch TO api_service")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public_serving.current_published_batch FROM api_service")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON public_serving.current_published_batch FROM batch_worker"
    )
    op.execute("REVOKE SELECT ON public_serving.derived_metrics_daily FROM api_service")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON public_serving.derived_metrics_daily FROM batch_worker"
    )

    op.drop_table("current_published_batch", schema="public_serving")
    op.drop_table("derived_metrics_daily", schema="public_serving")
