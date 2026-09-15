# UNIT-04 테스트 결과서 — 규제 대응 공통 컴포넌트 (면책 배너 / 금지표현 가이드라인 / 기준시각 표기)

## 1. 개요
- 테스트 대상: 단위(Unit) — UNIT-04 `frontend/` 신규 스캐폴딩 + REQ-006/007/008/009/010 구현
- 테스트 유형: 단위(06-unit-tester)
- 테스트 목적: 5단계(`docs/harness/units/unit-04-note.md`)의 자체 보고를 신뢰하지 않고, REQ-006~010(규칙 I 대상, 9단계 미반영 시 Critical 취급) 각각의 인수 조건(AC-1~AC-5)이 실제 코드/렌더링 결과로 재현되는지 독립적으로 검증한다. 코디네이터가 지정한 5개 중점 확인 사항(면책 배너 실렌더링, 금지어 다른 케이스 재현, 기준시각 배지 서버값 그대로 표시 여부 및 목업 검증 방식, REQ-009 grep 검증의 충분성 판단·보강, 백엔드 회귀)을 전부 다룬다.
- 관련 산출물: `docs/harness/units/unit-04-note.md`(입력 계약, AC-1~AC-5), `docs/harness/02-planning.md` §4-1(REQ-006~010), `docs/harness/03-system-design.md` §3-4/§4-1/§6-1/§6-4, `docs/harness/04-ux-design.md` §2-0/§2-5/§2-6/§4, `services/public_api/schemas/envelope.py`(`DISCLAIMER_TEXT`/`DataFreshness`), `frontend/` 전체
- 테스트 수행자(에이전트): 06-unit-tester
- 테스트 일시: 2026-09-15

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - REQ-007(면책 배너 상시 노출) — 실제 `npm run build`/`npm run start` 렌더링 HTML 기준 재현
  - REQ-008(금지표현 CI 강제) — 5단계가 확인한 "추천 종목입니다" 외에 4개의 다른 금지어 + 임의 구간화 패턴을 독립적으로 각각 주입해 재현, 금지어 목록과 04-ux-design.md §2-6 대조표 전수 대조
  - REQ-006(데이터 기준시각 표기 컴포넌트) — 코드 레벨 자체계산 여부 확인 + 실제 렌더링(임시 QA 라우트)으로 4개 prop 조합 검증
  - REQ-009(사용자 식별 파라미터 부재) — 5단계의 grep 검증 방식의 한계를 판단하고, 실제 HTTP 요청(Authorization 헤더/쿠키/추가 쿼리파라미터)으로 응답 불변성을 블랙박스로 재검증
  - REQ-010(결제/광고 SDK 부재) — `frontend/package.json`/`requirements*.txt` 재검색
  - 백엔드 회귀 — `ruff check .`, `pytest tests/unit`
  - 프론트엔드 정적 분석 회귀 — `npm run lint`, `npx tsc --noEmit`
- 제외 범위(Out-of-Scope) 및 사유:
  - 실제 브라우저(Chrome/Safari 등)·Lighthouse/axe 기반 시각적 접근성 검증(배너 스크롤 고정 체감, 200% 확대 시 줄바꿈 체감, 포커스 링 육안 확인) — 이 환경은 headless curl/HTML 정적 분석만 가능하다. 대신 CSS 소스(`position: sticky`, `overflow-wrap: break-word`, `white-space: normal`, `text-overflow` 부재)와 컴파일된 CSS 청크를 직접 대조해 근거를 확보했다(§4 TC-009). 실제 브라우저/axe 검증은 note §3-1이 이미 명시한 잔존 리스크이며 §7에 재기재한다.
  - `DataFreshnessBadge`의 실 API 연결 검증 — 아직 어떤 화면도 이 컴포넌트를 사용하지 않는다(코드 전체에서 `DataFreshnessBadge`를 import하는 곳이 `DataFreshnessBadge.tsx` 자신 외에 없음, `Grep` 확인). UNIT-06~08이 실제로 연결한 뒤 재검증이 필요하다(note §3-2와 동일 결론).
  - CI 파이프라인(`automation/github-actions-harness.yml`)에 프론트엔드 빌드 잡 추가 — 이번 유닛 범위 아님(note §3-3과 동일 결론, §7에 리스크로 재기재).
  - REQ-001~004 실제 화면 콘텐츠, `GlobalNav` — UNIT-05~08 범위(note §0 명시).

