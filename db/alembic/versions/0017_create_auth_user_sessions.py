"""create auth.user_sessions — 서버 쪽 세션 목록(로그인 상태 유지 30일, DEC-070)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-05

30일짜리 로그인 쿠키는 서명만으로는 로그아웃·분실 시 **취소할 수 없다**. 그래서 로그인마다 이 표에 한 줄(session_id)을 만들고,
쿠키는 그 `session_id`를 담는다. 웹이 5분마다 하는 활성 확인에서 "이 세션이 취소·만료되지 않았는지"도 함께 본다.
`auth_service`는 INSERT, SELECT, 그리고 `last_check_at`·`revoked_at` 두 열의 UPDATE만 가능하다(만료 시각을 늘리거나 되살릴 수 없다:
되살리기는 `revoked_at`을 NULL로 되돌리는 UPDATE이므로 API 코드가 하지 않으며, 최소 권한 한계는 설계서에 적는다).
회원이 삭제되면 세션도 함께 지워진다(ON DELETE CASCADE).
"""

# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS_SQL = """
DO $do$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_service') THEN
    GRANT SELECT, INSERT ON auth.user_sessions TO auth_service;
    GRANT UPDATE (last_check_at, revoked_at) ON auth.user_sessions TO auth_service;
  ELSE
    RAISE NOTICE 'auth_service 역할이 없어 GRANT를 건너뜁니다. 역할을 만든 뒤 deploy/render/neon-auth-setup.sql을 실행하세요.';
  END IF;
END
$do$;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth.user_sessions (
            session_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       uuid NOT NULL REFERENCES auth.app_users (user_id) ON DELETE CASCADE,
            remember      boolean NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            expires_at    timestamptz NOT NULL,
            last_check_at timestamptz,
            revoked_at    timestamptz,
            CONSTRAINT ck_user_sessions_expiry CHECK (expires_at > created_at AND expires_at <= created_at + interval '31 days')
        )
        """
    )
    op.execute("CREATE INDEX ix_user_sessions_user ON auth.user_sessions (user_id)")
    op.execute("CREATE INDEX ix_user_sessions_expires ON auth.user_sessions (expires_at)")
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE auth.user_sessions")
