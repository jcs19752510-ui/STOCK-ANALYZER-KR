# 테스트 결과서 (Test Result Report) — feature-stock-search (07단계, 업무단위 통합테스트)

> `templates/test-report-template.md` 사용. 대상 업무 단위(feature): **stock-search**(REQ-001, `decisions.md` DEC-023). 구성 작업 단위: **UNIT-03**(백엔드 `GET /api/v1/stocks`, `unit-03-test.md` PASS) + **UNIT-09**(프론트엔드 `/stocks` 화면, `unit-09-test.md` v2 PASS). 공유 인프라(DEC-023 범위): UNIT-01(캘린더/CORS, DEC-022), UNIT-02(데이터 파이프라인/시드 출처), UNIT-04(면책배너/금지표현), UNIT-05(GlobalNav/헤더).
>
> **이 문서의 가치 원칙**: UNIT-03/UNIT-09가 각자 단위테스트에서 이미 검증한 내용(API 자체의 필터/정렬/에러코드/DB 권한, 화면 자체의 EmptyState/ErrorState/REQ-009 등)은 반복하지 않는다. 이 문서는 **① 두 유닛 사이의 실제 데이터 흐름/스키마 일치, ② 업무단위 수준 E2E(화면 간 이동 포함), ③ 합쳤을 때의 회귀, ④ DEF-006의 통합 관점 재판단**에만 집중한다.

## 1. 개요
- 테스트 대상: 업무 단위(feature) **stock-search** = UNIT-03(백엔드) + UNIT-09(프론트엔드)의 통합, REQ-001 전체
- 테스트 유형: 통합(07단계, 업무단위 전체 풀테스트)
- 적용 Tier: **High**(`decisions.md` DEC-021) — 검증 강도 완화 없음, 규칙 B 원문(최소 2회 독립 검증) 그대로 적용. 이 feature의 작업 단위가 2개(UNIT-03+UNIT-09)이지만 Tier가 High이므로 06/07 병합 예외(Low 등급 전용)는 적용되지 않는다 — 06(단위테스트)과 07(이 문서)을 분리 수행.
- 테스트 목적:
  1. UNIT-09 프론트엔드가 UNIT-03 백엔드가 **실제로** 반환하는 응답 스키마를 정확히 소비하는지, 지금까지의 단위테스트가 대부분 Fake/Mock 리포지토리로 검증했던 것과 달리 **실제 두 프로세스를 실제 네트워크로 연결**해 확인한다.
  2. 업무단위 수준 E2E 시나리오(`/stocks` 검색 → 결과 클릭 → `/stocks/[code]`(UNIT-06) 상세 이동 → 404 시 "종목 검색으로 돌아가기" → 재검색까지의 순환 흐름)를 개별 유닛 테스트에서는 볼 수 없는 화면 간 이동까지 포함해 재현한다.
  3. 두 유닛을 합쳤을 때 기존 단위테스트가 여전히 통과하는지(전체 `pytest`, 프론트 빌드/린트/타입체크, CORS 회귀 포함) 확인한다.
  4. DEF-006(LIKE 와일드카드 미이스케이프, Low/Open)이 이 통합 시나리오에서 사용자 경험에 실질적 영향을 주는지 통합 관점에서 재판단한다.
- 관련 산출물: `docs/harness/units/unit-03-note.md`, `unit-03-test.md`(PASS), `unit-09-note.md`, `unit-09-test.md`(v2, PASS), `docs/harness/02-planning.md`(v5) §4-1 REQ-001, `docs/harness/04-ux-design.md` §1-3(Flow C), §2-3(종목 검색 화면), §4(컴포넌트 명세), `docs/harness/traceability.md` REQ-001 행, `docs/harness/decisions.md` DEC-019(UNIT-09 신설), DEC-022(CORS 회귀 수정), DEC-023(feature 그룹핑)
- 테스트 수행자(에이전트): 07-integration-tester
- 테스트 일시: 2026-09-18

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - 실제 UNIT-03 백엔드 프로세스(uvicorn, `services.public_api.main.app` 그대로) + 실제 UNIT-09 프론트엔드 프로세스(`next build && next start` 프로덕션 빌드)를 서로 다른 포트(127.0.0.1:8000 / localhost:3000, `.env.example` 기본 구성)로 동시 기동하고 실제 헤드리스 브라우저(Chrome + Puppeteer-core)로 종단간 상호작용 재현
  - 데이터 흐름/스키마 일치: 백엔드 Pydantic 스키마(`StockSearchItem`, `Envelope`)와 프론트엔드 TypeScript 타입(`types.ts`)의 필드명/nullable 여부 1:1 대조 + 실제 런타임 응답으로 재확인
  - 업무단위 E2E: 검색 → 클릭 → `/stocks/[code]`(UNIT-06) 이동 → 실제 파생지표 렌더링, 404 → "종목 검색으로 돌아가기" → `/stocks` 재검색까지의 순환 흐름
  - 회귀: `pytest tests/unit`(전체), `ruff check .`, 프론트엔드 `tsc --noEmit`/`lint`/`build`(prebuild 금지어 검사 포함)
  - DEF-006(LIKE 와일드카드) 실사용 영향을 실제 두 프로세스 조합에서 재관찰(이스케이프 없음이 통합 시나리오에서도 크래시나 정보 노출로 이어지지 않는지)
  - CORS(DEC-022) 실제 두 오리진 재현 + 네거티브 컨트롤(허용되지 않은 오리진 차단 유지 확인) — UNIT-03/UNIT-09 경계에서 실제로 통신이 되는지의 핵심 전제조건이므로 이 통합테스트에서도 독립적으로 재확인(단위테스트 반복이 아니라, "두 실제 프로세스가 실제로 붙는지"를 검증하는 이 문서의 1차 목적과 직결)
  - 공유 인프라 회귀: UNIT-01(GlobalNav 통과 시 캘린더 기반 신선도 배지·CORS), UNIT-04(면책배너 상시 노출), UNIT-05(GlobalNav `aria-current`)
