#!/usr/bin/env bash
# Host-side wrapper for restore tests and real restores.
#   ./scripts/restore-run.sh --test daily/stock_screener-XXXX.dump.age  /path/to/age-private-key.txt
#   ./scripts/restore-run.sh --real daily/stock_screener-XXXX.dump.age  /path/to/age-private-key.txt
# Copy the private key to the server ONLY for the moment of restoring, then delete it again.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}"; OBJECT="${2:-}"; KEYFILE="${3:-}"
[ -n "$MODE" ] && [ -n "$OBJECT" ] && [ -f "$KEYFILE" ] || {
  echo "usage: restore-run.sh --test|--real <bucket object> <age private key file>" >&2; exit 2; }

if [ "$MODE" = "--real" ]; then
  echo "WARNING: this REPLACES the live database with the backup '$OBJECT'."
  read -r -p "Type RESTORE to continue: " answer
  [ "$answer" = "RESTORE" ] || { echo "cancelled"; exit 1; }
  docker compose stop caddy web api
fi

docker compose --profile tools run --rm -T \
  -v "$(readlink -f "$KEYFILE")":/run/age.key:ro \
  backup /opt/restore.sh "$MODE" "$OBJECT"

if [ "$MODE" = "--real" ]; then
  docker compose up -d --wait --wait-timeout 180
  echo "Stack restarted. Check the site and /api/v1/health."
fi
