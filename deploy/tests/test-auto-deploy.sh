#!/usr/bin/env bash
# Tests for deploy/scripts/auto-deploy.sh and deploy/scripts/deploy.sh (DEC-062).
# Uses a stub `docker`, a stub `curl` and throw-away git repositories. Nothing real is touched.
# Run:  bash deploy/tests/test-auto-deploy.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$HERE/../scripts"
PASS=0
FAIL=0
ORIG_PATH="$PATH"

t() {  # t "description" <command that must succeed>
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then PASS=$((PASS + 1)); echo "PASS  $desc"; else FAIL=$((FAIL + 1)); echo "FAIL  $desc"; fi
}
has() { grep -q -- "$2" "$1"; }          # has <file> <text>
hasnt() { ! grep -q -- "$2" "$1"; }
eq() { [ "$1" = "$2" ]; }

new_world() {
  W="$(mktemp -d)"; export W
  git init -q --bare "$W/remote.git"
  git -C "$W/remote.git" symbolic-ref HEAD refs/heads/PROD_SCH
  git clone -q "$W/remote.git" "$W/dev" 2>/dev/null
  git -C "$W/dev" config user.email t@t; git -C "$W/dev" config user.name t
  git -C "$W/dev" checkout -q -b PROD_SCH
  mkdir -p "$W/dev/deploy/scripts" "$W/dev/services" "$W/dev/docs"
  cp "$SCRIPTS/deploy.sh" "$SCRIPTS/auto-deploy.sh" "$W/dev/deploy/scripts/"
  echo "v1" > "$W/dev/services/app.py"; echo "doc" > "$W/dev/docs/a.md"
  git -C "$W/dev" add -A; git -C "$W/dev" commit -qm "init"; git -C "$W/dev" push -q origin PROD_SCH 2>/dev/null
  git clone -q -b PROD_SCH "$W/remote.git" "$W/srv" 2>/dev/null
  echo "AUTO_DEPLOY_WEBHOOK_URL=https://hooks.example/test" > "$W/srv/deploy/.env"

  mkdir -p "$W/bin"
  cat > "$W/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $* [APP_TAG=${APP_TAG:-}]" >> "$STUB_LOG"
mode="$(cat "$STUB_DIR/mode" 2>/dev/null || echo ok)"
if [[ "$*" == *"ps --status running"* ]]; then echo db; exit 0; fi
if [[ "$*" == *"run --rm -T backup"* && "$mode" == "fail_backup" ]]; then exit 1; fi
if [[ "$*" == *"up -d --remove-orphans --wait"* ]]; then
  failtag="$(cat "$STUB_DIR/fail_tag" 2>/dev/null || true)"
  if [ -n "$failtag" ] && [ "${APP_TAG:-}" = "$failtag" ]; then exit 1; fi
fi
exit 0
EOF
  cat > "$W/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$CURL_LOG"
exit 0
EOF
  chmod +x "$W/bin/docker" "$W/bin/curl"
  export PATH="$W/bin:$ORIG_PATH" STUB_DIR="$W" STUB_LOG="$W/docker.log" CURL_LOG="$W/curl.log"
  export AUTO_DEPLOY_LOCK="$W/auto.lock"
  : > "$STUB_LOG"; : > "$CURL_LOG"; echo ok > "$W/mode"; : > "$W/fail_tag"
  # the first deployment is done by hand (as in the guide) so the running version is known
  (cd "$W/srv" && bash deploy/scripts/deploy.sh PROD_SCH >"$W/first.out" 2>&1)
  : > "$STUB_LOG"; : > "$CURL_LOG"
}

push() {  # push <path> <content> <message>
  mkdir -p "$(dirname "$W/dev/$1")"
  printf '%s\n' "$2" > "$W/dev/$1"
  git -C "$W/dev" add -A; git -C "$W/dev" commit -qm "$3"; git -C "$W/dev" push -q origin PROD_SCH 2>/dev/null
}

