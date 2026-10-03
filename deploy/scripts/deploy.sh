#!/usr/bin/env bash
# Deploys the "release" branch on THIS server. Called by the GitHub Actions workflow over SSH,
# or by hand:   ./deploy/scripts/deploy.sh [branch]
# Steps: lock -> fetch -> backup -> build -> migrate -> start (wait healthy) -> rollback on failure.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
BRANCH="${1:-release}"
cd "$DEPLOY_DIR"
[ -f .env ] || { echo "[STOP] deploy/.env is missing (run scripts/init-env.sh)" >&2; exit 1; }

# Phase 1 (old script): take the lock, update the code, then restart THIS script from the new files.
# (Replacing a bash script while it is running is unsafe, so the real work runs from the fresh copy.)
if [ -z "${DEPLOY_REEXEC:-}" ]; then
  exec 9>/tmp/stock-analyzer-deploy.lock
  flock -n 9 || { echo "[STOP] another deploy is running" >&2; exit 1; }
  echo "[deploy] fetching origin/${BRANCH}"
  git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
  git -C "$REPO_DIR" reset --hard "origin/${BRANCH}"
  export DEPLOY_REEXEC=1
  exec "$DEPLOY_DIR/scripts/deploy.sh" "$@"   # fd 9 (the lock) is inherited
fi

PREV_TAG="$(cat .current_tag 2>/dev/null || true)"
NEW_TAG="$(git -C "$REPO_DIR" rev-parse --short=12 HEAD)"
echo "[deploy] new version ${NEW_TAG} (previous: ${PREV_TAG:-none})"

if [ "${SKIP_BACKUP:-0}" != "1" ] && docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  echo "[deploy] backing up before changing anything"
  APP_TAG="${PREV_TAG:-$NEW_TAG}" docker compose --profile tools run --rm -T backup \
    || { echo "[STOP] backup failed, deployment cancelled (nothing was changed)" >&2; exit 1; }
fi

echo "[deploy] building images"
export APP_TAG="$NEW_TAG"
docker compose build

echo "[deploy] starting database"
docker compose up -d --wait --wait-timeout 120 db

echo "[deploy] applying DB migrations"
if ! docker compose --profile tools run --rm -T migrate; then
  echo "[FAIL] migration failed. Old containers are untouched." >&2
  exit 1
fi

echo "[deploy] starting services"
if docker compose up -d --remove-orphans --wait --wait-timeout 240; then
  echo "$NEW_TAG" > .current_tag
  [ -n "$PREV_TAG" ] && echo "$PREV_TAG" > .previous_tag || true
  echo "[OK] deployed ${NEW_TAG}"
  docker image prune -f >/dev/null || true
  exit 0
fi

echo "[FAIL] new version did not become healthy." >&2
docker compose logs --tail=60 api web caddy >&2 || true
if [ -n "$PREV_TAG" ]; then
  echo "[rollback] returning to ${PREV_TAG}" >&2
  export APP_TAG="$PREV_TAG"
  docker compose up -d --remove-orphans --wait --wait-timeout 240 \
    && echo "[rollback] previous version is running again" >&2 \
    || echo "[rollback][FAIL] manual action needed" >&2
  echo "NOTE: database migrations are NOT undone automatically. If a migration caused the problem, restore a backup (docs/ops/oracle-deploy-guide.md)." >&2
fi
exit 1
