"""index derived_metrics_daily(trade_date, market) for GET /screen (REQ-003)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-17

03-system-design.md §5-1 "Public API 응답시간 목표... `derived_metrics_daily`에
`market`, `return_pct`, `market_cap_raw_krw`, `per_raw`, `pbr_raw`,
`volume_anomaly_score` 복합 인덱스 구성으로 달성"을 반영한다. 다만 이
테이블의 기본키가 이미 `(stock_code, trade_date, market)` 순서(0006)라
`WHERE trade_date = ? AND market = ?`(모든 `GET /screen` 요청이 항상 거치는
1차 필터, `screen_repository.py` 참조) 조건에는 이 PK 인덱스가 활용되지
않는다(선두 컬럼이 stock_code라 리프 스캔이 되지 않음).

거래일당 전체 종목 수가 코스피+코스닥 합쳐 약 2,500개 규모(02-planning.md
§8-A3/03-system-design.md §2-1)라는 전제 하에서, `(trade_date, market)`
인덱스 하나로 1차 필터를 좁히고 나면 그 이후 range 필터/정렬은 최대
2,500행 이내 스캔이라 추가 컬럼별 인덱스(`*_raw`, `volume_anomaly_score`
등)까지는 이번 규모에서 불필요하다고 판단했다(과설계 방지, YAGNI —
§2-1/§5-2가 이미 채택한 "실측 후 병목 확인 시 추가" 원칙을 그대로 적용).
근거는 `unit-07-note.md` §2 참조.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_derived_metrics_daily_trade_date_market"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "derived_metrics_daily",
        ["trade_date", "market"],
        schema="public_serving",
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="derived_metrics_daily", schema="public_serving")