## 3. 테스트 환경
- 실행 환경: Windows 10, Node.js v24.18.0, npm 11.16.0, Next.js 16.3.5(Turbopack), React 19.3.0, TypeScript 6.0.3(strict), Python(백엔드 회귀용, 버전은 리포지토리 anaconda 환경), `pytest`/`ruff`는 리포지토리 `requirements-dev.txt` 고정.
- 테스트 데이터: `frontend/src/content/copy.ko.json`(운영 데이터 그대로), AC-2 검증용 `DataFreshness` mock 객체 4종(정상/지연/`freshness=null`/`session_close_at=null`, unit-04-note.md §7 AC-2 원문과 동일한 값), REQ-008 검증용 임의 주입 문자열 5종("매수신호", "손실보전", "수익보장", "PER 상위 20% 구간", "확실한" — 5단계가 이미 확인한 "추천 종목입니다"와 겹치지 않게 의도적으로 선정).
- 전제 조건: `frontend/node_modules` 설치 완료(5단계 산출물 그대로 재사용, 재설치 없음), 로컬 PostgreSQL 불필요(이 유닛의 백엔드 회귀 대상 3개 엔드포인트는 FastAPI `TestClient` + DI 오버라이드로 DB 없이 테스트 가능).

## 4. 테스트 케이스 및 결과

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-001 | 백엔드 정적 분석 회귀 | 변경 없음(UNIT-04는 백엔드 미변경) | `python -m ruff check .` | 전부 통과 | `All checks passed!` | Pass | AC 외 회귀 확인 목적(코디네이터 지시 5) |
| TC-002 | 백엔드 단위테스트 회귀 | 동일 | `python -m pytest tests/unit -q` | 전부 통과, 신규 실패 없음 | `79 passed, 1 warning`(경고는 `httpx` deprecation, 기존부터 존재) | Pass | UNIT-01~03의 79건 전부 회귀 없음 |
| TC-003 | 프론트엔드 ESLint | `frontend/` 의존성 설치됨 | `npm run lint` | 0 error / 0 warning | 출력에 오류/경고 없음(빈 결과) | Pass | |
| TC-004 | TypeScript strict 컴파일 | 동일 | `npx tsc --noEmit` | 오류 없음 | 오류 없음(출력 없음) | Pass | |
| TC-005 | 프로덕션 빌드(정상 상태) | copy.ko.json 원본 상태 | `npm run build` | `prebuild`(금지어 린트) 통과 → `next build` 성공 → 라우트 3개(`/`,`/_not-found`,`/about`) 정적 생성 | 로그와 동일하게 재현됨(`금지표현 검사 통과 (검사 파일 11개)` → `Compiled successfully` → 3개 라우트) | Pass | note §4 재현 확인(자체 보고 신뢰 안 하고 독립 실행) |
| TC-006 | REQ-007 — `/` 실제 렌더 HTML에 배너 존재 | `npm run build && npm run start -p 4321` | `curl -s http://localhost:4321/` 후 HTML에서 `class="disclaimer-banner"` 및 정확한 문장 검색 | `<div class="disclaimer-banner" role="note" ...>` 존재, 내부에 "이 서비스는 투자자문업 등록 사업자가 아니며, 제공되는 정보는 투자 조언이 아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다." 정확히 포함 | 정확히 일치하는 마크업/문구 확인(§4 원문 HTML 캡처) | Pass | AC-1 불릿1 |
| TC-007 | REQ-007 — `/about` 실제 렌더 HTML에도 배너 존재 | 동일 서버 기동 상태 | `curl -s http://localhost:4321/about` 후 동일 검사 | `/`와 동일한 배너 마크업이 `/about`에도 존재(RootLayout 공통 적용 증거) | 동일 마크업 확인 | Pass | "모든 페이지"가 실제로 최소 2개 라우트에서 증명됨(3번째 라우트 `/_not-found`는 페이지 콘텐츠가 없어 검사 대상에서 제외) |
| TC-008 | REQ-007 — 닫기 버튼 부재 | TC-006/007 HTML 확보 | `grep -o "닫기\|close\|Close\|CLOSE"` 실행 | 매칭 0건 | 매칭 0건(빈 출력) | Pass | `button` 태그 자체가 배너 안에 없음도 HTML 구조로 확인(단순 텍스트에 `<button`이 없음) |
| TC-009 | REQ-007 — 말줄임 미사용 | TC-006/007 HTML + 컴파일된 CSS 청크 확보 | (1) HTML에서 리터럴 `"..."` 검색 (2) `.next/static/chunks/*.css`에서 `.disclaimer-banner__text` 규칙 확인 | HTML에 `...` 없음, CSS에 `text-overflow`/`nowrap` 없이 `white-space: normal; overflow-wrap: break-word`만 존재 | HTML 매칭 0건, CSS 규칙 `overflow-wrap:break-word;white-space:normal;margin:0;font-size:13px;line-height:1.5` 확인(`text-overflow` 없음) | Pass | 컴파일된(사용자가 실제 받는) CSS로 확인 — 소스 CSS만 본 것이 아님 |
| TC-010 | REQ-007 — 배너/푸터 문구와 백엔드 `DISCLAIMER_TEXT` 문자 단위 일치 | 없음 | Python 스크립트로 `envelope.py`의 `DISCLAIMER_TEXT`와 `copy.ko.json`의 `disclaimer.banner`/`disclaimer.footerFull`을 각각 문자열 등가 비교 | 3개 문자열이 완전히 동일 | `banner == backend`: True, `footer == backend`: True | Pass | 5단계 note의 "MATCH" 주장을 스크립트로 재실행해 독립 재현(터미널 인코딩상 한글이 깨져 보이지만 in-memory UTF-8 비교 결과는 True로 확정) |
| TC-011 | REQ-007 — 푸터 이중 노출 | TC-006 HTML | HTML에서 `class="site-footer"` 내부 텍스트 확인 | 면책 전문 + 데이터 출처 고지 + "원본 시세를 그대로 제공하지 않는다" 문구 존재 | 3개 문구 전부 `<footer class="site-footer">` 안에 존재 확인 | Pass | |
| TC-012 | REQ-007 — `/about` 6개 섹션 제목 | TC-007 HTML | HTML에서 `<h2>` 6개 텍스트 추출 | "이 서비스는 무엇인가요", "투자자문업 등록 여부", "데이터 지연 및 기준시각", "데이터 가공 원칙", "데이터 출처", "문의" 순서대로 존재 | 6개 전부 정확한 문구·순서로 확인 | Pass | |
| TC-013 | REQ-006 — 정상 케이스 텍스트 정확도 | 임시 QA 라우트(`frontend/src/app/qa-freshness-temp/page.tsx`, 검증 후 즉시 삭제) + `npm run build && npm run start -p 4322` | `freshness={market:"KRX", trade_date:"2026-09-11", session_close_at:"2026-09-11T15:30:00+09:00", generated_at:"2026-09-12T07:10:00+09:00", is_latest_trading_day:true, expected_last_trading_day:"2026-09-11", staleness_note:null}`로 렌더 후 `curl`로 텍스트 조합 확인 | "국내증권시장(KRX) 기준 2026-09-11 15:30 마감 데이터 · 2026-09-12 07:10 갱신" 정확히 일치(공백/구두점 포함) | HTML 텍스트 노드 결합 결과 정확히 일치 | Pass | AC-2 불릿1 — 5단계는 이 렌더링을 직접 수행한 로그가 note §4에 없었음(TS 컴파일만 확인). 6단계가 최초로 실제 렌더 검증 수행 |
| TC-014 | REQ-006 — 지연 케이스, 색상 비의존 경고 | 동일 | `is_latest_trading_day:false, staleness_note:"예상보다 1영업일 지연된 데이터입니다"`로 렌더 | `staleness_note` 텍스트가 `role="status"`인 `<p>`에 그대로 노출(색상 전용 아님, 스크린리더가 읽을 수 있는 텍스트 노드) | `<p class="data-freshness-badge__warning" role="status"><span aria-hidden="true">⚠</span> 예상보다 1영업일 지연된 데이터입니다</p>` 확인 | Pass | AC-2 불릿2. `aria-hidden` 아이콘과 별개로 텍스트가 실제 DOM 텍스트 노드임을 확인(스크린리더 접근성 요건 충족) |
| TC-015 | REQ-006 — `freshness=null` 예외 없음 | 동일 | `freshness={null}`로 렌더, HTTP 상태코드 확인 | 크래시 없음(200), "데이터 기준시각을 확인하는 중입니다" 표시 | HTTP 200, 해당 문구 정확히 렌더 | Pass | AC-2 불릿3 |
| TC-016 | REQ-006 — `session_close_at=null` 대체 표시 | 동일 | `session_close_at: null`(나머지 정상 케이스와 동일)로 렌더 | 예외 없이 `trade_date`("2026-09-11")로 대체 표시 | "국내증권시장(KRX) 기준 2026-09-11 마감 데이터 · 2026-09-12 07:10 갱신" — `trade_date`로 정상 대체됨, 크래시 없음 | Pass | AC-2 불릿4 |
| TC-017 | REQ-006 — 자체 계산 금지 코드 리뷰 | `DataFreshnessBadge.tsx`, `formatKst.ts` 소스 | `formatKstDateTime` 호출부 전수 확인, `Date.now()`/인자 없는 `new Date()` 사용 여부 검색 | 모든 시각 포맷 호출이 서버가 내려준 ISO 문자열(`freshness.session_close_at`/`freshness.generated_at`)만 인자로 사용, 클라이언트 현재시각을 참조하는 코드 없음 | 확인됨 — `formatKstDateTime(freshness.session_close_at)`, `formatKstDateTime(freshness.generated_at)` 2곳뿐이며 둘 다 props 값만 사용 | Pass | AC-2 마지막 불릿. `formatKst.ts`도 `new Date(iso)`로 인자를 항상 요구(인자 생략 불가한 함수 시그니처) |
| TC-018 | REQ-006 — (AC 범위 밖, 위험도 기반 추가) 잘못된 ISO 문자열 입력 시 예외 처리 | `formatKstDateTime` 단독 실행(Node REPL) | `formatKstDateTime("")`, `formatKstDateTime("not-a-date")` 호출 | AC에 명시는 없으나, 최소한 페이지 전체를 크래시시키지 않아야 함(방어적 처리 기대) | 둘 다 `RangeError: Invalid time value`로 즉시 throw됨. 이 함수는 try/catch 없이 컴포넌트 렌더 본문에서 직접 호출되므로, 백엔드가 어떤 이유로든(버그/스키마 드리프트) 빈 문자열이나 형식이 깨진 ISO 값을 `generated_at`/`session_close_at`에 담아 보내면 `DataFreshnessBadge`를 사용하는 페이지 전체가 렌더링 중 예외로 죽는다 | **Fail(결함)** | DEF-001로 등록(§6). 현재는 dead code(어디서도 import되지 않음)라 배포된 화면에 영향 없음 — UNIT-06~08 연결 전 반드시 해결 필요 |
| TC-019 | REQ-008 — 정상 상태 린트 통과 | `copy.ko.json` 원본 | `npm run lint:copy` | exit 0, "금지표현 검사 통과" 출력 | `금지표현 검사 통과 (검사 파일 11개).`, exit 0 | Pass | AC-3 불릿1. `npm run lint:copy`라는 명명된 스크립트로 직접 실행(단순 `node scripts/...` 직접 호출이 아님) |
| TC-020 | REQ-008 — 금지어 "매수신호" 독립 재현 | 없음 | `copy.ko.json`에 "매수신호" 임시 주입 → `node scripts/lint-forbidden-copy.mjs` → 원복 → 재실행 | exit 1, 파일 경로/줄번호/금지어 출력 → 원복 후 exit 0 | `...:34 — 금지어 "매수신호"`, exit 1 → 원복 후 `금지표현 검사 통과`, exit 0 | Pass | 5단계가 확인한 "추천 종목입니다"와 다른 용어로 독립 재현(코디네이터 지시 2) |
| TC-021 | REQ-008 — 금지어 "손실보전" 독립 재현 | 없음 | 동일 절차 | exit 1 + 정확한 위치·용어 출력 → 원복 후 exit 0 | `...:34 — 금지어 "손실보전"`, exit 1 → 원복 후 통과 | Pass | |
| TC-022 | REQ-008 — 금지어 "수익보장" 독립 재현 | 없음 | 동일 절차 | 동일 | `...:34 — 금지어 "수익보장"`, exit 1 → 원복 후 통과 | Pass | |
| TC-023 | REQ-008 — 임의 구간화 패턴 "PER 상위 20% 구간" 독립 재현 | 없음 | 동일 절차 | 리터럴 문자열이 아니라 정규식 패턴(`FORBIDDEN_PATTERNS`)으로 잡혀야 함 | `...:34 — 금지어 "PER/PBR 임의 구간화 표현(백분위 방식과 불일치)"`, exit 1 → 원복 후 통과 | Pass | 04-ux-design.md §2-6 마지막 행(percentile 불일치) 매핑 확인 |
| TC-024 | REQ-008 — 금지어 "확실한" 독립 재현 | 없음 | 동일 절차 | 동일 | `...:34 — 금지어 "확실한"`, exit 1 → 원복 후 통과 | Pass | |
| TC-025 | REQ-008 — `npm run build`가 금지어 발견 시 완전 중단 | 없음 | `copy.ko.json`에 "매수신호" 주입 후 `npm run build` 전체 실행(단축 스크립트가 아니라 실제 build 명령) | `prebuild` 단계에서 실패해 `next build`(Compiled/Route 생성 로그)가 전혀 출력되지 않아야 함 | `prebuild` 실패 메시지만 출력되고 "Compiled successfully"/"Route (app)" 등 `next build`의 어떤 로그도 나타나지 않음, `npm run build` 전체 exit 1 → 원복 후 재실행 시 정상적으로 `next build`까지 완주 | Pass | AC-3 불릿3 |
| TC-026 | REQ-008 — 금지어 목록 대조표 전수 대조 | `04-ux-design.md` §2-6, `lint-forbidden-copy.mjs` | 표의 좌측 컬럼 7개 행을 `FORBIDDEN_TERMS`/`FORBIDDEN_PATTERNS`와 1:1 대조 | 7개 행 전부 리터럴 또는 정규식으로 커버되어야 함 | 7행 전부 커버 확인: ①"추천 종목/목록"→"추천"(부분일치로 포괄, "TOP 추천주"도 "추천" 포함이라 함께 커버), ②"매수/매도 신호"→4개 리터럴("매수 신호"/"매수신호"/"매도 신호"/"매도신호") 정확 매핑, ③"수익보장/손실보전/원금보장"→3개 리터럴 정확 매핑, ④"지금 사세요/매수 타이밍"→2개 리터럴 정확 매핑, ⑤"베스트 종목"→리터럴 정확 매핑, ⑥"PER 상위 20% 구간"→정규식 `(PER\|PBR)\s*상위\s*\d+\s*%\s*구간` 매핑, ⑦"확실한/안전한 조건"→2개 리터럴 정확 매핑 | Pass | AC-3 불릿4. 갭 없음 확인 |
| TC-027 | REQ-008 — (AC 범위 밖, 위험도 기반 추가) 물리적 줄바꿈으로 금지어 우회 가능성 | 없음 | `frontend/src/lib/`에 백틱 멀티라인 문자열로 "손실보\n전"(중간에 실제 줄바꿈)을 담은 임시 `.ts` 파일 생성 → 린트 실행 → 파일 삭제 → 재실행 | 스캐너가 파일 전체 내용이 아니라 물리적 줄 단위로 검사하므로, 용어가 줄바꿈으로 분리되면 탐지에 실패할 위험이 있음 | 실제로 탐지 실패: "금지표현 검사 통과 (검사 파일 12개)"로 **위반을 통과시킴**(exit 0) → 파일 삭제 후 재실행하면 원래대로 11개 파일로 통과 | **Fail(결함)** | DEF-002로 등록(§6). 현재 실제 카피 리소스(`copy.ko.json`)는 전부 단일 라인 JSON 문자열이라 이 경로로 실제 위반이 발생한 사례는 없음(즉각적 REQ-008 미반영은 아님). 다만 "CI가 반드시 잡는다"는 설계 의도(03-system-design §6-4)에 구조적 공백이 있어, 향후 `.tsx` 안에 여러 줄 JSX 텍스트/템플릿 리터럴로 카피를 작성하면 우회될 수 있음 |
| TC-028 | REQ-009 — 정적 코드 검토, 사용자 식별 파라미터 부재 | `services/public_api/api/*.py` | `stocks.py`/`calendar.py`/`health.py`의 모든 `Query(...)` 선언 목록화 | `user_id`/`holding_price`/`quantity`/`account`/`token` 등 없어야 함 | `stocks.py`: `query`, `market`만 존재. `calendar.py`: `market`, `as_of`만 존재. `health.py`: 파라미터 없음. 개인식별/개인화 파라미터 0건 | Pass | AC-4 불릿1. 5단계와 동일한 결론이나, 6단계가 직접 3개 파일을 다시 읽어 재확인(재인용 아님) |
| TC-029 | REQ-009 — 정적 코드 검토, 헤더/쿠키 분기 부재 | `services/public_api/main.py` | 미들웨어/`Request` 객체 사용처 전수 확인 | 헤더/쿠키를 읽어 응답을 분기하는 코드가 없어야 함 | `main.py`에 등록된 미들웨어 없음, `Request` 매개변수는 FastAPI 예외 핸들러 시그니처 요구사항으로만 존재하며 실제로 헤더/쿠키를 읽는 코드는 없음 | Pass | AC-4 불릿2 |
| TC-030 | REQ-009 — **(보강, 코디네이터 지시 4)** 블랙박스 동일성 검증 | FastAPI `TestClient`, DI로 `get_stock_search_repository` 오버라이드 | 동일한 `query=삼성`에 대해 (a) 헤더/쿠키 없음, (b) `Authorization: Bearer fake-token-123` + 쿠키 `session_id`/`user_id` 포함 두 가지 요청을 보내 응답 바디를 비교 | 두 응답이 완전히 동일해야 함(요청자 식별 정보가 응답에 영향을 주지 않음을 실제 HTTP 계층에서 증명) | `r1.json()['data'] == r2.json()['data']` → `True`, 둘 다 200 | Pass | 5단계의 grep 기반 정적 검증은 "코드에 그런 코드가 없다"만 증명하고 "실제로 요청자를 구분하지 않는다"는 런타임 사실을 증명하지 못한다(코드가 grep 대상 밖의 방식—예: FastAPI 미들웨어 스택 최상위, ASGI 레벨—으로 개인화할 가능성을 배제 못함). 이번 TC-030으로 런타임 동일성을 직접 증명해 grep 검증의 한계를 보강함 |
| TC-031 | REQ-009 — (경계값) 알 수 없는 쿼리파라미터(`user_id`) 첨부 시 무시 여부 | 동일 | `GET /api/v1/stocks?query=삼성&user_id=999` 요청 | FastAPI가 정의되지 않은 파라미터를 무시하고 정상 응답해야 함(개인화 시도가 있어도 응답에 반영되지 않음) | 200, 응답 데이터가 파라미터 없는 요청과 동일 | Pass | REQ-009의 "불특정 다수 대상 동일 정보 제공" 원칙이 악의적/실수로 개인 식별 파라미터를 보내도 깨지지 않음을 확인 |
| TC-032 | REQ-010 — 프론트엔드 결제/광고 SDK 부재 | `frontend/package.json` | `dependencies`/`devDependencies`를 `stripe`/`iamport`/`toss`/`kakaopay`/`adsense`/`admob`/`paypal`/`coupang` 키워드로 검색 | 매칭 없음 | 매칭 없음(No files found) | Pass | AC-5 |
| TC-033 | REQ-010 — 백엔드 결제/광고 SDK 부재 | `requirements.txt`/`requirements-dev.txt` | 동일 키워드 검색 | 매칭 없음 | 매칭 없음 | Pass | AC-5 |

