#!/usr/bin/env bash
# Auto deploy (DEC-062): run by cron every few minutes ON THE SERVER. It checks whether the production branch
# (default PROD_SCH) has a new commit that changes RUNTIME code and, if so, runs deploy.sh
# (backup -> build -> migrate -> start -> automatic rollback when the new version is not healthy).
#
#  * Pushes that only change docs / tests / QA scripts / *.md / images are skipped (no rebuild).
#  * A commit whose deployment failed is NOT retried on every poll. It is retried when a newer commit arrives,
#    or after:  ./scripts/auto-deploy.sh --retry
#  * Pause / resume:  ./scripts/auto-deploy.sh --pause   |   --resume
#  * State:           ./scripts/auto-deploy.sh --status
#
# The server only makes OUTBOUND connections (git over SSH with a read-only deploy key). No inbound port is needed.
# Exit codes: 0 normal (nothing to do / skipped / paused / deployed), 1 deployment failed.
set -uo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
BRANCH="${AUTO_DEPLOY_BRANCH:-PROD_SCH}"
LOCK_FILE="${AUTO_DEPLOY_LOCK:-/tmp/stock-analyzer-autodeploy.lock}"

F_DEPLOYED="$DEPLOY_DIR/.deployed_sha"   # commit that is running now (written by deploy.sh)
F_CHECKED="$DEPLOY_DIR/.checked_sha"     # newest commit already evaluated and skipped (no runtime change)
F_FAILED="$DEPLOY_DIR/.failed_sha"       # newest commit whose deployment failed
F_PAUSED="$DEPLOY_DIR/.auto-deploy-paused"

