#!/usr/bin/env bash
# Creates deploy/.env from the template and fills the random secrets. Run once on the server.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -e .env ]; then
  echo "[STOP] deploy/.env already exists. Not overwriting. Edit it by hand or delete it first." >&2
  exit 1
fi
command -v openssl >/dev/null || { echo "[STOP] openssl is required (sudo apt install openssl)" >&2; exit 1; }

cp .env.production.example .env
chmod 600 .env
for key in POSTGRES_ADMIN_PASSWORD MIGRATOR_PASSWORD BATCH_WORKER_PASSWORD API_SERVICE_PASSWORD PUBLIC_API_INTERNAL_TOKEN; do
  value="$(openssl rand -hex 24)"
  sed -i "s|^${key}=.*|${key}=${value}|" .env
done

echo "deploy/.env created (mode 600). Random secrets are filled in."
echo "Now open it and fill the lines that say FILL_ME:   nano deploy/.env"
echo "Secret values were not printed."