> 정상 경로(TC-005~007, TC-013, TC-019, TC-028~029, TC-032~033), 경계값(TC-009, TC-016, TC-026, TC-031), 예외 입력(TC-015, TC-018, TC-027, TC-020~025 금지어 주입)을 모두 포함했다. 동시성/부하, 권한 경계(로그인·역할 기반 접근제어)는 이 서비스에 인증 자체가 없으므로(REQ-009/REQ-016 Out-of-Scope) 해당 없음.

## 5. 커버리지
- 커버리지 지표: `unit-04-note.md` §7의 인수 조건(AC-1~AC-5) 전체 불릿을 1:1로 테스트 케이스에 매핑함 — AC-1(6개 불릿) → TC-006~012(7건, 불릿5는 이중노출까지 나눠 TC-011로 별도 확인), AC-2(5개 불릿) → TC-013~017(5건 1:1), AC-3(4개 불릿) → TC-019/020~024/025/026(4개 불릿 전부 커버, 금지어는 5종으로 확장), AC-4(2개 불릿) → TC-028~031(2건 1:1 + 보강 2건), AC-5(1개 항목) → TC-032~033(프론트/백엔드 분리 확인). AC 불릿 커버리지 100%.
- 커버되지 않은 부분과 사유: §2 제외 범위에 명시한 4가지(실 브라우저/접근성 도구, `DataFreshnessBadge` 실 데이터 연결, CI 파이프라인 프론트엔드 잡, REQ-001~004 화면)는 이번 유닛의 AC 문면 밖이거나 후속 유닛/인프라 작업 범위라 커버하지 않았다. 이는 note가 이미 자인한 리스크와 동일하며, 5단계의 "만들지 않았다"는 서술을 그대로 받아들이지 않고 직접 grep으로 미사용(dead code)임을 재확인했다(§4 TC-013 비고).

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도(Critical/High/Medium/Low) | 상태(Open/Fixed/Deferred) | 조치 내용 |
|----|------|-----------|-----------------------------------|----------------------------|-----------|
| DEF-001 | `formatKstDateTime()`이 빈 문자열/형식이 깨진 ISO 문자열을 받으면 `RangeError: Invalid time value`를 던진다. `DataFreshnessBadge`가 이 함수를 try/catch 없이 렌더 본문에서 직접 호출하므로, 백엔드가 어떤 이유로든(스키마 드리프트, 직렬화 버그) `generated_at`/`session_close_at`에 빈 값·깨진 값을 담아 보내면 이 컴포넌트를 쓰는 화면 전체가 렌더링 예외로 크래시한다. | `frontend/`에서 `node -e "..."`로 `formatKstDateTime('')`/`formatKstDateTime('not-a-date')`를 직접 호출(§4 TC-018). 둘 다 즉시 `RangeError` throw. | Medium | Open | 미조치. 현재 `DataFreshnessBadge`는 어떤 화면에서도 import되지 않는 dead code라 지금 당장 REQ-006 미반영으로 이어지지는 않지만, UNIT-06~08이 이 컴포넌트를 실 API 응답에 연결하기 전에 반드시 방어 코드(try/catch 또는 값 유효성 검사 후 대체 문구)를 추가해야 한다. 5단계 또는 UNIT-06~08 담당 유닛으로 재작업 요청. |
| DEF-002 | `frontend/scripts/lint-forbidden-copy.mjs`가 파일을 물리적 줄(line) 단위로 스캔하기 때문에, 금지어가 실제 줄바꿈으로 분리되어 있으면(예: 템플릿 리터럴/멀티라인 JSX 텍스트 안의 "손실보\n전") 탐지하지 못하고 빌드를 통과시킨다. | `frontend/src/lib/`에 백틱 멀티라인 문자열로 "손실보\n전"을 담은 임시 `.ts` 파일을 만들고 `node scripts/lint-forbidden-copy.mjs` 실행(§4 TC-027) → "금지표현 검사 통과"로 오탐 없이 통과(exit 0), 실제로는 위반. | Medium | Open | 미조치. 현재 실제 카피(`copy.ko.json`)는 전부 단일 라인 JSON 문자열이라 즉시 발생하는 위반 사례는 없다(REQ-008 현재 미반영 아님). 그러나 03-system-design.md §6-4가 "위반 시 빌드 실패"를 CI 게이트의 핵심 보장으로 명시한 만큼, 향후 `.tsx`에 멀티라인 JSX 텍스트/템플릿 리터럴 카피가 추가되면 우회 가능하다. 스캔 로직을 파일 전체 문자열 기준(개행 제거 후 검사) 또는 AST 기반으로 강화하도록 5단계에 재작업 요청 권고. |

