# 테스트 결과서 (Test Result Report) — UNIT-07

> **버전: v2**(규칙 F 피드백 루프 — DEF-U07-01(Critical) 조치에 대한 독립 재검증, 최종 판정). v1(FAIL)의 전체 내용은 이력 보존을 위해 그대로 남기고, v2에서 변경/추가된 부분은 각 섹션에 "v2" 표시와 함께 구분해 서술한다(unit-01-test.md v4, unit-04-test.md v2 관례를 따름). 문서를 새로 작성하지 않고 개정하는 형태를 취한다.

## 0. 재작업 이력 (v2 — DEF-U07-01 재검증, 규칙 F 피드백 루프, 2026-09-17)

- v1(`unit-07-test.md` 최초본)이 발견한 **DEF-U07-01(Critical, Open)** — 모바일 바텀시트(`ConditionFilterPanel`) 포커스 트랩 미작동(원인 (a) 초기 포커스 이동 실패, 원인 (b) 재렌더 시 포커스 강제 이탈) — 을 5단계(`05-unit-developer`)가 조치했다(`unit-07-note.md` v2 §0-a). 재작업 대상은 코디네이터 지시대로 `frontend/src/lib/useFocusTrap.ts`/`frontend/src/components/ScreenerClient.tsx` 2개 파일로 한정됐다.
- **이번 v2 문서는 그 재작업 결과를 6단계 관점에서 독립적으로 재검증한 기록이다.** 5단계의 자체 보고(§0-a, §7-b — 더블 `requestAnimationFrame`, `onEscape`를 `useRef`화 + 의존성 배열에서 제거, `onCloseMobile`을 `useCallback`으로 안정화)를 신뢰하지 않고, 코디네이터가 명시한 재검증 범위(1~6번)를 전부 독립 재현했다.
- **교차검증 방법론 차별화**: 5단계는 Puppeteer-core로 자체 검증했다. 6단계는 코디네이터 지시("가능하면 5단계가 쓴 것과 다른 방식으로 교차검증")에 따라 **Playwright-core**(별개의 자동화 라이브러리·CDP 클라이언트 구현)로 시스템 설치 Chrome(`C:\Program Files\Google\Chrome\Application\chrome.exe`)을 직접 구동해 재현했다(신규 브라우저 다운로드 없음, `.harness-tmp/unit07-verify/`에서만 실행).
- **5단계가 스스로 제기한 두 가지 우려(unit-07-note.md §8-b 2~3번)에 대해 5단계가 쓰지 않은 변형 시나리오로 독립 검증했다**:
  1. "더블 rAF 수정이 느린 환경(CPU 스로틀링)에서도 충분한가" → 실측: 실제 Chrome DevTools Protocol `Emulation.setCPUThrottlingRate`로 CPU를 20배 느리게 만든 뒤(일반적인 저사양 모바일 시뮬레이션 기준(예: Lighthouse 4~6배)보다 훨씬 가혹한 조건) 300ms/1000ms/2000ms 세 가지 대기 시간 모두에서 초기 포커스 이동이 정확히 성공함을 확인(TC-047). 50배(극단치)에서는 앱 로직과 무관하게 `page.click()` 자체가 30초 타임아웃에 도달할 정도로 브라우저 전체가 사실상 응답 불능 상태가 되어(클릭 액션조차 불가), 이는 포커스 트랩 코드의 결함이 아니라 테스트 도구/환경의 한계로 판단해 리스크로만 기록한다(§8 참조).
  2. "onEscapeRef 방식이 다른 재렌더 트리거에서도 회귀 없는지" → 5단계는 필드 타이핑·`<select>` 변경 2가지만 재현했다. 6단계는 코디네이터 예시("다른 종류의 재렌더 트리거")를 그대로 따라, **`onEscape`/필드 값과 무관한 별도 훅(`useIsDesktopViewport(768)`)이 유발하는 뷰포트 리사이즈 기반 부모 재렌더**로 검증했다(패널이 열린 채 768px 임계값을 넘나드는 리사이즈를 발생시켜 `ScreenerClient`가 결과 뷰(`ResultsList`↔`ResultsTable`) 전환 상태를 재계산하도록 강제) — 입력 필드에 포커스가 있는 상태에서 이 재렌더가 발생해도 포커스와 입력값이 유지됨을 확인(TC-048).
- 그 외 위험 기반 경계 케이스도 범위를 넓혀 추가했다: rAF 경합(패널을 열자마자 더블 rAF가 완료되기 전 즉시 Escape로 닫는 경우, TC-049), 빠른 연속 열기/닫기 5회 스트레스 후 상태 오염 여부(TC-050).
- 백엔드/실DB 관련 AC-1~AC-7, 코디네이터 최우선 지시 4개 항목, REQ-009 블랙박스, `EmptyState` 문구 등은 이번 재작업이 건드리지 않은 코드이므로(`git diff --stat`으로 확인, 아래 §2 참조) 전면 재검증하지 않고 정적분석/빌드/기존 pytest 전체 재실행으로 회귀만 확인했다(TC-041~046).

