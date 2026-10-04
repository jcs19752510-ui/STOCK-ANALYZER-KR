-- 로그인 기능(DEC-067)용 DB 계정 `auth_service` 만들기 + 권한 부여. Neon SQL 편집기 또는 psql로 소유자(neondb_owner) 연결에서 실행한다.
-- 여러 번 실행해도 안전하다(이미 있으면 비밀번호만 바꾼다).
--
--   psql "<소유자 직접 접속 주소>" -v ON_ERROR_STOP=1 -v auth='<새 비밀번호>' -f deploy/render/neon-auth-setup.sql
--
-- 마이그레이션 0015가 먼저 적용되어 있어야 한다(`alembic upgrade head`, render-deploy 워크플로가 수행).
-- 비밀번호는 이 파일에 쓰지 않는다. 명령줄 변수로만 넘기고, 같은 값을 Render API 서비스의 PUBLIC_API_AUTH_DATABASE_URL에 넣는다.

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