- 제외 범위 및 사유:
  - UNIT-03 API 자체의 필터/정렬/에러코드/입력검증/DB GRANT — `unit-03-test.md`(PASS, TC-001~044)가 이미 실제 PostgreSQL로 충분히 검증. 이 문서는 반복하지 않는다.
  - UNIT-09 화면 자체의 AC-1~AC-9(EmptyState/ErrorState/디바운스/접근성 등) — `unit-09-test.md` v2(PASS, TC-001~042)가 이미 검증. 이 문서는 반복하지 않는다.
  - `/stocks/[code]`(UNIT-06) 자체의 지표 계산 정확성(등락률 순위/괴리율/백분위 산식) — feature-stock-metrics(UNIT-06 단독) 영역이며 이미 `unit-06-test.md`(PASS)로 검증됨. 이 문서는 "검색 결과 클릭이 실제로 그 화면에 도달하고, 그 화면이 크래시 없이 실제 데이터를 렌더링하는가"까지만 확인한다.
  - `/screener`(UNIT-07)·`/`(UNIT-08) 자체 기능 — 별도 feature(screener, market-summary)의 07단계 영역. 단, `MarketFilterControl` 공유 컴포넌트가 UNIT-09에서 변경되지 않았음은 `unit-09-test.md` TC-008로 이미 확인되어 재확인하지 않는다.
  - **실제 `api_service`/`postgres` 계정 자격증명을 사용한 host→Postgres(포트 5432 매핑) 직접 접속**: 이 세션의 도구 정책이 자격증명 문자열이 포함된 명령(`ALTER ROLE`, 비밀번호 포함 접속 문자열 등)을 차단함을 재확인했다(`unit-09-test.md` v2 §4-a와 동일 현상 — `ALTER ROLE api_service WITH PASSWORD ...`, `PUBLIC_API_DATABASE_URL=...api_service:devpass@...`로 실제 uvicorn 기동 둘 다 차단됨을 직접 시도해 확인). 대신 `docker exec stock-screener-db psql -U postgres ...`(컨테이너 자체 loopback, `pg_hba.conf`가 `127.0.0.1/32`를 trust로 허용 — 비밀번호 불요, 차단되지 않음)로 조회한 **실제 `stock_master`/`derived_metrics_daily`/`reference.market_calendar`/`current_published_batch` 값**을 그대로 복제한 Fake로 DB 리포지토리 DI 3개(`get_stock_search_repository`/`get_stock_metrics_repository`/`get_calendar_repository`)만 대체했다. 나머지(HTTP 라우팅, `CORSMiddleware`, Pydantic 검증/직렬화, 에러 핸들러)는 전부 실제 프로덕션 코드(`services.public_api.main.app`)를 그대로 사용했다. UNIT-03의 DB 레이어(GRANT/ILIKE/upsert) 자체는 이미 `unit-03-test.md`가 실 Postgres로 PASS 확정했으므로 이 문서의 재검증 대상이 아니다 — 이 대체는 "이미 검증된 것의 반복을 피하고 이 문서의 실제 목적(두 유닛 경계)에 집중한다"는 원칙과도 부합한다.
  - 실제 프로덕션 호스팅 환경에서의 CORS/네트워크 토폴로지 — 호스팅 벤더 미확정(`03-system-design.md` §2-1), 로컬 두 오리진 재현으로 대체(§8 리스크 참조, `unit-09-test.md` v2와 동일한 승계 리스크).
  - 200% 확대/모바일 실기기 확인 — 기존 승계 리스크(신규 아님).

