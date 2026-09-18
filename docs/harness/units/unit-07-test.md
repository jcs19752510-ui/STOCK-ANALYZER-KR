# 테스트 결과서 (Test Result Report) — UNIT-07

> **버전: v3**(규칙 F 피드백 루프 — UNIT-09 검증 중 발견된 DEF-U09-01(Critical, `services/public_api/main.py`, UNIT-01 소관) 조치에 따른 **CORS 회귀 확인**. UNIT-07 자신의 AC-1~AC-7과 DEF-U07-01(포커스 트랩)은 v2에서 이미 **최종 PASS/Fixed로 확정**되어 있으므로 전면 재검증하지 않는다 — 오케스트레이터 지시 범위와 동일). v1(FAIL)·v2(PASS, DEF-U07-01 Fixed) 전체 내용은 이력 보존을 위해 그대로 남기고, v3에서 추가된 부분은 §4-3/§9(v3 판정)/§10(v3 검증)에 "v3" 표시와 함께 구분해 서술한다. 문서를 새로 작성하지 않고 개정하는 형태를 취한다.

## 0. 재작업 이력 (v2 — DEF-U07-01 재검증, 규칙 F 피드백 루프, 2026-09-17)

- v1(`unit-07-test.md` 최초본)이 발견한 **DEF-U07-01(Critical, Open)** — 모바일 바텀시트(`ConditionFilterPanel`) 포커스 트랩 미작동(원인 (a) 초기 포커스 이동 실패, 원인 (b) 재렌더 시 포커스 강제 이탈) — 을 5단계(`05-unit-developer`)가 조치했다(`unit-07-note.md` v2 §0-a). 재작업 대상은 코디네이터 지시대로 `frontend/src/lib/useFocusTrap.ts`/`frontend/src/components/ScreenerClient.tsx` 2개 파일로 한정됐다.
- **이번 v2 문서는 그 재작업 결과를 6단계 관점에서 독립적으로 재검증한 기록이다.** 5단계의 자체 보고(§0-a, §7-b — 더블 `requestAnimationFrame`, `onEscape`를 `useRef`화 + 의존성 배열에서 제거, `onCloseMobile`을 `useCallback`으로 안정화)를 신뢰하지 않고, 코디네이터가 명시한 재검증 범위(1~6번)를 전부 독립 재현했다.
- **교차검증 방법론 차별화**: 5단계는 Puppeteer-core로 자체 검증했다. 6단계는 코디네이터 지시("가능하면 5단계가 쓴 것과 다른 방식으로 교차검증")에 따라 **Playwright-core**(별개의 자동화 라이브러리·CDP 클라이언트 구현)로 시스템 설치 Chrome(`C:\Program Files\Google\Chrome\Application\chrome.exe`)을 직접 구동해 재현했다(신규 브라우저 다운로드 없음, `.harness-tmp/unit07-verify/`에서만 실행).
- **5단계가 스스로 제기한 두 가지 우려(unit-07-note.md §8-b 2~3번)에 대해 5단계가 쓰지 않은 변형 시나리오로 독립 검증했다**:
  1. "더블 rAF 수정이 느린 환경(CPU 스로틀링)에서도 충분한가" → 실측: 실제 Chrome DevTools Protocol `Emulation.setCPUThrottlingRate`로 CPU를 20배 느리게 만든 뒤(일반적인 저사양 모바일 시뮬레이션 기준(예: Lighthouse 4~6배)보다 훨씬 가혹한 조건) 300ms/1000ms/2000ms 세 가지 대기 시간 모두에서 초기 포커스 이동이 정확히 성공함을 확인(TC-047). 50배(극단치)에서는 앱 로직과 무관하게 `page.click()` 자체가 30초 타임아웃에 도달할 정도로 브라우저 전체가 사실상 응답 불능 상태가 되어(클릭 액션조차 불가), 이는 포커스 트랩 코드의 결함이 아니라 테스트 도구/환경의 한계로 판단해 리스크로만 기록한다(§8 참조).
  2. "onEscapeRef 방식이 다른 재렌더 트리거에서도 회귀 없는지" → 5단계는 필드 타이핑·`<select>` 변경 2가지만 재현했다. 6단계는 코디네이터 예시("다른 종류의 재렌더 트리거")를 그대로 따라, **`onEscape`/필드 값과 무관한 별도 훅(`useIsDesktopViewport(768)`)이 유발하는 뷰포트 리사이즈 기반 부모 재렌더**로 검증했다(패널이 열린 채 768px 임계값을 넘나드는 리사이즈를 발생시켜 `ScreenerClient`가 결과 뷰(`ResultsList`↔`ResultsTable`) 전환 상태를 재계산하도록 강제) — 입력 필드에 포커스가 있는 상태에서 이 재렌더가 발생해도 포커스와 입력값이 유지됨을 확인(TC-048).
- 그 외 위험 기반 경계 케이스도 범위를 넓혀 추가했다: rAF 경합(패널을 열자마자 더블 rAF가 완료되기 전 즉시 Escape로 닫는 경우, TC-049), 빠른 연속 열기/닫기 5회 스트레스 후 상태 오염 여부(TC-050).
- 백엔드/실DB 관련 AC-1~AC-7, 코디네이터 최우선 지시 4개 항목, REQ-009 블랙박스, `EmptyState` 문구 등은 이번 재작업이 건드리지 않은 코드이므로(`git diff --stat`으로 확인, 아래 §2 참조) 전면 재검증하지 않고 정적분석/빌드/기존 pytest 전체 재실행으로 회귀만 확인했다(TC-041~046).

## 0-2. 재검증 이력 (v3 — CORS 회귀 확인, 규칙 F 피드백 루프, 2026-09-18)