log() { printf '[auto-deploy] %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# Returns 0 when the path does NOT affect the running service (docs, tests, QA tooling, server-side examples).
# Anything not listed here is treated as runtime code (fail-open: when in doubt, deploy).
is_ignored_path() {
  case "$1" in
    # baked into the backup image -> a change must rebuild it
    deploy/scripts/backup.sh | deploy/scripts/restore.sh) return 1 ;;
    docs/* | tests/* | TEST/* | 99.* | templates/* | automation/* | .github/*) return 0 ;;
    정찬욱*) return 0 ;;
    deploy/tests/* | deploy/scripts/* | deploy/crontab.example | deploy/logrotate.stock-analyzer | deploy/.env.production.example) return 0 ;;
    frontend/scripts/qa/* | frontend/scripts/check-*.mjs) return 0 ;;
    scripts/*.ps1) return 0 ;;
    .gitignore | pyproject.toml | requirements-dev.txt) return 0 ;;
    *.md | *.MD | *.png | *.jpg | *.jpeg | *.webp | *.gif) return 0 ;;
  esac
  return 1
}

notify() {
  local url text
  url="$(grep -E '^AUTO_DEPLOY_WEBHOOK_URL=' "$DEPLOY_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r')"
  [ -n "$url" ] || return 0
  # JSON-escape: drop control characters (except tab/newline), escape backslash, quote and tab, newline -> \n
  text="$(printf '%s' "$1" | tr -d '\000-\010\013-\037' | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | awk '{printf "%s\\n", $0}')"
  curl -fsS -m 10 -H 'Content-Type: application/json' -d "{\"text\":\"${text}\"}" "$url" >/dev/null 2>&1 || true
}

# The commit that is running now. Falls back to the version tag, then to the checked-out HEAD (first run).
base_sha() {
  local s
  if [ -s "$F_DEPLOYED" ]; then cat "$F_DEPLOYED"; return; fi
  if [ -s "$DEPLOY_DIR/.current_tag" ]; then
    s="$(git -C "$REPO_DIR" rev-parse --verify -q "$(cat "$DEPLOY_DIR/.current_tag")^{commit}" 2>/dev/null || true)"
    [ -n "$s" ] && { echo "$s"; return; }
  fi
  git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true
}

remote_sha() {
  git -C "$REPO_DIR" ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | awk 'NR==1{print $1}'
}

show_status() {
  local r
  r="$(remote_sha)"
  echo "branch            : $BRANCH"
  echo "running (deployed): $(base_sha | cut -c1-12)"
  echo "remote head       : ${r:0:12}${r:+ }$([ -z "$r" ] && echo '(cannot read GitHub)')"
  echo "last failed       : $(cut -c1-12 "$F_FAILED" 2>/dev/null || echo none)"
  echo "last skipped      : $(cut -c1-12 "$F_CHECKED" 2>/dev/null || echo none)"
  if [ -e "$F_PAUSED" ]; then echo "auto deploy       : PAUSED (resume: ./scripts/auto-deploy.sh --resume)"; else echo "auto deploy       : on"; fi
}

run_once() {
  exec 8>"$LOCK_FILE"
  flock -n 8 || exit 0   # a previous run (possibly a long deploy) is still working

  [ -f "$DEPLOY_DIR/.env" ] || { log "[STOP] deploy/.env is missing"; exit 1; }
  [ -e "$F_PAUSED" ] && exit 0

  local remote deployed
  remote="$(remote_sha)"
  if [ -z "$remote" ]; then
    log "[WARN] cannot read origin/$BRANCH (network, key or branch name?)"
    exit 0
  fi
  deployed="$(base_sha)"
  [ "$remote" = "$deployed" ] && exit 0
  [ "$remote" = "$(cat "$F_CHECKED" 2>/dev/null || true)" ] && exit 0
  [ "$remote" = "$(cat "$F_FAILED" 2>/dev/null || true)" ] && exit 0

  if ! git -C "$REPO_DIR" fetch --quiet origin "$BRANCH" 2>/dev/null; then
    log "[WARN] git fetch failed; will retry on the next run"
    exit 0
  fi

  # Decide from the files that differ between the RUNNING version and the new commit.
  local total=0 runtime=0 f decided="deploy" why=""
  if git -C "$REPO_DIR" cat-file -e "${deployed}^{commit}" 2>/dev/null &&
     git -C "$REPO_DIR" cat-file -e "${remote}^{commit}" 2>/dev/null; then
    while IFS= read -r -d '' f; do
      total=$((total + 1))
      is_ignored_path "$f" || runtime=$((runtime + 1))
    done < <(git -C "$REPO_DIR" -c core.quotepath=false diff --name-only -z "$deployed" "$remote" 2>/dev/null)
    if [ "$runtime" -eq 0 ]; then decided="skip"; fi
    why="${total} changed files, ${runtime} runtime"
  else
    why="running version unknown, deploying to be safe"
  fi

  local subject
  subject="$(git -C "$REPO_DIR" log -1 --format=%s "$remote" 2>/dev/null | cut -c1-80)"

  if [ "$decided" = "skip" ]; then
    echo "$remote" > "$F_CHECKED"
    log "skip ${remote:0:12} (${why}): docs/tests/QA only, no redeploy"
    exit 0
  fi

  log "new commit ${remote:0:12} (${why}) \"${subject}\" -> deploying"
  local out rc
  out="$(mktemp)"
  bash "$DEPLOY_DIR/scripts/deploy.sh" "$BRANCH" 2>&1 | tee "$out"
  rc="${PIPESTATUS[0]}"

  case "$rc" in
    0)
      rm -f "$F_FAILED" "$F_CHECKED"
      log "[OK] deployed ${remote:0:12}"
      notify "[배포 성공] ${remote:0:12} ${subject}"
      rm -f "$out"
      exit 0
      ;;
    75)
      log "another deploy is running; will retry on the next run"
      rm -f "$out"
      exit 0
      ;;
    *)
      echo "$remote" > "$F_FAILED"
      log "[FAIL] deployment of ${remote:0:12} failed (exit ${rc}); the previous version was restored when possible. Not retrying this commit."
      notify "[배포 실패] ${remote:0:12} ${subject}
$(tail -n 6 "$out" | cut -c1-160)
(이전 버전으로 복귀를 시도했습니다. 새 커밋을 푸시하거나 서버에서 ./scripts/auto-deploy.sh --retry 를 실행하면 다시 시도합니다.)"
      rm -f "$out"
      exit 1
      ;;
  esac
}

main() {
  case "${1:-}" in
    --status) show_status ;;
    --pause)  touch "$F_PAUSED"; echo "auto deploy paused (resume: ./scripts/auto-deploy.sh --resume)" ;;
    --resume) rm -f "$F_PAUSED"; echo "auto deploy resumed" ;;
    --retry)  rm -f "$F_FAILED" "$F_CHECKED"; echo "failed/skipped markers cleared; the next run will evaluate the branch again" ;;
    -h | --help) sed -n '2,13p' "${BASH_SOURCE[0]}" ;;
    "") run_once ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
}

# Allow tests to source this file for is_ignored_path without running anything.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
