#!/usr/bin/env node
/**
 * REQ-008 금지표현 가이드라인 CI 강제 (03-system-design.md §6-4,
 * 04-ux-design.md §2-6). `npm run build`의 `prebuild` 훅으로 자동 실행되어,
 * 금지어가 하나라도 발견되면 빌드 자체를 실패시킨다(exit code 1).
 *
 * 대조표(04-ux-design.md §2-6)의 왼쪽 컬럼(금지 표현)을 그대로 정규식/리터럴로
 * 옮긴 것이다 — 화이트리스트가 아니라 블랙리스트 검사이므로, 이 목록에 없는
 * 새로운 위반 패턴이 발견되면 §2-6 표와 이 목록을 함께 갱신해야 한다.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const SCAN_ROOT = join(__dirname, "..", "src");
const IGNORE_DIRS = new Set(["node_modules", ".next"]);
const SCAN_EXTENSIONS = new Set([".ts", ".tsx", ".json"]);

// DEF-002 수정으로 검사가 공백 제거 후 비교되므로("매수 신호"/"매수신호"가
// 동일하게 취급됨), 공백 유무 변형을 중복으로 나열하지 않는다 — 아래 각
// 항목은 공백을 어떻게 쓰든 전부 매칭된다.
const FORBIDDEN_TERMS = [
  "추천",
  "매수신호",
  "매도신호",
  "수익보장",
  "손실보전",
  "원금보장",
  "지금 사세요",
  "매수 타이밍",
  "베스트 종목",
  "확실한",
  "안전한 조건",
];

const FORBIDDEN_PATTERNS = [
  {
    name: "PER/PBR 임의 구간화 표현(백분위 방식과 불일치)",
    regex: /(PER|PBR)\s*상위\s*\d+\s*%\s*구간/,
  },
];

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    if (IGNORE_DIRS.has(entry)) continue;
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      walk(fullPath, files);
    } else if (SCAN_EXTENSIONS.has(extname(entry))) {
      files.push(fullPath);
    }
  }
  return files;
}

const WHITESPACE_RE = /\s/;

// DEF-009(unit-04-test.md TC-050 계열) 대응: 이 스캐너는 파일을 텍스트
// 그대로 읽을 뿐 JS 파서가 아니므로, 소스 코드에 "실제 개행 문자"가 아니라
// "개행을 나타내는 이스케이프 시퀀스"가 백슬래시+문자 형태의 리터럴 텍스트로
// 들어있으면(예: `"손실보\n전"`의 소스 텍스트는 실제로는 백슬래시(1글자)와
// n(1글자) 두 개의 평범한 문자다) 아래 WHITESPACE_RE가 이를 공백으로 인식하지
// 못해 탐지를 우회당한다. \n/\r/\t 이스케이프와 공백류를 나타내는 \uXXXX
// 유니코드 이스케이프까지 같은 방식으로 "공백류"로 취급해 건너뛴다.
const ESCAPE_WHITESPACE_CHARS = new Set(["n", "r", "t"]);
const WHITESPACE_CODEPOINTS = new Set([0x09, 0x0a, 0x0d, 0x20, 0xa0]);
const HEX4_RE = /^[0-9a-fA-F]{4}$/;

/**
 * DEF-002(unit-04-test.md TC-027) 대응: 예전 구현은 파일을 물리적 줄(line)
 * 단위로 쪼개 검사했기 때문에, 금지어가 실제 줄바꿈으로 분리되면(예: 멀티라인
 * 템플릿 리터럴/JSX 텍스트 안의 "손실보\n전") 탐지를 통과시켰다. 이를 없애기
 * 위해 파일 전체에서 공백류 문자(스페이스/탭/개행/CR)를 전부 제거한 "정규화
 * 문자열"을 만들어 검사한다 — 물리적 줄 경계 자체를 없애 우회 자체가 불가능한
 * 구조로 바꾼 것이다. 정규화 과정에서 원본 문자 위치를 그대로 추적(`indexMap`)해,
 * 정규화 후에도 정확한 원본 줄번호를 리포트할 수 있게 한다.
 *
 * DEF-009 대응: 실제 공백류 문자뿐 아니라, 소스 텍스트상의 JS 이스케이프
 * 시퀀스(백슬래시+n/r/t, 또는 공백류 코드포인트를 가리키는 \uXXXX)도 동일하게
 * 건너뛴다.
 */