- 위 2건 외 결함 없음. TC-001~017, 019~026, 028~033(29건)은 모두 예상 결과와 실제 결과가 일치해 Pass 처리했으며, 각 행의 "실제 결과" 열에 재현 가능한 근거(명령/출력)를 남겼다.

## 7. 리스크 및 잔존 이슈
- **DEF-001/DEF-002는 REQ-006/REQ-008 자체의 "현재 미반영"을 의미하지 않는다** — 둘 다 아직 실제 화면/실제 카피에 노출되지 않은 잠재적 우회 경로다. 다만 규칙 I 대상 REQ이므로 시간이 지나 UNIT-05~08이 이 컴포넌트/카피 인프라를 확장할 때 이 두 결함이 실제 피해(REQ-006 화면 크래시, REQ-008 금지어 노출)로 이어지지 않도록 **UNIT-06/07/08 착수 전 해결을 권고**한다. traceability.md 비고에 이 의존성을 명시했다.
- 실 브라우저 기반 접근성 검증(sticky 체감, 200% 확대 줄바꿈, 포커스 링 육안 확인)은 여전히 미실시 — note §3-1과 동일한 리스크, headless 환경의 구조적 한계다. UNIT-05(반응형 UI 셸) 또는 별도 접근성 감사에서 재검증 필요.
- `automation/github-actions-harness.yml`에 프론트엔드 빌드 잡이 없어, 로컬에서만 확인된 `npm run build`(및 그 안의 금지어 게이트)가 실제 PR/머지 시점에 자동 강제되지 않는다 — 10단계(배포테스트) 또는 별도 인프라 작업으로 이관(note §3-3과 동일).
- REQ-009 검증은 이번에 3개 엔드포인트에 대해서만 유효하다. UNIT-06~08이 새 엔드포인트(`/stocks/{code}/metrics`, `/screen`, `/market-summary`)를 추가하면 TC-028~031과 동일한 검증(정적 파라미터 검토 + 블랙박스 헤더/쿠키 동일성 테스트)을 반드시 반복해야 한다(note §1-5 "주의" 문단과 동일 결론, 회귀 위험으로 traceability.md에 이미 반영되어 있음).
- 금지어 블랙리스트 방식 자체의 한계(대소문자/공백 변형, 유니코드 정규화, 완전히 새로운 신조어)는 이번 테스트에서 별도로 전수 조사하지 않았다 — 스크립트 자체 주석("화이트리스트가 아니라 블랙리스트 검사")이 이미 이 한계를 인정하고 있으며, 04-ux-design.md §2-6 표가 갱신될 때마다 스크립트도 함께 갱신해야 한다는 원칙이 유지된다.