- UNIT-09(종목 검색 화면) 6단계 검증 중 UNIT-09 자신의 파일 범위 밖에서 **DEF-U09-01(Critical, Open)** — `services/public_api/main.py`(UNIT-01 최초 작성)에 CORS 미들웨어가 전혀 없어 프론트엔드/백엔드가 다른 오리진일 때 브라우저의 모든 크로스오리진 fetch가 100% 차단됨 — 이 발견됐다(`unit-09-test.md` §8, `decisions.md` DEC-022). `screenApi.ts`(UNIT-07)도 동일한 클라이언트 컴포넌트 fetch 패턴을 쓰므로(`frontend/src/app/screener/page.tsx`에 `"use client"` 존재) 이 결함에 동일하게 노출되어 있었다.
- 5단계가 `services/public_api/main.py`/`core/config.py`에 `CORSMiddleware`/`get_cors_allowed_origins()`를 추가해 조치했다(`unit-01-note.md` v4, `decisions.md` DEC-022). 5단계 자체 확인은 (a) `TestClient` 인프로세스 pytest 4건, (b) 실제 `uvicorn` 서버에 대한 `curl` OPTIONS 프리플라이트 수동 확인에 그쳤고, **UNIT-07/UNIT-09의 실제 헤드리스 브라우저 두 오리진 fetch 재현은 5단계 범위에서 수행되지 않았다**(`unit-01-note.md` §3 "v4 신규" 항목).
- **이번 v3는 오케스트레이터 지시에 따라 이 CORS 회귀만 좁게 확인한다.** AC-1~AC-7·DEF-U07-01(포커스 트랩)은 v2에서 이미 최종 PASS/Fixed로 확정되어 재실행하지 않되, 이번 CORS 수정이 다른 회귀를 일으키지 않았는지는 최소한의 정적분석/빌드/pytest 전체 재실행으로 확인한다(§4-3 TC-106/107).
- 상세 테스트 케이스와 결과는 §4-3, 최종 판정은 §9(v3) 참조.

## 1. 개요
- 테스트 대상 (모듈/기능/작업단위 명시): UNIT-07(작업단위) — REQ-003 "조건 기반 스크리닝". v2: DEF-U07-01 조치 산출물인 `frontend/src/lib/useFocusTrap.ts`/`frontend/src/components/ScreenerClient.tsx` 2개 파일에 한정. **v3: `services/public_api/main.py`/`core/config.py`(UNIT-01 소관 CORS 수정, DEC-022)가 `frontend/src/lib/screenApi.ts`(UNIT-07)에 미치는 영향 — 두 오리진 실제 브라우저 fetch 재현에 한정.**
- 테스트 유형: 단위(Unit) — 6단계(단위 업무 직후 테스트). v2: 규칙 F 피드백 루프에 따른 결함 수정 재검증. **v3: 규칙 F 피드백 루프에 따른 회귀(CORS) 확인 — 전면 재검증 아님.**
- 적용 Tier: **High**(decisions.md DEC-021 확정) — 검증 강도 완화 없음, 최소 2회 독립 검증(규칙 B) 원문 그대로 적용
- 테스트 목적: v1과 동일(AC-1~AC-7 독립 검증) + v2 추가 목적(위 §0 참조) + **v3 추가 목적**: (1) `services/public_api/main.py`/`core/config.py`의 CORS 수정이 실제로 `screenApi.ts`의 크로스오리진 fetch를 차단 없이 통과시키는지 실제 헤드리스 브라우저 두 오리진(프론트 3000번대/백엔드 8000번대, `.env.example` 기본값과 동일한 포트 구성)으로 재현, (2) `get_cors_allowed_origins()` 폴백/쉼표파싱 pytest 4건 독립 재실행 + 다중 오리진 변형 시나리오 1건 추가, (3) 이번 CORS 수정이 UNIT-07의 다른 AC/게이트에 회귀를 일으키지 않았는지 최소 확인.
- 관련 산출물: `docs/harness/units/unit-07-note.md`(v2, 입력 계약), `docs/harness/units/unit-07-test.md`(v1 FAIL, v2 PASS), `docs/harness/units/unit-01-note.md`(v4, CORS 수정), `docs/harness/units/unit-09-test.md`(DEF-U09-01 최초 발견), `docs/harness/decisions.md` DEC-021/DEC-022, `03-system-design.md` §6-3
- 테스트 수행자(에이전트): `06-unit-tester`
- 테스트 일시: 2026-09-17(v1 최초), 2026-09-17(v2 재검증), **2026-09-18(v3, CORS 회귀 확인)**

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope): v1과 동일(§2 원문 유지, 아래 참조) + 범위(In-Scope, v2 추가, 위 §0 참조) + **범위(In-Scope, v3 추가)**:
  - `frontend/src/lib/screenApi.ts`(UNIT-07)가 실제 헤드리스 브라우저에서 프론트(localhost:3000)/백엔드(127.0.0.1:8000) 두 오리진 간 `/screen` fetch를 CORS 차단 없이 수행하고 결과가 실제로 화면에 렌더링되는지 재현
  - `get_cors_allowed_origins()`/`CORSMiddleware` pytest 4건 독립 재실행 + 다중 오리진(쉼표+공백) 변형 시나리오 1건
  - 이번 CORS 수정이 UNIT-07의 다른 AC/게이트에 회귀를 일으키지 않았는지 최소 정적분석/빌드/pytest 전체 재실행 확인