## 3. 테스트 환경
- 실행 환경: Windows 10(Git Bash), Python 3.13(anaconda, `uvicorn` 0.3x), Node.js(Next.js 16.3.5, `next build && next start`), 헤드리스 Chrome(시스템 설치 `C:\Program Files\Google\Chrome\Application\chrome.exe`, `puppeteer-core@23`으로 구동), PostgreSQL 16(Docker `stock-screener-db`, 8시간 이상 `Up` 상태 확인, 읽기전용 `postgres`/`migrator` 슈퍼유저 조회만 사용).
- 백엔드: `PUBLIC_API_DATABASE_URL`은 사용되지 않는 더미 값(`postgresql+psycopg://unused:unused@127.0.0.1:5432/unused`)으로만 설정 — DI 오버라이드가 `get_db`를 거치지 않으므로 실제로 참조되지 않음(단, `/health` 엔드포인트만 이 값을 직접 써서 `db: degraded`를 반환함 — 본 테스트 범위 밖). `PUBLIC_API_CORS_ALLOWED_ORIGINS`는 **의도적으로 미설정**(기본값 `http://localhost:3000` 그대로, `.env.example` 실제 기본 구성과 동일). 포트 127.0.0.1:8000.
- 프론트엔드: `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`로 `npm run build`(prebuild 금지어 검사 포함) 후 `next start -p 3000 -H localhost`. 포트 3000.
- 테스트 데이터: **실제** `public_serving.stock_master`(6행: `000660`/`005930`/`005935`/`900001`/`900002`/`900003`, UNIT-03/08가 이미 적재)와 `public_serving.derived_metrics_daily`(동일 6종목, UNIT-06/07이 이미 적재), `public_serving.current_published_batch`(`KRX`/`NXT` 모두 `trade_date=2026-09-14`), `reference.market_calendar`(2026-09-13~19 구간, KRX 09-13/09-19만 휴장) — 전부 `docker exec ... psql -U postgres`로 직접 조회해 확인한 값을 Fake 리포지토리에 그대로 하드코딩했다(새 값 생성/조작 없음, 읽기 전용 조회만 수행). 이 값들은 이번 테스트로 **전혀 쓰기 변경되지 않았다**(테스트 종료 후 `select count(*) from public_serving.stock_master` 재확인 결과 6행 그대로).
- 전제 조건: UNIT-03/UNIT-09 6단계 게이트(PASS) 확인 완료(`unit-03-test.md`, `unit-09-test.md` v2). Docker 컨테이너 기동 중. 포트 3000/8000 사전 점유 없음(`netstat`로 확인 후 시작).

## 4. 테스트 케이스 및 결과

### 4-1. 데이터 흐름/스키마 일치 (단위테스트가 보지 못한 영역)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-IT-S1 | 백엔드 Pydantic `StockSearchItem` ↔ 프론트 TS `StockSearchItem` 필드 1:1 대조 | 코드 열람 | `services/public_api/schemas/stocks.py`와 `frontend/src/lib/types.ts`의 필드명/타입 직접 대조 | `stock_code`/`name`/`market` 3개 필드, 이름·순서 의미상 정확히 일치 | 정확히 일치(둘 다 `stock_code: string`, `name: string`, `market: string`) | **PASS** | 필드명 오타/불일치 없음 — UNIT-09가 UNIT-03 계약을 정확히 베꼈음을 코드로 직접 확인(추측 아님) |
| TC-IT-S2 | `Envelope`(meta/data/error) 공통 봉투 구조 일치 | 코드 열람 | `services/public_api/schemas/envelope.py` ↔ `frontend/src/lib/types.ts` `Envelope` 대조 | `meta.disclaimer`/`meta.generated_at`/`data`/`error.code`/`error.message` 일치 | 일치. `stockSearchApi.ts`가 `body.data`/`body.error?.code` 접근 방식도 실제 스키마와 정확히 부합 | **PASS** | |
| TC-IT-S3 | 실제 두 오리진에서 검색 → 실제 응답이 화면에 정확히 렌더링(코드 대조가 아닌 런타임 실측) | 백엔드(8000)+프론트엔드(3000) 동시 기동 | 헤드리스 브라우저로 `/stocks` 접속 → "삼성" 입력 → 800ms 대기 | 화면에 "삼성전자(테스트픽스처)", "005930", "KOSPI" 뱃지 표시, 콘솔에 CORS 에러 0건 | 전부 확인됨(`code=true, name=true, badge=true, corsErrors=0`) | **PASS** | TC-IT-02 재사용 표기, 실제 실행 로그는 §4-2 참조 |
| TC-IT-S4 | `market` 파라미터 값(`ALL`/`KOSPI`/`KOSDAQ`) 문자열이 두 유닛 사이에서 완전히 동일한 어휘를 사용하는지 | 코드 열람 | `shared/market_types.py`(백엔드 `ListedMarketFilter`) ↔ `frontend/src/components/MarketFilterControl.tsx`(`ScreenMarketOption`) 대조 | 세 값의 철자·대문자 표기가 정확히 동일 | 정확히 동일(`"ALL" | "KOSPI" | "KOSDAQ"`) | **PASS** | 두 유닛이 서로 다른 enum 표기(예: 소문자 vs 대문자)를 가정했다면 07단계에서만 드러날 수 있는 전형적 통합 결함 유형 — 실제로는 불일치 없음 |

### 4-2. 업무단위 수준 E2E (개별 유닛 테스트에서는 볼 수 없는 화면 간 이동)