run_auto() {  # sets OUT, RC
  OUT="$W/auto.out"
  (cd "$W/srv" && bash deploy/scripts/auto-deploy.sh) >"$OUT" 2>&1
  RC=$?
}
builds() { grep -c "compose build" "$STUB_LOG"; }
head_full() { git -C "$W/dev" rev-parse HEAD; }
head_short() { git -C "$W/dev" rev-parse --short=12 HEAD; }
deployed() { cat "$W/srv/deploy/.deployed_sha" 2>/dev/null; }

echo "=== T0 path filter (is_ignored_path) ==="
# shellcheck disable=SC1091
source "$SCRIPTS/auto-deploy.sh"
for p in "docs/qa/a.md" "docs/qa/2026-10-03/x.png" "tests/unit/test_a.py" "frontend/scripts/qa/a.mjs" \
         "frontend/scripts/check-x.mjs" "README.md" "USAGE-GUIDE.md" "GIT연동(주식분석서비스).MD" \
         "정찬욱주식현황요청_카톡/a.png" ".github/workflows/x.yml" "deploy/scripts/deploy.sh" \
         "deploy/scripts/auto-deploy.sh" "deploy/crontab.example" "deploy/tests/test-auto-deploy.sh" \
         "scripts/start_local_api.ps1" ".gitignore" "services/readme.md"; do
  t "ignored (no redeploy): $p" is_ignored_path "$p"
done
for p in "services/public_api/main.py" "shared/x.py" "db/alembic/versions/0015_x.py" "scripts/run_daily_batch.py" \
         "frontend/src/app/page.tsx" "frontend/package.json" "frontend/scripts/lint-forbidden-copy.mjs" \
         "frontend/next.config.mjs" "requirements.txt" "alembic.ini" "data/calendar/2027.yaml" \
         "deploy/docker-compose.yml" "deploy/Caddyfile" "deploy/backend.Dockerfile" "deploy/frontend.Dockerfile" \
         "deploy/scripts/backup.sh" "deploy/scripts/restore.sh" "deploy/db/init/01-roles.sh" ".dockerignore" \
         "unknown-new-dir/x.py"; do
  t "deploys (runtime/unknown): $p" bash -c "! ( source '$SCRIPTS/auto-deploy.sh'; is_ignored_path '$p' )"
done

echo "=== T1 idle: nothing changed ==="
new_world
run_auto
t "no change -> exit 0, no output, no build" bash -c "[ $RC = 0 ] && [ ! -s '$OUT' ] && [ \$(grep -c 'compose build' '$STUB_LOG') = 0 ]"
t "first manual deploy recorded the running commit" bash -c "[ -s '$W/srv/deploy/.deployed_sha' ] && [ -s '$W/srv/deploy/.current_tag' ]"
t "deploy.sh default branch is PROD_SCH" grep -q 'AUTO_DEPLOY_BRANCH:-PROD_SCH' "$SCRIPTS/deploy.sh"

echo "=== T2 docs-only push is skipped, then a code push deploys everything since the running version ==="
push "docs/qa/new.md" "report" "docs: new report"
run_auto
t "docs-only push: skipped (no build)" bash -c "[ $RC = 0 ] && [ \$(grep -c 'compose build' '$STUB_LOG') = 0 ] && grep -q 'skip' '$OUT'"
t "docs-only push: marked as checked" bash -c "[ \"\$(cat '$W/srv/deploy/.checked_sha')\" = \"$(head_full)\" ]"
run_auto
t "same head polled again: silent (idempotent)" bash -c "[ $RC = 0 ] && [ ! -s '$OUT' ]"
push "services/app.py" "v2" "feat: code change"
run_auto
t "code push: deployed once" bash -c "[ $RC = 0 ] && [ \$(grep -c 'compose build' '$STUB_LOG') = 1 ] && grep -q '\[OK\] deployed' '$OUT'"
t "running commit now equals the pushed commit" eq "$(deployed)" "$(head_full)"
t "skip marker cleared after deploy" bash -c "[ ! -e '$W/srv/deploy/.checked_sha' ]"
t "backup ran before build" bash -c "grep -n 'run --rm -T backup' '$STUB_LOG' | head -1 | cut -d: -f1 | { read b; grep -n 'compose build' '$STUB_LOG' | head -1 | cut -d: -f1 | { read c; [ \"\$b\" -lt \"\$c\" ]; }; }"
t "migration ran" has "$STUB_LOG" "run --rm -T migrate"
t "success notification sent" has "$CURL_LOG" "배포 성공"
run_auto
t "after deploy polling is idle again" bash -c "[ $RC = 0 ] && [ ! -s '$OUT' ]"