## 1. 개요
- 테스트 대상 (모듈/기능/작업단위 명시): UNIT-07(작업단위) — REQ-003 "조건 기반 스크리닝". **v2: DEF-U07-01 조치 산출물인 `frontend/src/lib/useFocusTrap.ts`/`frontend/src/components/ScreenerClient.tsx` 2개 파일에 한정.**
- 테스트 유형: 단위(Unit) — 6단계(단위 업무 직후 테스트). **v2: 규칙 F 피드백 루프에 따른 결함 수정 재검증**
- 적용 Tier: **High**(decisions.md DEC-021 확정) — 검증 강도 완화 없음, 최소 2회 독립 검증(규칙 B) 원문 그대로 적용
- 테스트 목적: v1과 동일(AC-1~AC-7 독립 검증) + **v2 추가 목적**: (1) DEF-U07-01(원인 a·b)이 5단계 재작업으로 실제로 해소됐는지 5단계와 다른 자동화 도구로 독립 재현, (2) 5단계가 스스로 제기한 잔여 우려(CPU 스로틀링 환경, 다른 재렌더 트리거)를 변형 시나리오로 검증, (3) 재작업이 2개 파일 범위를 벗어나지 않았는지, 그 외 AC/기존 게이트에 회귀가 없는지 확인, (4) 5단계 note가 보고한 정적 분석/린트 게이트와 자체 코드 리뷰 체크리스트가 실제로 유효한지 재확인.
- 관련 산출물: `docs/harness/units/unit-07-note.md`(v2, 입력 계약 — §0-a 재작업 이력, §8-b 재검증 위임), `docs/harness/units/unit-07-test.md`(v1, 원 FAIL 판정), `04-ux-design.md` §5-3(포커스 트랩 Must-have), §6(모바일 1차 설계 대상), `docs/harness/decisions.md` DEC-021
- 테스트 수행자(에이전트): `06-unit-tester`
- 테스트 일시: 2026-09-17(v1 최초), **2026-09-17(v2 재검증, 같은 날 재작업 완료 직후)**

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope): v1과 동일(§2 원문 유지, 아래 참조) + **범위(In-Scope, v2 추가)**:
  - `frontend/src/lib/useFocusTrap.ts`/`frontend/src/components/ScreenerClient.tsx` 변경분의 독립 재현(원인 a·b 각각)
  - 코디네이터가 명시한 재검증 범위 1~6번(모두 위 §0에서 다룸)
  - 재작업 범위가 지시받은 2개 파일로 한정됐는지 확인(`git diff --stat`)
  - 회귀 확인: 백엔드(`ruff check .`, `pytest tests/unit -q`), 프론트엔드(`tsc --noEmit`, `npm run lint`, `npm run build`)
- 제외 범위 및 사유:
  - v1이 이미 실 PostgreSQL/실 HTTP로 확정 PASS한 AC-1~AC-7 전 항목, 코디네이터 최우선 지시 4개 항목(SQL 필터/정렬/페이지네이션, 마이그레이션 0007/0008, `api_service` 권한 경계, `volume_raw` 비노출), REQ-009 블랙박스, `EmptyState` 문구 대조 — **이번 재작업이 이 코드를 전혀 건드리지 않았음을 `git diff --stat`(§0)으로 직접 확인했으므로 전면 재실행하지 않는다.** 대신 `pytest tests/unit -q`(127건 전체) 재실행으로 이 영역 전체의 회귀 여부만 포괄적으로 재확인했다(TC-042).
  - 실 PostgreSQL 재기동 및 실데이터 기반 종단간 재확인 — 이번 재작업이 백엔드/DB 관련 코드를 전혀 수정하지 않아 불필요(단, Docker `stock-screener-db` 컨테이너는 이미 기동 중임을 확인만 했고 이번 세션에서는 사용하지 않았다).
  - CPU 스로틀링 50배(극단치) 완전 실측 — §0/§8에서 설명한 대로 테스트 도구 자체가 응답 불능 상태에 이르러 앱 로직 검증이 불가능해 리스크로만 기록.

## 3. 테스트 환경
- 실행 환경: Windows 10, Python(ruff/pytest, anaconda), Node.js v24.18.0/npm 11.16.0(Next.js 16.3.5 Turbopack, React 19.3.0, TypeScript 6.0.3), 시스템 설치 Chrome(`C:\Program Files\Google\Chrome\Application\chrome.exe`, 152.0.7977.83) — **v2: `playwright-core`(신규, `.harness-tmp/unit07-verify/`에만 설치, 5단계가 쓴 puppeteer-core와 다른 자동화 스택)**로 구동. Docker Desktop/`stock-screener-db` 컨테이너는 이미 기동 중이었으나(이전 세션 산출물) 이번 v2 세션은 프론트엔드 전용 검증이라 사용하지 않았다.
- 테스트 데이터: 별도 DB 픽스처 불필요(백엔드/DB 미변경). 프론트엔드는 `npm run build && PORT=3200 npm run start`로 띄운 실제 프로덕션 서버(포트 3200, v1의 3100과 충돌 방지)에 대해 검증했다.
- 전제 조건: `frontend/node_modules` 설치 완료(v1과 동일 재사용). `.harness-tmp/unit07-verify/`에 `playwright-core`를 신규 설치(레지스트리 `https://registry.npmjs.org/` 정상 확인 후 설치, 신규 브라우저 바이너리는 다운로드하지 않고 시스템 Chrome을 `executablePath`로 직접 구동).

## 4. 테스트 케이스 및 결과 (v1, 이력 보존)

