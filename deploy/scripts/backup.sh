#!/bin/bash
# Runs INSIDE the backup container. pg_dump -> age encryption -> Cloudflare R2.
# The server holds only the age PUBLIC key, so a stolen server cannot read old backups.
set -euo pipefail

: "${AGE_RECIPIENT:?}" "${R2_BUCKET:?}" "${PGPASSWORD:?}"
KEEP_DAILY="${BACKUP_KEEP_DAILY_DAYS:-14}"
KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY_DAYS:-60}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="stock_screener-${TS}.dump.age"
REMOTE="r2:${R2_BUCKET}"

echo "[backup] start ${TS}"
# -Fc = compressed custom format (restorable table by table). Encrypted before it leaves the server.
pg_dump -Fc --no-owner | age -r "${AGE_RECIPIENT}" | rclone rcat "${REMOTE}/daily/${NAME}"

SIZE="$(rclone size --json "${REMOTE}/daily/${NAME}" | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p')"
if [ -z "${SIZE}" ] || [ "${SIZE}" -lt 1024 ]; then
  echo "[backup][FAIL] uploaded object is missing or too small (${SIZE:-none} bytes)" >&2
  exit 1
fi
echo "[backup] uploaded daily/${NAME} (${SIZE} bytes)"

# Sunday (UTC) copy goes to weekly/ so it lives longer than the daily ones.
if [ "$(date -u +%u)" = "7" ]; then
  rclone copyto "${REMOTE}/daily/${NAME}" "${REMOTE}/weekly/${NAME}"
  echo "[backup] weekly copy made"
fi

# Retention runs only after a successful upload (set -e), so the newest backup always exists.
rclone delete "${REMOTE}/daily"  --min-age "${KEEP_DAILY}d"
rclone delete "${REMOTE}/weekly" --min-age "${KEEP_WEEKLY}d"
echo "[backup] done"
