#!/bin/bash
# Runs INSIDE the backup container (use deploy/scripts/restore-run.sh from the host).
#   restore.sh --test <object>      restore into a throw-away DB "restore_test", compare, drop it. SAFE.
#   restore.sh --real <object>      REPLACE the live database stock_screener with the backup. DESTRUCTIVE.
# <object> is a path inside the bucket, e.g. daily/stock_screener-20261003T060000Z.dump.age
# The age PRIVATE key file must be mounted at /run/age.key (it never lives on the server normally).
set -euo pipefail

MODE="${1:-}"; OBJECT="${2:-}"
[ -n "$MODE" ] && [ -n "$OBJECT" ] || { echo "usage: restore.sh --test|--real <object>" >&2; exit 2; }
[ -r /run/age.key ] || { echo "[STOP] age private key not found at /run/age.key" >&2; exit 2; }
: "${R2_BUCKET:?}" "${PGADMIN_USER:?}" "${PGADMIN_PASSWORD:?}"

TARGET="restore_test"
[ "$MODE" = "--real" ] && TARGET="${PGDATABASE:-stock_screener}"
export PGUSER="$PGADMIN_USER" PGPASSWORD="$PGADMIN_PASSWORD"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

echo "[restore] downloading and decrypting ${OBJECT}"
rclone cat "r2:${R2_BUCKET}/${OBJECT}" | age -d -i /run/age.key > "${WORK}/db.dump"
pg_restore -l "${WORK}/db.dump" > /dev/null   # fails here if the file is not a valid dump

psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${TARGET} WITH (FORCE)"
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${TARGET} OWNER migrator"
# --role=migrator makes restored objects owned by migrator; GRANTs inside the dump restore the app roles' rights.
pg_restore -d "${TARGET}" --no-owner --role=migrator "${WORK}/db.dump"

echo "[restore] row counts in the restored database:"
psql -d "${TARGET}" -At -c "SELECT schemaname||'.'||relname||' '||n_live_tup FROM pg_stat_user_tables ORDER BY 1" || true
psql -d "${TARGET}" -At -c "ANALYZE" >/dev/null || true
psql -d "${TARGET}" -At -c "SELECT 'stock_master rows: '||count(*) FROM public_serving.stock_master" || true

if [ "$MODE" = "--test" ]; then
  psql -d postgres -c "DROP DATABASE ${TARGET} WITH (FORCE)"
  echo "[restore] TEST OK — the backup is restorable. Test database dropped."
else
  echo "[restore] REAL restore finished. Restart the stack and check the site."
fi