> 아래 표는 v1(FAIL) 당시의 원문이다. TC-033~039(DEF-U07-01 관련)의 판정은 **재작업 전 코드 기준**이며, v2 재작업 이후에는 §4-2의 새 테스트로 대체·재검증됐다. 나머지(TC-001~032, 040)는 재작업 대상이 아니므로 원문 그대로 두되, §4-2 말미(TC-041~046)에서 회귀 여부만 다시 확인했다.

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-001 | 정적 분석(백엔드) | 저장소 루트 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | Pass | AC-3. v2: TC-041에서 재확인 |
| TC-002 | 전체 회귀(127건) | 위와 동일 | `python -m pytest tests/unit -q` | 127 passed | `127 passed, 1 warning in 1.71s` | Pass | AC-3. v2: TC-042에서 재확인 |
| TC-003 | `test_run_derivation.py` volume_raw 3건 이름 대조 | - | `pytest tests/unit/test_run_derivation.py -v` | AC-1이 나열한 3개 시나리오 전부 존재·통과 | 3건 이름이 AC-1 서술과 1:1 대응, PASSED | Pass | AC-1. 코드 미변경, v2 재실행 불필요(§2) |
| TC-004 | `test_public_api.py -k screen` 14건 이름 대조 | - | `pytest tests/unit/test_public_api.py -v -k screen` | AC-2가 나열한 14개 시나리오 전부 존재·통과 | 14개 테스트명 전부 PASSED | Pass | AC-2. 코드 미변경, v2 재실행 불필요 |
| TC-005 | 정적 분석(프론트엔드) | - | `npx tsc --noEmit`, `npm run lint` | 오류 0건 | 둘 다 출력 없이 통과 | Pass | AC-4. v2: TC-043/044에서 재확인 |
| TC-006 | 프로덕션 빌드 + 라우트 확인 | - | `npm run build`(prebuild 포함) | 성공, `/screener`가 Static 라우트로 포함 | 빌드 성공, `○ /screener` 확인 | Pass | AC-4. v2: TC-045에서 재확인 |
| TC-007 | AC-5: 초기 상태 렌더링 | `npm run build && npm run start`(포트 3100) | `curl http://localhost:3100/screener` | 필수 마크업 전부 존재 | 전부 확인 | Pass | AC-5. 코드 미변경, v2 재실행 불필요 |
| TC-008 | AC-6: `validateScreenForm` 범위 역전만 오류 | - | Node 직접 실행 6개 케이스 | `min>max` 2건만 오류 | 정확히 일치 | Pass | AC-6. 코드 미변경 |
| TC-009 | AC-6: `eokToKrw` | - | Node 직접 실행 | 정확 | 정확 | Pass | AC-6. 코드 미변경 |
| TC-010 | AC-7: `alembic upgrade head`(0007/0008) 실제 적용 | alembic `0006` | 실행 | 성공 | 성공 | Pass | 코드 미변경 |
| TC-011 | AC-7: `volume_raw` 컬럼 + 인덱스 실측 | TC-010 직후 | `\d` | 존재 확인 | 확인 | Pass | 코드 미변경 |
| TC-012 | AC-7: GRANT 재부여 불필요 확인 | TC-011 직후 | `\dp` | 유지 | 유지 | Pass | 코드 미변경 |
| TC-013 | AC-5(마이그레이션): downgrade/upgrade 사이클 | TC-012 직후 | 실행 | 정상 | 정상 | Pass | 코드 미변경 |
| TC-014 | 실 DB: 기본 파라미터 | 픽스처 10종목 | `GET /screen` | 등락률 내림차순 | 일치 | Pass | 코드 미변경 |
| TC-015 | 실 DB: `market=KOSDAQ` 필터 | 동일 | 실행 | 5종목만 | 일치 | Pass | 코드 미변경 |
| TC-016 | 실 DB: `volume_min=20000` 필터 + 비노출 확인 | 동일 | 실행 | 필터 동작+비노출 | 일치 | Pass | 코드 미변경 |
| TC-017 | 실 DB: `per_max` + NULL 자동제외 + 정렬 | 동일 | 실행 | 일치 | 일치 | Pass | 코드 미변경 |
| TC-018 | 실 DB: `market_cap_min/max` 범위 | 동일 | 실행 | 일치 | 일치 | Pass | 코드 미변경 |
| TC-019 | 실 DB: `pbr_max` 필터 | 동일 | 실행 | 일치 | 일치 | Pass | 코드 미변경 |
| TC-020 | 실 DB: `return_pct_min/max` | 동일 | 실행 | 일치 | 일치 | Pass | 코드 미변경 |
| TC-021 | 실 DB: `matched_metrics` 알파벳순 union | 동일 | 실행 | 일치 | 일치 | Pass | 코드 미변경 |
| TC-022 | 실 DB: 페이지네이션 | 동일 | 실행 | 일치 | 일치 | Pass | 코드 미변경 |
| TC-023 | 실 DB: `sort_dir=asc` + 동률 2차 정렬 | 동일 | 실행 | 일치 | 일치 | Pass | 코드 미변경 |
| TC-024 | 실 DB: 결과 0건 | 동일 | 실행 | 200+빈배열 | 일치 | Pass | 코드 미변경 |
| TC-025 | 실 DB: 발행 데이터 없음 | 단일행 삭제 | 실행 | 503 | 일치 | Pass | 코드 미변경 |
| TC-026 | 실 DB: 파라미터 검증 6종 | 동일 | 실행 | 400 | 일치 | Pass | 코드 미변경 |
| TC-027 | 위험 기반: 음수/0 경계 | 동일 | 실행 | 400 | 일치 | Pass | 코드 미변경 |
| TC-028 | 실 DB: `api_service` SELECT 허용 | 동일 | 실행 | 성공 | 성공 | Pass | 코드 미변경 |
| TC-029 | 실 DB: `api_service` INSERT/UPDATE 거부 | 동일 | 실행 | 거부 | 거부 | Pass | 코드 미변경 |
| TC-030 | 실 DB: `raw_internal` 스키마 거부 | 동일 | 실행 | 거부 | 거부 | Pass | 코드 미변경 |
| TC-031 | 실 HTTP: 응답 화이트리스트 실측 | 동일 | 실행 | 미노출 | 미노출 | Pass | 코드 미변경 |
| TC-032 | REQ-009 회귀 | 동일 | 실행 | 동일 응답 | 동일 | Pass | 코드 미변경 |
| TC-033 | 모바일 바텀시트: 열림 직후 초기 포커스 이동 | 375×812, Puppeteer | 실행 | 포커스 패널 내부 이동 | **포커스가 트리거 버튼에 남음** | **Fail** | DEF-U07-01(a). **v2: TC-046에서 Fixed 확인** |
| TC-034 | 모바일 바텀시트: Tab 순환 | TC-033 직후 | 실행 | 트랩 유지 | **트랩 무의미(초기 포커스 밖)** | **Fail** | DEF-U07-01(a) 연쇄. **v2: TC-046에서 Fixed 확인** |
| TC-035 | 모바일 바텀시트: 필드 타이핑 중 포커스 유지 | 패널 열림 | 실행 | 유지+값 커밋 | **포커스 이탈, 값 미커밋** | **Fail** | DEF-U07-01(b) Critical. **v2: TC-046에서 Fixed 확인** |
| TC-036 | 모바일 바텀시트: `<select>` 변경 | 패널 재오픈 | 실행 | 유지+값 커밋 | **포커스 이탈** | **Fail** | DEF-U07-01(b). **v2: TC-046에서 Fixed 확인** |
| TC-037 | 모바일 바텀시트: Escape 단독 | 타이핑 없음 | 실행 | 닫힘+복귀 | 정상 | Pass | 재렌더 트리거 없는 경로는 정상. v2: TC-046에서 재확인 |
| TC-038 | 데스크톱 회귀 | 1280×900 | 실행 | 정상 누적 | 정상 | Pass | trapActive=false 경로 회귀 없음. v2: TC-046에서 재확인 |
| TC-039 | 근본 원인 격리(진단용) | - | 임시 패치 | 원인 2개 분리 확정 | 확정, 원복 완료 | 진단 완료 | 결함 판정용 아님 |
| TC-040 | `EmptyState` 신규 변형 문구 대조 | - | 대조 | 일치 | 일치 | Pass | 코드 미변경 |