- 제외 범위 및 사유:
  - v1이 이미 실 PostgreSQL/실 HTTP로 확정 PASS한 AC-1~AC-7 전 항목, 코디네이터 최우선 지시 4개 항목(SQL 필터/정렬/페이지네이션, 마이그레이션 0007/0008, `api_service` 권한 경계, `volume_raw` 비노출), REQ-009 블랙박스, `EmptyState` 문구 대조 — 이번 재작업(v2)이 이 코드를 전혀 건드리지 않았음을 `git diff --stat`(§0)으로 직접 확인했으므로 전면 재실행하지 않는다. 대신 `pytest tests/unit -q`(v3 시점 155건 전체) 재실행으로 이 영역 전체의 회귀 여부만 포괄적으로 재확인했다(TC-106).
  - DEF-U07-01(포커스 트랩) 전면 재검증 — v2에서 이미 5단계와 다른 자동화 스택으로 독립 재현해 Fixed로 최종 확정됐고, 이번 v3 CORS 수정이 `useFocusTrap.ts`/`ScreenerClient.tsx`를 전혀 건드리지 않았음을 `git diff`로 확인했으므로 재검증 대상이 아니다(오케스트레이터 지시 범위와 일치 — "UNIT-07의 AC-1~AC-7은 이미 최종 PASS로 확정되어 있으므로 재실행 불필요").
  - 실 PostgreSQL 재기동 및 실데이터 기반 종단간 재확인 — v2와 동일 사유로 불필요. **v3도 DB 계층은 실접속이 아니라 실제 `docker exec ... psql -U postgres`로 읽어온 6행 픽스처를 그대로 복제한 Fake 리포지토리로 대체했다**(자격증명 정책상 `api_service` 실접속 불가 — `unit-09-test.md` §4-a와 동일한 근거, 아래 §3 참조). 이 대체는 CORS 미들웨어가 라우트 핸들러 진입 이전(요청 경로 진입 전) 레벨에서 동작해 DB 계층과 독립적이므로 CORS 판정 자체의 타당성에 영향을 주지 않는다.
  - CPU 스로틀링 50배(극단치) 완전 실측 — v2에서 이미 다룸, 변경 없음.

## 3. 테스트 환경
- 실행 환경: Windows 10, Python(ruff/pytest, anaconda), Node.js v24.18.0/npm 11.16.0(Next.js 16.3.5, React 19.3.0, TypeScript 6.0.3), 시스템 설치 Chrome(`C:\Program Files\Google\Chrome\Application\chrome.exe`) — v2: `playwright-core`로 구동. **v3(신규): `puppeteer-core@23`(`.harness-tmp/cors-regression/`에만 설치, 신규 브라우저 다운로드 없이 시스템 Chrome을 `executablePath`로 직접 구동)로 구동.** Docker `stock-screener-db` 컨테이너(기동 중)에서 `docker exec ... psql -U postgres`로 `public_serving.stock_master` 실 픽스처 6행을 직접 조회해 Fake 리포지토리 데이터로 그대로 복제(자격증명 세션 정책상 `api_service`/`postgres` 계정으로의 직접 TCP 접속·비밀번호 노출 명령은 이번에도 차단됨을 확인 — `unit-09-test.md` §4-a와 동일한 제약).
- 테스트 데이터: **v3**: `public_serving.stock_master` 실 픽스처 6행(005930/000660/005935/900001/900002/900003, UNIT-03/08/09가 이미 적재)을 그대로 복제한 `FakeStockSearchRepository`, `FakeScreenRepository`(2개 종목: 005930/000660), `FakeCalendarRepository`(KRX 마감 15:30 고정)로 실제 `services.public_api.main.app`(UNIT-01 최초 작성, CORS 미들웨어 포함 실물 코드)의 DI 지점(`get_screen_repository`/`get_calendar_repository`)만 오버라이드. `PUBLIC_API_DATABASE_URL`은 사용되지 않는 더미 값으로 주입(오버라이드된 DI가 DB에 접근하지 않으므로 실제로 참조되지 않음).
- 전제 조건: **v3**: 프론트엔드는 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`으로 `npm run build`(프로덕션 빌드) 후 `next start -p 3000 -H localhost`로 기동(포트 3000, `.env.example` 프론트 기본 개발 포트와 동일). 백엔드는 `uvicorn`으로 포트 8000에 기동(`.env.example` 백엔드 기본 포트와 동일). `PUBLIC_API_CORS_ALLOWED_ORIGINS`는 **의도적으로 설정하지 않아** `get_cors_allowed_origins()`의 로컬 기본값(`http://localhost:3000`)이 그대로 적용되는 "기본 구성"을 재현했다 — 오케스트레이터 지시("`.env.example` 기본값과 동일한 구성")와 일치. 5단계 게이트(정적 분석/자체 코드 리뷰) 통과 여부는 `unit-01-note.md` v4 §5/§6에서 확인했고(`ruff check .` All checks passed, `pytest tests/unit -q` 155 passed), 이번 v3가 TC-104/106에서 독립 재확인했다 — 게이트 통과 확인됨, 5단계로 반려할 사유 없음.

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
| TC-033 | 모바일 바텀시트: 열림 직후 초기 포커스 이동 | 375×812, Puppeteer | 실행 | 포커스 패널 내부 이동 | **포커스가 트리거 버튼에 남음** | **Fail** | DEF-U07-01(a). v2: TC-046에서 Fixed 확인 |
| TC-034 | 모바일 바텀시트: Tab 순환 | TC-033 직후 | 실행 | 트랩 유지 | **트랩 무의미(초기 포커스 밖)** | **Fail** | DEF-U07-01(a) 연쇄. v2: TC-046에서 Fixed 확인 |
| TC-035 | 모바일 바텀시트: 필드 타이핑 중 포커스 유지 | 패널 열림 | 실행 | 유지+값 커밋 | **포커스 이탈, 값 미커밋** | **Fail** | DEF-U07-01(b) Critical. v2: TC-046에서 Fixed 확인 |
| TC-036 | 모바일 바텀시트: `<select>` 변경 | 패널 재오픈 | 실행 | 유지+값 커밋 | **포커스 이탈** | **Fail** | DEF-U07-01(b). v2: TC-046에서 Fixed 확인 |
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

**TC-051 참고(재조사 상세, "실행해보니 에러 없음"으로 얼버무리지 않기 위한 기록)**: 최초 1회 실행에서 `page.on("console")`이 잡은 `Failed to load resource: 404`를 발견해 즉시 FAIL로 표시하고 원인을 추적했다. (1) 동일 시나리오를 단독으로 3회 재실행(`verify_stress3.mjs`)한 결과 3회 모두 4xx/5xx 응답도 `pageerror`도 0건으로 재현되지 않았다. (2) 최초 실행 직전 별도 세션에서 CPU 스로틀링 50배 테스트가 타임아웃 중이었던 정황이 있어(백그라운드 프로세스 잔존 가능성), 시스템 리소스 경합으로 인한 일회성 네트워크 타이밍 이슈로 잠정 결론지었다. (3) 같은 최초 실행 안에서 스트레스 직후 재오픈 시 초기 포커스가 정상 작동했다는 사실(TC-051의 후반부)은 이 404가 포커스 트랩의 DOM/React 상태를 오염시키지 않았음을 방증한다. 결함으로 등록하지 않되, 이 재현 불가 이상 현상 자체는 투명하게 기록한다(§8 참고사항). **(v3 참고)** 아래 §4-3 TC-108에서 `/screener` 자체에서도 유사한 404가 관찰되어 원인을 특정했다 — `favicon.ico` 자산 부재(포커스 트랩/CORS와 무관, 별개의 사전 존재 이슈).