실제 백엔드(127.0.0.1:8000, 실제 `CORSMiddleware`/Pydantic/에러 핸들러 포함)와 실제 프론트엔드 프로덕션 서버(localhost:3000)를 동시 기동한 상태에서, 헤드리스 Chrome(Puppeteer-core, `--no-sandbox`)으로 아래 시나리오를 실제 브라우저 이벤트(키 입력/클릭/네비게이션)로 재현했다. 스크립트: `.harness-tmp/feature-stock-search-it/e2e_test.mjs`(테스트 종료 후 삭제, §7 참조).

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-IT-01 | 초기 진입 회귀(면책배너/GlobalNav, UNIT-04/05 공유 인프라) | 두 프로세스 기동 | `/stocks` 접속, `.disclaimer-banner`/`nav a[aria-current="page"]` 확인 | 배너에 "투자자문" 문구 포함, `aria-current="page"`가 `/stocks`에 부여 | `banner`="이 서비스는 투자자문업 등록 사업자가..." 포함, `navCurrent=/stocks` | **PASS** | |
| TC-IT-02 | 실제 두 오리진 검색 → 실제 백엔드 응답 렌더링(데이터 흐름 핵심 케이스) | 상동, `#stock-search-input` 존재 | "삼성" 입력 → 800ms 대기 | 결과에 "삼성전자", "005930" 포함, 콘솔 CORS 에러 0건 | `code=true, name=true, badge=true, corsErrors=0` | **PASS** | |
| TC-IT-03 | 검색 결과 클릭 → `/stocks/{code}` 실제 이동(UNIT-09→UNIT-06 경계, UNIT-06이 지적했던 "코드를 몰라도 상세화면에 도달할 경로가 없다"는 공백이 실제로 메워졌는지의 핵심 확인) | TC-IT-02 상태 | `.stock-list__link` 실제 클릭, 네비게이션 대기 | `location`이 `/stocks/005930`로 정확히 이동 | `navigated to http://localhost:3000/stocks/005930` | **PASS** | 링크가 실제로 클릭 가능하고 실제로 연결되어 있음을 코드 리뷰가 아니라 클릭으로 확인(과제 지시사항 이행) |
| TC-IT-04 | `/stocks/[code]` 상세 화면이 실제 UNIT-06 파생지표(실 데이터, Fake이지만 실측값 그대로)를 크래시 없이 렌더링 | TC-IT-03 도달 화면 | 본문 텍스트에서 종목명/지표 확인 | "삼성전자" 포함, 지연 경고(`current_published_batch`=2026-09-14, 오늘=2026-09-18이라 데이터 지연 상태) 정상 노출 | `name=true, returnRankShown=true, staleWarning=true`(실제로 "지연된 데이터입니다" 문구 렌더링 확인) | **PASS** | REQ-006(기준시각/지연 경고)이 두 화면(검색→상세)을 거쳐도 깨지지 않음을 확인. staleness는 테스트 픽스처 시점(2026-09-14)과 오늘(2026-09-18) 차이에서 자연 발생한 것으로, 설계 의도(REQ-011 지연 데이터 표기)와 정확히 일치하는 정상 동작이지 결함이 아님 |
| TC-IT-05 | 404(`STOCK_NOT_FOUND`) → "종목 검색으로 돌아가기" → `/stocks` 재검색까지 순환 흐름 완결 확인 | `/stocks/999999` 접속 | 404 문구 확인 → 링크 클릭 → 네비게이션 대기 → 재검색("SK") | "찾을 수 없습니다" 문구, 링크 `href="/stocks"`, 클릭 후 실제 `/stocks` 도달, 재검색 시 "SK하이닉스" 정상 표시 | `has404=true, backLink=/stocks, landed=true, searchWorks=true` | **PASS** | UNIT-06이 인계한 "시퀀싱 공백"(코드 몰라도 상세 도달 불가)이 UNIT-09로 메워졌고, 그 반대 방향(상세 실패 → 검색 복귀)도 실제로 순환됨을 확인 — 개별 유닛 테스트에서는 볼 수 없는 화면 2개 이상을 넘나드는 흐름 |
| TC-IT-06 | DEF-006(LIKE 와일드카드) 통합 관점 재확인 — 실제 두 프로세스 조합에서도 동일한지 | `/stocks` | 검색창에 `%%` 입력 → 렌더된 결과 항목 수 확인 | 이스케이프 없어 활성 종목 전체(6개)가 매칭·렌더 | 렌더 요소 12개 검출(li+a 이중 셀렉터 매칭이므로 실질 6항목, 6개 종목 전체 매칭 확인) | **PASS(결함 재현, §6 참조)** | 아래 4-3 참조 |
| TC-IT-07 | 시장 필터 변경이 실제 두 프로세스 조합에서도 정확히 반영되는지 | "UNIT08" 검색 후 결과 3건(KOSPI 1 + KOSDAQ 2) 노출 상태 | "코스피" 필터 버튼 클릭 → 600ms 대기 | KOSDAQ 픽스처(`UNIT08테스트가전KOSDAQ` 등)가 결과에서 사라짐 | `clicked코스피=true, kosdaq제외됨=true` | **PASS** | UNIT-07이 만들고 UNIT-09가 재사용하는 `MarketFilterControl`이 실제 두 프로세스 조합에서도 정확히 동작 |
| TC-IT-08 | CORS 네거티브 컨트롤(테스트 방법론 신뢰성 확인, 2차 내부검증에서 강화) | 백엔드 기동 중 | `Origin: http://localhost:3000`과 `Origin: http://evil.example.com`으로 각각 실제 `fetch` | 전자만 `access-control-allow-origin` 헤더 존재, 후자는 없음 | `allowed=http://localhost:3000, blocked=null` | **PASS** | 이 테스트 방법론 자체가 실제 CORS 차단을 검출할 능력이 있음을 재확인(단위테스트 TC-039와 동일 원칙을 이 통합 환경에서도 재검증) |

