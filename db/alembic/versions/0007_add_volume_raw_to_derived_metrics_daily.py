"""add derived_metrics_daily.volume_raw (REQ-003 스크리닝 거래량 필터)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-17

03-system-design.md §4-2 `GET /screen`는 `volume_min`(거래량 최소값, 주)
필터 파라미터를 요구하지만, §3-2 `derived_metrics_daily` 정의에는 거래량
원문을 담을 컬럼이 없다(§4-3 데이터 가공 원칙 1차 방어 — open/high/low/
close/volume 원문 컬럼 부재). 이 간극은 §3-2가 PER/PBR/시가총액에 대해
이미 확립한 `*_raw`(필터 전용, API 비노출)/`*_percentile`(노출) 이원 구조
(DEC-014)와 동일한 패턴으로 해소한다 — `volume_raw`는 `per_raw`/`pbr_raw`/
`market_cap_raw_krw`와 동일하게 DB 컬럼으로는 존재하되 API 응답 화이트
리스트(`services/public_api/schemas/screen.py`)에는 절대 포함하지 않는다.
근거는 `unit-07-note.md` §2 참조.

`volume_raw`는 PER/PBR/시가총액과 달리 대응하는 `*_percentile` 컬럼을
만들지 않는다 — 04-ux-design.md 어디에도 "거래량 백분위" 표시 문구가
정의되어 있지 않고, `sort_by` 허용값(§4-2)에도 거래량이 포함되지 않아
필터 전용으로만 쓰인다(단순 필터, `matched_metrics`에는 노출하지 않음).

테이블 단위 GRANT(0006)가 이미 `batch_worker`(SELECT/INSERT/UPDATE)/
`api_service`(SELECT)에 부여되어 있고 PostgreSQL의 컬럼 권한은 기본적으로
테이블 권한을 그대로 상속하므로, 이 리비전은 별도 GRANT를 실행하지 않는다
(DEF-003 교훈은 "새 테이블 생성 시 GRANT 누락 금지"였고, 이번은 기존
테이블에 컬럼만 추가하는 경우라 해당하지 않음).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "derived_metrics_daily",
        sa.Column("volume_raw", sa.BigInteger(), nullable=True),
        schema="public_serving",
    )


def downgrade() -> None:
    op.drop_column("derived_metrics_daily", "volume_raw", schema="public_serving")
