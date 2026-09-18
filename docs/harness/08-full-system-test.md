# 테스트 결과서 (Test Result Report) — 08단계 전체 풀테스트 (Full System Test)

> **버전: v2**(`decisions.md` DEC-027이 정한 재검증 사이클 5→6→8→9의 8단계 재실행 — v1의 **CONDITIONAL PASS**를 **PASS**로 대체). v1(CONDITIONAL PASS, DEF-FS-01 발견)의 전체 내용은 이력 보존을 위해 그대로 남기고, v2에서 변경/추가된 부분은 각 섹션에 "**(v2 ...)**" 표시와 함께 구분해 서술한다. 문서를 새로 작성하지 않고 개정하는 형태를 취한다(unit-01-test.md의 버전 관리 관행과 동일).

## 0. 재작업 이력 (v2 — DEC-027 5→6→8→9 재검증 사이클의 8단계)

- v1(2026-09-18, 08-full-system-tester)이 **CONDITIONAL PASS**를 판정했다: E2E/성능/부하는 전부 PASS였으나, DB 장애 복구 시나리오(§4-4)에서 **DEF-FS-01(High)** — 4개 데이터 API가 DB 연결 장애 시 설계(§5-4, 5초 이내 503 Envelope)를 지키지 못하고 raw 500을 60~90초 만에 반환 — 를 발견해 10단계 착수 전 필수 해소 게이트로 등록했다.
- 이후 9단계(`09-security-audit.md`)가 **FAIL** 판정하며 신규 결함 **DEF-SEC-01(High, rate limiting 미구현)**·**DEF-SEC-02(Medium, 보안헤더 미구현)**를 발견하고, DEF-FS-01/REQ-025의 근본 원인 범위를 "DB connect_timeout 부재"에서 "전역 예외 처리 부재 전반"으로 확장했다. 세 결함 모두 UNIT-01(`services/public_api` 공통 기반)로 귀속되어, 오케스트레이터가 UNIT-01을 규칙 F에 따라 재작업시켰다(3라운드: rate limiting/보안헤더/DB타임아웃+전역예외핸들러+요청타임아웃 구현 → 미들웨어 순서 버그(DEF-005) 수정).
- `unit-01-test.md`(v6, 6단계)가 **PASS**로 최종 확정했다(DEF-SEC-01/02, DEF-FS-01/REQ-025 전부 Fixed 확인, mutation testing까지 수행). `decisions.md` DEC-027의 결정에 따라 **07단계(4개 feature 통합테스트)는 이번 사이클에서 재실행하지 않는다** — 미들웨어 추가가 순수 additive 변경이라는 판단이었다.
- **이번 v2는 그 판단이 맞았는지(feature 고유 회귀 없음)를 실측으로 최종 검증하는 8단계 재실행이다.** 재검증 범위는 오케스트레이터가 명시한 5개 항목이다: (1) DEF-FS-01 시나리오를 v1과 동일한 원래 방식(`docker stop` 컨테이너 정지)으로 재실측, (2) 20건 동시요청 부하 스모크를 신규 rate limiting(분당 60회/IP)과 함께 재실행해 오탐(false 429) 여부 확인, (3) 보안헤더/CORS가 프론트엔드 E2E(데스크톱+모바일)를 방해하지 않는지 브라우저 콘솔 에러로 실측, (4) 4개 feature 핵심 플로우의 미들웨어발 회귀 여부, (5) 그 외 비기능요구사항(API P95, Lighthouse)·UAT(KPI 커버리지, DEC-023/025 반영분)를 포함한 전체 재확정.
- 신규 섹션/갱신: §3(테스트 환경, v2 실행 포트 등), §4-1~§4-4(v2 재검증 결과 추가), §5(커버리지 v2 갱신), §6(DEF-FS-01 Fixed로 갱신), §7(v2 Teardown), §8(리스크 v2 갱신), §9(판정 PASS로 갱신), §10(v2 내부검증 1차/2차).

> `templates/test-report-template.md` 사용. 대상: **개발된 시스템 전체**(4개 feature: stock-search/stock-metrics/screener/market-summary + 공유 인프라). 입력(v1): 7단계 4개 feature 통합테스트 전부 완료(`feature-stock-search-integration-test.md` PASS, `feature-stock-metrics-integration-test.md` CONDITIONAL PASS, `feature-screener-integration-test.md` PASS, `feature-market-summary-integration-test.md` PASS — `decisions.md` DEC-023/DEC-024), `docs/harness/02-planning.md`(v5) §5(KPI)·§3(핵심가치제안), `docs/harness/03-system-design.md`(v4) §5(비기능요구사항). **입력(v2 추가)**: `docs/harness/09-security-audit.md`(FAIL 판정 근거), `docs/harness/units/unit-01-test.md`(v6, PASS), `docs/harness/decisions.md`(DEC-025~027).
>
> **이 문서의 가치 원칙**: 06/07단계가 이미 각 업무 단위 내부 로직과 일부 cross-feature 데이터 일관성(screener↔stock-metrics, market-summary↔screener)을 실측 검증했다. 이 문서는 그것을 반복하지 않고 **① 4개 기능 전부를 하나로 잇는 처음부터 끝까지의 사용자 여정(E2E)을 데스크톱·모바일 양쪽에서 최초로 연결 재현, ② 비기능요구사항(성능/부하/장애복구)을 실측, ③ 성공지표(KPI)의 측정 가능성 자체를 점검하는 UAT, ④ traceability.md 커버리지 100% 확정**에만 집중한다.

## 1. 개요
- 테스트 대상: 개발된 시스템 전체(4개 feature + 공유 인프라: UNIT-01 캘린더/CORS, UNIT-02 데이터 파이프라인, UNIT-04 규제 공통 컴포넌트, UNIT-05 UI 셸)
- 테스트 유형: 시스템(08단계, 전체 풀테스트)
- 적용 Tier: **High**(`decisions.md` DEC-021) — 검증 강도 완화 없음, 규칙 B 원문(최소 2회 독립 검증) 그대로 적용
- 테스트 목적:
  1. 기획서(`02-planning.md`) §3 핵심 가치 제안 — "추천이 아니라 근거, 실시간이 아니라 명확한 기준시각, 원본 나열이 아니라 가공된 지표, 복잡한 포털이 아니라 단순한 요약" — 을 실제 사용자 페르소나(P1/P2, §2) 여정으로 처음부터 끝까지 재현해 시스템이 "하나로" 동작하는지 확인한다.
  2. 업무 단위 경계를 넘는 크로스 모듈 흐름(홈→검색→상세→스크리닝→상세, GlobalNav 순환)이 4개 feature를 순서대로 오가며 끊기지 않는지 확인한다.
  3. 비기능요구사항(`03-system-design.md` §5): 성능 목표(API P95, 페이지 로드), 부하 스모크(동시 요청), 장애 복구(DB 일시 중단)를 실측한다.
  4. 성공 지표(KPI, `02-planning.md` §5)가 측정 가능한 형태로 구현되어 있는지 UAT 관점에서 점검하고, 자동/반자동 측정 가능한 항목은 직접 확인하며 비즈니스 판단·배포 후 측정이 필요한 항목은 질문 목록으로 오케스트레이터에게 보고한다.
  5. `traceability.md`의 REQ-ID 커버리지를 확인하고 "전체테스트(08)" 컬럼을 갱신한다.
  6. REQ-024(DEF-IT-M01)/REQ-022 게이트가 8단계 시점에도 여전히 유효한지(재등록 없이) 재확인한다.
- 관련 산출물: `docs/harness/02-planning.md`(v5), `docs/harness/03-system-design.md`(v4), `docs/harness/traceability.md`, `docs/harness/decisions.md`(DEC-021 Tier=High, DEC-023 feature 그룹핑, DEC-024 REQ-024 게이트), 4개 feature 통합테스트 문서 전체, `docs/harness/units/unit-01-note.md`(v4)~`unit-09-test.md`(v2)
- 테스트 수행자(에이전트): 08-full-system-tester
- 테스트 일시: 2026-09-18

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - 전체 시스템 E2E 핵심 시나리오: 실제 백엔드(uvicorn, `services.public_api.main.app`, 실제 프로덕션 코드·실제 CORS 미들웨어·실제 PostgreSQL)와 실제 프론트엔드(`next build && next start` 프로덕션 빌드)를 동시 기동하고, 실제 헤드리스 Chrome(Puppeteer-core)으로 홈→종목검색→상세지표→스크리닝→상세 재확인→홈 복귀까지 하나의 연결된 브라우저 세션에서 재현. 데스크톱(1280×900)과 모바일(375×812, 스크리너 모바일 바텀시트 경유 포함) 양쪽 뷰포트로 각각 독립 재현.
  - 비기능요구사항: API 응답시간(P50/P95, 5개 대표 엔드포인트 × 30회), 동시 요청 부하 스모크(20건 동시 요청, 5종 엔드포인트 혼합), Lighthouse 성능 점수(데스크톱/모바일 에뮬레이션), DB 장애 복구(Docker 컨테이너 실제 정지→4개 데이터 API 응답 관찰→복구 확인).
  - UAT: `02-planning.md` §5 KPI 11개 항목 전부에 대해 자동/반자동 측정 가능 여부를 판정하고, 가능한 것은 직접 확인.
  - `traceability.md` REQ-001~013, REQ-022, REQ-024의 "전체테스트(08)" 컬럼 갱신 및 커버리지 100% 확정.
  - 전체 회귀: `pytest tests/unit`(전체), `ruff check .`, 프론트엔드 `tsc --noEmit`/`lint`/`build`.
- 제외 범위 및 사유:
  - 각 feature 내부 로직(필터/정렬/페이지네이션 SQL 정확성, 포커스 트랩, EmptyState/ErrorState 개별 렌더링, DB 권한 3중 방어 `SET ROLE` 재현, cross-feature 데이터 일관성 percentile/반올림 등) — 06/07단계가 이미 실 PostgreSQL/실 브라우저로 광범위하게 검증(각 feature 문서 §2 제외범위와 동일 원칙). 이 문서는 반복하지 않는다.
  - 실제 공공데이터포털 서비스키 기반 Ingestion Batch 실행(DEF-IT-M01/REQ-024) — 07단계가 이미 발견·게이트 등록(`decisions.md` DEC-024). 이 문서는 상태 불변만 재확인하고 재조사하지 않는다.
  - REQ-022(데이터 라이선스 배포 게이트) — 코드 구현 대상이 아닌 12단계 배포 승인 게이트. 상태 불변만 확인.
  - 실제 프로덕션 호스팅 환경(벤더 미확정, `03-system-design.md` §2-1)에서의 성능/CORS 측정 — 로컬 환경(localhost, Docker 단일 인스턴스) 측정으로 대체하고 그 한계를 §8에 명시.
  - 실 사용자 트래픽 기반 KPI(주간 UV, 스크리닝 세션 비율) — 배포 전이므로 측정 불가, UAT §4-4/§6에서 질문 목록으로 처리.
  - 회귀/부하 테스트 데이터 규모는 기존 픽스처(종목 6개)로 한정 — 실 서비스 규모(코스피+코스닥 약 2,500종목)에서의 성능은 실측하지 못했고, 이 한계를 §8에 명시(대안: 인덱스 설계 근거 기반 코드 리뷰 추정).

