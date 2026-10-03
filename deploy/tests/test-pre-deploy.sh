#!/usr/bin/env bash
# Tests deploy/render/pre-deploy.sh with stub alembic/backup (no network, no database). Run: bash deploy/tests/test-pre-deploy.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../render/pre-deploy.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
check() { if eval "$2"; then ok; else bad "$1"; fi; }

# stub alembic: records the URL it saw; fails when STUB_ALEMBIC_FAIL=1
cat > "$T/alembic" <<'S'
#!/usr/bin/env bash
echo "alembic $* url=$ALEMBIC_DATABASE_URL" >> "$STUB_LOG"
[ "${STUB_ALEMBIC_FAIL:-0}" = 1 ] && exit 3
exit 0
S
chmod +x "$T/alembic"

# Copy script into a fake repo so deploy/scripts/backup.sh can be a stub too
R="$T/repo"; mkdir -p "$R/deploy/render" "$R/deploy/scripts"
cp "$SCRIPT" "$R/deploy/render/pre-deploy.sh"
cat > "$R/deploy/scripts/backup.sh" <<'S'
#!/usr/bin/env bash
echo "backup host=$PGHOST port=$PGPORT db=$PGDATABASE user=$PGUSER ssl=$PGSSLMODE r2=$RCLONE_CONFIG_R2_ENDPOINT" >> "$STUB_LOG"
[ "${STUB_BACKUP_FAIL:-0}" = 1 ] && exit 9
exit 0
S

ARGS=()
run() { # args: env assignments...
  : > "$T/log"
  env -i PATH="$PATH" STUB_LOG="$T/log" ALEMBIC_CMD="$T/alembic" "$@" bash "$R/deploy/render/pre-deploy.sh" "${ARGS[@]}" > "$T/out" 2>&1
  RC=$?
}
URL='postgresql+psycopg://owner:p%40ss@ep-x.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'
BK=(AGE_RECIPIENT=age1xyz R2_BUCKET=b R2_ACCESS_KEY_ID=a R2_SECRET_ACCESS_KEY=s R2_ENDPOINT=https://acc.r2.cloudflarestorage.com)

# 1 no URL
run; check "1 missing URL -> exit 2" '[ $RC -eq 2 ]'
# 2 wrong driver prefix
run NEON_OWNER_URL="postgresql://o:p@h/d"; check "2 wrong prefix -> exit 2" '[ $RC -eq 2 ]'
# 3 pooled endpoint refused
run NEON_OWNER_URL="postgresql+psycopg://o:p@ep-x-pooler.neon.tech/d"; check "3 pooled -> exit 2" '[ $RC -eq 2 ] && grep -q pooled "$T/out"'
check "3b nothing executed" '[ ! -s "$T/log" ]'
# 4 no backup vars -> warn, migrate
run NEON_OWNER_URL="$URL"; check "4 no backup vars -> ok" '[ $RC -eq 0 ] && grep -q "skipping the pre-deploy backup" "$T/out"'
check "4b alembic ran with owner url" 'grep -q "alembic upgrade head url=$URL" "$T/log"'
check "4c no backup call" '! grep -q "^backup" "$T/log"'
# 5 partial backup vars -> stop before DB
run NEON_OWNER_URL="$URL" AGE_RECIPIENT=age1xyz R2_BUCKET=b; check "5 partial backup -> exit 2" '[ $RC -eq 2 ]'
check "5b nothing executed" '[ ! -s "$T/log" ]'
# 6 full backup vars -> backup then migrate, URL parsed, password decoded, ssl required
run NEON_OWNER_URL="$URL" "${BK[@]}"; check "6 backup+migrate ok" '[ $RC -eq 0 ]'
check "6b libpq vars parsed" 'grep -q "backup host=ep-x.ap-southeast-1.aws.neon.tech port=5432 db=neondb user=owner ssl=require r2=https://acc" "$T/log"'
check "6c backup before alembic" '[ "$(sed -n 1p "$T/log" | cut -c1-6)" = backup ] && sed -n 2p "$T/log" | grep -q "^alembic"'
check "6d password never printed" '! grep -q "p%40ss\|p@ss" "$T/out"'
# 7 backup failure stops before migration
run NEON_OWNER_URL="$URL" "${BK[@]}" STUB_BACKUP_FAIL=1; check "7 backup fail -> exit 1" '[ $RC -eq 1 ]'
check "7b migration NOT run" '! grep -q "^alembic" "$T/log"'
# 8 migration failure
run NEON_OWNER_URL="$URL" STUB_ALEMBIC_FAIL=1; check "8 migration fail -> exit 1" '[ $RC -eq 1 ] && grep -q "migration failed" "$T/out"'
# 9 explicit port
run NEON_OWNER_URL="postgresql+psycopg://o:p@h.example:6543/d" "${BK[@]}"; check "9 port parsed" 'grep -q "port=6543" "$T/log"'

# 10 --backup-only: backup, no migration
ARGS=(--backup-only)
run NEON_OWNER_URL="$URL" "${BK[@]}"; check "10 backup-only ok" '[ $RC -eq 0 ] && grep -q "^backup" "$T/log" && ! grep -q "^alembic" "$T/log"'
run NEON_OWNER_URL="$URL"; check "10b backup-only without vars -> exit 2" '[ $RC -eq 2 ] && [ ! -s "$T/log" ]'
run NEON_OWNER_URL="$URL" "${BK[@]}" STUB_BACKUP_FAIL=1; check "10c backup-only failure -> exit 1" '[ $RC -eq 1 ]'
ARGS=(--bogus)
run NEON_OWNER_URL="$URL"; check "11 unknown option -> exit 2" '[ $RC -eq 2 ]'
ARGS=()

echo "pre-deploy tests: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