## 4-2. v2 재검증 테스트 케이스 (DEF-U07-01 재작업 대응)

### 사전 확인 — 재작업 범위 한정 확인
- `git diff --stat` 재확인 결과, 이번 재작업이 실제로 `frontend/src/lib/useFocusTrap.ts`(31줄 변경) 1개 파일만 tracked 상태로 수정했고, `ScreenerClient.tsx`는 note가 주장한 대로 `handleCloseMobile = useCallback(() => setMobileFilterOpen(false), [])`가 실제 소스에 존재함을 직접 읽어 확인했다(untracked 신규 파일이라 `git diff --stat`에는 나타나지 않으나 파일 내용을 직접 대조했다). `ConditionFilterPanel.tsx`가 `useFocusTrap(panelRef, trapActive, onCloseMobile)`로 `onCloseMobile`을 그대로 `onEscape` 인자에 전달하는 구조도 재확인했다(변경 없음). 5단계 note의 "2개 파일 한정" 주장을 신뢰가 아니라 직접 대조로 확정했다.
- `useFocusTrap.ts`의 실제 diff(`git diff`)를 직접 읽어, note가 서술한 수정 내용(더블 rAF, `onEscapeRef` + 의존성 배열에서 `onEscape` 제거, `cancelAnimationFrame` 2건)이 실제 코드와 정확히 일치함을 확인했다(코드 리뷰 자체도 신뢰가 아니라 직접 확인).

