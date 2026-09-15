"""grant reference schema privileges to batch_worker/api_service (DEF-003)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15

03-system-design.md §1-1(2차 방어 — DB 권한 분리), §3-1(스키마별 역할 매트릭스:
`reference`는 batch_worker/api_service 둘 다 읽기, 쓰기는 batch_worker만).

0001은 `reference` 스키마와 `market_calendar` 테이블만 만들고 GRANT를 전혀
실행하지 않아, `alembic upgrade head` 직후에는 batch_worker/api_service
둘 다 이 스키마에 접근할 수 없었다(REQ-012 핵심 운영 절차인
`scripts/load_calendar.py`가 실제 역할 분리 환경에서 100% 실패 —
`unit-01-test.md` v3 DEF-003, TC-065). 이 리비전이 그 GRANT를 코드화한다.

전제(중요): `batch_worker`/`api_service` **역할(role) 자체의 생성**은 이
마이그레이션의 책임이 아니다. 역할 생성·비밀번호 관리는 인프라 프로비저닝
영역이며, 스키마 마이그레이션이 자격증명을 다루면 안 된다고 판단했다
(unit-01-note.md 참조). 두 역할이 아직 없는 환경에서 이 리비전을 실행하면
PostgreSQL이 `role "batch_worker" does not exist` 등으로 명시적으로
실패한다(조용한 스킵 없음) — 운영자는 역할을 먼저 프로비저닝해야 한다는
신호를 명확하게 받는다.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA reference TO batch_worker")
    op.execute("GRANT USAGE ON SCHEMA reference TO api_service")
    op.execute("GRANT SELECT, INSERT, UPDATE ON reference.market_calendar TO batch_worker")
    op.execute("GRANT SELECT ON reference.market_calendar TO api_service")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON reference.market_calendar FROM api_service")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON reference.market_calendar FROM batch_worker")
    op.execute("REVOKE USAGE ON SCHEMA reference FROM api_service")
    op.execute("REVOKE USAGE ON SCHEMA reference FROM batch_worker")