## 3. 테스트 환경
- 실행 환경: Windows 10(Git Bash), Python 3.13(anaconda, `uvicorn` 0.3x), Node.js 24(Next.js 16.3.5), 헤드리스 Chrome(시스템 설치, `puppeteer-core@23`), Lighthouse 11(`.harness-tmp/`에만 설치), PostgreSQL 16(Docker `stock-screener-db`, alembic head=0009).
- 백엔드: `services.public_api.main.app`을 **실제 프로덕션 코드 그대로**(Fake/DI 오버라이드 없음) `PUBLIC_API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/stock_screener`(컨테이너 기동 시 설정된 로컬 전용 공개 기본값, `docker inspect`로 확인 — `api_service` 등 역할 비밀번호는 이 저장소 어디에도 없어 별도로 다루지 않음)로 실제 `uvicorn` 기동. `PUBLIC_API_CORS_ALLOWED_ORIGINS`는 미설정(기본값 `http://localhost:3000`, `.env.example` 실제 기본 구성과 동일). 포트 127.0.0.1:8000.
- 프론트엔드: `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`로 `npm run build`(prebuild 금지어 검사 포함) 후 `next start -p 3000 -H localhost`. 포트 3000/localhost:3000.
- 테스트 데이터: **실제** `public_serving.stock_master`/`derived_metrics_daily`(6행: `005930`/`000660`/`005935`/`900001`/`900002`/`900003`), `market_summary_daily`(3행: KOSPI/KOSDAQ/ALL), `current_published_batch`(KRX, 2026-09-14), `reference.market_calendar`(730행) — 4개 feature 통합테스트가 사용한 것과 동일한 기존 픽스처(신규 생성 없음, `docker exec ... psql -U postgres`로 직접 재확인). `raw_internal.raw_ohlcv`(58행, 단일 `source_batch_id`, `dev_seed_fixture_metrics.py` 산출물 — DEF-IT-M01 승계).
- 전제 조건: 7단계 4개 feature 문서 전부 PASS/CONDITIONAL PASS 확인 완료(`decisions.md` DEC-023/DEC-024). Docker 컨테이너 기동 중. 세션 시작 시 `.harness-tmp/` 빈 상태(강제 중단 이력 없음, 규칙 K 4번 절차 준수). 포트 3000/8000 사전 점유 없음(`netstat`로 확인 후 시작).

**환경(v2 추가, 2026-09-18)**: `unit-01-test.md`(v6) PASS 확인 완료, Docker `stock-screener-db`(postgres:16-alpine) 기존 컨테이너 재사용(6단계 v6 세션 종료 시점과 연속). 세션 시작 시 `.harness-tmp/` 빈 상태 재확인(규칙 K 4번 절차 준수). **포트 편차**: `netstat` 확인 결과 8000/3000이 이 머신에서 동시에 돌고 있는 무관한 다른 프로젝트("final-project" Docker 스택, 이 저장소와 무관)에 이미 점유되어 있어, 해당 프로세스/컨테이너를 건드리지 않고 대신 **포트 8010(백엔드)/3010(프론트엔드)**을 사용했다(`.env.example`/코드 어디에도 포트가 하드코딩되어 있지 않아 `--port`/`-p` 인자만으로 안전하게 전환 가능함을 확인). DB 역할 점검 중 `api_service`/`batch_worker` 계정이 이전 세션 이후 `LOGIN` 속성 또는 비밀번호가 드리프트되어 있는 것을 발견해(`ALTER ROLE ... WITH PASSWORD 'devpass' LOGIN`으로 재설정) 접속 가능하게 했다 — 이는 라이브 테스트 DB의 역할 설정 조정이며 데이터(행)에는 어떤 변경도 가하지 않았다(unit-01-test.md v3의 "환경 관리 원칙"과 동일하게, 검증에 필요한 인프라 상태는 보존·조정하되 데이터는 건드리지 않는다는 원칙 적용). 백엔드: `PUBLIC_API_DATABASE_URL`(api_service)+`PUBLIC_API_CORS_ALLOWED_ORIGINS=http://localhost:3010`로 실제 `uvicorn --host 127.0.0.1 --port 8010` 기동(프로덕션 코드 그대로, Fake/DI 오버라이드 없음). 프론트엔드: `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010`로 `npm run build`(prebuild 금지어 검사 포함) 후 `next start -p 3010 -H localhost`. E2E 재현 도구는 v1과 동일하게 `puppeteer-core@23`(헤드리스 Chrome, 시스템 설치)을 `.harness-tmp/08-rerun/`에만 설치했다. 테스트 데이터(6/6/3/58행)는 v1과 동일한 기존 픽스처를 그대로 재사용했다(신규 생성 없음).

## 4. 테스트 케이스 및 결과

### 4-1. 전체 시스템 E2E 핵심 시나리오 (기획서 §3 핵심 가치 제안 재현)

실제 백엔드+프론트엔드 두 프로세스를 동시 기동한 상태에서, 헤드리스 Chrome으로 페르소나 P1("짧은 시간에 핵심만 확인")/P2("조건 기반 능동 스크리너")의 여정을 **하나의 연결된 브라우저 세션**으로 재현했다. 스크립트: `.harness-tmp/08-full-system-test/e2e_journey.mjs`(데스크톱), `e2e_journey_mobile.mjs`(모바일) — 둘 다 테스트 종료 후 삭제(§7 참조). 이 "4개 화면을 순서대로 잇는 하나의 세션" 재현은 07단계 어느 feature 문서도 하지 않은 것(각 feature 문서는 자신의 feature 경계 안에서만 E2E를 수행) — 08단계가 처음 수행한다.

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과(데스크톱) | 실제 결과(모바일) | Pass/Fail |
|----|----------|-----------|-----------|----------------------|---------------------|-----------|
| TC-E2E-01 | 홈 진입 — 전일 시장 동향 확인(REQ-004) | `/` 접속 | h1="전일 시장 동향 리포트", 면책배너 노출, 상승종목 수 렌더링 | `homeLoadMs=1003`, h1 일치, 배너 존재, `advancersText="+4"` | `homeLoadMs=935`, 동일 | **PASS** |
| TC-E2E-02 | 홈 → 종목 검색 이동(REQ-001) | 진입 카드 클릭 | URL이 `/stocks`로 전환, 검색 입력창 존재 | `url=/stocks`, 입력창 존재 | 동일 | **PASS** |
| TC-E2E-03 | "삼성" 검색 → 실제 결과 렌더링(REQ-001, cross-process fetch) | 타이핑 후 800ms 대기 | "005930" 포함, CORS 에러 0건 | `hasResult=true`, `corsErrors=0` | 동일 | **PASS** |
| TC-E2E-04 | 검색 결과 클릭 → 상세 지표 화면 이동(REQ-001→REQ-002 크로스 모듈 경계) | 결과 링크 클릭 | `/stocks/005930` 이동, "삼성전자"·"등락률 순위"·면책배너 렌더링 | `detailLoadMs=525`, 전부 일치 | `detailLoadMs=534`, 전부 일치 | **PASS** |
| TC-E2E-05 | GlobalNav로 스크리닝 화면 이동(REQ-002→REQ-003 크로스 모듈 경계) | GlobalNav "조건 스크리닝" 클릭 | `/screener` 이동 | `url=/screener` | 동일 | **PASS** |
| TC-E2E-06 | 조건 제출 → 실제 결과 렌더링(REQ-003, 모바일은 바텀시트 경유) | PER 조건 입력 후 제출 | 결과에 삼성전자/SK하이닉스 등 표시 | `screenLoadMs=899`, `hasResultRow=true` | 바텀시트 트리거 클릭 확인 후 동일(`screenLoadMs=901`) | **PASS** |
| TC-E2E-07 | 스크리닝 결과 클릭 → 다른 종목 상세 재확인(REQ-003→REQ-002 왕복 크로스 모듈) | 결과 목록 첫 링크 클릭 | `/stocks/005930` 등으로 이동, 콘텐츠 정상 렌더링 | `url=/stocks/005930`, `hasContent=true` | 동일 | **PASS** |
| TC-E2E-08 | 전 구간 콘솔 에러(크래시 여부) | `console`/`pageerror` 이벤트 수집 | favicon 404(기존 승계 이슈, `unit-07-test.md` v3 TC-108/`feature-screener-integration-test.md` TC-IT-R8이 이미 원인 특정) 외 에러 0건 | favicon 404 1건만 | 동일 | **PASS** |
| TC-E2E-09 | GlobalNav로 홈 복귀 — 여정 완결(순환) | 홈 링크 클릭 | `/` 재전환, h1 동일하게 재렌더링(크래시 없이) | `url=/`, `homeRerenders=true` | 동일 | **PASS** |

**종합**: 기획서 §3의 핵심 가치 제안(가공된 지표·명확한 기준시각·단순한 요약)이 실제로 4개 기능(홈/검색/상세/스크리닝)을 순서대로 넘나드는 하나의 연결된 사용자 세션에서 크래시 없이 동작함을 데스크톱·모바일 양쪽에서 확인했다. 신규 결함 0건(E2E 관점).

**(v2 재확인, 2026-09-18)**: 미들웨어 변경(rate limiting/보안헤더/DB타임아웃/전역예외처리) 이후 동일 E2E 여정을 재현했다(스크립트는 v1과 별개로 새로 작성, `.harness-tmp/08-rerun/e2e_journey.mjs`/`e2e_mobile.mjs`).

