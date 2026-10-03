#!/usr/bin/env bash
# FIRST-TIME data loading on a new server (after the stack is up). Safe to re-run (idempotent upserts).
# Each step prints what it does. Long steps are resumable. Run from anywhere:  ./deploy/scripts/bootstrap-data.sh <step>
#   calendar   load the market holiday calendar (default data/calendar/2026.yaml; pass another file as 2nd argument)
#   master     load the stock master (all listed stocks)
#   batch      run the daily batch once (collects the latest trading day, derives metrics)
#   backfill   past prices (needed for the pattern screen: >= 80 trading days). Uses many API calls.
#   earnings   yearly earnings from DART (about 30 minutes)
#   corpfin    quarterly financials for PER/PBR from DART (about 30-60 minutes)
set -euo pipefail
cd "$(dirname "$0")/.."

run() { docker compose --profile tools run --rm -T batch "$@"; }

case "${1:-}" in
  calendar) shift; run python scripts/load_calendar.py "${1:-data/calendar/2026.yaml}" ;;
  master)   run python scripts/seed_stock_master.py ;;
  batch)    run python scripts/run_daily_batch.py ;;
  backfill) shift; run python scripts/backfill_ohlcv.py "$@" ;;
  earnings) run python scripts/enrich_earnings.py ;;
  corpfin)  run python scripts/enrich_corp_financials.py ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