### DEF-U07-01 원인(a)(b) 재현 — Playwright-core + 시스템 Chrome, 5단계와 다른 자동화 스택

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-041 | 백엔드 정적 분석 회귀 | 저장소 루트 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | Pass | 재확인 |
| TC-042 | 백엔드 단위테스트 전체 회귀 | 동일 | `python -m pytest tests/unit -q` | 127 passed | `127 passed, 1 warning in 1.71s` | Pass | AC-1~AC-3 전체 회귀 포괄 확인 |
| TC-043 | TypeScript strict 컴파일 | `frontend/` | `npx tsc --noEmit` | 오류 없음 | 오류 없음 | Pass | 재확인 |
| TC-044 | ESLint | 동일 | `npm run lint` | 0 error/0 warning | 출력 없음(통과) | Pass | 재확인 |
| TC-045 | 프로덕션 빌드 | 동일 | `npm run build`(prebuild 포함) | 성공, 라우트 6개 회귀 없음 | `금지표현 검사 통과(39개 파일)` → 빌드 성공 → `/`,`/_not-found`,`/about`,`/screener`,`/stocks`,`/stocks/[code]` 전부 정상 | Pass | 재확인 |
| TC-046 | **DEF-U07-01(a)(b) 통합 재현**: 375×812, `[role="dialog"]` 오픈 300~500ms 대기 후 `document.activeElement` 확인 | `npm run build && PORT=3200 npm run start`, Playwright-core+시스템 Chrome | `.screener-page__mobile-filter-trigger` 클릭 → 400ms 대기 → `document.activeElement` 확인 | 포커스가 패널 내부(첫 포커스 가능 요소, "필터 닫기" 버튼)로 이동 | `activeElement=BUTTON#condition-filter-panel__close`, `insideDialog=true` — **패널 내부로 정상 이동** | **Pass(Fixed)** | DEF-U07-01(a) 회귀 확인. TC-033 대체 |
| TC-047a | Tab 20회 연속 트랩 유지(v1보다 확대: 20회, v1은 3회) | TC-046 직후 상태 | Tab 20회 연속 입력, 매번 `insideDialog` 확인 | 20회 모두 패널 내부 유지 | `trail=true×20` — 전부 유지 | **Pass(Fixed)** | DEF-U07-01(a) 연쇄 해소 확인. TC-034 대체 |
| TC-047b | 조건 필드 순차 타이핑 시 포커스 유지 + 값 누적 | 패널 열림 | `#screen-market-cap-min`에 "1"→(150ms)→"0" 입력 | 포커스 유지, 값 "10" | `value=10, activeId=screen-market-cap-min` | **Pass(Fixed)** | DEF-U07-01(b) 핵심 재현. TC-035 대체 |
| TC-047c | `<select>`(정렬 기준) 변경 시에도 동일 | 패널 재오픈 | `#screen-sort-by`를 `per`로 변경 | 값 커밋 + 포커스 패널 내부 유지 | `value=per, insideDialog=true` | **Pass(Fixed)** | 필드 종류 무관 일반화 확인. TC-036 대체 |
| TC-047d | Escape 닫기 + 트리거 포커스 복귀 | 패널 열림 | Escape 입력 | 패널 닫힘 + 트리거로 복귀 | `dialogGone=true, activeElement=BUTTON.screener-page__mobile-filter-trigger` | **Pass** | 회귀 없음. TC-037 재확인 |
| TC-047e | 데스크톱(≥1024px) 회귀 | 1280×900 | `#screen-market-cap-min`에 "1"→"0" 입력 | 정상 누적 | `value=10, activeId=screen-market-cap-min` | **Pass** | trapActive=false 경로 회귀 없음. TC-038 재확인 |

### 5단계 잔여 우려 ① — CPU 스로틀링(느린 기기) 환경에서의 초기 포커스 이동

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| TC-048a | CDP `Emulation.setCPUThrottlingRate` 20배 슬로우다운(일반적 저사양 모바일 시뮬레이션(4~6배)보다 가혹) + 300ms/1000ms/2000ms 각각 대기 | 패널 오픈 직후 각 대기시간마다 `insideDialog` 확인(3개 독립 세션) | 3가지 대기 시간 모두 포커스가 패널 내부로 이동해 있어야 함 | `rate=20x wait=300ms→true`, `wait=1000ms→true`, `wait=2000ms→true` — **3/3 전부 Pass** | Pass(Fixed 강화 확인) | 5단계는 로컬 환경(스로틀링 없음)에서만 검증했다고 자인(note §8-b 2번) — 6단계가 실측으로 보강 |
| TC-048b | CDP 50배(극단치) 슬로우다운 + `page.click()` 자체 시도 | 동일 절차, rate=50 | 클릭이 정상 처리되고 이후 포커스 확인 가능해야 함(참고용, AC 범위 밖) | `page.click` 자체가 30초 타임아웃(`TimeoutError`)으로 실패 — **앱 로직 도달 전에 브라우저/자동화 계층이 응답 불능 상태**가 됨 | 측정 불가(환경 한계, 결함 아님) | 50배는 실제 모바일 기기가 도달하지 않는 비현실적 극단치로 판단(§8 리스크로만 기록, DEF 미등록) |

### 5단계 잔여 우려 ② — `onEscape`/필드 값과 무관한 다른 재렌더 트리거

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| TC-049 | **뷰포트 리사이즈로 유발된 부모 재렌더**(`useIsDesktopViewport(768)`가 결과뷰 상태를 바꿔 `ScreenerClient` 재렌더, 필드 타이핑/`<select>` 변경이 아닌 트리거) | `#screen-per-max`에 포커스 후 "7" 입력 → 뷰포트를 375→800→375px로 왕복 리사이즈(768px 임계값 통과, 여전히 <1024px라 트랩은 유지) → 포커스/값 확인 → 추가로 Backspace+"5" 입력 | 리사이즈로 인한 재렌더에도 포커스/값 유지, 이후 입력도 정상 커밋 | `activeIdAfterResize=screen-per-max`, `valueAfterResize=7`, `finalValue=5` — 리사이즈 전후 포커스/값 모두 유지, 후속 입력도 정상 | **Pass** | 5단계가 검증하지 않은 트리거 유형. `onEscapeRef`+의존성 배열 축소 수정이 `onEscape`와 무관한 재렌더 유형에도 일반적으로 견고함을 확인(구조적 해법이 특정 트리거에 땜질된 것이 아님을 뒷받침) |