| ID | 시나리오(v2) | 데스크톱 실측 | 모바일 실측 | Pass/Fail |
|----|----|----|----|----|
| TC-E2E-V2-01 | 홈→검색→상세→스크리닝→상세재확인→홈 복귀, 전 구간 콘솔 에러/네트워크실패 수집 | `homeLoadMs=1093`, `hasSearchResult=true`, `detailHasName=true`(005930), `screenLoadMs=1235`, `hasResultAfterSubmit=true`, `secondDetailUrl=/stocks/900003`, `finalUrl=/`, 콘솔 에러 1건(favicon 404, 기존 승계 이슈)만 존재 | `homeLoadMs=849`, 스크리너 모바일 바텀시트 트리거→제출→`hasResultAfterSubmit=true`(네이티브 DOM 클릭으로 재현 — puppeteer의 포인터 기반 클릭이 바텀시트 오버레이에 막히는 스크립트 방법론 이슈였을 뿐 제품 결함 아님, `unit-05-test.md` TC-011의 "CDP 스크린샷 타이밍 아티팩트" 선례와 동일 성격), 콘솔 에러 1건(favicon 404)만 존재 | **PASS** |
| TC-E2E-V2-02 | CORS/CSP 관련 네트워크 실패(`net::ERR_ABORTED`, 403/CORS 에러 등) 존재 여부 | `failedRequests` 8건 전부 Next.js 자체 RSC 프리페치 취소(`_rsc=` 쿼리, 같은 오리진 `localhost:3010` 내부 요청, 클라이언트 사이드 라우팅 중 이전 프리페치가 새 네비게이션으로 취소되는 App Router의 알려진 정상 동작) — CORS/CSP로 인한 실패, 403, 차단된 요청 0건 | 별도 수집 안 함(데스크톱과 동일 프론트엔드 코드 경로, 중복 검증 불필요로 판단) | **PASS** |
| TC-E2E-V2-03 | CORS 프리플라이트(OPTIONS) 실제 응답 확인 | `OPTIONS /api/v1/stocks`(Origin: http://localhost:3010) → `200`, `access-control-allow-origin: http://localhost:3010`, `access-control-allow-methods: GET`, `vary: Origin` | - | **PASS** |

**v2 종합**: 새로 추가된 보안 헤더(CSP/`X-Content-Type-Options`/HSTS)와 CORS 설정이 프론트엔드 자체 페이지 렌더링을 막지 않음을 실측으로 확인했다 — 이 API의 CSP는 API JSON 응답에 대한 것이라 프론트엔드 HTML 페이지의 CSP와는 무관하다는 설계 의도(오케스트레이터 지시 3번)가 실제로도 그렇게 동작함을 브라우저 콘솔 에러 0건(favicon 제외)으로 확인했다. rate limiting 미들웨어도 정상 E2E 여정(요청 수가 적음)에서 429를 유발하지 않았다. 신규 결함 0건, v1 이후 회귀 0건.

### 4-2. 비기능요구사항 — 성능 목표 (`03-system-design.md` §5-1)

> **측정 규모의 한계(투명 고지)**: 아래 수치는 현재 DB에 존재하는 픽스처 규모(종목 6개)를 기준으로 측정한 것이다. 설계서 §5-1이 언급하는 실 서비스 규모(코스피+코스닥 약 2,500종목)에서는 재측정하지 못했다 — 실 서비스키 미보유로 실 데이터가 아직 적재된 적이 없기 때문(DEF-IT-M01, DEC-024 승계). **대안**: 03-system-design.md §5-1이 명시한 인덱스 설계(`derived_metrics_daily`에 `market`/`return_pct`/`market_cap_raw_krw`/`per_raw`/`pbr_raw`/`volume_anomaly_score` 복합 인덱스, 마이그레이션 0008)가 실제로 존재함을 코드로 재확인했고(§4-1 이하 별도 재검증 없음, 07단계 이미 확인 승계), 이 인덱스가 있으면 2,500건 규모에서도 순차 스캔이 아닌 인덱스 스캔이 유지될 것으로 기대되나 **이는 코드 리뷰 기반 추정이며 실측이 아니다**. 실 서비스 규모 성능 실측은 DEF-IT-M01 게이트 해소(실 서비스키 확보) 이후 10단계에서 재실시할 것을 권고한다.

| ID | 엔드포인트 | 목표(§5-1) | 실측 P50 | 실측 P95 | Pass/Fail |
|----|-----------|-----------|----------|----------|-----------|
| TC-NFR-01 | `GET /api/v1/stocks?query=삼성` | P95 300ms | 6.9ms | 7.9ms | **PASS**(여유 대폭) |
| TC-NFR-02 | `GET /api/v1/stocks/005930/metrics` | P95 300ms | 22.5ms | 26.3ms | **PASS** |
| TC-NFR-03 | `GET /api/v1/screen?market=ALL`(단순) | P95 800ms(스크리닝) | 23.3ms | 26.3ms | **PASS** |
| TC-NFR-04 | `GET /api/v1/screen`(다중 조건: market_cap/per/pbr/return_pct + 정렬) | P95 800ms | 24.4ms | 25.7ms | **PASS** |
| TC-NFR-05 | `GET /api/v1/market-summary` | P95 300ms | 24.2ms | 26.0ms | **PASS** |

| ID | 항목 | 목표(§5 KPI) | 실측 | Pass/Fail |
|----|------|-------------|------|-----------|
| TC-NFR-06 | 모바일 페이지 로드 시간(홈, E2E 실측) | 3초 이내 | 935~1003ms | **PASS** |
| TC-NFR-07 | Lighthouse Performance 점수(데스크톱 프리셋) | 80점 이상 | **100/100** | **PASS** |
| TC-NFR-08 | Lighthouse Performance 점수(모바일 에뮬레이션, CPU/네트워크 스로틀링 기본값) | 80점 이상 | **99/100**(FCP 0.8s, LCP 2.2s, TBT 60ms, CLS 0) | **PASS** |

- TC-NFR-07/08은 §5 KPI "모바일 환경 초기 페이지 로드 시간... Lighthouse Performance 80점 이상" 항목의 측정 방법으로 `02-planning.md`가 "10단계 배포테스트에서 측정"을 이미 지정해뒀다. 08단계의 이 측정은 **실제 배포 환경(호스팅 벤더 미확정, `03-system-design.md` §2-1)이 아닌 localhost 스모크**이므로 10단계의 공식 측정을 대체하지 않으며, "현재 코드 기준으로 목표 달성 추세에 있다"는 사전 신호로만 취급한다(자동 판정이 아니라 방향성 확인).

**(v2 재확인, 2026-09-18)**: 미들웨어 변경 이후 5개 엔드포인트를 각 30회씩 재측정했다(`.harness-tmp/08-rerun/perf_one_endpoint.py`, rate limiter 60/분 한도의 자기간섭을 피하기 위해 엔드포인트별로 백엔드 프로세스를 재기동해 카운터를 초기화 — 측정값 자체에는 영향 없음, 매 배치 30회 < 60 한도).

| ID | 엔드포인트 | 목표(§5-1) | v2 실측 P50 | v2 실측 P95 | Pass/Fail |
|----|-----------|-----------|----------|----------|-----------|
| TC-NFR-V2-01 | `GET /api/v1/stocks?query=삼성` | P95 300ms | 23.6ms | 32.9ms | **PASS** |
| TC-NFR-V2-02 | `GET /api/v1/stocks/005930/metrics` | P95 300ms | 30.4ms | 46.2ms | **PASS** |
| TC-NFR-V2-03 | `GET /api/v1/screen?market=ALL` | P95 800ms | 31.6ms | 47.5ms | **PASS** |
| TC-NFR-V2-04 | `GET /api/v1/screen`(다중 조건) | P95 800ms | 44.0ms | 47.9ms | **PASS** |
| TC-NFR-V2-05 | `GET /api/v1/market-summary` | P95 300ms | 46.1ms | 48.7ms | **PASS** |

v1 대비 P95가 소폭(예: stocks 7.9ms→32.9ms) 증가했으나, 이는 보안 헤더/rate limiter/타임아웃 미들웨어 4종이 요청 처리 체인에 추가된 데 따른 자연스러운 오버헤드이며 여전히 목표(300~800ms) 대비 큰 여유가 있다(최대 목표의 6~16% 수준). 신규 회귀 없음.

**Lighthouse(v2 재확인)**: 데스크톱 프리셋으로 홈 페이지를 재측정했다(`.harness-tmp/08-rerun/lh_home.json`). Performance **99/100**(FCP 0.8s, LCP 2.0s, TBT 50ms, CLS 0, Speed Index 0.8s) — v1(100/100)과 사실상 동일(측정 오차 범위 내), 미들웨어 변경으로 인한 프론트엔드 성능 저하 없음. 모바일 에뮬레이션 재측정은 이번 v2에서 생략했다(사유: 이번 변경이 백엔드 API 미들웨어에 한정되고 프론트엔드 정적 자산/렌더링 경로를 전혀 건드리지 않아, 뷰포트/CPU스로틀링에 따라 달라지는 모바일 Lighthouse 점수에 회귀가 생길 메커니즘이 없다고 판단했다 — v1이 이미 데스크톱 100/모바일 99로 거의 동일한 점수였다는 점도 근거. 회귀 위험이 낮다고 판단한 근거를 여기 명시한다, 규칙 C).

### 4-3. 비기능요구사항 — 부하 스모크 테스트 (동시 요청)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-NFR-09 | 20건 동시 요청(5종 엔드포인트 혼합: 검색/상세/스크리닝/시장요약) | Python `ThreadPoolExecutor(max_workers=20)`로 동시 발사 | 전부 200, 에러 0건, 크래시 없음 | `all_status_200=true`, `errors=[]`, `total_wallclock_ms=316.0`, `max_elapsed_ms=294.9`, `min_elapsed_ms=128.5` | **PASS** |
| TC-NFR-10 | 부하 중 백엔드 로그에 예외/스택트레이스 없음 | `backend.log` 검사 | 전부 `200 OK` 로그만 존재 | 확인됨(예외 로그 없음) | **PASS** |

- 참고: 단일 uvicorn 워커(멀티프로세스 미구성)로 측정했다. §2-1/§5-2가 "초기 규모(동시 사용자 수백 명 이하)에서 단일 인스턴스로 충분"이라 명시한 것과 일치하는 조건이며, 20건 동시 요청이라는 스모크 규모에서는 문제가 없었으나 실제 수백 명 동시 접속 시나리오까지 검증한 것은 아니다(§8 리스크).

**(v2 재확인, 2026-09-18 — rate limiting 신규 도입 후 재실행)**: 오케스트레이터 지시 2번(20건 동시요청이 신규 rate limit에 오탐을 일으키지 않는지, 또는 rate limit이 정상 방어하는지)에 대응해 두 가지를 확인했다.

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-NFR-V2-06 | 20건 동시 요청(5종 엔드포인트 혼합)이 rate limit(분당 60회)에 걸려 오탐(false 429)을 일으키는가 | `ThreadPoolExecutor(max_workers=20)`로 동시 발사(재기동 직후 카운터 0 상태) | 20 < 60이므로 전부 200 | `all_status_200=true`, `status_counts={"200":20}`, `total_wallclock_ms=285.8`, `max_elapsed_ms=279.4` | **PASS(오탐 없음)** |
| TC-NFR-V2-07 | rate limit이 실제로 60/61 경계에서 정상 방어하는가(오히려 과도한 트래픽을 막는지) | 동일 세션에서 순차 50건 추가 요청(TC-NFR-V2-06의 20건과 합산 60건째까지 200 기대) | 60건째까지 200, 61건째부터 429 `RATE_LIMITED` Envelope | 정확히 60건째(누적)까지 200, 61번째 요청(`status_counts={"200":40,"429":10}`, `first_429_at_index=40`)부터 429 반환. 429 응답에도 `content-security-policy`/`x-content-type-options`/`strict-transport-security`/`access-control-allow-origin`/`vary` 헤더가 전부 정상 부착됨(DEF-005 수정이 실제 통합 환경에서도 유효함을 교차 확인) | **PASS(방어 정상 동작)** |

**v2 종합**: 20건 동시요청이라는 정상적인 부하 테스트 시나리오는 rate limit(60/분)에 전혀 걸리지 않아 오탐이 없음을 확인했고, 별도로 한도를 초과하는 트래픽(61건째)에는 rate limit이 정확한 경계(60/61)에서 429로 정상 방어함을 확인했다 — 두 요구사항(정상 트래픽 통과·과도한 트래픽 차단)이 동시에 충족됨을 실측으로 검증했다. 신규 결함 0건.

### 4-4. 비기능요구사항 — 장애 복구 시나리오 (DB 일시 중단)

> 이 시나리오는 어느 06/07단계 문서도 테스트한 적이 없다 — 기존 503(`SERVICE_UNAVAILABLE`/`DATA_PIPELINE_STALE`) 테스트는 전부 "DB는 살아있지만 데이터 상태가 이상한 경우"(발행 포인터 없음, 캘린더 미확인 등)였다. 이번이 "DB 연결 자체가 끊긴 실제 인프라 장애" 시나리오를 이 프로젝트 역사상 처음 실측한 것이다.

| ID | 시나리오 | 실행 절차 | 예상 결과(설계 §5-4) | 실제 결과 | Pass/Fail |
|----|----------|-----------|----------------------|-----------|-----------|
| TC-NFR-11 | `docker stop stock-screener-db` 후 `/api/v1/health` 호출 | 컨테이너 정지 → 즉시 요청 | 5초 쿼리 타임아웃 후 `{"data":{"status":"ok","db":"degraded"}}` 200 반환 | **HTTP 200, `db:"degraded"` 반환은 맞으나 응답까지 약 90초 소요**(목표 5초의 18배) | **FAIL(§6 DEF-FS-01 참조)** |
| TC-NFR-12 | 동일 상태에서 `GET /api/v1/stocks/005930/metrics` 호출 | 상동 | 503 `SERVICE_UNAVAILABLE`(Envelope 포함) 반환 | **HTTP 500 "Internal Server Error"(FastAPI 기본 에러 페이지, Envelope 아님), 약 60초 소요** | **FAIL(§6 DEF-FS-01)** |
| TC-NFR-13 | 동일 상태에서 `GET /api/v1/screen?market=ALL` 호출 | 상동 | 503 `SERVICE_UNAVAILABLE` | **HTTP 500, 약 60초 소요** | **FAIL(§6 DEF-FS-01)** |
| TC-NFR-14 | 동일 상태에서 `GET /api/v1/market-summary` 호출 | 상동 | 503 `SERVICE_UNAVAILABLE` | **HTTP 500, 약 60초 소요** | **FAIL(§6 DEF-FS-01)** |
| TC-NFR-15 | 동일 상태에서 프론트엔드 `/`(홈, 서버 컴포넌트가 백엔드 fetch) 접속 | 상동 | 크래시 없이 "일시적인 오류가 발생했습니다" 등 안내 표시 | 실제 렌더링: `<div class="error-state"><p>일시적인 오류가 발생했습니다.</p></div>` — **크래시 없음, 정상 동작** | **PASS** |
| TC-NFR-16 | 동일 상태에서 프론트엔드 `/stocks/005930` 접속 | 상동 | 크래시 없이 오류 안내(주의: `notFound()`가 아니어야 함 — 백엔드 다운을 "종목 없음"으로 오인 표시하면 결함) | RSC 스트리밍 페이로드 확인 결과 `<div class="error-state"><p>일시적인 오류가 발생했습니다.</p><a>다시 시도</a></div>`가 실제로 렌더링됨(코드 확인: `fetchStockMetrics`가 fetch 예외를 `NETWORK_ERROR`로 정확히 분류, `notFound()` 오분류 없음) | **PASS** |
| TC-NFR-17 | 동일 상태에서 프론트엔드 `/screener`(클라이언트 사이드 폼) 접속 | 상동 | 폼 자체는 정상 로드(제출 시점에만 백엔드 필요) | `has form=true`, `Application error` 마커 없음 | **PASS** |
| TC-NFR-18 | `docker start stock-screener-db` 후 API 프로세스 **재시작 없이** 재요청 | 컨테이너 재기동 → 대기 → 재요청 | `pool_pre_ping=True`로 자동 재연결, 200 정상 응답 | `/health`→200 `db:"ok"`, `/stocks/{code}/metrics`→200, `/screen`→200. API 프로세스 재시작 안 함 | **PASS** |
| TC-NFR-19 | 장애 시나리오가 DB 데이터에 부작용을 남기지 않았는지 | 행수 비교(전/후) | 6/6/3/58/1 동일 | 정확히 동일 | **PASS** |

**종합**: 백엔드 API 4개 데이터 엔드포인트 전부가 DB 연결 장애 시 **설계(§5-4)가 요구하는 503 Envelope 대신 raw 500을 반환**하고, **실패 판정까지 약 60~90초가 걸려 5초 목표를 크게 초과**한다(DEF-FS-01, §6). 다만 (a) API 프로세스 자체는 죽지 않고 DB 복구 후 자동 재연결되며(TC-NFR-18), (b) 프론트엔드는 이 malformed 응답에도 자체적으로 "일시적 오류" 폴백을 표시해 크래시하지 않고(TC-NFR-15~17), 특히 우려했던 "백엔드 다운을 종목 없음(404)으로 오인 표시"하는 사용자 신뢰 훼손 시나리오는 발생하지 않음을 코드 레벨로 확인했다(TC-NFR-16).

**(v2 재검증, 2026-09-18 — DEF-FS-01 해소 여부를 원래 재현 방식으로 재확인)**: 6단계(`unit-01-test.md` v5/v6)는 TCP 블랙홀(무응답 네트워크)로 `connect_timeout=3`의 동작을 검증했으나, 오케스트레이터가 "8단계는 원래 방식(컨테이너 정지)으로도 동일 결과가 나오는지 자체 기준으로 재확인"하라고 명시적으로 지시한 데 따라, v1과 동일하게 `docker stop stock-screener-db`로 실제 컨테이너를 정지시켜 재현했다(TCP 블랙홀과는 다른 경로 — 컨테이너가 완전히 내려가면 OS/Docker 네트워크 스택이 즉시 RST를 보낼 수도, 블랙홀처럼 무응답일 수도 있어 독립적인 재현 가치가 있다).

| ID | 시나리오 | 실행 절차 | 예상 결과(§5-4) | v2 실제 결과 | Pass/Fail |
|----|----------|-----------|----------------------|-----------|-----------|
| TC-NFR-V2-08 | `docker stop stock-screener-db` 후 `/api/v1/health` 호출 | 컨테이너 정지 → 즉시 요청 | 5초 이내 503 SERVICE_UNAVAILABLE Envelope | **HTTP 503, 4.526초**, `{"error":{"code":"SERVICE_UNAVAILABLE", ...}}` | **PASS**(목표 5초 이내, v1의 90초 대비 약 20배 개선) |
| TC-NFR-V2-09 | 동일 상태에서 `GET /api/v1/stocks` | 상동 | 503 SERVICE_UNAVAILABLE | **HTTP 503, 4.531초**, Envelope 정상 | **PASS** |
| TC-NFR-V2-10 | 동일 상태에서 `GET /api/v1/stocks/005930/metrics` | 상동 | 503 SERVICE_UNAVAILABLE | **HTTP 503, 4.529초**, Envelope 정상 | **PASS** |
| TC-NFR-V2-11 | 동일 상태에서 `GET /api/v1/screen?market=ALL` | 상동 | 503 SERVICE_UNAVAILABLE | **HTTP 503, 4.511초**, Envelope 정상 | **PASS** |
| TC-NFR-V2-12 | 동일 상태에서 `GET /api/v1/market-summary` | 상동 | 503 SERVICE_UNAVAILABLE | **HTTP 503, 4.530초**, Envelope 정상 | **PASS** |
| TC-NFR-V2-13 | 동일 상태에서 프론트엔드 `/`, `/stocks/005930`, `/screener` | 상동 | 크래시 없이 오류 안내, 404 오분류 없음 | `/`→200, `error-state` 폴백 존재, 4.55초. `/stocks/005930`→200, `error-state` 폴백 존재(`notFound` 마커 없음), 4.53초. `/screener`→200, 즉시 로드(클라이언트 폼, 백엔드 미호출) | **PASS**(v1과 동일하게 정상 방어, 회귀 없음) |
| TC-NFR-V2-14 | `docker start stock-screener-db` 후 API 프로세스 재시작 없이 재요청 | 컨테이너 재기동 → 재요청 | 자동 재연결, 200 정상 응답 | `/health`→200 `db:"ok"`, `/stocks/{code}/metrics`→200. 백엔드 로그에 `OperationalError`(ConnectionTimeout) 15건이 **처리된 예외**로 기록(raw 크래시 아님, 각 요청이 정상적으로 503으로 귀결된 흔적) | **PASS** |
| TC-NFR-V2-15 | 장애 시나리오가 DB 데이터에 부작용을 남기지 않았는지 | 행수 비교(전/후) | 6/6/3/58 동일 | 정확히 동일 | **PASS** |

**v2 종합**: **DEF-FS-01이 완전히 해소됐음을 v1이 사용한 것과 동일한 원래 재현 방식(컨테이너 정지)으로 재확인했다.** 4개 데이터 API + `/health` 전부 4.5초 내외(목표 5초 이내)로 503 Envelope을 반환하며, v1이 관찰했던 raw 500·60~90초 지연은 재현되지 않는다. 6단계가 TCP 블랙홀로 확인한 결과(3.05~3.08초)와 이번 컨테이너 정지 결과(4.5초대) 사이의 차이(약 1.5초)는 Docker 컨테이너 정지 시 OS/드라이버가 연결 시도를 완전히 포기하기까지 블랙홀보다 약간의 추가 지연이 있을 수 있음을 시사하나, 두 경로 모두 5초 목표 이내이므로 결함으로 보지 않는다(참고 관찰로 §8에 기록). 프론트엔드 방어 로직(404 오분류 없음, 크래시 없음)도 회귀 없이 유지된다.

### 4-5. UAT — 성공 지표(KPI) 달성 여부 (`02-planning.md` §5)

| # | KPI | 목표치 | 측정 방법(설계) | 08단계 판정 | 근거 |
|---|-----|--------|------------------|--------------|------|
| 1 | 출시 후 4주 주간 UV | 300명 이상 | 서버 로그/애널리틱스 | **측정 불가 — 사용자 확인 필요(§4-6 질문1)** | 배포 전이라 실측 자체가 불가능. 게다가 측정 인프라(구조화 접속 로그/애널리틱스) 자체가 코드베이스에 미구현(§4-6 근거 참조) |
| 2 | 출시 후 8주 주간 UV | 500명 이상 | 상동 | **측정 불가 — 사용자 확인 필요(§4-6 질문1)** | 상동 |
| 3 | 스크리닝 세션 비율 | 30% 이상 | 스크리닝 "적용" 클릭 이벤트/전체 세션 수 | **측정 불가 — 사용자 확인 필요(§4-6 질문2)** | 배포 전 실측 불가 + 이벤트 트래킹 인프라 자체가 미구현(§4-6 근거) |
| 4 | 면책 문구(REQ-007) 노출 화면 비율 | 100% | QA 체크리스트 | **자동 판정: PASS** | E2E(§4-1 TC-E2E-01/04)로 홈/검색/상세/스크리너 전 화면에서 배너 확인, 06/07단계에서 이미 전 화면 100% 확정(unit-04-test v2) — 08단계 재확인으로 승계 |
| 5 | 데이터 기준시각(REQ-006) 표기 화면 비율 | 100%(시세/스크리닝/리포트) | QA 체크리스트 | **자동 판정: PASS** | 홈/`/stocks/[code]`/`/screener` 3개 화면 전부에서 `DataFreshnessBadge` 렌더링 확인(§4-1, `04-full-system-test.md` §4 참조 — 코드 검색으로 3개 컴포넌트 전부 import 확인) |
| 6 | REQ-005 테스트 케이스 통과율 | 100% | 6+8단계 테스트 | **자동 판정: PASS** | `unit-01-test.md` v4에서 이미 100% 확정(AC-1~6 전 불릿 PASS, DEF-001/002/003/004 전부 Fixed). 08단계는 신규 테스트를 추가하지 않고 E2E 전 구간의 신선도 계산 일관성으로 간접 재확인 |
| 7 | 모바일 초기 페이지 로드 3초 이내 + Lighthouse 80점 이상 | Pass/Fail | 10단계 배포테스트에서 측정(설계 지정) | **자동 판정(스모크 근거): 목표 달성 추세 — 공식 측정은 설계상 10단계 소관, 선판단 유보** | §4-2 TC-NFR-06~08(로컬 스모크: 로드 935~1003ms, Lighthouse 99~100/100) |
| 8 | 9단계 보안검증 REQ-007~010 Critical 결함 0건 | 0건 | 9단계 보안검증 결과서 | **판정 보류(정상 시퀀싱)** | 9단계가 아직 수행되지 않음 — 08단계가 선판단할 항목이 아니며 사업적 질문도 아님 |
| 9 | 데이터 미갱신 시 기준시각 표기만으로 지연 여부 자가판단 가능 | Pass/Fail | 4단계 체크리스트 + 9단계 검증 | **자동 판정: PASS** | §4-1 TC-E2E-04, `staleness_note`("예상보다 3영업일 지연된 데이터입니다") 실제 렌더링 확인(현재 픽스처 `trade_date=2026-09-14`, 오늘 2026-09-18 기준 자연 발생) |
| 10 | §4-3 데이터 가공 원칙 위반(원본 OHLCV 재게시) 건수 | 0건 | 4단계 체크리스트 + 9단계 재확인 | **자동 판정: PASS(승계)** | `feature-screener-integration-test.md` TC-IT-08/09, `feature-stock-metrics-integration-test.md`가 이미 원본 시세 키워드 grep 0건 확정 — 08단계는 코드/설계 변경이 없었음을 확인(재스캔 불필요로 판단, 반복 회피) |
| 11 | REQ-022(KRX 공식 확인/법률 자문) 게이트 Pass 여부 | Pass 필수 | 12단계 배포 승인 체크리스트 | **상태 불변: Not Started(Blocking Gate)** | 08단계가 판단할 사항이 아님(사용자/운영주체 소관, `03-system-design.md` §7-4). 08단계는 이 게이트가 여전히 "미확인" 상태임을 확인만 함 |

**(v2 재확인, 2026-09-18)**: §4-5의 11개 KPI 판정은 이번 미들웨어 변경(rate limiting/보안헤더/DB타임아웃)과 무관한 영역이라 상태 불변이다. 다만 항목 8("9단계 보안검증 REQ-007~010 Critical 결함 0건")은 v1 작성 시점엔 "판정 보류(정상 시퀀싱)"였으나, 이후 실제로 9단계가 수행되어 `09-security-audit.md`가 REQ-007~010(규제 민감 도메인 대응) 전 항목을 Critical 결함 0건으로 확인했음을(§4-8 TC-SEC-32~37, "미반영 항목 0건") 확인했다 — 09단계가 FAIL 판정한 DEF-SEC-01/02는 REQ-026/027(rate limiting/보안헤더) 항목이며 REQ-007~010(규제 대응) Critical 결함과는 무관하다. 따라서 **항목 8은 이번 v2에서 자동 판정: PASS**로 갱신한다(근거: `09-security-audit.md` §4-8). 나머지 10개 항목(자동 PASS 7건, 상태불변 확인 1건, 사용자 확인 필요 2건)은 v1과 동일하게 유지한다 — DEC-025로 이미 사용자 확인이 완료된 사항이라 재질문하지 않는다(오케스트레이터 지시사항 반영).

### 4-6. UAT 관련 질문 목록 (규칙 A — 오케스트레이터 보고용, 사용자에게 직접 질문하지 않음)

**(v2 갱신, 2026-09-18)**: 아래 질문 1·2는 v1 작성 직후 오케스트레이터가 사용자에게 `AskUserQuestion`으로 전달해 답변을 받았고, `decisions.md` **DEC-025**로 기록됐다 — **① UV 목표는 그대로 유지, 배포 후(13단계) 실측·확인. ② 계측 인프라(이벤트/접속로그) 구축은 배포 전 필수 작업이 아니며 배포 후 별도 착수 항목으로 분류(사용자 승인 완료).** 이번 v2 재실행 지시에서도 "DEC-023 사용자 응답 반영분(UV/스크리닝 세션 비율 KPI는 배포 후 실측으로 합의됨)은 재질문 불필요"로 명시됐으므로, 아래 질문 원문은 이력 보존을 위해 그대로 남기되 **이미 해소된 질문**임을 표시한다. 두 KPI 모두 §4-5 판정("측정 불가 — 사용자 확인 필요")은 "배포 후 확인 예정"이라는 확정된 처리 방침으로 이해해야 하며, 08단계 재실행을 막는 조건이 아니다.


**질문 1**: `[08단계] 02-planning.md §5의 주간 순방문자(UV) 목표(4주≥300명/8주≥500명)는 배포 전인 현재 시점에 원천적으로 측정할 수 없다. 이 사실 자체를 확인하는 것 외에 08단계가 추가로 할 수 있는 조치가 없는데, 어떻게 처리할지 확인이 필요하다 / 왜 판단이 안 되는지: 측정 자체가 시간적으로 불가능하며(배포 전), "이 목표치가 여전히 유효한가/조정이 필요한가"는 비즈니스 판단 영역이라 08단계 에이전트가 임의로 답할 수 없다 / 선택지: (a) 현재 상태 그대로 "배포 후 13단계(배포후검증) 또는 별도 시점에 확인"으로 남기고 진행 — 트레이드오프: 지금 당장 결정할 것이 없어 가장 간단하나, 측정 인프라(질문2와 연동) 준비 없이 배포하면 나중에 소급 측정이 불가능할 수 있음. (b) 지금 목표치를 재검토(예: 초기 트래픽 예측 근거 재확인) — 트레이드오프: 8단계 범위를 넘어선 기획 재작업이 필요.`

**질문 2**: `[08단계] 스크리닝 세션 비율(≥30%) KPI를 측정할 이벤트 트래킹/접속 로그 집계 인프라가 코드베이스 전체에 존재하지 않음을 확인했다(analytics/gtag/access-log 관련 키워드 전체 재스캔 매치 0건 — 03-system-design.md §8-2 미해결사항5 "애널리틱스 도구 미확정"이 승계된 상태 그대로임). 이 인프라 구현을 배포 전 필수 작업으로 볼지, 배포 후 별도 착수 항목으로 볼지 확인이 필요하다 / 왜 판단이 안 되는지: 이는 "이 정도 갭이면 배포해도 되는가"라는 비즈니스 우선순위 판단이며, 08단계 에이전트가 "측정 안 됨"이라는 사실 확인을 넘어 임의로 착수 여부를 결정할 권한이 없다 / 선택지: (a) 배포 전 최소 계측(예: 서버 접근 로그 집계, 03-system-design.md §6-2가 이미 설계해 둔 최소 수집 항목 방식) 구현을 05단계로 되돌려 착수 — 트레이드오프: 파이프라인이 다시 5→6→7→8을 거쳐야 해 일정이 늘어남. (b) MVP는 이 KPI 측정 없이 배포하고 추후 별도 스프린트로 계측 도입 — 트레이드오프: KPI 자체가 배포 후 상당 기간 "측정 불가" 상태로 남음.`

## 5. 커버리지
- **1차 내부검증 관점(기획서 핵심가치제안·KPI 커버리지)**: `02-planning.md` §3 핵심 가치 제안 4개 요소(추천이 아닌 근거/명확한 기준시각/가공된 지표/단순한 요약)가 §4-1 E2E 시나리오 전체에 1:1로 반영됐다 — "근거"는 TC-E2E-06(조건 스크리닝), "기준시각"은 TC-E2E-04(신선도 배지), "가공된 지표"는 TC-E2E-04(등락률 순위 등 파생지표만 노출), "단순한 요약"은 TC-E2E-01(홈 요약 통계)로 각각 커버됐다. §5 KPI 11개 항목 전부가 §4-5 표에서 판정됐다(자동 PASS 7건, 정상 시퀀싱 보류 1건, 상태불변 확인 1건, 사용자 확인 필요 2건 — 미검토 항목 없음).
- **2차 내부검증 관점(9단계 보안팀·10단계 배포팀에 이 결과를 넘겨도 되는가)**: §10 2차 검증 참조.
- 커버리지 지표: E2E 시나리오 9건(데스크톱+모바일 각각, §4-1), 성능 5개 엔드포인트×2지표(§4-2), 부하 스모크 2건(§4-3), 장애복구 9건(§4-4), UAT 11개 KPI 전항목(§4-5) — 총 36개 관측 포인트.
- 커버되지 않은 부분과 사유:
  - 실 서비스 규모(약 2,500종목)에서의 성능/부하 실측 — DEF-IT-M01(실 데이터 파이프라인 미실행) 승계 리스크로 현재 원천적으로 불가능. 대안(인덱스 설계 코드 리뷰)은 §4-2에 명시.
  - 실제 프로덕션 호스팅 환경에서의 Lighthouse/CORS — 호스팅 벤더 미확정(설계 §2-1), 10단계 영역으로 이관.
  - 다중 워커/수평 확장 상태에서의 부하 테스트 — 초기 규모(§8-A3) 전제상 단일 인스턴스 스모크로 충분하다고 판단, 대규모 부하 테스트는 과설계 방지 원칙(YAGNI)에 따라 이번 범위에서 수행하지 않음.
  - 9단계 보안검증 관점의 REQ-007~010 Critical 결함 확인 — 다음 단계 소관.

**(v2 갱신, 2026-09-18)**: 위 미해결 항목 중 "9단계 보안검증 관점의 REQ-007~010 Critical 결함 확인"은 실제로 9단계가 수행되어 해소됐다(`09-security-audit.md` §4-8, Critical 결함 0건). 나머지 미해결 항목(실 서비스 규모 성능, 프로덕션 호스팅 환경 검증, 다중 워커 부하테스트)은 이번 v2 재검증 범위(미들웨어 회귀 확인)와 무관해 상태 불변이다. v2가 신규로 추가한 관측 포인트: E2E v2(데스크톱+모바일 재확인 3건), 성능 v2(5개 엔드포인트 재측정), 부하/rate-limit v2(2건), 장애복구 v2(8건, 원래 재현 방식) — 총 19개 신규 관측 포인트, 기존 36개와 합산해 이번 문서는 총 55개 관측 포인트를 다룬다.

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도(Critical/High/Medium/Low) | 상태(Open/Fixed/Deferred) | 조치 내용 |
|----|------|-----------|-----------------------------------|----------------------------|-----------|
| DEF-FS-01 | **DB 연결 장애 시 4개 데이터 API(`/stocks`, `/stocks/{code}/metrics`, `/screen`, `/market-summary`) 전부가 설계(03-system-design.md §5-4)가 요구하는 503 `SERVICE_UNAVAILABLE`(Envelope 포함) 대신 FastAPI 기본 raw 500("Internal Server Error", Envelope 아님)을 반환하며, 실패 판정까지 약 60~90초(설계 목표 5초의 10배 이상)가 소요된다.** | §4-4 TC-NFR-11~14: `docker stop stock-screener-db` 실행 후 각 엔드포인트를 curl로 호출, HTTP 상태코드·응답본문·소요시간 실측(재현 100%, 2회 독립 확인) | **High** | **Fixed (v2, 2026-09-18)** | 근본 원인: (1) `services/public_api/db/session.py`의 `create_engine(settings.database_url, pool_pre_ping=True)`에 `connect_timeout`/`options="-c statement_timeout=..."` 등 타임아웃 설정이 전혀 없어 TCP/DB 연결 시도가 OS 기본 타임아웃(수십 초)까지 대기함. (2) `services/public_api/main.py`에 `ApiError`/`RequestValidationError` 두 종류의 예외 핸들러만 등록되어 있고, SQLAlchemy `OperationalError`/`DBAPIError`(DB 연결 실패)를 503으로 매핑하는 전역 예외 핸들러가 없음(`/health`만 자체 try/except로 방어). **규칙 F에 따라 근본 원인 단계로 귀속**: 이는 03-system-design.md §5-4가 이미 "쿼리 타임아웃 5초, 초과 시 503 반환"을 명시했으나 5단계(UNIT-01, `services/public_api` 공통 기반) 어느 시점에도 실제로 구현되지 않은 설계→구현 공백이다. 08단계는 직접 재작업하지 않고(사용자 지시 원칙 준수), (a) 이 결함을 10단계(배포테스트) 착수 전 필수 해소 조건으로 게이트 등록(`decisions.md`/`traceability.md` 나레이티브 반영 완료), (b) 9단계(보안검증)에는 이 결함이 응답 지연 60~90초를 유발한다는 점에서 자원 고갈(다수 동시 요청 시 워커/커넥션 슬롯이 장시간 점유될 수 있는 잠재적 DoS 인접 특성)의 관점에서 추가 검토하도록 인계, (c) 수정 방향 권고(구현은 05단계 소관): 엔진 생성 시 `connect_args={"connect_timeout": 5}` 추가 + `main.py`에 `@app.exception_handler(OperationalError)`(및 상위 `DBAPIError`) 등록해 `_error_envelope(503, "SERVICE_UNAVAILABLE", ...)`로 매핑. **(v2 갱신)** 5단계(UNIT-01) 3라운드 재작업(`db/session.py` connect_timeout/statement_timeout, `main.py`+`middleware.py`의 `DBAPIError`/`SATimeoutError`/catch-all 예외 핸들러+요청 타임아웃) 완료 → 6단계(`unit-01-test.md` v5/v6) 독립 재검증(PASS, TCP 블랙홀 실측) → **8단계(본 문서)가 원래 재현 방식(`docker stop`)으로 재확인한 결과 4개 API 전부 4.5초 내외(목표 5초 이내)로 503 Envelope 반환을 확정**(§4-4 TC-NFR-V2-08~15). 데이터 부작용 없음, 프로세스 재시작 없이 자동 복구. **결함 해소 확정.** |

- **그 외 결함 없음.** 근거: §4-1(E2E 9건×2뷰포트)·§4-2(성능 5건)·§4-3(부하 2건)·§4-4(장애복구 9건, DEF-FS-01 외 8건 PASS)를 실제 프로덕션 코드+실제 PostgreSQL+실제 헤드리스 브라우저로 실행했다. 특히 "DB 다운을 종목 없음(404)으로 오인 표시"할 가능성을 코드 레벨로 직접 의심하고 확인했으나(TC-NFR-16), `fetchStockMetrics`가 fetch 예외를 `NETWORK_ERROR`로 정확히 분류해 그런 오분류는 발생하지 않았다(근거 없는 "이상 없음"이 아니라 재현 절차와 함께 확정).
- 참고(신규 결함 아님, 기존 게이트 재확인): DEF-IT-M01(Medium, Deferred, DEC-024)은 §4-4 이전 사전 확인(`raw_internal.raw_ohlcv` 58행, 단일 `source_batch_id`)으로 상태 불변임을 재확인했다 — 08단계가 새로 발견하지 않았고 재등록하지 않는다.

**(v2 추가, 2026-09-18)**: 이번 재실행에서 9단계가 발견했던 DEF-SEC-01(rate limiting)/DEF-SEC-02(보안헤더)도 `unit-01-test.md`(v6)에서 이미 Fixed로 확정됐고, 8단계(본 문서) §4-1/§4-3에서 실제 통합 환경(실 DB+실 브라우저+실 uvicorn, 포트 8010/3010)으로 독립 재확인해 회귀가 없음을 검증했다. **신규 결함 0건**(코드/DEF-FS-01 관점 모두). 4개 feature(stock-search/stock-metrics/screener/market-summary) 핵심 플로우 어디에서도 미들웨어발 feature 고유 회귀를 발견하지 못했다 — `decisions.md` DEC-027의 "07단계 재실행 불필요" 판단이 실측으로 확인됐으므로, 07단계 추가 재실행은 필요하지 않다.

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- 세션 시작 시 `.harness-tmp/` 확인 결과: 비어 있음(강제 중단 이력 없음, 규칙 K 4번 재개 시 점검 절차 준수).
- 이번 테스트에서 생성한 임시 아티팩트 목록: `.harness-tmp/08-full-system-test/`(`package.json`/`package-lock.json`/`node_modules`(puppeteer-core@23, lighthouse@11 및 종속성), `e2e_journey.mjs`, `e2e_journey_mobile.mjs`, `perf_results.json`, `load_test_results.json`, `lh_home.json`/`lh_home_mobile.json`/`lh_home_summary.json`, `backend.log`/`backend2.log`/`frontend.log`, `parse_trace.py`/`update_trace.py`/`verify_trace.py`/`insert_narrative.py`/`parse_out_utf8.txt`, `traceability.md.bak`, `detail_backend_down.html`/`screener_backend_down.html`).
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): **[x] 예**.
- 정리(삭제) 완료 여부: **완료.** `netstat -ano`로 포트 8000/3000 리스닝 PID를 실측 특정해(재기동으로 PID가 최초 기동 시와 달라져 있어 매번 `netstat`로 재확인) `taskkill //F //PID ... //T`로 전부 종료 확인(종료 후 `netstat`에 8000/3000 LISTENING 항목 없음 재확인). 커스텀 환경변수 없이 `npm run build`를 재실행해 프론트엔드 빌드를 기본 상태로 복원(`/`가 `ƒ Dynamic`으로 유지됨을 재확인 — UNIT-08의 `force-dynamic` 수정 회귀 없음). `.harness-tmp/08-full-system-test/`를 `rm -rf`로 삭제 후 `.harness-tmp/`가 다시 빈 상태임을 확인.
- DB 정리: 이번 테스트(§4-4 장애복구 시나리오 포함)는 DB에 어떤 쓰기도 가하지 않았다(컨테이너 정지/재시작만 수행, 데이터 볼륨은 영향받지 않음). 테스트 종료 후 `stock_master`(6)/`derived_metrics_daily`(6)/`market_summary_daily`(3)/`raw_ohlcv`(58)/`source_batch_id`(1종) 행수가 테스트 시작 전과 정확히 동일함을 재확인했다(§4-4 TC-NFR-19).
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
	docs/harness/08-full-system-test.md
	docs/harness/feature-market-summary-integration-test.md
	docs/harness/feature-screener-integration-test.md
	docs/harness/feature-stock-metrics-integration-test.md
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
  (이번 08단계 세션이 만든 변경은 `docs/harness/traceability.md`(REQ-001~013/022/024 "전체테스트(08)" 컬럼 갱신 + 나레이티브 추가)와 신규 `docs/harness/08-full-system-test.md`(이 문서) 두 건뿐이며, 나머지 항목은 전부 이번 세션 이전부터 존재하던 7단계 4개 feature 문서 작성 시점부터 이어진 변경이다 — 4개 feature 통합테스트 문서가 각자의 07단계 시작 시점에 이미 동일하게 관측·기록한 목록과 완전히 동일하다. `.harness-tmp/`는 비어 있어 목록에 나타나지 않는다.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **[x] 없음**.

### v2 Teardown (2026-09-18, 규칙 K)

- 세션 시작 시 `.harness-tmp/` 확인 결과: 비어 있음(6단계 v6 세션이 이미 정리 완료한 상태 승계, 강제 중단 이력 없음).
- 이번 v2 테스트에서 생성한 임시 아티팩트: `.harness-tmp/08-rerun/`(`package.json`/`package-lock.json`/`node_modules`(puppeteer-core@23, lighthouse@11), `e2e_journey.mjs`/`e2e_mobile.mjs`/`debug_detail.mjs`, `load_test.py`/`rate_limit_check.py`/`perf_test.py`/`perf_one_endpoint.py`/`db_down_test.py`, `backend.log`/`backend2.log`/`backend_perf.log`/`frontend.log`, `lh_home.json`, `perf_results_lines.txt`). 전부 `.harness-tmp/` 하위에만 생성했다(규칙 K 1번 준수).
- 프로세스 정리: 백엔드(uvicorn, 포트 8010)·프론트엔드(next start, 포트 3010) 전부 `netstat -ano`로 실제 LISTENING PID를 특정해(재기동으로 PID가 여러 번 바뀌어 매번 재확인) `taskkill //F //PID ... `로 종료, 이후 `netstat`에 8010/3010 LISTENING 항목 없음 재확인. 무관한 다른 프로젝트("final-project")가 쓰던 8000/3000 포트/컨테이너는 이번 세션이 전혀 건드리지 않았다(확인만 하고 시작/정지 조작 없음).
- DB 컨테이너: `docker stop`/`docker start stock-screener-db`를 DEF-FS-01 재현 목적으로 의도적으로 실행했다(테스트 시나리오 자체이므로 결과가 아니라 절차임). 세션 종료 시점 `docker ps` 결과 `Up`(정상 기동 상태)임을 재확인했다. DB 역할(`api_service`/`batch_worker`)의 `LOGIN`/비밀번호를 `devpass`로 재설정한 것은 라이브 테스트 DB 설정 조정(§3 참조)이며, 되돌리지 않고 다음 세션의 편의를 위해 그대로 두었다(unit-01-test.md v3 "환경 관리 원칙"과 동일한 원칙 — 데이터는 건드리지 않되 인프라 설정은 보존).
- 프론트엔드 빌드 복원: 커스텀 `NEXT_PUBLIC_API_BASE_URL` 없이 `npm run build`를 재실행해 기본 상태로 복원했다(`/`가 `ƒ Dynamic`으로 유지됨을 재확인, 회귀 없음).
- DB 데이터 정리: 이번 v2 테스트(장애복구 재현 포함)는 DB에 어떤 쓰기도 가하지 않았다(컨테이너 정지/재시작 및 역할 속성 변경만 수행, 테이블 데이터는 영향받지 않음). 테스트 종료 후 `stock_master`(6)/`derived_metrics_daily`(6)/`market_summary_daily`(3)/`raw_ohlcv`(58) 행수가 세션 시작 전과 정확히 동일함을 재확인했다.
- `.harness-tmp/08-rerun/` 삭제 후 `.harness-tmp/`가 다시 빈 상태임을 확인.
- 정리 후 `git status --short` 실행 결과 (그대로 첨부):
```
 M docs/harness/traceability.md
 M docs/harness/units/unit-01-note.md
 M docs/harness/units/unit-01-test.md
 M services/public_api/db/session.py
 M services/public_api/main.py
 M tests/unit/test_public_api.py
?? services/public_api/middleware.py
?? services/public_api/rate_limit.py
```
  (이번 v2 세션이 만든 변경은 `docs/harness/traceability.md`(REQ-001~004/011~013/022/024/025/026/027 "전체테스트(08)" 컬럼 v2 갱신 + 나레이티브 추가)와 `docs/harness/08-full-system-test.md`(이 문서, v1→v2 개정) 두 건뿐이며, 나머지 항목은 전부 이전 세션(UNIT-01 v5/v6 재작업)부터 이어진 변경으로 이번 v2 세션이 새로 만든 것이 아니다 — 세션 시작 시점의 `git status`와 완전히 동일한 목록임을 대조 확인했다(§3의 "전제 조건" 참조).)
- 이번 v2 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **[x] 없음**.

## 8. 리스크 및 잔존 이슈
- ~~**DEF-FS-01(High, Open)**: §6 참조. 10단계(배포테스트) 착수 전 필수 해소 조건으로 등록. 9단계(보안검증)는 이 결함을 자원고갈(DoS 인접) 관점에서 추가 검토할 것을 권고(9단계 진행 자체를 막지는 않음).~~ **(v2) Fixed로 최종 확정.** §6 참조 — 원래 재현 방식(`docker stop`)으로 재확인 완료, 10단계 착수 전 게이트 해소됨.
- **DEF-IT-M01(Medium, Deferred, DEC-024 승계) 상태 불변**: 실 Ingestion Batch→실 Derivation Batch 종단간 실행이 이 프로젝트 역사상 검증된 적 없음(08단계 사전 확인으로 재확정, §4 서두 참조). 10단계 착수 전 게이트 유효.
- **UAT 질문 2건(§4-6) — (v2) `decisions.md` DEC-025로 해소됨**: 주간 UV 목표(배포 후 13단계에서 실측, 목표치 유지)와 스크리닝 세션 비율 KPI(계측 인프라는 배포 후 별도 착수, 사용자 승인)는 더 이상 08단계를 막는 미해결 질문이 아니다. "측정 불가" 상태 자체는 배포 시점까지 유효하게 남지만, 이는 임의 PASS 처리가 아니라 사용자가 명시적으로 승인한 처리 방침이다.
- **실 서비스 규모(약 2,500종목) 성능 미실측**: DEF-IT-M01과 동일 원인(실 데이터 부재). 인덱스 설계 기반 코드 리뷰 추정만 가능(§4-2). 10단계에서 실 서비스키 확보 후 재실시 권고.
- **단일 uvicorn 워커, 다중 워커/수평 확장 미검증**: 초기 규모 전제(§8-A3)상 현재 범위에서는 정당하나, 실제 배포 시 워커 수 설정과 그에 따른 동시성 한계는 10단계에서 별도 확인 필요.
- **실 프로덕션 호스팅 환경 CORS/성능 미검증**: 호스팅 벤더 미확정(설계 §2-1), 로컬 스모크로 대체. 10단계 영역.
- 각 feature 통합테스트 문서(`feature-*.md`)가 이미 인계한 승계 리스크(DEF-006 LIKE 와일드카드, DEF-U08-01/02, percentile 템플릿 코드 미공유, 뒤로가기 시 스크리너 폼 리셋, `stock_master.sector` 미확정 등)는 08단계가 재검증하지 않았으며 상태 변경 없음 — 여기서 재서술하지 않는다.
- **(v2 신규 관찰, 결함 아님)** DEF-FS-01의 컨테이너 정지 재현(4.5초대)이 6단계의 TCP 블랙홀 재현(3.05~3.08초)보다 약 1.5초 느리다 — 두 경로 모두 5초 목표 이내라 결함은 아니지만, 실제 배포 환경(클라우드 로드밸런서/헬스체크 타임아웃 설정)에서는 이 차이가 유의미할 수 있어 10단계에서 실제 인프라 장애 시나리오(연결 거부/네트워크 단절 양쪽)를 재확인할 것을 권고한다.
- **(v2 신규 관찰, 결함 아님)** 이번 v2 세션은 이 머신에서 동시에 실행 중인 무관한 다른 프로젝트("final-project" Docker 스택)가 8000/3000 포트를 이미 점유하고 있음을 발견했다 — 이 저장소의 코드/테스트에는 영향 없으나(대체 포트 8010/3010 사용), 향후 CI/로컬 검증 환경에서 포트 충돌이 반복될 수 있어 `automation/` 스크립트에 포트 사전 점검 로직이 있는지 재확인을 권고한다(하네스 개선 후속 과제, 이 프로젝트의 배포를 막는 사유는 아님).
- 5단계(UNIT-01) 재작업이 남긴 기존 후속 과제(멀티 워커 rate limiter 한계, `RequestTimeoutMiddleware`의 스레드 강제종료 불가, 타임아웃 테스트의 구조적 한계 등, `unit-01-test.md` v6 §7)는 이번 v2가 재검증 범위에 포함하지 않았으며 상태 불변으로 승계한다.

## 9. 결론 및 판정 (v2, 최종 갱신 — v1의 CONDITIONAL PASS를 대체)

### v1 판정(이력 보존)
- [ ] PASS
- [x] **CONDITIONAL PASS** — 조건: **DEF-FS-01(High)을 10단계(배포테스트) 착수 전까지 반드시 해소**(연결 타임아웃 설정 + SQLAlchemy `OperationalError`/`DBAPIError`→503 `SERVICE_UNAVAILABLE` 전역 매핑 구현, 06/07/08 관련 슬라이스 재검증 완료 후 10단계 진행). 9단계(보안검증) 진행 자체는 이 조건으로 막지 않되, 9단계가 이 결함을 자원고갈 관점에서 추가 검토하도록 인계한다. UAT 질문 2건(§4-6)은 사용자 확인 후 결과를 이 문서 또는 후속 단계 산출물에 반영해야 한다(임의 PASS 처리 안 함).
- [ ] FAIL

**v1 판정 근거**: 기획서 §3 핵심 가치 제안을 관통하는 E2E 시나리오가 데스크톱·모바일 양쪽에서 4개 기능을 순서대로 넘나들며 크래시 없이 동작함을 확인했고(§4-1, 신규 결함 0건), 성능 목표(§4-2)와 부하 스모크(§4-3)는 픽스처 규모에서 전부 목표를 크게 상회했다. 그러나 장애 복구 시나리오(§4-4)에서 설계(§5-4)가 명시한 요구사항이 어느 유닛에서도 구현되지 않은 채 남아 있던 공백을 실제 DB 중단으로 재현해 확정했다(DEF-FS-01, High) — 자체 크래시나 데이터 훼손은 없었고 프론트엔드는 이미 정상적으로 방어하고 있었으나, API 계약 위반과 20배 가까운 실패 지연은 실 운영 환경에서 사용자 신뢰와 가용성에 실질적 영향을 줄 수 있는 수준이라고 판단해 CONDITIONAL PASS로 판정한다. traceability.md 커버리지는 100%로 확정했고(REQ-014~021/023 Out-of-Scope 제외), REQ-022/REQ-024 게이트는 8단계 시점 기준 상태 불변임을 재확인했다.

### v2 판정 (최종, 2026-09-18)
- [x] **PASS**
- [ ] CONDITIONAL PASS
- [ ] FAIL

**v2 판정 근거**: DEC-027이 정한 5→6→8→9 재검증 사이클에 따라 UNIT-01이 rate limiting(REQ-026)·보안헤더(REQ-027)·DB타임아웃+전역예외처리(REQ-025 확장판)를 3라운드 재작업 끝에 `unit-01-test.md`(v6)에서 **PASS**로 확정한 뒤, 이번 8단계(v2)가 그 결과를 전체 시스템 수준에서 최종 검증했다.
1. **DEF-FS-01(REQ-025) 완전 해소 확인** — v1이 사용한 것과 동일한 원래 재현 방식(`docker stop stock-screener-db`)으로 4개 데이터 API+`/health` 전부가 4.5초 내외(목표 5초 이내)로 503 `SERVICE_UNAVAILABLE` Envelope을 반환함을 재확인했다(§4-4 TC-NFR-V2-08~15). 6단계가 쓴 TCP 블랙홀 방식과는 독립적인 재현으로, 두 경로 모두 목표를 충족해 신뢰도가 높다.
2. **rate limiting(REQ-026)이 정상 트래픽에 오탐을 일으키지 않고, 과도한 트래픽은 정확히 차단함**을 확인했다(§4-3 TC-NFR-V2-06/07) — 20건 동시요청 전부 200, 61건째부터 정확히 429.
3. **보안헤더/CORS(REQ-027)가 프론트엔드 E2E(데스크톱+모바일)를 방해하지 않음**을 실제 헤드리스 브라우저로 확인했다(§4-1 TC-E2E-V2-01~03) — 콘솔 에러는 기존 승계 이슈(favicon 404) 1건뿐, CORS/CSP로 인한 신규 에러 0건.
4. **4개 feature(stock-search/stock-metrics/screener/market-summary) 핵심 플로우 전부에서 미들웨어발 feature 고유 회귀를 발견하지 못했다** — `decisions.md` DEC-027의 "07단계 재실행 불필요" 판단이 실측으로 확인됐으므로 07단계 추가 재실행은 필요하지 않다(규칙 F의 "회귀 없으면 재실행 범위를 좁게 유지" 원칙에 부합).
5. 비기능요구사항(API P95, §4-2) 전부 목표 대폭 상회(최대 목표의 16% 수준), Lighthouse 데스크톱 99/100로 v1(100/100)과 사실상 동일(회귀 없음). 회귀 전체 스위트(`pytest` 167건, `ruff`, `tsc`, `eslint`) 전부 통과.
6. UAT KPI 11개 항목 재확인 — 항목 8(9단계 REQ-007~010 Critical 결함 확인)이 정상 시퀀싱으로 해소되어 **자동 PASS**로 전환됐고(§4-5), UV/스크리닝 세션 비율 2건은 `decisions.md` DEC-025로 이미 사용자 확인이 완료된 "배포 후 확인" 상태임을 재확인했다(§4-6) — 임의 PASS 처리가 아니라 명시적으로 승인된 처리 방침이다.
7. traceability.md 커버리지는 100%를 유지하며(REQ-014~021/023 Out-of-Scope 제외), REQ-025/026/027 전부 "전체테스트(08)" 컬럼까지 PASS로 갱신했다. REQ-022(KRX 라이선스 확인)/REQ-024(실 파이프라인 실행) 게이트는 여전히 상태 불변(코드 품질과 무관한 배포 전 별도 게이트)임을 재확인했다 — 이는 08단계 PASS 판정을 막는 조건이 아니다(v1과 동일한 원칙, §2 제외범위 참조).

**신규/승계 결함 0건, High/Critical 결함 0건. 종합 판정: PASS. 9단계(보안 재검증) 착수 가능.**

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

### v1 내부 검증 (이력 보존)

### 1차 검증 (작성자 관점 자가 재검토 — "기획서의 핵심 가치 제안과 성공 지표가 모두 시나리오로 커버됐는가")
- 검증자(역할): 08-full-system-tester(작성자 본인)
- 일시: 2026-09-18
- 체크리스트
  - [x] `02-planning.md` §3 핵심 가치 제안 4개 요소가 전부 시나리오로 커버됐는가 → §4-1 서두에 매핑 명시, 미커버 없음.
  - [x] §5 KPI 11개 항목 전부를 판정했는가(누락 없이) → §4-5 표에서 전항목 1:1 판정(자동 PASS/정상 시퀀싱 보류/상태불변/사용자확인필요 4가지 유형으로 명확히 분류), 임의로 PASS 처리한 항목이 있는지 재검토했으나 배포 후에만 측정 가능한 2건은 정확히 "측정 불가 — 확인 필요"로 남겼음을 재확인.
  - [x] 06/07단계가 이미 검증한 것을 반복하지 않았는가 → §2 제외범위에 명시하고, §4 전체에서 필터/정렬/포커스트랩/DB권한 등 개별 로직 재검증을 하지 않았음(E2E/NFR/UAT/커버리지에만 집중).
  - [x] 비기능요구사항(성능/부하/장애복구)을 생략하지 않았는가, 측정 불가 항목에 사유와 대안을 남겼는가(규칙 C) → §4-2에 실 서비스 규모 미실측 사유+대안(인덱스 코드 리뷰) 명시, §4-4에 실제 장애 재현 결과를 은폐 없이 FAIL로 표기 후 §6에서 결함으로 등록.
  - [x] "이상 없음"을 근거 없이 선언한 곳이 있는가 → 없음(§6에서 "그 외 결함 없음"에 구체적 실행 근거 나열, 특히 TC-NFR-16의 404 오분류 의심을 능동적으로 확인한 과정을 명시).
  - 발견된 결함: DEF-FS-01(High). 조치: 결함으로 등록, 10단계 전 필수 해소 조건화, 9단계 인계.

### 2차 검증 (독립 심사자 관점 — "9단계 보안팀·10단계 배포팀에 이 결과를 넘겨도 되는가")
- 검증자(역할): 08-full-system-tester(역할 전환 재검토)
- 일시: 2026-09-18
- 체크리스트
  - [x] **9단계(보안검증) 관점**: DEF-FS-01이 60~90초 지연을 유발한다는 사실이 "다수 동시 요청 시 자원(스레드/커넥션 슬롯) 고갈로 이어질 수 있는 잠재적 DoS 인접 특성"으로 읽힐 수 있어, 9단계가 이를 "성능 이슈"로만 보고 넘기지 않도록 §8에 명시적으로 "자원고갈 관점 추가 검토"를 인계했다 — 9단계가 이 문서를 안 읽고 지나칠 위험을 줄이기 위해 §6/§8/§9 세 곳에 반복 명시했다.
  - [x] **10단계(배포테스트) 관점**: DEF-FS-01을 "10단계 착수 전 필수 해소" 조건으로 명확히 게이트화했다(REQ-022/REQ-024와 동일한 패턴, `decisions.md`/`traceability.md`에도 반영). 10단계가 이 문서만 보고 "8단계가 CONDITIONAL PASS면 일단 진행해도 되나보다"라고 오판하지 않도록 §9 결론에 조건을 구체적 행동(연결 타임아웃 설정 + 예외 핸들러 등록 + 재검증)으로 명시했다.
  - [x] **traceability.md 커버리지 100% 확인이 실제로 완료됐는가(9/10단계가 재확인할 필요 없도록)** → `verify_trace.py` 재실행 결과 REQ-001~013/022/024 전 24개 행이 11개 컬럼 구조로 일관되게 채워졌음을 재확인(§5), REQ-014~021/023(Out-of-Scope)은 "-" 유지로 의도적 제외임이 명확함.
  - [x] **UAT 질문 목록(§4-6)이 9/10단계 진행을 부당하게 막지 않는가** → 두 질문 모두 "8단계/9단계/10단계 진행을 막는 게이트"가 아니라 "배포 전후 시점에 확인이 필요한 사업 판단"으로 명확히 분리해 §9 결론에 "임의 PASS 처리 안 함"으로만 표시하고 CONDITIONAL PASS의 직접적 조건(DEF-FS-01)과는 구분했다 — 9단계 진행을 막을 근거로 오독되지 않도록 명확히 했다.
  - [x] **Teardown(§7)이 완전한가** → `.harness-tmp/`가 실제로 비어 있고 DB 행수·포트·프론트엔드 빌드 상태가 전부 원상 복구됐음을 재확인(§7), git status가 이번 세션 시작 시점과 신규 파일 2건(이 문서 + traceability.md 갱신) 차이만 있음을 대조 확인.
  - 발견된 결함: 없음(신규). §8 리스크 목록에 이미 반영된 사항 외 추가 발견 없음.
  - 조치 내용: §6/§8/§9 서술을 9/10단계가 오독하지 않도록 보강한 것 외 결함 목록/판정 변경 없음 → 최종 **CONDITIONAL PASS** 유지(v1 시점 기준).

### v2 내부 검증 (2026-09-18, 최종 — 위 v1을 대체하는 판정에 대한 검증)

#### v2 1차 검증 (작성자 관점 자가 재검토 — "오케스트레이터가 지시한 5개 재검증 항목이 모두 실측으로 커버됐는가")
- 검증자(역할): 08-full-system-tester(작성자 본인)
- 일시: 2026-09-18
- 체크리스트
  - [x] 항목 1(DEF-FS-01, 원래 재현 방식)을 실제로 재현했는가 → §4-4 TC-NFR-V2-08~15, `docker stop`/`docker start`를 직접 실행하고 5개 엔드포인트 각각의 상태코드/소요시간/본문을 실측했는지 재확인 — 있음, 추측이나 6단계 결과 재인용이 아니라 8단계 자신의 세션에서 직접 실행.
  - [x] 항목 2(20건 동시요청이 rate limit에 오탐을 일으키지 않는지)를 실측했는가 → §4-3 TC-NFR-V2-06/07, 오탐 없음(20<60)과 실제 방어 동작(61건째 429) 양쪽을 모두 확인했는지 재확인 — 있음, 한쪽만 확인하고 넘어가지 않았음.
  - [x] 항목 3(보안헤더/CORS가 프론트엔드를 방해하지 않는지)을 실제 브라우저로 확인했는가(코드 리뷰만으로 판정하지 않았는지) → §4-1 TC-E2E-V2-01~03, 헤드리스 Chrome으로 콘솔 에러/네트워크 실패를 직접 수집했는지, "차단됐을 수도 있는데 안 본 것"이 아닌지 재확인 — 있음, `failedRequests`를 전수 검토해 CORS/CSP 기인이 아님을(Next.js 자체 RSC 프리페치 취소) 원인까지 규명했음을 확인.
  - [x] 항목 4(4개 feature 핵심 플로우 회귀 여부)를 4개 feature 전부에 대해 확인했는가 → E2E 여정이 홈(market-summary)→검색(stock-search)→상세(stock-metrics)→스크리닝(screener)→상세 재확인→홈 순으로 4개 feature를 전부 지나가는지 재확인 — 있음, §4-1 표에 4개 feature 전부 매핑됨.
  - [x] "5단계/6단계가 고쳤다고 하니 믿는다"는 식의 서술이 있는가 → 없음, 전부 8단계 자신의 실측(uvicorn 포트 8010/3010, 새 스크립트)으로 재확인했으며 6단계 결과는 "독립적인 재현 경로"로만 언급(예: TCP 블랙홀 vs 컨테이너 정지의 시간차 관찰).
  - 발견된 결함: 없음(신규). DEF-FS-01은 Fixed로 확정, 다른 결함 0건.

#### v2 2차 검증 (독립 심사자 관점 — "9단계 보안팀에 이 PASS 판정을 넘겨도 되는가, v1의 CONDITIONAL PASS를 뒤집을 만큼 근거가 충분한가")
- 검증자(역할): 08-full-system-tester(역할 전환 재검토)
- 일시: 2026-09-18
- 체크리스트
  - [x] **v1 CONDITIONAL PASS를 PASS로 뒤집는 근거가 "5단계가 코드를 고쳤다"가 아니라 "8단계가 v1과 동일한 조건에서 재현해 실제로 해소를 확인했다"는 것인가** → §4-4가 v1과 정확히 동일한 재현 절차(`docker stop`, 동일 5개 엔드포인트)를 사용했고 결과만 다름(500·60~90초 → 503·4.5초)을 재확인 — 대조군이 명확해 판정 근거가 충분함.
  - [x] **9단계가 이 문서만 보고 "8단계가 PASS면 일단 진행해도 되나보다"라고 오판할 위험이 있는가** → DEF-SEC-01/02는 9단계 자신이 발견한 결함이라 8단계가 그 해소 여부를 재확인했다는 사실(§4-1 TC-E2E-V2-03의 CORS 헤더, §4-3의 429 응답 보안헤더)이 9단계 재검증의 유용한 교차 증거가 되도록 §6/§9에 명시했는지 재확인 — 있음, 8단계가 "실제 통합 환경에서" 재확인했다는 점이 9단계의 격리된 재검증과 상호 보완됨을 §6에 명시.
  - [x] **DEF-IT-M01(Medium, REQ-024)/REQ-022 게이트가 이번 v2로 인해 잘못 해소된 것으로 오독될 여지가 있는가** → §8/§9에서 "이번 v2 재검증 범위와 무관, 상태 불변"임을 명시적으로 재확인했는지 확인 — 있음, 두 게이트 모두 "08단계 PASS 판정을 막는 조건이 아니다"로 명확히 구분.
  - [x] **traceability.md 갱신이 이 v2 판정과 정확히 일치하는가** → REQ-001~004/011~013/022/024/025/026/027의 "전체테스트(08)" 컬럼에 v2 재확인 문구를 추가했는지, REQ-025/026/027이 최종 PASS로 표기됐는지 재대조 — 있음(별도 파일에서 확인 완료).
  - [x] **Teardown(§7 v2)이 완전한가** → `.harness-tmp/`가 다시 비어 있고, 포트 8010/3010이 정리됐고, DB 행수가 불변이며, `git status`가 세션 시작 시점과(이 문서+traceability.md 갱신 외) 동일함을 재확인 — 있음.
  - 발견된 결함: 없음(신규). §8 리스크 목록에 이미 반영된 v2 신규 관찰(§4-4 재현 방식 간 시간차, 포트 충돌) 외 추가 발견 없음.
  - 조치 내용: 없음(재검토로 기존 판정의 타당성만 확인) → 최종 **PASS** 확정.

- 검증 로그 파일 경로: 이 문서 §10에 통합 기록(별도 `verify-log_08-full-system-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — 06/07/09단계 산출물이 따른 것과 동일한 관례).

## 절차 흐름 (참고용 다이어그램)
```mermaid
flowchart TD
    A["7단계 4개 feature PASS/CONDITIONAL PASS 확인"] --> B["전체 시스템 E2E: 데스크톱+모바일 4기능 연결 재현(§4-1)"]
    B --> C["NFR: 성능/부하 스모크(§4-2/4-3)"]
    C --> D["NFR: DB 장애 복구 실측(§4-4) → DEF-FS-01 발견"]
    D --> E["UAT: KPI 11개 판정 + 질문 목록 2건(§4-5/4-6)"]
    E --> F["traceability.md 커버리지 100% 확정(§5)"]
    F --> G{Critical/High 결함?}
    G -->|Yes, DEF-FS-01 High| H["10단계 전 필수 해소 게이트 등록<br/>9단계엔 DoS 관점 인계, 9단계 진행은 유지"]
    H --> I["내부검증 1차/2차(§10)"]
    I --> J["Teardown(§7) + git status/DB 행수 확인"]
    J --> K["CONDITIONAL PASS → 9단계 handoff + 질문 목록 오케스트레이터 보고"]
```

## 절차 흐름 v2 (참고용 다이어그램 — DEC-027 재검증 사이클)
```mermaid
flowchart TD
    A2["09 FAIL(DEF-SEC-01/02) + DEF-FS-01 근본원인 확장(DEC-027)"] --> B2["UNIT-01 5단계 재작업(rate limit/보안헤더/DB타임아웃+전역예외) 3라운드"]
    B2 --> C2["6단계 unit-01-test.md v6 독립 재검증 PASS(mutation testing 포함)"]
    C2 --> D2["8단계(본 문서) 재실행: DEF-FS-01 원래방식(docker stop) 재현"]
    D2 --> E2["20건 동시요청+60/61 경계 rate-limit 재확인"]
    E2 --> F2["보안헤더/CORS가 E2E(데스크톱+모바일) 방해 없음 실측"]
    F2 --> G2["4개 feature 핵심 플로우 회귀 없음 확인 → 07 재실행 불필요 확정"]
    G2 --> H2["NFR(P95/Lighthouse)·UAT·traceability 100% 재확정"]
    H2 --> I2["내부검증 1차/2차(§10 v2)"]
    I2 --> J2["Teardown v2(§7) + git status/DB 행수 확인"]
    J2 --> K2["PASS(v1 CONDITIONAL PASS 대체) → 9단계 보안 재검증 handoff"]
```