echo "=== T3 mixed push (docs + code) deploys ==="
printf 'x\n' > "$W/dev/docs/more.md"; push "services/other.py" "o" "feat: mixed"
run_auto
t "docs + code in one push: deployed" bash -c "[ \$(grep -c 'compose build' '$STUB_LOG') = 2 ]"

echo "=== T4 new version does not become healthy: automatic rollback, no retry loop ==="
new_world
prev_tag="$(cat "$W/srv/deploy/.current_tag")"
push "services/app.py" "broken" "feat: broken release"
head_short > "$W/fail_tag"
run_auto
t "failed deploy: exit 1" eq "$RC" "1"
t "failed deploy: rollback attempted to previous tag" bash -c "grep -q '\[rollback\] returning to $prev_tag' '$OUT'"
t "failed deploy: running version tag unchanged" bash -c "[ \"\$(cat '$W/srv/deploy/.current_tag')\" = '$prev_tag' ]"
t "failed deploy: commit recorded as failed" bash -c "[ \"\$(cat '$W/srv/deploy/.failed_sha')\" = \"$(head_full)\" ]"
t "failed deploy: failure notification with details" has "$CURL_LOG" "배포 실패"
b1="$(builds)"
run_auto
t "next poll does NOT retry the same failed commit" bash -c "[ $RC = 0 ] && [ \"\$(grep -c 'compose build' '$STUB_LOG')\" = '$b1' ] && [ ! -s '$OUT' ]"
: > "$W/fail_tag"
push "services/app.py" "fixed" "fix: working release"
run_auto
t "a newer commit is deployed after a failure" bash -c "[ $RC = 0 ] && grep -q '\[OK\] deployed' '$OUT'"
t "failed marker cleared after success" bash -c "[ ! -e '$W/srv/deploy/.failed_sha' ]"

echo "=== T5 backup failure cancels the deployment (nothing changed) ==="
new_world
echo fail_backup > "$W/mode"
push "services/app.py" "v2" "feat: needs backup"
run_auto
t "backup failure: exit 1, build never ran" bash -c "[ $RC = 1 ] && [ \$(grep -c 'compose build' '$STUB_LOG') = 0 ] && grep -q 'backup failed' '$OUT'"
t "backup failure: containers untouched (no up/migrate)" bash -c "! grep -q 'run --rm -T migrate' '$STUB_LOG'"
echo ok > "$W/mode"
(cd "$W/srv" && bash deploy/scripts/auto-deploy.sh --retry >/dev/null)
run_auto
t "--retry lets the same commit deploy after the cause is fixed" bash -c "[ $RC = 0 ] && grep -q '\[OK\] deployed' '$OUT'"

echo "=== T6 pause / resume / status ==="
new_world
(cd "$W/srv" && bash deploy/scripts/auto-deploy.sh --pause >/dev/null)
push "services/app.py" "v2" "feat: while paused"
run_auto
t "paused: no deploy, silent" bash -c "[ $RC = 0 ] && [ ! -s '$OUT' ] && [ \$(grep -c 'compose build' '$STUB_LOG') = 0 ]"
t "--status shows PAUSED" bash -c "cd '$W/srv' && bash deploy/scripts/auto-deploy.sh --status | grep -q PAUSED"
(cd "$W/srv" && bash deploy/scripts/auto-deploy.sh --resume >/dev/null)
run_auto
t "resumed: the pending commit is deployed" bash -c "[ $RC = 0 ] && grep -q '\[OK\] deployed' '$OUT'"
t "--status shows branch and running commit" bash -c "cd '$W/srv' && bash deploy/scripts/auto-deploy.sh --status | grep -q 'branch            : PROD_SCH'"

