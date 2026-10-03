#!/bin/bash
# Runs ONCE, only when the database volume is created for the first time (postgres image entrypoint).
# Creates the three least-privilege roles the application expects (docs/harness/03-system-design.md §1-1):
#   migrator      owns the database, runs Alembic migrations (DDL)
#   batch_worker  batch jobs (write reference/raw_internal/public_serving)
#   api_service   public API (read-only on public_serving/reference; NO access to raw_internal)
# Table-level GRANTs are applied by the Alembic migrations themselves.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     -v mig="$MIGRATOR_PASSWORD" -v bat="$BATCH_WORKER_PASSWORD" -v api="$API_SERVICE_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE migrator     LOGIN PASSWORD :'mig' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE batch_worker LOGIN PASSWORD :'bat' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE api_service  LOGIN PASSWORD :'api' NOSUPERUSER NOCREATEDB NOCREATEROLE;

ALTER DATABASE stock_screener OWNER TO migrator;
REVOKE ALL ON DATABASE stock_screener FROM PUBLIC;
GRANT CONNECT ON DATABASE stock_screener TO migrator, batch_worker, api_service;

-- Nobody but the owner may create objects in the default schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