## 4-3. v3 재검증 테스트 케이스 (CORS 회귀 확인, 2026-09-18)

> DEF-U09-01(services/public_api/main.py, UNIT-01 소관) 수정이 `screenApi.ts`(UNIT-07)의 실제 두 오리진 브라우저 fetch를 정상화했는지 확인한다. AC-1~AC-7/DEF-U07-01은 재검증하지 않는다(§2 제외 범위 참조).

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-101 | 실제 두 오리진 브라우저 재현: `/screener` 기본 조건 제출 → 결과 렌더링 | 프론트(`http://localhost:3000`, `next start` 프로덕션 빌드)/백엔드(`http://127.0.0.1:8000`, 실제 `services.public_api.main.app` + `CORSMiddleware`, DB는 실제 Postgres 픽스처를 복제한 Fake 리포지토리로 대체) 별도 오리진(포트 상이)으로 기동, `PUBLIC_API_CORS_ALLOWED_ORIGINS` **미설정**(기본값 `http://localhost:3000` 그대로, `.env.example` 기본 구성과 동일) | 데스크톱 뷰포트(1280×900)로 `/screener` 접속 → 조건 폼 기본값 그대로 `.condition-filter-panel__submit` 클릭 → `.screener-page__results` 렌더링 대기 → `page.on('console')`/`page.on('requestfailed')`로 CORS 관련 이벤트 포착 | CORS 관련 콘솔 에러 0건, 결과 영역에 실제 종목명("삼성전자","SK하이닉스") 렌더링 | CORS 에러 0건. 결과 텍스트: "조건 충족 종목 목록 (총 2건) ... 삼성전자(테스트픽스처) (005930) KOSPI 상승 +3.3% SK하이닉스(테스트픽스처) (000660) KOSPI 상승 +1.1%" | **Pass** | 실행 로그 전문을 §7에 근거로 남김(`snippet` 필드) |
| TC-102 | 재현성 확인: 서버 완전 재기동 후 동일 시나리오 재실행 | TC-101 종료 후 백엔드(uvicorn)/프론트(`next start`) 프로세스 전부 `taskkill`로 종료(포트 3000/8000 `netstat` 리스너 없음 확인) → 처음부터 재기동 | TC-101과 완전히 동일한 스크립트(`cors_browser_test.mjs`) 재실행 | 동일하게 CORS 에러 0건, 결과 렌더링 | 재기동 후 동일 결과 재현: CORS 에러 0건, "삼성전자"/"SK하이닉스"/등락률 렌더링 확인 | **Pass** | 규칙 B 2회 독립 검증의 1/2차 실행 근거(우연이 아님을 서버 재기동으로 확인) |
| TC-103 | 부정 통제(네거티브 컨트롤): 허용되지 않은 오리진은 여전히 차단됨 — 테스트 방법론 자체의 타당성 확인 | 동일 백엔드(포트 8000) | `curl -i "http://127.0.0.1:8000/api/v1/stocks?query=삼성&market=ALL" -H "Origin: http://evil.example.com"` | 응답에 `access-control-allow-origin` 헤더가 없어야 함(있으면 이 테스트 자체가 CORS 차단을 검출 못하는 무의미한 방법론이라는 뜻) | `200 OK`, 응답 헤더에 `access-control-allow-origin` 없음. 동일 요청을 `Origin: http://localhost:3000`으로 바꾸면 `access-control-allow-origin: http://localhost:3000` 헤더가 실제로 반환됨(대조 확인) | **Pass** | 내부검증 2차 관점 — "테스트가 결함을 놓칠 가능성"을 이 대조군으로 반증 |
| TC-104 | `get_cors_allowed_origins()`/`CORSMiddleware` pytest 4건 독립 재실행 | 저장소 루트 | `python -m pytest tests/unit/test_public_api.py -k cors -v` | 4 passed | `test_cors_allows_default_localhost_frontend_origin`/`test_cors_blocks_unlisted_origin`/`test_get_cors_allowed_origins_reads_comma_separated_env_var`/`test_get_cors_allowed_origins_falls_back_to_default_when_unset` — 4 passed | **Pass** | 5단계 주장을 신뢰하지 않고 직접 실행 |
| TC-105 | **변형 시나리오(신규)**: 쉼표+공백 혼합 다중 오리진 환경변수가 파서 단위테스트뿐 아니라 실제 `CORSMiddleware` 앱 레벨에서도 올바르게 반영되는지 확인 | `PUBLIC_API_CORS_ALLOWED_ORIGINS=" http://localhost:3000 , http://localhost:4000 "` 설정 후 `services.public_api.main.app`을 재로드, `get_stock_search_repository` DI만 Fake로 오버라이드(`FastAPI TestClient`) | 3개 오리진(등록 2개: `localhost:3000`/`localhost:4000`, 미등록 1개: `localhost:9999`)으로 각각 `GET /api/v1/stocks` 요청, `access-control-allow-origin` 헤더 대조 | 등록된 2개만 각각 자신의 오리진으로 ACAO 헤더 반환, 미등록은 헤더 없음 | `origin='http://localhost:3000' -> ACAO='http://localhost:3000'`, `origin='http://localhost:4000' -> ACAO='http://localhost:4000'`, `origin='http://localhost:9999' -> ACAO=None` | **Pass** | 기존 4건 pytest(TC-104)는 `get_cors_allowed_origins()` 파서 단위테스트 1건 + 단일 오리진 미들웨어 테스트 2건뿐, "다중 오리진이 실제 미들웨어에서 각각 올바르게 매칭되는가"라는 통합 공백을 이번에 메움(오케스트레이터 지시 "변형 시나리오 하나 추가" 이행) |
| TC-106 | 회귀: 백엔드 전체 pytest/ruff | 저장소 루트 | `python -m pytest tests/unit -q`, `python -m ruff check .` | 155 passed, 오류 0건 | `155 passed, 2 warnings`(경고 2건은 기존에 이미 존재하던 `httpx`/쿠키 관련 Deprecation, 이번 CORS 수정과 무관 — v4 이전부터 존재), `All checks passed!` | **Pass** | 이번 CORS 수정이 UNIT-07이 의존하는 백엔드 다른 AC를 훼손하지 않음을 확인 |
| TC-107 | 회귀: 프론트엔드 정적분석/빌드 | `frontend/` | `npx tsc --noEmit`, `npm run lint`, `npm run build` | 오류 0건, 빌드 성공 | 오류 없음(tsc), lint 통과(출력 없음), 빌드 성공(금지표현 검사 통과 47개 파일 → 라우트 6개 동일: `/`,`/_not-found`,`/about`,`/screener`,`/stocks`,`/stocks/[code]`) | **Pass** | 이번 CORS 수정은 프론트엔드 파일을 전혀 변경하지 않았으나(백엔드 전용 수정) 회귀 확인 차원에서 재실행 |
| TC-108 | 콘솔 404(`favicon.ico`) 원인 특정 — 이상현상 은폐 방지 | `/screener` 접속 | `page.on('response')`로 상태코드 404인 응답의 URL을 전부 캡처 | 원인이 CORS/데이터 fetch와 무관함을 특정해야 함 | `404: http://localhost:3000/favicon.ico` — 프론트엔드 프로젝트에 파비콘 자산이 없어 발생하는 사전 존재 이슈(UNIT-07/CORS 수정과 무관, 백엔드 fetch 실패 아님) | **Pass(결함 아님, 투명 기록)** | TC-101/102에서 관찰된 "consoleErrors" 중 CORS 무관 404가 이것임을 근거로 확정. UNIT-07/UNIT-01 범위 밖(프론트엔드 정적 자산 공백) — 신규 결함으로 등록하지 않되 §8에 리스크로 기록 |
| TC-109 | **2차 내부검증에서 식별한 추가 위험 케이스**: 에러 응답(4xx/404)에도 CORS 헤더가 붙는지 — DEF-U09-01의 원래 증상은 상태코드와 무관하게 모든 fetch가 100% 차단되는 것이었으므로, 성공 응답만 확인한 것으로는 충분하지 않을 수 있다는 의심에서 추가 | 동일 백엔드(포트 8000), `get_stock_search_repository` DI를 정상 Fake로 오버라이드한 `TestClient` | `market=INVALID`로 400 유도, 존재하지 않는 경로로 404 유도, 둘 다 `Origin: http://localhost:3000` 헤더 포함 요청 | 400/404 응답에도 `access-control-allow-origin` 헤더가 그대로 존재해야 함(그래야 프론트엔드가 `ErrorState`를 정상 렌더링할 수 있다 — CORS가 막히면 상태코드와 무관하게 브라우저가 응답 자체를 읽지 못한다) | `400 status, ACAO=http://localhost:3000`, `404 status, ACAO=http://localhost:3000` — 둘 다 정상 반환 | **Pass** | `CORSMiddleware`가 Starlette 미들웨어 스택의 최외곽에 위치해 예외 핸들러가 만든 에러 응답에도 동일하게 적용됨을 실측 확인(코드 추론이 아니라 실제 요청/응답으로 검증) |