echo "=== T7 another deploy running: skip without marking failed, retry next poll ==="
new_world
push "services/app.py" "v2" "feat: lock test"
exec 7>/tmp/stock-analyzer-deploy.lock; flock -n 7
run_auto
exec 7>&-
t "busy: exit 0, no build, not marked failed" bash -c "[ $RC = 0 ] && [ \$(grep -c 'compose build' '$STUB_LOG') = 0 ] && [ ! -e '$W/srv/deploy/.failed_sha' ] && grep -q 'another deploy is running' '$OUT'"
run_auto
t "lock released: deployed on the next poll" bash -c "[ $RC = 0 ] && grep -q '\[OK\] deployed' '$OUT'"

echo "=== T8 two auto-deploy runs at once: the second exits immediately ==="
new_world
push "services/app.py" "v2" "feat: concurrency"
exec 6>"$AUTO_DEPLOY_LOCK"; flock -n 6
run_auto
exec 6>&-
t "auto lock held: silent exit 0, no build" bash -c "[ $RC = 0 ] && [ ! -s '$OUT' ] && [ \$(grep -c 'compose build' '$STUB_LOG') = 0 ]"

echo "=== T9 GitHub unreachable ==="
new_world
push "services/app.py" "v2" "feat: network test"
git -C "$W/srv" remote set-url origin /nonexistent/repo.git
run_auto
t "unreachable: warning, exit 0, nothing marked, no build" bash -c "[ $RC = 0 ] && grep -q 'cannot read origin' '$OUT' && [ \$(grep -c 'compose build' '$STUB_LOG') = 0 ] && [ ! -e '$W/srv/deploy/.failed_sha' ]"
git -C "$W/srv" remote set-url origin "$W/remote.git"
run_auto
t "reachable again: deployed" bash -c "[ $RC = 0 ] && grep -q '\[OK\] deployed' '$OUT'"

echo "=== T10 running version unknown or branch moved backwards ==="
new_world
push "services/app.py" "v2" "feat: unknown base"
echo "0000000000000000000000000000000000000000" > "$W/srv/deploy/.deployed_sha"
run_auto
t "unknown running commit: deploys to be safe" bash -c "[ $RC = 0 ] && grep -q 'running version unknown' '$OUT' && grep -q '\[OK\] deployed' '$OUT'"
git -C "$W/dev" reset -q --hard HEAD~1; git -C "$W/dev" push -q -f origin PROD_SCH 2>/dev/null
run_auto
t "branch moved back (force push): the older commit is deployed" bash -c "[ $RC = 0 ] && grep -q '\[OK\] deployed' '$OUT' && [ \"\$(cat '$W/srv/deploy/.deployed_sha')\" = \"$(head_full)\" ]"

echo "=== T11 webhook ==="
new_world
push "services/app.py" "q" $'fix: "quoted" subject with \\ backslash and\ttab'
run_auto
cat > "$W/check_payload.py" <<'PY'
import json, re, sys
line = [l for l in open(sys.argv[1], encoding="utf-8") if '{"text"' in l][0]
payload = line[line.index('{"text"'):line.rindex('}') + 1]
d = json.loads(payload)
assert "quoted" in d["text"] and "backslash" in d["text"] and "\t" in d["text"], d
PY
t "webhook payload is valid JSON even with quotes, backslashes and a tab in the commit subject" python3 "$W/check_payload.py" "$CURL_LOG"
new_world
: > "$W/srv/deploy/.env"
push "services/app.py" "w" "feat: no webhook configured"
run_auto
t "no webhook configured: deploy works and curl is never called" bash -c "[ $RC = 0 ] && [ ! -s '$CURL_LOG' ] && grep -q '\[OK\] deployed' '$OUT'"

echo "=== T12 misc ==="
new_world
t "--help prints usage" bash -c "cd '$W/srv' && bash deploy/scripts/auto-deploy.sh --help | grep -q 'Auto deploy'"
t "unknown option exits 2" bash -c "cd '$W/srv' && bash deploy/scripts/auto-deploy.sh --bogus; [ \$? = 2 ]"
t "missing deploy/.env stops with exit 1" bash -c "rm -f '$W/srv/deploy/.env'; cd '$W/srv' && bash deploy/scripts/auto-deploy.sh >/dev/null 2>&1; [ \$? = 1 ]"

echo
echo "RESULT: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