function normalizeWithIndexMap(content) {
  const chars = [];
  const indexMap = [];
  let i = 0;
  while (i < content.length) {
    const ch = content[i];

    if (WHITESPACE_RE.test(ch)) {
      i += 1;
      continue;
    }

    if (ch === "\\" && i + 1 < content.length) {
      const next = content[i + 1];
      if (ESCAPE_WHITESPACE_CHARS.has(next)) {
        i += 2;
        continue;
      }
      if (next === "u" && i + 6 <= content.length) {
        const hex = content.slice(i + 2, i + 6);
        if (HEX4_RE.test(hex) && WHITESPACE_CODEPOINTS.has(parseInt(hex, 16))) {
          i += 6;
          continue;
        }
      }
    }

    chars.push(ch);
    indexMap.push(i);
    i += 1;
  }
  return { normalized: chars.join(""), indexMap };
}

function lineNumberAt(content, originalIndex) {
  let line = 1;
  for (let i = 0; i < originalIndex; i += 1) {
    if (content[i] === "\n") line += 1;
  }
  return line;
}

function scanFile(filePath) {
  const content = readFileSync(filePath, "utf-8");
  const { normalized, indexMap } = normalizeWithIndexMap(content);
  const violations = [];

  for (const term of FORBIDDEN_TERMS) {
    // 금지어 자체의 공백도 제거해 대조한다 — "매수 신호"(공백 포함)와
    // "매수신호"(공백 없음) 두 표기를 하나의 로직으로 함께 잡기 위함이며,
    // 정규화된 콘텐츠(공백 없음)와 형태를 맞추기 위해 필요하다.
    const needle = term.replace(/\s+/g, "");
    if (needle.length === 0) continue;

    let fromIndex = 0;
    let idx = normalized.indexOf(needle, fromIndex);
    while (idx !== -1) {
      violations.push({ file: filePath, line: lineNumberAt(content, indexMap[idx]), term });
      fromIndex = idx + 1;
      idx = normalized.indexOf(needle, fromIndex);
    }
  }

  for (const { name, regex } of FORBIDDEN_PATTERNS) {
    const flags = regex.flags.includes("g") ? regex.flags : `${regex.flags}g`;
    const globalRegex = new RegExp(regex.source, flags);
    let match = globalRegex.exec(normalized);
    while (match !== null) {
      violations.push({ file: filePath, line: lineNumberAt(content, indexMap[match.index]), term: name });
      if (globalRegex.lastIndex === match.index) {
        globalRegex.lastIndex += 1; // 0폭 매치 무한루프 방지(현재 패턴엔 없으나 방어적으로 유지)
      }
      match = globalRegex.exec(normalized);
    }
  }

  return violations;
}

const files = walk(SCAN_ROOT);
const allViolations = files.flatMap(scanFile);

if (allViolations.length > 0) {
  console.error("금지표현 가이드라인(REQ-008) 위반이 발견되어 빌드를 중단합니다:\n");
  for (const v of allViolations) {
    console.error(`  ${v.file}:${v.line} — 금지어 "${v.term}"`);
  }
  console.error(
    `\n총 ${allViolations.length}건. docs/harness/04-ux-design.md §2-6 금지 표현 대조표를 참고해 문구를 수정하세요.`
  );
  process.exit(1);
}

console.log(`금지표현 검사 통과 (검사 파일 ${files.length}개).`);
process.exit(0);