## 5. 커버리지
- v1 커버리지(AC-1~AC-7 100%, 코디네이터 최우선 지시 4개 100%, note §8 위임 5개 항목 100%)는 그대로 유지.
- v2 커버리지(`unit-07-note.md`(v2) §8-b가 6단계에 위임한 재검증 항목 5개 100%)는 그대로 유지(TC-046~051).
- **v3 추가**: 오케스트레이터가 이번 세션에 위임한 CORS 회귀 확인 범위를 전부 커버했다.
  1. UNIT-07(`/screener`) 실제 두 오리진 브라우저 fetch 재현, CORS 차단 없음 + 실제 데이터 렌더링 확인 → TC-101, TC-102(재현성)
  2. `get_cors_allowed_origins()`/`CORSMiddleware` pytest 4건 독립 재실행 + 변형 시나리오 1건 추가 → TC-104, TC-105
  3. 이번 CORS 수정이 다른 회귀를 일으키지 않았는지 최소 정적분석/빌드 재확인 → TC-106, TC-107
  4. `traceability.md` REQ-003 행 동기화 → 본 문서 완료 후 별도 갱신(오케스트레이터 보고 참조)
- 커버되지 않은 부분과 사유:
  - CPU 스로틀링 50배(극단치)의 완전한 실측 — v2와 동일(변경 없음), 테스트 도구 자체의 한계로 판단해 결함 미등록.
  - 실 모바일 기기(iOS Safari/Android Chrome 실기기)에서의 실측 — v1/v2와 동일한 제약, 이번 v3(CORS)도 데스크톱 Chromium 엔진으로만 검증(회귀 확인이 목적이라 범위 확장하지 않음).
  - 실제 프로덕션 호스팅 환경에서의 CORS 동작 — 호스팅 벤더 미확정(`03-system-design.md` §2-1)이라 로컬 두 오리진(3000/8000) 재현으로 대체, `unit-09-test.md`와 동일한 리스크로 §8에 유지.

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도(Critical/High/Medium/Low) | 상태(Open/Fixed/Deferred) | 조치 내용 |
|----|------|-----------|-----------------------------------|----------------------------|-----------|
| **DEF-U07-01** | (v1에서 이관) 모바일 바텀시트 포커스 트랩 미작동(원인 a: 초기 포커스 이동 실패, 원인 b: 재렌더 시 포커스 강제 이탈) | v1 §6 참조 | Critical | **Fixed(v2 독립 재검증 완료, v3에서도 회귀 없음 재확인)** | v2에서 5단계 조치를 Playwright-core로 독립 재현해 Fixed 확정(TC-046~047e). **v3**: 이번 CORS 수정(`services/public_api/main.py`/`core/config.py`)이 `useFocusTrap.ts`/`ScreenerClient.tsx`를 전혀 건드리지 않았음을 `git diff`로 확인했고(§2), 프론트엔드 전체 빌드/린트/tsc가 회귀 없이 통과함(TC-107)을 확인해 이 결함이 재발하지 않았음을 재확인했다. |
| **DEF-U09-01(승계 확인)** | `services/public_api/main.py`(UNIT-01 최초 작성)에 CORS 미들웨어가 없어 `frontend/src/lib/screenApi.ts`(UNIT-07)를 포함한 모든 크로스오리진 fetch가 100% 차단되던 결함(최초 발견은 UNIT-09, `unit-09-test.md` DEF-U09-01) | `unit-09-test.md` §8 참조(원 재현 절차) | Critical | **Fixed(v3에서 UNIT-07 관점으로 독립 재확인)** | 5단계가 `CORSMiddleware`/`get_cors_allowed_origins()`를 추가해 조치(`unit-01-note.md` v4, DEC-022). **본 v3가 `screenApi.ts`를 사용하는 `/screener` 화면에서 실제 헤드리스 브라우저 두 오리진(포트 3000/8000) 재현으로 CORS 에러 0건 + 실제 데이터 렌더링을 확인**(TC-101, TC-102 — 서버 완전 재기동 후 재현성까지 확인)했다. 부정 통제(TC-103)로 테스트 방법론 자체가 실제 차단을 검출할 수 있음도 확인해, 이 Fixed 판정이 "테스트가 느슨해서 통과한 것"이 아님을 뒷받침한다. |