## 8. 결론 및 판정
- [ ] PASS — 다음 단계 진행 가능
- [x] CONDITIONAL PASS — 조건: **DEF-001(Medium)·DEF-002(Medium) 둘 다 현재 배포된 화면/카피에는 영향이 없어(전자는 dead code, 후자는 현재 카피가 전부 단일 라인) REQ-006/007/008/009/010의 "현재 상태" 반영 여부는 PASS로 판정한다.** 단, (1) UNIT-06/07/08가 `DataFreshnessBadge`를 실 API 데이터에 연결하기 **전에** DEF-001을 해결해야 하고, (2) UNIT-05~08가 카피 리소스에 멀티라인 문자열(템플릿 리터럴/멀티라인 JSX 텍스트)을 도입하기 **전에** DEF-002를 해결해야 한다는 것을 다음 단계(07 통합테스트, 그리고 UNIT-05~08)로 넘기는 명시적 조건으로 건다. 두 결함 모두 Critical/High가 아니라 Medium으로 분류한 근거는 (a) AC-2/AC-3 문면이 요구한 케이스는 전부 실제로 Pass했고, (b) 두 결함 모두 현재 시점에 실제 REQ 미반영으로 이어지지 않았기 때문이다 — 그러나 근거 없이 낮게 평가하지 않기 위해 "왜 지금은 영향이 없는지"를 각 결함 설명에 명시했다.
- [ ] FAIL — 사유 및 재작업 요청 사항:
- REQ-006/007/009/010은 AC 문면 기준 결함 0건으로 **PASS**. REQ-008은 AC 문면 기준 결함 0건(TC-019~026 전부 Pass)이나, AC 범위를 벗어나 위험 기반으로 추가한 TC-027에서 CI 게이트 자체의 구조적 우회 가능성(DEF-002)을 발견해 **CONDITIONAL PASS**로 하향했다. 규칙 I("확신이 없으면 위험을 낮게 평가하지 않는다")에 따라 실제 카피에 영향이 없다는 이유로 결함을 은폐하거나 등급을 낮추지 않고 그대로 기록했다.

