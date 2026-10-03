#!/usr/bin/env bash
# Pre-deploy steps for the Render + Neon beta (DEC-063). Run by GitHub Actions (render-deploy.yml) BEFORE Render
# is told to deploy new code, so the database schema is always ready for the new version:
#   1) backup the Neon database (pg_dump -> age -> Cloudflare R2) with the existing deploy/scripts/backup.sh
#   2) alembic upgrade head
#
# Required env:  NEON_OWNER_URL      postgresql+psycopg://OWNER:PW@HOST/DB?sslmode=require  (DIRECT endpoint, not "-pooler")
# Backup env (all or none): AGE_RECIPIENT R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ENDPOINT
#   * none set  -> backup is SKIPPED with a warning (Neon keeps 6h of history; fine for a beta)
#   * some set  -> treated as a misconfiguration: stop before touching the database
#   * all set   -> a failed backup STOPS the deploy (same rule as deploy/scripts/deploy.sh)
# Option:  --backup-only   only the backup (used by the scheduled backup workflow); all 5 backup vars are then REQUIRED.
# Exit: 0 ok, 1 failure, 2 configuration error.
set -euo pipefail

BACKUP_ONLY=0
case "${1:-}" in
  "") ;;
  --backup-only) BACKUP_ONLY=1 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
ALEMBIC="${ALEMBIC_CMD:-alembic}"

log() { printf '[pre-deploy] %s\n' "$*"; }
die() { printf '[pre-deploy][STOP] %s\n' "$*" >&2; exit "${2:-1}"; }

[ -n "${NEON_OWNER_URL:-}" ] || die "NEON_OWNER_URL is not set" 2
case "$NEON_OWNER_URL" in
  postgresql+psycopg://*) ;;
  *) die "NEON_OWNER_URL must start with postgresql+psycopg:// (alembic needs the driver name)" 2 ;;
esac
case "$NEON_OWNER_URL" in
  *-pooler*) die "NEON_OWNER_URL points at the pooled endpoint (-pooler). Use the DIRECT connection string for migrations/backups." 2 ;;
esac

# Split the URL into libpq variables (never print the password).
eval "$(NEON_OWNER_URL="$NEON_OWNER_URL" python3 - <<'PY'
import os, shlex
from urllib.parse import urlsplit, unquote
u = urlsplit(os.environ["NEON_OWNER_URL"].replace("postgresql+psycopg://", "postgresql://", 1))
for k, v in {
    "PGHOST": u.hostname or "", "PGPORT": str(u.port or 5432), "PGDATABASE": (u.path or "/").lstrip("/"),
    "PGUSER": unquote(u.username or ""), "PGPASSWORD": unquote(u.password or ""),
}.items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"
export PGSSLMODE=require

set_count=0
for v in AGE_RECIPIENT R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ENDPOINT; do
  [ -n "${!v:-}" ] && set_count=$((set_count + 1))
done

if [ "$set_count" -eq 0 ] && [ "$BACKUP_ONLY" -eq 1 ]; then
  die "--backup-only needs AGE_RECIPIENT R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ENDPOINT" 2
elif [ "$set_count" -eq 0 ]; then
  log "[WARN] backup secrets are not set -> skipping the pre-deploy backup (Neon history is the only safety net)"
elif [ "$set_count" -ne 5 ]; then
  die "backup settings are incomplete ($set_count of 5 set). Set all of AGE_RECIPIENT R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ENDPOINT, or none." 2
else
  export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_ACL=private
  export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
  export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
  export RCLONE_CONFIG_R2_ENDPOINT="$R2_ENDPOINT"
  log "backing up the database to R2 (encrypted)"
  bash "$REPO/deploy/scripts/backup.sh" || die "backup failed -> deployment stopped before any schema change"
fi

if [ "$BACKUP_ONLY" -eq 1 ]; then log "[OK] backup done"; exit 0; fi

log "alembic upgrade head"
export ALEMBIC_DATABASE_URL="$NEON_OWNER_URL"
( cd "$REPO" && $ALEMBIC upgrade head ) || die "migration failed (nothing was deployed). Fix the migration or restore from backup."
log "[OK] database is ready for the new version"