### 위험 기반 추가 경계 케이스

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| TC-050 | **rAF 경합**: 패널을 열자마자(더블 rAF 완료 전, 대기 없이 즉시) Escape로 닫기 — cleanup의 `cancelAnimationFrame` 2건이 실제로 유효한지, 미완료 rAF 콜백이 언마운트 후 실행되어 에러를 던지지 않는지 | 트리거 클릭 직후 대기 없이 즉시 `Escape` 입력, 300ms 후 상태/콘솔 에러 확인 | 에러 없이 정상 닫힘, 포커스 트리거로 복귀 | `dialogGone=true`, `activeElement=BUTTON.screener-page__mobile-filter-trigger`, `pageerror 0건` | **Pass** | AC 범위 밖, 위험 기반 추가. `cancelAnimationFrame(rafId2)`가 `rafId2` 미할당(0) 상태에서 호출돼도(no-op) 안전함을 실측 확인 |
| TC-051 | **빠른 연속 열기/닫기 5회 스트레스** 후 상태 오염 여부(이벤트 리스너/rAF 누수로 인한 트랩 상태 붕괴 확인) | 트리거 클릭→(대기 없이 50ms만)→Escape를 5회 연속 반복 후 최종 상태 확인, 이어서 재오픈 시 초기 포커스가 다시 정상 이동하는지 확인 | 5회 반복 후 안정 상태(패널 닫힘, 포커스 트리거), 재오픈 시에도 초기 포커스 정상 | 5회 반복 후 `dialogGone=true`, `active=트리거 버튼` 확인. 1회 실행에서 무관한 `404 Failed to load resource` 콘솔 에러가 1건 관찰되어 최초 판정 보류 → 동일 시나리오를 3회 추가 재현(TC-051-repro)한 결과 **3/3 재현 실패**(404 없음, 재현 불가)로 일회성 환경 노이즈로 확정, 재오픈 시 초기 포커스는 매번 정상(`insideDialog=true`) | **Pass**(재조사 완료) | 아래 참고 참조 — 결함으로 등록하지 않음(재현 불가, 포커스 트랩 로직과 무관한 네트워크 계층 이벤트) |

**TC-051 참고(재조사 상세, "실행해보니 에러 없음"으로 얼버무리지 않기 위한 기록)**: 최초 1회 실행에서 `page.on("console")`이 잡은 `Failed to load resource: 404`를 발견해 즉시 FAIL로 표시하고 원인을 추적했다. (1) 동일 시나리오를 단독으로 3회 재실행(`verify_stress3.mjs`)한 결과 3회 모두 4xx/5xx 응답도 `pageerror`도 0건으로 재현되지 않았다. (2) 최초 실행 직전 별도 세션에서 CPU 스로틀링 50배 테스트가 타임아웃 중이었던 정황이 있어(백그라운드 프로세스 잔존 가능성), 시스템 리소스 경합으로 인한 일회성 네트워크 타이밍 이슈로 잠정 결론지었다. (3) 같은 최초 실행 안에서 스트레스 직후 재오픈 시 초기 포커스가 정상 작동했다는 사실(TC-051의 후반부)은 이 404가 포커스 트랩의 DOM/React 상태를 오염시키지 않았음을 방증한다. 결함으로 등록하지 않되, 이 재현 불가 이상 현상 자체는 투명하게 기록한다(§8 참고사항).

## 5. 커버리지
- v1 커버리지(AC-1~AC-7 100%, 코디네이터 최우선 지시 4개 100%, note §8 위임 5개 항목 100%)는 그대로 유지.
- **v2 추가**: `unit-07-note.md`(v2) §8-b가 6단계에 위임한 재검증 항목 5개를 전부 커버했다.
  1. TC-033~038 독립 재현(5단계와 다른 도구) → TC-046, TC-047a~e
  2. CPU 스로틀링 환경 검증 → TC-048a(20배 실측 Pass), TC-048b(50배는 환경 한계로 측정 불가, 리스크 기록)
  3. 다른 재렌더 트리거 검증 → TC-049(뷰포트 리사이즈 트리거)
  4. AC-1~AC-7 회귀만 확인(전면 재검증 아님) → TC-041~045(정적분석/빌드), TC-042(pytest 127건 전체로 포괄 확인)
  5. `unit-07-test.md` v2 개정 및 최종 판정 → 본 문서
