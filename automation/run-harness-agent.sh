#!/usr/bin/env bash
# 실제로 Claude Code CLI를 헤드리스로 실행해 지정한 하네스 단계를 수행시키는 스크립트.
# 사전 준비물 (README.md 참고):
#   - PATH에 `claude` (Claude Code CLI, --agent 플래그를 지원하는 버전) 존재
#   - 인증 완료 (예: ANTHROPIC_API_KEY 환경변수, 또는 CI 러너에 로그인된 claude 세션)
#   - `jq` 또는 `node` 중 하나 (JSON 결과 파싱용)
#   - 이 스크립트는 저장소 루트(ORCHESTRATOR.md, .claude/agents/, templates/ 가 있는 곳)에서 실행해야 함
#
# 사용법:
#   ./automation/run-harness-agent.sh <stage-name> ["추가 지시사항"]
# 예:
#   ./automation/run-harness-agent.sh 06-unit-tester "docs/harness/units/ 를 스캔해서 아직 테스트되지 않은 모든 단위를 처리하라"
#
# 종료 코드:
#   0  = 해당 단계 PASS
#   1  = 해당 단계 FAIL, 또는 claude CLI 자체 오류, 또는 판정 불명
#   75 = 규칙 A(모르면 질문)에 걸려 사람의 응답이 필요해 정지함 — FAIL과 다르게 취급할 것

set -euo pipefail

STAGE="${1:?사용법: run-harness-agent.sh <stage-name> [추가 지시]}"
shift || true
EXTRA_INSTRUCTION="${*:-}"

AGENT_FILE=".claude/agents/${STAGE}.md"
if [ ! -f "$AGENT_FILE" ]; then
  echo "[harness] 에러: ${AGENT_FILE} 가 없습니다. STAGE 이름(예: 06-unit-tester)을 확인하세요." >&2
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "[harness] 에러: claude CLI를 찾을 수 없습니다. PATH를 확인하거나 CI 이미지에 설치하세요." >&2
  exit 1
fi

# 에이전트 frontmatter의 `tools:` 줄을 그대로 --allowedTools 값으로 사용한다.
ALLOWED_TOOLS="$(sed -n 's/^tools:[[:space:]]*//p' "$AGENT_FILE" | head -n1)"
if [ -z "$ALLOWED_TOOLS" ]; then
  echo "[harness] 에러: ${AGENT_FILE} 에 tools: frontmatter가 없습니다." >&2
  exit 1
fi

OUT_DIR="docs/harness/_ci-logs"
mkdir -p "$OUT_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT_JSON="${OUT_DIR}/${STAGE}-${TS}.json"

PROMPT=$(cat <<EOF
ORCHESTRATOR.md에 정의된 전역 규칙(A~K)을 반드시 지킨다. 특히 지금은 CI(무인 환경)에서 실행 중이라
사람이 실시간으로 질문에 답할 수 없다는 점을 명심한다.

- 규칙 A에 해당하는 상황(모르면 물어봐야 하는 상황)을 만나면, 절대로 추측해서 진행하지 말고
  표준출력 첫 줄에 정확히 "HARNESS_BLOCKED:" 를 출력한 뒤 그 다음 줄부터 질문 목록을 적고 즉시 멈춘다.
  이 경우 어떤 산출물도 PASS로 표시하지 않는다.
- 정상적으로 끝까지 완료했다면, 표준출력 첫 줄에 정확히 "HARNESS_DONE: PASS" 또는 "HARNESS_DONE: FAIL" 을
  출력한다 (해당 단계의 최종 판정과 반드시 일치해야 한다).
- 규칙 K(중단-안전 정리): 검증용 venv/임시 DB/설정 파일은 반드시 .harness-tmp/ 하위에만 만들고,
  완료 직전 정리 후 git status가 깨끗함을 결과서 7절(Teardown)에 남겨야 PASS로 표시할 수 있다.
  헤드리스 실행이 중간에 죽으면(CLI 프로세스 강제 종료 등) 다음 실행 시작 시 automation/harness-janitor.sh로
  잔여물부터 확인한다.

지금 수행할 단계: ${STAGE}
${EXTRA_INSTRUCTION}
EOF
)

set +e
claude -p "$PROMPT" \
  --agent "$STAGE" \
  --output-format json \
  --allowedTools "$ALLOWED_TOOLS" \
  --permission-mode dontAsk \
  --permission-prompts none \
  > "$RESULT_JSON"
CLI_EXIT=$?
set -e

if [ "$CLI_EXIT" -ne 0 ]; then
  echo "[harness] claude CLI 자체가 비정상 종료(exit ${CLI_EXIT})했습니다. 원문: ${RESULT_JSON}" >&2
  cat "$RESULT_JSON" >&2 || true
  exit 1
fi

RESULT_TEXT=""
if command -v jq >/dev/null 2>&1; then
  RESULT_TEXT="$(jq -r '.result // empty' "$RESULT_JSON" 2>/dev/null || true)"
elif command -v node >/dev/null 2>&1; then
  RESULT_TEXT="$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('${RESULT_JSON}','utf8')).result||'')}catch(e){}" 2>/dev/null || true)"
else
  echo "[harness] 경고: jq/node가 없어 JSON을 파싱할 수 없습니다. 원문을 그대로 확인하세요: ${RESULT_JSON}" >&2
  exit 1
fi

echo "$RESULT_TEXT"

FIRST_LINE="$(printf '%s\n' "$RESULT_TEXT" | head -n1)"

if printf '%s' "$FIRST_LINE" | grep -q "^HARNESS_BLOCKED:"; then
  echo "[harness] ${STAGE} 단계가 사람의 판단이 필요해 정지했습니다. 위 질문을 확인하고 응답한 뒤 다시 실행하세요." >&2
  exit 75
fi

if printf '%s' "$FIRST_LINE" | grep -q "^HARNESS_DONE: PASS"; then
  exit 0
fi

echo "[harness] ${STAGE} 단계가 FAIL로 종료됐거나 판정을 확인할 수 없습니다. 원문: ${RESULT_JSON}" >&2
exit 1