- 그 외 결함 없음(v3 기준). 근거: §4-3 TC-101~108(8개 케이스, TC-047 계열 포함 시 누적 다수) 전부 Pass, TC-106/107(백엔드 155건 전체 pytest + ruff, 프론트엔드 tsc/lint/build)이 이번 CORS 수정으로 인한 다른 회귀가 없음을 확인했다. TC-108에서 관찰된 404(`favicon.ico`)는 원인을 특정해 CORS/데이터 fetch와 무관함을 확정했으므로(§8 리스크로만 기록) 결함으로 등록하지 않는다.

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K

### v2 Teardown (이력 보존)
- 이번 테스트에서 생성한 임시 아티팩트 목록:
  - `.harness-tmp/unit07-verify/`(신규) — `package.json`/`package-lock.json`/`node_modules`(playwright-core), 검증 스크립트 8개(`verify.mjs`, `verify_throttle_extra.mjs`, `verify_404check.mjs`, `verify_stress.mjs`, `verify_stress2.mjs`, `verify_stress3.mjs`), 서버 로그(`frontend-server.log`)
  - 프론트엔드 프로덕션 서버 프로세스(포트 3200, `PORT=3200 npm run start`, PID 15624)
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): [x] 예 — 서버 프로세스(PID)는 파일시스템 아티팩트가 아니라 실행 중 프로세스라 `.harness-tmp/` 개념이 적용되지 않으며, 별도로 종료 처리했다.
- 정리(삭제) 완료 여부: 완료. 프론트엔드 서버 프로세스(PID 15624)를 `Stop-Process -Force`로 강제 종료 후 재시도 결과 연결 거부 확인. `.harness-tmp/` 디렉터리 전체를 `rm -rf`로 삭제 후 확인.
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: [x] 없음.

