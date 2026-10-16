-- 로그인 기능용 로컬 DB 계정 `auth_service` 만들기 + 권한 부여(psql용 원본). 보통은 `py -3.12 scripts\setup_local_auth.py`가 이 파일의 GRANT 문을 읽어 대신 적용한다.
-- 직접 쓸 때(로컬 Docker DB, 소유자 접속):
--   psql "<ALEMBIC_DATABASE_URL 의 주소>" -v ON_ERROR_STOP=1 -v auth='<새 비밀번호>' -f deploy/local/auth-service-setup.sql
-- 여러 번 실행해도 안전하다(이미 있으면 비밀번호만 바꾼다). 마이그레이션 0015 이상이 먼저 적용되어 있어야 한다.
-- 비밀번호는 이 파일에 쓰지 않는다.

SELECT format('CREATE ROLE auth_service LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'auth')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_service') \gexec
SELECT format('ALTER ROLE auth_service LOGIN PASSWORD %L', :'auth') \gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO auth_service', current_database()) \gexec
GRANT USAGE ON SCHEMA auth TO auth_service;
GRANT SELECT ON auth.app_users TO auth_service;
GRANT UPDATE (password_hash, failed_attempts, lockout_level, locked_until, last_login_at, updated_at)
  ON auth.app_users TO auth_service;
GRANT INSERT ON auth.login_audit TO auth_service;
GRANT USAGE ON SEQUENCE auth.login_audit_audit_id_seq TO auth_service;
-- 0017(로그인 상태 유지 30일, DEC-070): 서버 쪽 세션 목록
GRANT SELECT, INSERT ON auth.user_sessions TO auth_service;
GRANT UPDATE (last_check_at, revoked_at) ON auth.user_sessions TO auth_service;
-- 0018(권한·가입 승인·관리자 기록, DEC-074)
GRANT INSERT (username, display_name, password_hash) ON auth.app_users TO auth_service;
GRANT UPDATE (display_name, role, is_active, approved_at) ON auth.app_users TO auth_service;
GRANT DELETE ON auth.app_users TO auth_service;
GRANT INSERT ON auth.admin_audit TO auth_service;
GRANT USAGE ON SEQUENCE auth.admin_audit_audit_id_seq TO auth_service;
