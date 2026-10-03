"""add pattern metrics columns to derived_metrics_daily (REQ-030, 패턴 스크리닝 "급등 전 압축주")

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-02

docs/pattern-screening/02-system-design.md §3-1: 패턴 지표 11개를 `derived_metrics_daily`에
**모두 nullable**로 추가한다(additive only — 기존 컬럼·쿼리·`GET /screen` 계약은 불변).
이전 배치 행은 `pattern_metrics_status IS NULL`이며 API(UNIT-16)가 이를 "산정 불가
(METRIC_UNAVAILABLE)"로 취급한다.

`pattern_metrics_status`는 VARCHAR(24) + CHECK(`OK`/`INSUFFICIENT_HISTORY`/`SUSPECT_PRICE_JUMP`,
NULL 허용 = 구 배치 행). 계산 정의는 `shared/pattern_params.py`,
`services/derivation_batch/compute.py`.

GRANT는 실행하지 않는다 — 0007과 같은 근거로, 이 리비전은 기존 테이블에 컬럼만 추가하며
`batch_worker`(SELECT/INSERT/UPDATE)·`api_service`(SELECT)의 테이블 권한을 상속한다. 다만
"상속된다"는 가정은 실제 역할로 검증한다(`tests/integration/test_pattern_derivation_db.py` TC-D05).

인덱스는 추가하지 않는다: 조회는 항상 `trade_date`(+`market`) 단일 거래일(약 2,700행)로 좁혀지며
0008의 `(trade_date, market)` 인덱스가 이미 있다(설계서 §3-1).

downgrade: CHECK 제약과 11개 컬럼을 제거한다(가역). 이 컬럼들의 데이터는 배치 재실행으로 복원 가능.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "derived_metrics_daily"
SCHEMA = "public_serving"
STATUS_CHECK_NAME = "ck_derived_metrics_daily_pattern_metrics_status"

NUMERIC_COLUMNS = (
    "sideways_range_pct",
    "sideways_net_change_pct",
    "ma_convergence_pct",
    "volatility_contraction_ratio",
    "ma60_gap_pct",
    "ma20_vs_ma60_gap_pct",
    "ma60_slope_pct",
    "volume_ratio_5_60",
)


def upgrade() -> None:
    for name in NUMERIC_COLUMNS:
        op.add_column(TABLE, sa.Column(name, sa.Numeric(), nullable=True), schema=SCHEMA)
    op.add_column(
        TABLE, sa.Column("ma60_cross_up_days", sa.SmallInteger(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        TABLE, sa.Column("recent_surge_flag", sa.Boolean(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        TABLE, sa.Column("pattern_metrics_status", sa.String(24), nullable=True), schema=SCHEMA
    )
    op.create_check_constraint(
        STATUS_CHECK_NAME,
        TABLE,
        "pattern_metrics_status IN ('OK', 'INSUFFICIENT_HISTORY', 'SUSPECT_PRICE_JUMP')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(STATUS_CHECK_NAME, TABLE, schema=SCHEMA, type_="check")
    for name in (
        "pattern_metrics_status",
        "recent_surge_flag",
        "ma60_cross_up_days",
        *reversed(NUMERIC_COLUMNS),
    ):
        op.drop_column(TABLE, name, schema=SCHEMA)
