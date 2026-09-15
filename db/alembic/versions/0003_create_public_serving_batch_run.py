"""create public_serving schema and batch_run table + grants (REQ-011)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15

03-system-design.md §3-2 `public_serving.batch_run`, §1-1(2차 방어 — DB 권한
분리), §3-1(스키마별 역할 매트릭스: `public_serving` 쓰기는 batch_worker,
읽기는 batch_worker/api_service 둘 다).

unit-01-note.md DEF-003(스키마 생성과 GRANT를 분리했다가 GRANT를 빠뜨린 결함)
교훈을 적용해, 이번에는 스키마/테이블 생성과 GRANT를 **같은 리비전**에 포함한다.

이 리비전은 `public_serving`의 전체 데이터 모델(stock_master 등, UNIT-03/06~08
소관)이 아니라 Ingestion Batch가 필요로 하는 `batch_run` 테이블만 만든다
(범위 외 확장 금지).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = ("public_serving",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS public_serving")

    batch_run_type_enum = postgresql.ENUM(
        "ingest", "derive", name="batch_run_type", schema="public_serving"
    )
    batch_run_type_enum.create(op.get_bind(), checkfirst=True)

    batch_run_status_enum = postgresql.ENUM(
        "SUCCESS", "FAILED", "PARTIAL", name="batch_run_status", schema="public_serving"
    )
    batch_run_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "batch_run",
        sa.Column("batch_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_type",
            postgresql.ENUM(
                "ingest", "derive", name="batch_run_type", schema="public_serving",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "SUCCESS", "FAILED", "PARTIAL", name="batch_run_status", schema="public_serving",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("trade_date_covered", sa.Date(), nullable=True),
        sa.Column("validation_passed", sa.Boolean(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        schema="public_serving",
    )

    op.execute("GRANT USAGE ON SCHEMA public_serving TO batch_worker")
    op.execute("GRANT USAGE ON SCHEMA public_serving TO api_service")
    op.execute("GRANT SELECT, INSERT, UPDATE ON public_serving.batch_run TO batch_worker")
    op.execute("GRANT SELECT ON public_serving.batch_run TO api_service")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public_serving.batch_run FROM api_service")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON public_serving.batch_run FROM batch_worker")
    op.execute("REVOKE USAGE ON SCHEMA public_serving FROM api_service")
    op.execute("REVOKE USAGE ON SCHEMA public_serving FROM batch_worker")

    op.drop_table("batch_run", schema="public_serving")

    postgresql.ENUM(
        "SUCCESS", "FAILED", "PARTIAL", name="batch_run_status", schema="public_serving"
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "ingest", "derive", name="batch_run_type", schema="public_serving"
    ).drop(op.get_bind(), checkfirst=True)

    op.execute("DROP SCHEMA IF EXISTS public_serving CASCADE")