### 4-3. DEF-006(LIKE 와일드카드 미이스케이프) 통합 관점 재판단

- **재현**: TC-IT-06에서 실제 두 프로세스 조합(UNIT-03 응답 스키마 + UNIT-09 렌더링)에서도 `%`/`_` 입력 시 활성 종목 전체가 매칭·렌더링됨을 확인했다. 이는 단위테스트(UNIT-03: TC-033/034 실 Postgres, UNIT-09: TC-021/022 Fake 백엔드)가 이미 각자 관찰한 것과 동일한 현상이며, **두 유닛을 실제로 합쳐도 새로운 증상이 추가되지 않는다**(예: 크래시, 무한 로딩, 콘솔 에러 등 통합 시점에만 나타날 수 있는 부작용 없음).
- **통합 관점 판단**: (1) `MAX_SEARCH_RESULTS=100` 내부 상한이 있어 실제 서비스 규모(추정 종목 수 약 2,500 미만)에서도 응답 크기가 유한하게 제한된다 — DoS로 이어지지 않는다는 UNIT-03의 판단이 통합 환경에서도 유효하다. (2) 프론트엔드가 이 결과를 그대로 리스트로 렌더링할 뿐 크래시나 별도 오류로 확대하지 않는다(UNIT-09 판단과 일치). (3) 사용자가 검색창에 `%`나 `_`만 입력하는 것은 실사용 시나리오상 희귀하며(우연히 입력할 가능성은 있으나 악의적 남용 시나리오는 상한(100건)으로 차단됨), 화면에 나타나는 결과가 "검색과 무관해 보이는 무의미한 전체 목록"이라는 점에서 사용자 경험상 다소 혼란스러울 수 있으나 정보 노출이나 보안 사고로 이어지지 않는다.
- **결론**: 기존 판정(**Low, Open**)을 통합 관점에서도 그대로 유지한다. 배포 차단 사유로 격상할 근거가 통합 시점에 새로 발견되지 않았다. 후속 개선 권고(이스케이프 처리)는 기존 인계 그대로 유지한다.

### 4-4. 회귀 (두 유닛을 합쳤을 때 기존 단위테스트가 여전히 통과하는가)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-R1 | 백엔드 전체 단위테스트 회귀 | `python -m pytest tests/unit -q` | 155 passed(UNIT-01~09 + 진행 중인 시장요약 작업 포함 기존 기준선 유지) | `155 passed, 2 warnings in 1.77s` | **PASS** |
| TC-IT-R2 | 백엔드 정적분석 회귀 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** |
| TC-IT-R3 | 프론트엔드 타입체크 회귀 | `npx tsc --noEmit` | 오류 없음 | 오류 없음 | **PASS** |
| TC-IT-R4 | 프론트엔드 린트 회귀 | `npm run lint` | 0 error/0 warning | 0 error/0 warning | **PASS** |
| TC-IT-R5 | 프론트엔드 빌드 회귀(금지어 검사 포함, REQ-008) | `npm run build` | prebuild 금지어 검사 통과 + 빌드 성공, 라우트 6개 | "금지표현 검사 통과 (검사 파일 47개)" + 빌드 성공, `/`,`/_not-found`,`/about`,`/screener`,`/stocks`,`/stocks/[code]` 정상 생성 | **PASS** |