### v3 Teardown (신규, 2026-09-18)
- 세션 시작 시 `.harness-tmp/` 확인 결과: 비어 있음(이전 세션이 남긴 잔여물 없음, 강제 중단 이력 없음 — 규칙 K 4번 재개 시 점검 절차 준수).
- 이번 테스트에서 생성한 임시 아티팩트 목록:
  - `.harness-tmp/cors-regression/`(신규) — `package.json`/`package-lock.json`/`node_modules`(puppeteer-core@23), `fake_backend.py`(실제 `services.public_api.main.app`을 DI 오버라이드로 구동하는 검증용 스크립트, 소스 무변경), `cors_browser_test.mjs`(TC-101/102/TC-B 재현 스크립트), `check404.mjs`(TC-108), `variant_multi_origin_check.py`(TC-105), `backend.log`/`backend2.log`/`frontend.log`/`frontend2.log`(서버 로그)
  - 백엔드(uvicorn, 포트 8000)/프론트엔드(`next start`, 포트 3000) 프로세스 각 2회(재기동 포함)
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): [x] 예.
- 정리(삭제) 완료 여부: **완료.** 백엔드/프론트엔드 프로세스를 `netstat -ano`로 포트(3000/8000) 리스닝 PID를 특정해 `taskkill //F //PID <pid>`로 전부 종료(포트 3000에 IPv4/IPv6 리스너가 각각 별도 PID로 존재해 둘 다 종료 확인). `.harness-tmp/cors-regression/` 디렉터리를 `rm -rf`로 삭제 후 `.harness-tmp/`가 다시 빈 상태임을 확인. 프론트엔드는 커스텀 `NEXT_PUBLIC_API_BASE_URL` 없이 `npm run build`를 재실행해 기본 상태로 복원(`.next/`는 `.gitignore` 대상이라 git 추적과 무관).
- 정리 후 `git status` 실행 결과 (그대로 첨부):
```
On branch PROD_SCH
Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   .env.example
	modified:   docs/harness/decisions.md
	modified:   docs/harness/traceability.md
	modified:   docs/harness/units/unit-01-note.md
	modified:   frontend/src/app/globals.css
	modified:   frontend/src/app/page.tsx
	modified:   frontend/src/app/stocks/page.tsx
	modified:   frontend/src/components/EmptyState.tsx
	modified:   frontend/src/content/copy.ko.json
	modified:   frontend/src/lib/types.ts
	modified:   services/derivation_batch/compute.py
	modified:   services/derivation_batch/raw_models.py
	modified:   services/derivation_batch/repository.py
	modified:   services/derivation_batch/run_derivation.py
	modified:   services/public_api/core/config.py
	modified:   services/public_api/main.py
	modified:   shared/db_models/public_serving.py
	modified:   tests/unit/test_public_api.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	db/alembic/versions/0009_create_public_serving_market_summary_daily.py
	docs/harness/units/unit-08-note.md
	docs/harness/units/unit-08-test.md
	docs/harness/units/unit-09-note.md
	docs/harness/units/unit-09-test.md
	docs/harness/units/verify-log_unit-08-test.md
	docs/harness/units/verify-log_unit-09-test.md
	frontend/src/components/SearchInput.tsx
	frontend/src/components/SectorSummaryList.tsx
	frontend/src/components/StatSummaryGrid.tsx
	frontend/src/components/StockListItem.tsx
	frontend/src/components/StockSearchClient.tsx
	frontend/src/lib/formatKrw.ts
	frontend/src/lib/marketSummary.ts
	frontend/src/lib/stockSearchApi.ts
	services/public_api/api/market_summary.py
	services/public_api/db/market_summary_repository.py
	services/public_api/schemas/market_summary.py
	tests/unit/test_market_summary_compute.py

no changes added to commit (use "git add" and/or "git commit -a")
```
  (`services/public_api/main.py`/`core/config.py`의 "modified" 표기는 5단계(UNIT-01 v4)가 이미 만든 CORS 수정분이며, 이번 v3 6단계는 이 파일들을 전혀 수정하지 않았음을 `git diff`로 직접 대조해 확인했다. `unit-07-test.md`/`traceability.md`는 이번 v3가 개정 중인 문서라 기존 목록에 이미 포함되어 있다. `.harness-tmp/`는 비어 있어 목록에 나타나지 않는다 — `.gitignore` 정상 동작. 이 목록은 세션 시작 시점 git 상태와 문서 개정 파일을 제외하면 정확히 동일하다.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: [x] 없음.

## 8. 리스크 및 잔존 이슈
- **DEF-U07-01은 v2에서 완전히 Fixed로 확정됐고(v3에서도 회귀 없음 재확인), DEF-U09-01(CORS)도 v3에서 UNIT-07 관점으로 Fixed 확정됐다** — 07단계(통합테스트) 진행을 막는 Open 결함이 UNIT-07 기준으로 더 이상 없다.
- **CPU 스로틀링 50배(극단치) 미측정**: §4-2 TC-048b 참조. 실제 모바일 기기가 도달하지 않는 비현실적 조건이라 판단해 결함으로 등록하지 않았으나, 향후 실기기 성능 프로파일링(9단계 보안/성능 검증 또는 운영 모니터링)에서 "포커스 이동 자체보다 앱 전체의 극단적 저사양 대응"이라는 더 넓은 주제로 다뤄야 한다.
- **TC-051의 1회성 재현 불가 `404` 콘솔 이벤트**: §4-2/§6 참조. 3회 추가 재현 시도로 재현 실패해 결함 미등록했으나, **v3(TC-108)에서 동일 계열의 404가 `favicon.ico` 자산 부재임을 실제로 특정**했다 — 포커스 트랩/CORS와 무관한 정적 자산 공백으로, 프론트엔드 배포 전 파비콘 추가를 권고(신규 결함으로 등록하지 않음, Low 수준의 후속 개선 사항).
- **실 모바일 기기 미검증**: 헤드리스 Chromium(Desktop Chrome 엔진 기반)으로만 검증했다(v1/v2와 동일한 제약, v3도 동일). iOS Safari 등 다른 렌더링 엔진에서의 실측은 여전히 미수행.
- **실제 프로덕션 호스팅 환경에서의 CORS 동작(v3 신규 명시)**: 호스팅 벤더 미확정(`03-system-design.md` §2-1)이므로, 로컬 두 오리진(3000/8000) 재현은 "기본 로컬 개발 구성"에서의 정상 동작만 증명한다. 실제 배포 도메인 확정 시 `PUBLIC_API_CORS_ALLOWED_ORIGINS`를 실제 프론트엔드 도메인으로 재정의해야 하며, 이는 10단계 배포테스트 착수 전 필수 확인 사항이다(`unit-01-note.md` §3 동일 항목).
- v1이 남긴 나머지 리스크(§5-1 인덱스 구성 편차, 424 실 DB 미검증, 실측 성능 미측정, DEF-U07-02 참고사항)는 이번 재작업이 건드리지 않은 영역이므로 그대로 유지된다(v1 §8 참조, 재서술 생략).

## 9. 결론 및 판정
- [x] PASS — 다음 단계 진행 가능
- [ ] CONDITIONAL PASS — 조건:
- [ ] FAIL — 사유 및 재작업 요청 사항:

**판정 근거(v2, 유지)**: v1이 발견한 유일한 결함 DEF-U07-01(Critical)이 5단계 재작업 후 6단계가 5단계와 다른 자동화 스택(Playwright-core)으로 독립 재현해 완전히 Fixed임을 확인했다(TC-046, TC-047a~e). 5단계 스스로 검증하지 못했다고 인정한 두 가지 잔여 우려도 변형 시나리오로 추가 검증해 구조적 해법이 특정 상황에 땜질된 것이 아니라 일반적으로 견고함을 확인했다.

**판정 근거(v3, 신규)**: UNIT-09 검증 중 발견된 DEF-U09-01(Critical, CORS 미들웨어 부재, UNIT-01 소관)이 `screenApi.ts`(UNIT-07)에도 동일하게 영향을 미쳤으나, 5단계의 조치(`CORSMiddleware`/`get_cors_allowed_origins()`)를 6단계가 실제 헤드리스 브라우저로 두 오리진(포트 3000/8000, `.env.example` 기본 구성과 동일) fetch를 재현해 **CORS 에러 0건 + 실제 데이터 렌더링**을 확인했다(TC-101). 서버를 완전히 재기동한 뒤 동일 시나리오를 재실행해 재현성도 확인했다(TC-102, 규칙 B 2회 독립 검증). 부정 통제(TC-103)로 테스트 방법론 자체가 실제 차단을 검출할 수 있음을 확인해 판정의 신뢰도를 뒷받침했다. `get_cors_allowed_origins()`/`CORSMiddleware` pytest 4건을 독립 재실행했고(TC-104), 기존 pytest가 다루지 않은 다중 오리진(쉼표+공백) 앱 통합 시나리오를 추가로 검증했다(TC-105). 이번 CORS 수정이 UNIT-07의 다른 부분에 회귀를 일으키지 않았음을 백엔드 전체 pytest(155건)/ruff, 프론트엔드 tsc/lint/build로 확인했다(TC-106/107). 콘솔에서 관찰된 404는 `favicon.ico` 자산 부재로 원인을 특정해 결함이 아님을 확정했다(TC-108). 2차 내부검증 관점에서 "성공 응답만 확인한 것이 충분한가"를 재검토해, 에러 응답(400/404)에도 CORS 헤더가 정상 부착됨을 추가로 실측해(TC-109) DEF-U09-01의 원래 증상(상태코드 무관 전면 차단)이 완전히 해소됐음을 보강 확인했다.

**종합 판정**: UNIT-07은 자체 AC-1~AC-7(v1) + DEF-U07-01 조치(v2) + DEF-U09-01(CORS) 조치의 UNIT-07 관점 영향(v3) 전부에서 신규 결함 0건, 기존 Critical 결함(DEF-U07-01) Fixed 유지, 승계된 Critical 결함(DEF-U09-01)도 UNIT-07 관점에서 Fixed로 확인되어 완료 조건을 충족한다. **07단계(통합테스트, `07-integration-tester`)로 handoff 가능.**

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)
- 1차 검증 결과 요약(v2, 유지): (아래 §10 상세는 `verify-log_unit-07-test.md`(v3) 참조) 작성자 관점 자가 재검토 — §0-b가 위임한 5개 항목이 §4-2/§5 표와 1:1 대응하는지 확인, DEF-U07-01 Fixed 판정의 근거(TC-046/047 계열)가 실제 실행 로그(activeElement/insideDialog/value 등 구체값)에 기반하고 "에러 없음"만으로 판정하지 않았는지 재확인, TC-051의 이상 현상을 은폐하지 않고 재조사 과정을 그대로 기록했는지 확인.
- 2차 검증 결과 요약(v2, 유지): 독립 심사자 관점 — "5단계 자체 검증(같은 Puppeteer, 같은 로컬 환경)을 6단계가 그대로 반복만 한 것은 아닌가"를 의심하며 재검토했다(4개 관점, 상세는 §10 v2 원문 참조).
- **1차 검증 결과 요약(v3, 신규)**: 작성자 관점 자가 재검토 — (1) 오케스트레이터가 위임한 4개 범위(UNIT-07 실제 두 오리진 재현, pytest 4건+변형 1건, 회귀 정적분석, `traceability.md` REQ-003 동기화)가 §4-3/§5에 1:1 대응하는지 확인, (2) "CORS 에러 0건"이라는 판정이 콘솔 로그를 실제로 필터링(`/CORS|blocked by CORS policy/i`)한 결과이지 단순히 "에러 없음"이라고 뭉뚱그린 것이 아닌지 스크립트(`cors_browser_test.mjs`) 원문 재확인, (3) 렌더링 확인이 "요청이 200으로 왔다"가 아니라 실제 DOM 텍스트("삼성전자","SK하이닉스")를 assert했는지 재확인, (4) Fake 리포지토리 데이터가 `docker exec ... psql -U postgres`로 직접 조회한 실 픽스처 값과 정확히 일치하는지(종목코드/종목명 오탈자 없음) 재대조.
- **2차 검증 결과 요약(v3, 신규)**: "오늘 처음 이 v3 섹션을 받아본 심사자" 관점 재검토 — (1) **"포트를 3000/8000으로 고정한 것이 실제 기본 구성을 대표하는가?"** → `.env.example`(백엔드) 기본 포트 8000, 프론트엔드 Next.js 개발 서버 기본 포트 3000, `services/public_api/core/config.py`의 `DEFAULT_CORS_ALLOWED_ORIGINS`가 정확히 `http://localhost:3000`인 것을 재대조해 인위적 선택이 아니라 실제 기본값 조합임을 확인. (2) **"이 테스트가 CORS 차단을 실제로 검출할 능력이 있는가?"** → TC-103(부정 통제)이 존재하고, 실제로 `access-control-allow-origin` 헤더 유무 차이를 관측했음을 재확인(테스트 자체가 느슨해서 통과한 게 아님). (3) **"Fake DI 오버라이드가 CORS 미들웨어 자체를 우회하지 않는가?"** → `app.dependency_overrides`는 라우트 핸들러의 DB 리포지토리 의존성만 교체하고 `app.add_middleware(CORSMiddleware, ...)`는 `services.public_api.main`의 앱 초기화 시점에 이미 등록된 실물 미들웨어 스택이라 DI 오버라이드로 우회될 수 없음을 `main.py`/`fake_backend.py` 코드 대조로 확인(미들웨어는 요청이 라우트에 도달하기 전 단계이므로 DI와 레이어가 다름). (4) **"재기동(TC-102)이 진짜 처음부터 다시 시작한 것인가, 캐시가 남아있던 것은 아닌가?"** → `netstat`로 리스닝 PID를 특정해 `taskkill`로 실제 프로세스를 종료하고 포트가 비어있음을 재확인한 뒤 완전히 새 프로세스로 재기동했음을 로그(PID 변경)로 확인. 4개 관점 모두 문서에 이미 반영되어 있음을 확인, 추가 결함 없음.
- 검증 로그 파일 경로: `docs/harness/units/verify-log_unit-07-test.md`(v3)
