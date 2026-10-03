-- Neon 최초 1회 설정 (DEC-063). Neon SQL 편집기 또는 psql로, DB 소유자(기본 neondb_owner)로 실행한다.
--
-- 로컬 Docker 구성(deploy/db/init/01-roles.sh)의 migrator 역할은 Neon에서는 "DB 소유자(neondb_owner)"가
-- 대신한다(마이그레이션 = 테이블 생성/권한 부여를 하는 계정). 앱은 아래 두 최소권한 역할만 쓴다.
--   batch_worker : 배치(수집·가공) — reference / raw_internal / public_serving 쓰기
--   api_service  : 공개 API — public_serving / reference 읽기 전용, raw_internal 접근 불가
-- 테이블별 GRANT는 `alembic upgrade head`가 적용한다(db/alembic/versions/*).
--
-- 사용법 (비밀번호는 각자 만든 긴 무작위 값으로 바꾼다. 따옴표/백슬래시 없이 영문+숫자 권장):
--   psql "$NEON_OWNER_DIRECT_URL" \
--        -v bat="배치용_비밀번호" -v api="API용_비밀번호" -f deploy/render/neon-setup.sql
-- 여러 번 실행해도 안전하다(이미 있으면 비밀번호만 갱신).

SELECT format('CREATE ROLE batch_worker LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'bat')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'batch_worker')
\gexec
SELECT format('CREATE ROLE api_service LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'api')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_service')
\gexec

SELECT format('ALTER ROLE batch_worker PASSWORD %L', :'bat') \gexec
SELECT format('ALTER ROLE api_service PASSWORD %L', :'api') \gexec

-- 현재 접속한 DB 이름을 그대로 쓴다(Neon 기본은 neondb).
SELECT format('GRANT CONNECT ON DATABASE %I TO batch_worker, api_service', current_database()) \gexec

-- 기본 public 스키마에는 소유자 외 생성 금지
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