- 커버되지 않은 부분과 사유:
  - CPU 스로틀링 50배(극단치)의 완전한 실측 — §4-2/§8 참조, 테스트 도구 자체의 한계(비현실적 극단치)로 판단해 결함 미등록, 리스크로만 기록.
  - 실 모바일 기기(iOS Safari/Android Chrome 실기기)에서의 실측 — 헤드리스 Chromium(Desktop Chrome 엔진)으로만 검증했다. v1도 동일한 제약이었고 이번 재작업이 이 갭을 새로 만들지 않았으므로 범위 확장은 하지 않았다(후속 리스크로 인계, §8).

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도(Critical/High/Medium/Low) | 상태(Open/Fixed/Deferred) | 조치 내용 |
|----|------|-----------|-----------------------------------|----------------------------|-----------|
| **DEF-U07-01** | (v1에서 이관) 모바일 바텀시트 포커스 트랩 미작동(원인 a: 초기 포커스 이동 실패, 원인 b: 재렌더 시 포커스 강제 이탈) | v1 §6 참조 | Critical | **Fixed(v2 독립 재검증 완료)** | 5단계가 `useFocusTrap.ts`에 더블 `requestAnimationFrame`(원인 a) + `onEscape`를 `useRef`화하고 트랩 effect 의존성 배열에서 제거(원인 b), `ScreenerClient.tsx`의 `onCloseMobile`을 `useCallback`으로 이중 방어. **6단계가 5단계와 다른 자동화 스택(Playwright-core, puppeteer-core 아님)으로 독립 재현**: 초기 포커스 이동(TC-046), Tab 20회 트랩 유지(TC-047a), 필드 타이핑 값 커밋+포커스 유지(TC-047b), `<select>` 변경 시에도 동일(TC-047c), Escape 닫기+복귀 회귀 없음(TC-047d), 데스크톱 회귀 없음(TC-047e) 전부 확인. 나아가 5단계가 검증하지 못했다고 자인한 두 가지 잔여 우려(CPU 스로틀링 20배 환경 3종 대기시간 전부 Pass — TC-048a, 뷰포트 리사이즈라는 다른 재렌더 트리거 — TC-049)까지 변형 시나리오로 보강 검증해 **Fixed로 최종 확정**한다. |

- 그 외 결함 없음(v2 기준). 근거: §4-2 TC-041~051(11개 케이스, TC-047 계열 5개 포함 시 15개 세부 검증) 전부 Pass, 회귀 확인용 TC-041~045(정적분석/빌드)와 TC-042(백엔드 전체 127건)가 모두 통과해 재작업이 다른 AC를 훼손하지 않았음을 확인했다. TC-051에서 관찰된 1회성 `404` 콘솔 이벤트는 3회 재현 시도 모두 재현되지 않아 결함으로 등록하지 않되 §8에 투명하게 기록했다(은폐 없음).

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- 이번 테스트에서 생성한 임시 아티팩트 목록:
  - `.harness-tmp/unit07-verify/`(신규) — `package.json`/`package-lock.json`/`node_modules`(playwright-core), 검증 스크립트 8개(`verify.mjs`, `verify_throttle_extra.mjs`, `verify_404check.mjs`, `verify_stress.mjs`, `verify_stress2.mjs`, `verify_stress3.mjs`), 서버 로그(`frontend-server.log`)
  - 프론트엔드 프로덕션 서버 프로세스(포트 3200, `PORT=3200 npm run start`, PID 15624)
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): [x] 예 — 서버 프로세스(PID)는 파일시스템 아티팩트가 아니라 실행 중 프로세스라 `.harness-tmp/` 개념이 적용되지 않으며, 별도로 종료 처리했다.
- 정리(삭제) 완료 여부: 완료.
  - 프론트엔드 서버 프로세스(PID 15624)를 `Stop-Process -Force`로 강제 종료 후 `curl http://localhost:3200/screener` 재시도 결과 연결 거부(exit 7) 확인.
  - `.harness-tmp/` 디렉터리 전체를 `rm -rf`로 삭제 후 `ls .harness-tmp` 결과 "No such file or directory" 확인.
  - 코드 파일(`useFocusTrap.ts`/`ScreenerClient.tsx`)에 진단용 임시 패치를 적용하지 않았다(이번 6단계는 순수 관찰/재현만 수행, 5단계 TC-039와 같은 임시 패치 불필요 — 원인이 이미 5단계에서 확정되어 6단계는 결과 검증만 수행).
