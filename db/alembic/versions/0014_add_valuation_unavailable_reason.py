"""add per/pbr unavailable reason columns to derived_metrics_daily (DEC-057)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-03

PER/PBR 백분위가 비는 이유를 화면에서 나눠 보여주기 위해 `derived_metrics_daily`에 사유 컬럼 2개를
**nullable**로 추가한다(additive only — 기존 컬럼·쿼리·API 계약은 불변).

- `per_unavailable_reason` / `pbr_unavailable_reason`: 값이 있으면 NULL, 없으면 `LOSS`(분모인
  당기순이익/자본총계가 0 이하 — 적자·자본잠식) 또는 `NO_DATA`(재무 원문이나 시가총액이 없음).
  이전 배치 행은 NULL이고 API는 이를 "알 수 없음"으로 취급해 원인을 단정하지 않는다.

GRANT는 실행하지 않는다(0011과 같은 근거: 기존 테이블에 컬럼만 추가, 테이블 권한 상속).
downgrade: CHECK 제약과 컬럼 2개를 제거한다(가역, 배치 재실행으로 복원 가능).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "derived_metrics_daily"
SCHEMA = "public_serving"
COLUMNS = ("per_unavailable_reason", "pbr_unavailable_reason")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column(TABLE, sa.Column(name, sa.String(12), nullable=True), schema=SCHEMA)
        op.create_check_constraint(
            f"ck_derived_metrics_daily_{name}",
            TABLE,
            f"{name} IN ('LOSS', 'NO_DATA')",
            schema=SCHEMA,
        )


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_constraint(f"ck_derived_metrics_daily_{name}", TABLE, schema=SCHEMA, type_="check")
        op.drop_column(TABLE, name, schema=SCHEMA)
