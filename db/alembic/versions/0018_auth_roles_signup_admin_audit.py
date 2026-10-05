"""auth: 권한(role)·가입 승인(approved_at)·관리자 작업 기록 (DEC-074 인증 재개발)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-05

- `app_users.role`: `user`(일반 사용자) / `admin`(관리자) 두 가지. 권한은 **DB가 기준**이다(서버 환경변수에 아이디를 두지 않는다).
- `app_users.approved_at`: NULL이면 가입 신청 후 **승인 대기**. 이미 있던 회원은 모두 승인된 것으로 채운다.
- `is_active` 기본값을 false로 바꾼다: 가입 신청 행은 승인 전까지 로그인할 수 없다. "활성이면 반드시 승인됨"을 DB 제약으로 강제한다.
- `admin_audit`: 관리자 작업(승인·거절·수정·삭제·권한 변경·비밀번호 초기화) 기록.
`auth_service`는 가입 신청에 필요한 **열 단위 INSERT**(아이디·이름·비밀번호 해시만 — 권한·활성·승인은 못 정한다)와 관리 작업에 필요한 열 단위 UPDATE·DELETE를 받는다.
관리 작업을 누가 요청했는지는 API가 매 호출마다 DB에서 "유효한 세션 + 활성 + admin"으로 다시 확인한다.
"""

# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS_SQL = """
DO $do$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_service') THEN
    GRANT INSERT (username, display_name, password_hash) ON auth.app_users TO auth_service;
    GRANT UPDATE (display_name, role, is_active, approved_at) ON auth.app_users TO auth_service;
    GRANT DELETE ON auth.app_users TO auth_service;
    GRANT INSERT ON auth.admin_audit TO auth_service;
    GRANT USAGE ON SEQUENCE auth.admin_audit_audit_id_seq TO auth_service;
  ELSE
    RAISE NOTICE 'auth_service 역할이 없어 GRANT를 건너뜁니다. 역할을 만든 뒤 deploy/render/neon-auth-setup.sql을 실행하세요.';
  END IF;
END
$do$;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE auth.app_users ADD COLUMN role text NOT NULL DEFAULT 'user'")
    op.execute("ALTER TABLE auth.app_users ADD COLUMN approved_at timestamptz")
    op.execute("UPDATE auth.app_users SET approved_at = created_at")  # 기존 회원은 이미 승인된 것으로 본다
    op.execute("ALTER TABLE auth.app_users ALTER COLUMN is_active SET DEFAULT false")
    op.execute("ALTER TABLE auth.app_users ADD CONSTRAINT ck_app_users_role CHECK (role IN ('user', 'admin'))")
    op.execute(
        "ALTER TABLE auth.app_users ADD CONSTRAINT ck_app_users_active_needs_approval CHECK (NOT is_active OR approved_at IS NOT NULL)"
    )
    op.execute("CREATE INDEX ix_app_users_pending ON auth.app_users (created_at) WHERE approved_at IS NULL")
    op.execute(
        """
        CREATE TABLE auth.admin_audit (
            audit_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at     timestamptz NOT NULL DEFAULT now(),
            actor_user_id   uuid REFERENCES auth.app_users (user_id) ON DELETE SET NULL,
            actor_username  text,
            action          text NOT NULL,
            target_username text,
            detail          text,
            CONSTRAINT ck_admin_audit_action_len CHECK (char_length(action) <= 40),
            CONSTRAINT ck_admin_audit_detail_len CHECK (detail IS NULL OR char_length(detail) <= 200)
        )
        """
    )
    op.execute("CREATE INDEX ix_admin_audit_occurred_at ON auth.admin_audit (occurred_at DESC)")
    op.execute("ALTER TABLE auth.login_audit DROP CONSTRAINT ck_login_audit_result")
    op.execute(
        "ALTER TABLE auth.login_audit ADD CONSTRAINT ck_login_audit_result CHECK (result IN ('SUCCESS', 'FAIL', 'LOCKED', 'INACTIVE', 'PENDING'))"
    )
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    op.execute("DELETE FROM auth.login_audit WHERE result = 'PENDING'")
    op.execute("ALTER TABLE auth.login_audit DROP CONSTRAINT ck_login_audit_result")
    op.execute(
        "ALTER TABLE auth.login_audit ADD CONSTRAINT ck_login_audit_result CHECK (result IN ('SUCCESS', 'FAIL', 'LOCKED', 'INACTIVE'))"
    )
    op.execute("DROP TABLE auth.admin_audit")
    op.execute("DROP INDEX auth.ix_app_users_pending")
    op.execute("ALTER TABLE auth.app_users DROP CONSTRAINT ck_app_users_active_needs_approval")
    op.execute("ALTER TABLE auth.app_users DROP CONSTRAINT ck_app_users_role")
    op.execute("ALTER TABLE auth.app_users ALTER COLUMN is_active SET DEFAULT true")
    op.execute("ALTER TABLE auth.app_users DROP COLUMN approved_at")
    op.execute("ALTER TABLE auth.app_users DROP COLUMN role")