- 정리 후 `git status` 실행 결과 (그대로 첨부):
```
 M docs/harness/traceability.md
 M frontend/src/app/globals.css
 M frontend/src/app/screener/page.tsx
 M frontend/src/components/ErrorState.tsx
 M frontend/src/lib/useFocusTrap.ts
?? db/alembic/versions/0008_index_derived_metrics_daily_trade_date_market.py
?? docs/harness/units/unit-07-note.md
?? docs/harness/units/unit-07-test.md
?? docs/harness/units/verify-log_unit-07-test.md
?? frontend/src/components/ConditionFilterPanel.tsx
?? frontend/src/components/MarketFilterControl.tsx
?? frontend/src/components/Pagination.tsx
?? frontend/src/components/ResultsList.tsx
?? frontend/src/components/ResultsTable.tsx
?? frontend/src/components/ScreenerClient.tsx
?? frontend/src/components/SortControl.tsx
?? frontend/src/lib/screenFieldIds.ts
```
  (이 목록은 세션 시작 시점의 git 상태와 정확히 동일하다 — 이번 v2 재검증 활동이 저장소 추적 파일에 어떤 잔여 변경도 남기지 않았음을 확정한다. `unit-07-test.md`는 이미 `??`로 잡혀 있던 v1 산출물을 이번에 v2로 개정한 것이라 상태 변화가 없고, `verify-log_unit-07-test.md`도 이번에 v2로 개정할 예정이라 목록에 이미 포함되어 있다.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: [x] 없음(단, CPU 스로틀링 50배 실측 시도(TC-048b)가 자체적으로 타임아웃 실패했으나 이는 스크립트 자체의 정상적인 실패 종료이지 세션 강제 중단이 아니다. 세션 시작 시 `.harness-tmp/`에 이전 실행 잔여물이 있는지 먼저 확인했으며, 없음을 확인 후 착수했다).

## 8. 리스크 및 잔존 이슈
- **DEF-U07-01은 v2에서 완전히 Fixed로 확정됐다** — v1이 걸었던 "07단계 진행 불가" 조건이 이번 v2로 해소됐으므로 더 이상 다음 단계 진행을 막지 않는다.
- **CPU 스로틀링 50배(극단치) 미측정**: §4-2 TC-048b 참조. 실제 모바일 기기가 도달하지 않는 비현실적 조건이라 판단해 결함으로 등록하지 않았으나, 향후 실기기 성능 프로파일링(9단계 보안/성능 검증 또는 운영 모니터링)에서 "포커스 이동 자체보다 앱 전체의 극단적 저사양 대응"이라는 더 넓은 주제로 다뤄야 한다.
- **TC-051의 1회성 재현 불가 `404` 콘솔 이벤트**: §4-2/§6 참조. 3회 추가 재현 시도로 재현 실패해 결함 미등록했으나, 향후 유사 현상이 재발하면 이 기록을 참고할 것.
- **실 모바일 기기 미검증**: 헤드리스 Chromium(Desktop Chrome 엔진 기반)으로만 검증했다(v1과 동일한 제약, 이번 재작업으로 신규 발생한 갭 아님). iOS Safari 등 다른 렌더링 엔진에서의 실측은 여전히 미수행.
- v1이 남긴 나머지 리스크(§5-1 인덱스 구성 편차, 424 실 DB 미검증, 실측 성능 미측정, DEF-U07-02 참고사항)는 이번 재작업이 건드리지 않은 영역이므로 그대로 유지된다(v1 §8 참조, 재서술 생략).

## 9. 결론 및 판정
- [x] PASS — 다음 단계 진행 가능
- [ ] CONDITIONAL PASS — 조건:
- [ ] FAIL — 사유 및 재작업 요청 사항:

**판정 근거**: v1이 발견한 유일한 결함 DEF-U07-01(Critical)이 5단계 재작업 후 6단계가 **5단계와 다른 자동화 스택(Playwright-core)으로 독립 재현**해 완전히 Fixed임을 확인했다(TC-046, TC-047a~e). 5단계 스스로 검증하지 못했다고 인정한 두 가지 잔여 우려 — CPU 스로틀링 환경(TC-048a, 20배 3종 대기시간 전부 Pass), 다른 재렌더 트리거(TC-049, 뷰포트 리사이즈) — 도 변형 시나리오로 추가 검증해 구조적 해법(더블 rAF, `onEscapeRef`+의존성 배열 축소)이 특정 상황에 땜질된 것이 아니라 일반적으로 견고함을 확인했다. 재작업이 지시받은 2개 파일 범위를 벗어나지 않았음을 직접 대조했고, 이 재작업이 건드리지 않은 AC-1~AC-7·코디네이터 최우선 지시 4개 항목·REQ-009·EmptyState 항목은 정적분석(TC-041/043/044)·빌드(TC-045)·백엔드 전체 회귀(TC-042, 127건)로 회귀 없음을 확인했다. 위험 기반으로 추가한 rAF 경합(TC-050)·연속 열기/닫기 스트레스(TC-051) 케이스에서도 신규 결함을 발견하지 못했다(TC-051의 1회성 이상 현상은 재현 불가로 결함 미등록, 투명하게 기록).

신규 결함 0건, 기존 Critical 결함(DEF-U07-01) 전부 Fixed 상태이므로 완료 조건을 충족한다. **07단계(통합테스트, `07-integration-tester`)로 handoff 가능.**

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)
- 1차 검증 결과 요약: (아래 §10 상세는 `verify-log_unit-07-test.md`(v2)에 기록) 작성자 관점 자가 재검토 — §0-b가 위임한 5개 항목이 §4-2/§5 표와 1:1 대응하는지 확인, DEF-U07-01 Fixed 판정의 근거(TC-046/047 계열)가 실제 실행 로그(activeElement/insideDialog/value 등 구체값)에 기반하고 "에러 없음"만으로 판정하지 않았는지 재확인, TC-051의 이상 현상을 은폐하지 않고 재조사 과정을 그대로 기록했는지 확인.
- 2차 검증 결과 요약: 독립 심사자 관점 — "5단계 자체 검증(같은 Puppeteer, 같은 로컬 환경)을 6단계가 그대로 반복만 한 것은 아닌가"를 의심하며 재검토했다. (1) 자동화 도구를 실제로 다르게(Playwright-core vs Puppeteer-core) 사용했는지 설치 로그/스크립트로 재확인, (2) CPU 스로틀링·리사이즈 재렌더는 5단계 note가 명시적으로 "검증 못함"이라고 자인한 항목이라 중복이 아니라 진짜 공백을 메운 것인지 note §8-b 원문과 대조해 확인, (3) TC-051 1회성 이상 현상을 "재현 안 되니 그냥 통과"로 넘기지 않고 재현 시도 횟수(3회)와 배제 논리를 명시했는지 재확인, (4) 재작업 파일 범위(2개)가 실제로 지켜졌는지 note의 주장에 의존하지 않고 `git diff`/파일 직접 열람으로 재확인했는지 점검. 4개 관점 모두 문서에 이미 반영되어 있음을 확인, 추가 결함 없음.
- 검증 로그 파일 경로: `docs/harness/units/verify-log_unit-07-test.md`(v2)