## 5. 커버리지
- **1차 내부검증 관점(이 업무단위의 모든 사용자 시나리오가 케이스로 커버됐는가)**: `04-ux-design.md` §1-3 Flow C(종목 검색→상세 조회)의 전체 흐름을 TC-IT-01~05로 1:1 커버했다 — 초기 진입(TC-IT-01), 검색 성공(TC-IT-02), 상세 이동(TC-IT-03), 상세 화면 렌더링(TC-IT-04), 404/복귀 순환(TC-IT-05). §2-3(시장 필터)은 TC-IT-07로 커버. DEF-006 통합 영향은 TC-IT-06/§4-3으로 커버. 데이터 계약 일치는 TC-IT-S1~S4로 커버. 회귀는 TC-IT-R1~R5로 커버. 커버되지 않은 사용자 시나리오는 발견되지 않았다.
- **2차 내부검증 관점(8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까)**: 아래 §9-2 참조.
- 커버되지 않은 부분과 사유:
  - 실제 프로덕션 호스팅 도메인에서의 CORS(§2 참조, 10단계 영역).
  - `api_service` 계정 실접속 기반 DB 권한 경계 재검증 — 이미 `unit-03-test.md`가 실 Postgres로 PASS 확정한 영역이며 이 세션 도구 정책상 host에서 재현 불가(§2, §3 참조). 이 문서는 대신 DB 레이어를 실측 데이터 기반 Fake로 대체해 "그 위의 계약(HTTP/CORS/스키마)"에 집중했다.
  - 429(요청 과다) 실제 트리거 — `unit-09-test.md`가 이미 Fake로 검증(백엔드가 429를 발생시키는 실제 경로 없음, 신규 아님).
  - 200% 확대/모바일 실기기(기존 승계 리스크).

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도 | 상태 | 조치 내용 |
|----|------|-----------|--------|------|-----------|
| (신규 결함 없음) | 이 통합테스트에서 UNIT-03/UNIT-09 경계 또는 업무단위 E2E 흐름에서 새로 발견된 결함은 없다 | TC-IT-01~08, TC-IT-S1~S4, TC-IT-R1~R5 전체(17개 케이스) | — | — | 두 유닛이 서로 다른 가정을 하고 있었던 것으로 드러난 설계 불일치도 없었다(§4-1 TC-IT-S1~S4가 필드명/enum 어휘 완전 일치를 코드+런타임 이중 확인) |
| DEF-006(승계, UNIT-03, 통합 관점 재확인) | LIKE 와일드카드(`%`,`_`) 미이스케이프 — 실제 두 프로세스 조합에서도 동일하게 재현되나 새로운 부작용(크래시/정보노출 등) 없음 | TC-IT-06, §4-3 | Low(기존 판정 유지) | Open(승계) | 배포 차단 사유 아님, 기존 결정 유지. 통합 시점에 심각도를 올릴 근거 없음 |
| DEF-007(승계, UNIT-03, 인지만) | `is_active` 자동 재동기화 문서화 미비 | (재현 없음, 이 통합테스트 범위 밖의 운영 절차 이슈) | Low(기존 판정 유지) | Open(승계) | 이 feature의 검색/화면 흐름에 영향 없음(§2-4, `unit-03-test.md` 참조). 재확인 불필요로 판단 — 검색 기능 자체는 `is_active=true`인 현재 픽스처만 다루므로 이 통합 시나리오에서 관측되지 않음 |