## 9. 내부 검증 (최소 2회, `verification-log-template.md` 사용)
- 1차 검증 결과 요약: 작성자 관점 재검토에서 (a) AC-2 검증이 note에는 없던 실제 렌더링 검증이었는지 재확인(있음, TC-013~017), (b) DEF-001/DEF-002의 심각도(Medium) 근거가 "현재는 영향 없음"이라는 이유만으로 안일하게 낮춰진 것은 아닌지 재검토해 "왜 지금은 미반영이 아닌지" 문장을 각 결함 설명에 명시적으로 추가, (c) TC-030(블랙박스 동일성 검증)이 코디네이터가 요구한 "grep 검증의 충분성 판단·보강"에 실제로 대응하는 문장인지 확인해 비고란에 근거 보강.
- 2차 검증 결과 요약: "오늘 처음 이 결과서를 받아본 07 통합테스터" 관점에서 (a) CONDITIONAL PASS 조건이 형식적이지 않고 구체적인 선행조건(UNIT-06~08 착수 전 DEF-001/002 해결)으로 걸려 있는지 재확인(그렇다), (b) DEF-002가 "결함 은폐"로 오독될 여지—AC 범위 밖 테스트에서 발견했다고 축소 서술하지 않았는지 재검토해 §8 결론에 규칙 I 문장을 추가, (c) traceability.md 갱신 문구가 이 문서의 CONDITIONAL PASS/DEF-001/DEF-002 내용과 정확히 대응하는지 상호 대조(반영 완료).
- 검증 로그 파일 경로: `docs/harness/units/verify-log_unit-04-test.md`
