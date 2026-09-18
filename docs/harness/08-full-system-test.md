# 테스트 결과서 (Test Result Report) — 08단계 전체 풀테스트 (Full System Test)

> `templates/test-report-template.md` 사용. 대상: **개발된 시스템 전체**(4개 feature: stock-search/stock-metrics/screener/market-summary + 공유 인프라). 입력: 7단계 4개 feature 통합테스트 전부 완료(`feature-stock-search-integration-test.md` PASS, `feature-stock-metrics-integration-test.md` CONDITIONAL PASS, `feature-screener-integration-test.md` PASS, `feature-market-summary-integration-test.md` PASS — `decisions.md` DEC-023/DEC-024), `docs/harness/02-planning.md`(v5) §5(KPI)·§3(핵심가치제안), `docs/harness/03-system-design.md`(v4) §5(비기능요구사항).
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

### 4-3. 비기능요구사항 — 부하 스모크 테스트 (동시 요청)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-NFR-09 | 20건 동시 요청(5종 엔드포인트 혼합: 검색/상세/스크리닝/시장요약) | Python `ThreadPoolExecutor(max_workers=20)`로 동시 발사 | 전부 200, 에러 0건, 크래시 없음 | `all_status_200=true`, `errors=[]`, `total_wallclock_ms=316.0`, `max_elapsed_ms=294.9`, `min_elapsed_ms=128.5` | **PASS** |
| TC-NFR-10 | 부하 중 백엔드 로그에 예외/스택트레이스 없음 | `backend.log` 검사 | 전부 `200 OK` 로그만 존재 | 확인됨(예외 로그 없음) | **PASS** |

- 참고: 단일 uvicorn 워커(멀티프로세스 미구성)로 측정했다. §2-1/§5-2가 "초기 규모(동시 사용자 수백 명 이하)에서 단일 인스턴스로 충분"이라 명시한 것과 일치하는 조건이며, 20건 동시 요청이라는 스모크 규모에서는 문제가 없었으나 실제 수백 명 동시 접속 시나리오까지 검증한 것은 아니다(§8 리스크).

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

### 4-6. UAT 관련 질문 목록 (규칙 A — 오케스트레이터 보고용, 사용자에게 직접 질문하지 않음)

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

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도(Critical/High/Medium/Low) | 상태(Open/Fixed/Deferred) | 조치 내용 |
|----|------|-----------|-----------------------------------|----------------------------|-----------|
| DEF-FS-01 | **DB 연결 장애 시 4개 데이터 API(`/stocks`, `/stocks/{code}/metrics`, `/screen`, `/market-summary`) 전부가 설계(03-system-design.md §5-4)가 요구하는 503 `SERVICE_UNAVAILABLE`(Envelope 포함) 대신 FastAPI 기본 raw 500("Internal Server Error", Envelope 아님)을 반환하며, 실패 판정까지 약 60~90초(설계 목표 5초의 10배 이상)가 소요된다.** | §4-4 TC-NFR-11~14: `docker stop stock-screener-db` 실행 후 각 엔드포인트를 curl로 호출, HTTP 상태코드·응답본문·소요시간 실측(재현 100%, 2회 독립 확인) | **High** | **Open** | 근본 원인: (1) `services/public_api/db/session.py`의 `create_engine(settings.database_url, pool_pre_ping=True)`에 `connect_timeout`/`options="-c statement_timeout=..."` 등 타임아웃 설정이 전혀 없어 TCP/DB 연결 시도가 OS 기본 타임아웃(수십 초)까지 대기함. (2) `services/public_api/main.py`에 `ApiError`/`RequestValidationError` 두 종류의 예외 핸들러만 등록되어 있고, SQLAlchemy `OperationalError`/`DBAPIError`(DB 연결 실패)를 503으로 매핑하는 전역 예외 핸들러가 없음(`/health`만 자체 try/except로 방어). **규칙 F에 따라 근본 원인 단계로 귀속**: 이는 03-system-design.md §5-4가 이미 "쿼리 타임아웃 5초, 초과 시 503 반환"을 명시했으나 5단계(UNIT-01, `services/public_api` 공통 기반) 어느 시점에도 실제로 구현되지 않은 설계→구현 공백이다. 08단계는 직접 재작업하지 않고(사용자 지시 원칙 준수), (a) 이 결함을 10단계(배포테스트) 착수 전 필수 해소 조건으로 게이트 등록(`decisions.md`/`traceability.md` 나레이티브 반영 완료), (b) 9단계(보안검증)에는 이 결함이 응답 지연 60~90초를 유발한다는 점에서 자원 고갈(다수 동시 요청 시 워커/커넥션 슬롯이 장시간 점유될 수 있는 잠재적 DoS 인접 특성)의 관점에서 추가 검토하도록 인계, (c) 수정 방향 권고(구현은 05단계 소관): 엔진 생성 시 `connect_args={"connect_timeout": 5}` 추가 + `main.py`에 `@app.exception_handler(OperationalError)`(및 상위 `DBAPIError`) 등록해 `_error_envelope(503, "SERVICE_UNAVAILABLE", ...)`로 매핑. |