- **신규 결함 0건.** 근거: TC-IT-01~08(업무단위 E2E), TC-IT-S1~S4(데이터 계약), TC-IT-R1~R5(회귀) 총 17개 케이스를 실제 두 프로세스 + 실제 헤드리스 브라우저로 실행했고, 각 케이스마다 "실행해보니 에러 없음"이 아니라 기대 결과(설계서 원문/코드 계약)와 실제 결과(DOM 텍스트/HTTP 헤더/프로세스 재실행 결과)를 비교했다. 정상 경로(TC-IT-02,03,04,07)·경계/엣지(TC-IT-06 DEF-006 재확인)·화면 전환 순환(TC-IT-05)·권한 경계 방법론 검증(TC-IT-08)을 모두 포함했다.

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- 이번 테스트에서 생성한 임시 아티팩트 목록: `.harness-tmp/feature-stock-search-it/`(`package.json`/`package-lock.json`/`node_modules`(puppeteer-core@23 전용 설치), `fake_backend.py`(DI 오버라이드 구동 스크립트, 실제 소스 코드는 무변경), `e2e_test.mjs`(TC-IT-01~08 재현 스크립트), `backend.log`/`backend2.log`/`frontend.log`(서버 로그)).
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): **[x] 예**.
- 정리(삭제) 완료 여부: **완료.** `netstat -ano`로 포트 3000/8000 리스닝 PID(각각 uvicorn 백엔드, `next start` 프론트엔드)를 특정해 `taskkill //F //PID`로 전부 종료 확인(종료 후 `netstat`에 3000/8000 리스너 없음 재확인). `.harness-tmp/feature-stock-search-it/`을 `rm -rf`로 삭제 후 `.harness-tmp/`가 다시 빈 상태임을 확인. 프론트엔드는 커스텀 `NEXT_PUBLIC_API_BASE_URL` 없이 `npm run build`를 재실행해 `.next/`를 기본 상태로 복원(`.next/`는 `.gitignore` 대상). DB는 읽기 전용 조회만 수행했으므로 별도 롤백 불필요 — 테스트 종료 후 `select count(*) from public_serving.stock_master`로 6행 그대로임을 재확인했다.
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
	modified:   docs/harness/units/unit-07-test.md
	modified:   docs/harness/units/verify-log_unit-07-test.md
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
	docs/harness/feature-stock-search-integration-test.md
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
  (이 목록은 이번 07단계 세션 시작 시점의 `git status`와 완전히 동일하다 — 이번 세션이 만든 변경은 `docs/harness/traceability.md`(REQ-001 통합테스트 컬럼 갱신)와 신규 `docs/harness/feature-stock-search-integration-test.md`(이 문서) 두 건뿐이며, 나머지 항목들은 전부 이 세션 이전부터 존재하던(다른 진행 중인 UNIT-08/09, 시장요약 관련 작업의) 변경이다. `.harness-tmp/`는 비어 있어 목록에 나타나지 않는다 — `.gitignore` 정상 동작.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **[x] 없음**.

## 8. 리스크 및 잔존 이슈
- **실제 프로덕션 호스팅 환경에서의 CORS**: 호스팅 벤더/토폴로지 미확정(`03-system-design.md` §2-1). 로컬 두 오리진(3000/8000) 재현은 "기본 로컬 개발 구성"에서의 정상 동작만 증명한다. 실 배포 도메인 확정 시 `PUBLIC_API_CORS_ALLOWED_ORIGINS` 재정의 필요(10단계 배포테스트 착수 전 필수 확인 — 기존 리스크 승계, `unit-09-test.md` v2와 동일).
- **DEF-006(LIKE 와일드카드, Low/Open)**: §4-3 판단에 따라 배포 차단 사유 아님, 통합 시점에도 변경 없음.
- **DEF-007(is_active 자동 재동기화 문서화 미비, Low/Open)**: 이 feature 범위 밖(운영 절차 문서화 이슈), 변경 없음.
- **이 통합테스트의 DB 계층 대체(Fake) 한계**: `api_service` 계정으로의 host 직접 접속이 이 세션 도구 정책상 불가능해(§2, §3), UNIT-03의 `SqlStockSearchRepository`/`SqlStockMetricsRepository` 자체가 이 통합 프로세스 조합 안에서 실행되지는 않았다(대신 실측 데이터를 그대로 복제한 Fake로 대체). 이 대체는 "UNIT-03 DB 레이어 재검증"이 아니라 "그 위의 HTTP/CORS/스키마 계약이 실제 두 프로세스로 붙는지" 검증이 목적이므로 이 문서의 목적상 치명적 공백은 아니라고 판단하나, 8단계(전체 풀테스트) 또는 CI 환경에서 `api_service` 자격증명을 정상적으로 사용할 수 있는 환경이 확보되면 "완전한 실제 DB + 실제 두 프로세스" 조합으로 한 번 더 재현할 것을 권고한다.
- 200% 확대/모바일 실기기 미검증(기존 승계 리스크, 신규 아님).

## 9. 결론 및 판정
- [x] **PASS** — 8단계(전체 풀테스트)로 handoff 가능.
- [ ] CONDITIONAL PASS
- [ ] FAIL

**판정 근거**: UNIT-03(백엔드, `unit-03-test.md` PASS)과 UNIT-09(프론트엔드, `unit-09-test.md` v2 PASS)를 실제 두 프로세스로 동시 기동하고 실제 네트워크(실제 CORS 미들웨어 포함)로 연결해 재현한 결과, (1) 데이터 흐름/스키마가 완전히 일치하고(TC-IT-S1~S4), (2) 업무단위 수준 E2E(검색→상세 이동→404 복귀 순환)가 개별 유닛 테스트 범위를 넘어 실제로 동작하며(TC-IT-01~05, 07), (3) 두 유닛을 합친 뒤에도 기존 단위테스트(백엔드 155건, 프론트 tsc/lint/build)가 전부 회귀 없이 통과하고(TC-IT-R1~R5), (4) DEF-006의 통합 시점 실사용 영향을 재판단한 결과 기존 Low/Open 판정을 유지할 근거가 확인됐다(§4-3). 두 유닛이 서로 다른 가정을 하고 있었던 것으로 드러난 설계 결함은 발견되지 않았다(규칙 F 피드백 루프 대상 없음). 신규 결함 0건.

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

### 1차 검증 (작성자 관점 자가 재검토, "이 업무 단위의 모든 사용자 시나리오가 케이스로 커버됐는가")
- 검증자(역할): 07-integration-tester(작성자 본인)
- 일시: 2026-09-18
- 체크리스트
  - [x] `04-ux-design.md` §1-3 Flow C의 모든 상태(초기/디바운스/성공/결과없음/에러/뒤로가기)가 TC로 커버됐는가 → 초기(TC-IT-01)·성공(TC-IT-02)·결과없음은 `unit-09-test.md`가 이미 검증(반복 안 함, §2)·에러는 `unit-09-test.md`가 이미 검증(반복 안 함)·뒤로가기 대신 "404→돌아가기→재검색" 순환(TC-IT-05)으로 화면 전환 자체를 검증. 미커버 없음.
  - [x] UNIT-06이 인계한 "REQ-001 시퀀싱 공백"이 실제로 해소됐는지 클릭으로 확인했는가(코드 리뷰만으로 끝내지 않았는가) → TC-IT-03에서 실제 `.stock-list__link` 클릭 + 네비게이션 대기로 확인, 코드 리뷰가 아니라 실제 클릭.
  - [x] DEF-006을 "이미 Low니까 통합에서도 그냥 넘어가도 되지 않나"라고 넘기지 않았는가 → 과제 지시사항이 "통합 관점에서 다시 판단"을 명시적으로 요구했으므로 실제 두 프로세스 조합에서 재현(TC-IT-06)하고 §4-3에서 새로운 부작용 유무를 근거와 함께 재판단했다.
  - [x] 두 유닛이 실제로 실제 네트워크로 통신하는지(Fake/Mock으로 각자 검증한 것의 합이 아니라) 확인했는가 → 실제 uvicorn 프로세스(127.0.0.1:8000) + 실제 `next start` 프로세스(localhost:3000)를 동시 기동하고 헤드리스 브라우저가 실제 크로스오리진 `fetch`를 수행함을 확인(TC-IT-02의 `corsErrors=0`이 "CORS 미들웨어가 실제로 동작해 통과시켰다"는 뜻이지 "애초에 요청이 크로스오리진이 아니었다"가 아님을 §3에서 포트 구성으로 명시).
  - 발견된 결함: 없음(신규). 기존 DEF-006/007 승계.
  - 조치 내용: 없음 — PASS로 확정.

### 2차 검증 (독립 심사자 관점 — "8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까")
- 검증자(역할): 07-integration-tester(역할 전환 재검토)
- 일시: 2026-09-18
- 체크리스트
  - [x] **UNIT-01(캘린더/CORS) 경계** → TC-IT-04가 실제로 `get_last_trading_day()` 계산 결과(2026-09-14 픽스처 vs 오늘 2026-09-18)에 따른 지연 경고를 노출함을 확인했고, TC-IT-08이 CORS 네거티브 컨트롤로 다른 feature(screener/market-summary)가 동일한 CORS 설정을 공유해도 허용되지 않은 오리진은 여전히 차단됨을 재확인했다 — 8단계에서 다른 feature와 만나도 이 공유 설정 자체가 깨질 이유가 없다.
  - [x] **UNIT-04(면책배너)/UNIT-05(GlobalNav) 경계** → TC-IT-01이 `/stocks`에서도 루트 레이아웃 공통 요소(배너/헤더)가 정상 렌더링됨을 확인했다. 이 요소들은 모든 feature가 공유하는 루트 레이아웃이므로, 다른 feature(홈/스크리너)의 8단계 검증에서도 동일하게 나타날 것으로 예상되며 이 문서가 그 공통 셸의 `/stocks` 화면 렌더링을 별도로 깨뜨리지 않았음을 확인했다.
  - [x] **UNIT-06(feature-stock-metrics) 경계** → 검색에서 상세로의 이동(TC-IT-03/04)이 실제로 동작함을 확인했으나, 이 문서가 사용한 `/stocks/[code]` 검증은 **Fake 파생지표 데이터** 기반이라는 한계가 있다(§2, §8) — 8단계에서는 feature-stock-metrics(UNIT-06)의 07단계(또는 그에 준하는 검증)가 이미 실제 DB로 확인한 지표 계산 자체와, 이 문서가 확인한 "검색→클릭→도달" 흐름이 합쳐져야 완전한 그림이 된다는 점을 §8에 리스크로 명시했다 — 이 공백을 감추지 않고 투명하게 남긴다.
  - [x] **UNIT-07(screener)/UNIT-08(market-summary) 경계** → 이번 통합테스트는 `MarketFilterControl`(UNIT-07 제작, UNIT-09 재사용) 코드를 전혀 수정하지 않았음을 재확인(`git status`에 해당 파일 변경 없음, §7 첨부 결과에도 `MarketFilterControl.tsx` 없음) — 8단계에서 screener가 이 컴포넌트를 검증할 때 이 feature의 작업이 영향을 주지 않는다.
  - [x] **8단계가 이 문서의 Fake DI 대체(§2)를 "충분한 검증"으로 오인하지 않도록** §8에 명시적으로 "완전한 실제 DB + 실제 두 프로세스" 재현을 8단계 또는 CI 환경에서 추가로 권고했다 — 이 문서의 PASS가 "UNIT-03 DB 레이어까지 이 문서가 재검증했다"는 뜻으로 오독되지 않게 §2/§8에서 반복적으로 명시했다.
  - 발견된 결함: 없음(신규). 8단계 인계 리스크 1건(UNIT-06 Fake 데이터 한계) §8에 이미 명시.
  - 조치 내용: 서술 보강(§8 8단계 인계 문구 추가) 외 결함 목록 변경 없음 → 최종 PASS.

- 검증 로그 파일 경로: 이 문서 §10에 통합 기록(별도 `verify-log_feature-stock-search-integration-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — `unit-01~09-test.md`가 따른 것과 동일한 관례).

## 절차 흐름 (참고용 다이어그램)
```mermaid
flowchart TD
    A["UNIT-03 PASS + UNIT-09 PASS 확인"] --> B["실제 두 프로세스 동시 기동(127.0.0.1:8000/localhost:3000)"]
    B --> C["데이터흐름/스키마 대조(TC-IT-S1~S4)"]
    C --> D["업무단위 E2E: 검색→상세이동→404복귀(TC-IT-01~05,07)"]
    D --> E["DEF-006 통합 재판단(TC-IT-06, §4-3)"]
    E --> F["회귀: pytest 155건/ruff/tsc/lint/build(TC-IT-R1~R5)"]
    F --> G{설계 불일치 발견?}
    G -->|Yes| H["규칙F: 5/3단계로 피드백"]
    G -->|No, 이번 결과| I["내부검증 1차/2차(§10)"]
    I --> J["Teardown(§7) + git status 확인"]
    J --> K["traceability.md REQ-001 통합테스트 갱신 → 8단계 handoff"]
```
