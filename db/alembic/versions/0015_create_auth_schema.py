"""create auth schema: app_users, login_audit (DEC-067 로그인 기능)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-05

회원(관리자가 직접 넣은 사람만)의 로그인 정보와 로그인 기록. 가입 기능은 없다.

- `auth` 스키마는 **전용 DB 계정 `auth_service`만** 최소 권한으로 접근한다. `api_service`(공개 데이터 조회)·`batch_worker`에는 어떤 권한도 주지 않는다.
  `auth_service`: `app_users` SELECT + (`failed_attempts`, `lockout_level`, `locked_until`, `last_login_at`, `password_hash`(재해시 갱신용), `updated_at`) 열 UPDATE만,
  `login_audit` INSERT만. 회원 추가·삭제·비활성화·비밀번호 변경은 관리자 스크립트(소유자/마이그레이터 연결)만 한다.
- **`auth_service` 역할이 아직 없어도 마이그레이션은 실패하지 않는다**(PC 로컬 DB는 로그인을 쓰지 않고, `start_local_api.ps1`이 시작할 때마다
  `alembic upgrade head`를 실행하므로 여기서 실패하면 로컬 API가 못 뜬다). 이 경우 GRANT는 건너뛰며, 역할을 만든 뒤
  `deploy/render/neon-auth-setup.sql`(같은 GRANT를 다시 적용)을 실행하면 된다.
- 아이디는 소문자 3~32자(영문·숫자·`.`·`_`·`-`) CHECK. 비밀번호는 해시(argon2id)만 저장한다.
downgrade: 테이블과 스키마를 제거한다(회원 데이터가 사라지므로 주의).
"""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS_SQL = """
DO $do$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_service') THEN
    GRANT USAGE ON SCHEMA auth TO auth_service;
    GRANT SELECT ON auth.app_users TO auth_service;
    GRANT UPDATE (password_hash, failed_attempts, lockout_level, locked_until, last_login_at, updated_at)
      ON auth.app_users TO auth_service;
    GRANT INSERT ON auth.login_audit TO auth_service;
    GRANT USAGE ON SEQUENCE auth.login_audit_audit_id_seq TO auth_service;
  ELSE
    RAISE NOTICE 'auth_service 역할이 없어 GRANT를 건너뜁니다. 역할을 만든 뒤 deploy/render/neon-auth-setup.sql을 실행하세요.';
  END IF;
END
$do$;
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA auth")
    op.execute("REVOKE ALL ON SCHEMA auth FROM PUBLIC")
    op.execute(
        """
        CREATE TABLE auth.app_users (
            user_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            username        text NOT NULL,
            display_name    text NOT NULL,
            password_hash   text NOT NULL,
            is_active       boolean NOT NULL DEFAULT true,
            failed_attempts integer NOT NULL DEFAULT 0,
            lockout_level   integer NOT NULL DEFAULT 0,
            locked_until    timestamptz,
            last_login_at   timestamptz,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_app_users_username UNIQUE (username),
            CONSTRAINT ck_app_users_username_format CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,31}$'),
            CONSTRAINT ck_app_users_display_name_length CHECK (char_length(display_name) BETWEEN 1 AND 40),
            CONSTRAINT ck_app_users_failed_attempts CHECK (failed_attempts >= 0),
            CONSTRAINT ck_app_users_lockout_level CHECK (lockout_level >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE auth.login_audit (
            audit_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at        timestamptz NOT NULL DEFAULT now(),
            user_id            uuid REFERENCES auth.app_users (user_id) ON DELETE SET NULL,
            username_attempted text,
            result             text NOT NULL,
            client_ip          text,
            CONSTRAINT ck_login_audit_result CHECK (result IN ('SUCCESS', 'FAIL', 'LOCKED', 'INACTIVE')),
            CONSTRAINT ck_login_audit_username_len CHECK (username_attempted IS NULL OR char_length(username_attempted) <= 64)
        )
        """
    )
    op.execute("CREATE INDEX ix_login_audit_occurred_at ON auth.login_audit (occurred_at DESC)")
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE auth.login_audit")
    op.execute("DROP TABLE auth.app_users")
    op.execute("DROP SCHEMA auth")
