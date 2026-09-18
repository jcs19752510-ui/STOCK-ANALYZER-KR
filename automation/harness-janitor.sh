#!/usr/bin/env bash
# 규칙 K(중단-안전 정리) 이행 여부를 점검하는 스크립트.
# "사람이 매번 find/git status를 손으로 돌려서 확인"하던 것을 대체하기 위한 것 — 즉 사용자가
# 세션 재개 전 직접 하던 수동 점검을, 매 실행마다 동일한 기준으로 강제하는 게 목적이다.
#
# 이 스크립트는 기본적으로 "읽기 전용 점검"이다. .harness-tmp/ 이외의 위치에 있는 파일은
# 스크립트가 스스로 판단해서 지우지 않는다 (규칙 K 5번 — 애매하면 사람에게 확인).
#
# 사용법:
#   ./automation/harness-janitor.sh            # 점검만 함 (기본값)
#   ./automation/harness-janitor.sh --check     # 위와 동일 (명시적 별칭)
#   ./automation/harness-janitor.sh --clean     # 점검 후 .harness-tmp/ 내용만 삭제 (레거시 패턴은 삭제 안 함, 목록만 안내)
#
# 종료 코드:
#   0 = 잔여물 없음 (또는 --clean으로 정리까지 완료)
#   1 = 잔여물이 남아있음 (--check 모드) — CI/pre-commit에서 이 코드로 실패 처리해 사람이 확인하게 한다
#
# 이 스크립트는 저장소 루트(ORCHESTRATOR.md가 있는 곳)에서 실행해야 한다.

set -euo pipefail

MODE="${1:---check}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

HARNESS_TMP=".harness-tmp"
FOUND=0

echo "[janitor] 점검 대상 저장소: ${REPO_ROOT}"

# 1) .harness-tmp/ — 규칙 K에 따라 이 하위는 janitor가 직접 정리해도 되는 영역이다.
if [ -d "$HARNESS_TMP" ] && [ -n "$(ls -A "$HARNESS_TMP" 2>/dev/null || true)" ]; then
  echo "[janitor] ${HARNESS_TMP}/ 안에 잔여 아티팩트가 있습니다:"
  find "$HARNESS_TMP" -maxdepth 2 -mindepth 1 -print | sed 's/^/  - /'
  FOUND=1
  if [ "$MODE" = "--clean" ]; then
    rm -rf "${HARNESS_TMP:?}"/*
    echo "[janitor] ${HARNESS_TMP}/ 내용을 삭제했습니다 (재생성 가능한 검증용 산출물이므로 --clean 실행 자체가 확인으로 간주됨)."
    FOUND=0
  fi
else
  echo "[janitor] ${HARNESS_TMP}/ 는 비어있거나 없습니다 — 이상 없음."
fi

# 2) 레거시 패턴 — .harness-tmp/ 도입 이전 관례(.venv_<name>, venv/)나, 위치를 잘못 잡아
#    저장소 루트에 직접 생성된 임시 아티팩트. 사용자의 실제 작업물일 가능성을 배제할 수 없으므로
#    --clean 모드에서도 자동 삭제하지 않고 "발견 사실 + 삭제 확인 필요"만 안내한다 (규칙 K 5번).
LEGACY_HITS="$(find . -maxdepth 1 \( -iname ".venv_*" -o -iname "venv" \) -not -path "./.git" 2>/dev/null || true)"
if [ -n "$LEGACY_HITS" ]; then
  echo "[janitor] 저장소 루트에 레거시 패턴의 임시 아티팩트로 보이는 항목이 있습니다 (자동 삭제 안 함 — 규칙A/K5):"
  printf '%s\n' "$LEGACY_HITS" | sed 's/^/  - /'
  echo "[janitor] 실제 검증용 임시 산출물이 맞는지 확인한 뒤, 맞다면 사람이 직접 삭제하거나 .harness-tmp/로 옮기세요."
  FOUND=1
fi

# 3) 커밋 직전 상태 참고용 — git status에 걸리는 미추적 대용량 디렉터리가 있는지 힌트만 제공.
UNTRACKED_DIRS="$(git status --porcelain=v1 --untracked-files=all 2>/dev/null | awk '$1=="??"{print $2}' | grep -E '^(\.venv|venv/|.*\.sqlite3$)' || true)"
if [ -n "$UNTRACKED_DIRS" ]; then
  echo "[janitor] git status 기준 미추적 상태의 venv/DB 패턴 파일:"
  printf '%s\n' "$UNTRACKED_DIRS" | sed 's/^/  - /'
  FOUND=1
fi

if [ "$FOUND" -eq 0 ]; then
  echo "[janitor] 잔여 임시 아티팩트 없음 — 다음 단계 진행 가능."
  exit 0
fi

echo "[janitor] 잔여 아티팩트가 발견되었습니다. 위 목록을 확인하세요 (--clean은 .harness-tmp/ 안만 정리합니다)."
exit 1