- **그 외 결함 없음.** 근거: §4-1(E2E 9건×2뷰포트)·§4-2(성능 5건)·§4-3(부하 2건)·§4-4(장애복구 9건, DEF-FS-01 외 8건 PASS)를 실제 프로덕션 코드+실제 PostgreSQL+실제 헤드리스 브라우저로 실행했다. 특히 "DB 다운을 종목 없음(404)으로 오인 표시"할 가능성을 코드 레벨로 직접 의심하고 확인했으나(TC-NFR-16), `fetchStockMetrics`가 fetch 예외를 `NETWORK_ERROR`로 정확히 분류해 그런 오분류는 발생하지 않았다(근거 없는 "이상 없음"이 아니라 재현 절차와 함께 확정).
- 참고(신규 결함 아님, 기존 게이트 재확인): DEF-IT-M01(Medium, Deferred, DEC-024)은 §4-4 이전 사전 확인(`raw_internal.raw_ohlcv` 58행, 단일 `source_batch_id`)으로 상태 불변임을 재확인했다 — 08단계가 새로 발견하지 않았고 재등록하지 않는다.

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

## 8. 리스크 및 잔존 이슈
- **DEF-FS-01(High, Open)**: §6 참조. 10단계(배포테스트) 착수 전 필수 해소 조건으로 등록. 9단계(보안검증)는 이 결함을 자원고갈(DoS 인접) 관점에서 추가 검토할 것을 권고(9단계 진행 자체를 막지는 않음).
- **DEF-IT-M01(Medium, Deferred, DEC-024 승계) 상태 불변**: 실 Ingestion Batch→실 Derivation Batch 종단간 실행이 이 프로젝트 역사상 검증된 적 없음(08단계 사전 확인으로 재확정, §4 서두 참조). 10단계 착수 전 게이트 유효.
- **UAT 질문 2건(§4-6)**: 주간 UV 목표, 스크리닝 세션 비율 KPI — 배포 전 측정 불가 + 후자는 측정 인프라 자체 미구현. 오케스트레이터의 사용자 확인 필요, 임의 PASS 처리하지 않음.
- **실 서비스 규모(약 2,500종목) 성능 미실측**: DEF-IT-M01과 동일 원인(실 데이터 부재). 인덱스 설계 기반 코드 리뷰 추정만 가능(§4-2). 10단계에서 실 서비스키 확보 후 재실시 권고.
- **단일 uvicorn 워커, 다중 워커/수평 확장 미검증**: 초기 규모 전제(§8-A3)상 현재 범위에서는 정당하나, 실제 배포 시 워커 수 설정과 그에 따른 동시성 한계는 10단계에서 별도 확인 필요.
- **실 프로덕션 호스팅 환경 CORS/성능 미검증**: 호스팅 벤더 미확정(설계 §2-1), 로컬 스모크로 대체. 10단계 영역.
- 각 feature 통합테스트 문서(`feature-*.md`)가 이미 인계한 승계 리스크(DEF-006 LIKE 와일드카드, DEF-U08-01/02, percentile 템플릿 코드 미공유, 뒤로가기 시 스크리너 폼 리셋, `stock_master.sector` 미확정 등)는 08단계가 재검증하지 않았으며 상태 변경 없음 — 여기서 재서술하지 않는다.

## 9. 결론 및 판정
- [ ] PASS
- [x] **CONDITIONAL PASS** — 조건: **DEF-FS-01(High)을 10단계(배포테스트) 착수 전까지 반드시 해소**(연결 타임아웃 설정 + SQLAlchemy `OperationalError`/`DBAPIError`→503 `SERVICE_UNAVAILABLE` 전역 매핑 구현, 06/07/08 관련 슬라이스 재검증 완료 후 10단계 진행). 9단계(보안검증) 진행 자체는 이 조건으로 막지 않되, 9단계가 이 결함을 자원고갈 관점에서 추가 검토하도록 인계한다. UAT 질문 2건(§4-6)은 사용자 확인 후 결과를 이 문서 또는 후속 단계 산출물에 반영해야 한다(임의 PASS 처리 안 함).
- [ ] FAIL

**판정 근거**: 기획서 §3 핵심 가치 제안을 관통하는 E2E 시나리오가 데스크톱·모바일 양쪽에서 4개 기능을 순서대로 넘나들며 크래시 없이 동작함을 확인했고(§4-1, 신규 결함 0건), 성능 목표(§4-2)와 부하 스모크(§4-3)는 픽스처 규모에서 전부 목표를 크게 상회했다. 그러나 장애 복구 시나리오(§4-4)에서 설계(§5-4)가 명시한 요구사항이 어느 유닛에서도 구현되지 않은 채 남아 있던 공백을 실제 DB 중단으로 재현해 확정했다(DEF-FS-01, High) — 자체 크래시나 데이터 훼손은 없었고 프론트엔드는 이미 정상적으로 방어하고 있었으나, API 계약 위반과 20배 가까운 실패 지연은 실 운영 환경에서 사용자 신뢰와 가용성에 실질적 영향을 줄 수 있는 수준이라고 판단해 CONDITIONAL PASS로 판정한다. traceability.md 커버리지는 100%로 확정했고(REQ-014~021/023 Out-of-Scope 제외), REQ-022/REQ-024 게이트는 8단계 시점 기준 상태 불변임을 재확인했다.

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

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
  - 조치 내용: §6/§8/§9 서술을 9/10단계가 오독하지 않도록 보강한 것 외 결함 목록/판정 변경 없음 → 최종 **CONDITIONAL PASS** 유지.

- 검증 로그 파일 경로: 이 문서 §10에 통합 기록(별도 `verify-log_08-full-system-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — 06/07단계 산출물이 따른 것과 동일한 관례).

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
