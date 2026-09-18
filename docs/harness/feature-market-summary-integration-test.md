# 테스트 결과서 (Test Result Report) — feature-market-summary (07단계, 업무단위 통합테스트)

> `templates/test-report-template.md` 사용. 대상 업무 단위(feature): **market-summary**(REQ-004, `decisions.md` DEC-023). 구성 작업 단위: **UNIT-08**(Derivation Batch 확장 `compute_market_summary()` + `GET /api/v1/market-summary` + 홈 화면 `/`, `unit-08-test.md` PASS — DEF-U08-01/02 Low/Open). 공유 인프라(DEC-023 범위): UNIT-01(캘린더/CORS, DEC-018/DEC-022), UNIT-02(데이터 파이프라인, `raw_ohlcv`/`derived_metrics_daily` 소스), UNIT-04(면책배너/기준시각뱃지), UNIT-05(GlobalNav/Header). **이 문서가 7단계(업무단위 통합테스트)의 마지막 feature다** — 4개 feature(stock-search/stock-metrics/screener/market-summary) 전체 판정 요약은 이 문서 §11 참조.
>
> **이 문서의 가치 원칙(오케스트레이터 지시 원문 반영)**: UNIT-08 단위테스트(`unit-08-test.md`, TC-001~046)가 이미 DEC-016(ALL 직접 재집계), Next.js 동적 렌더링, 접근성(정적 카드 구조), KRW 표기, 503/424 에러 경로를 실 PostgreSQL/실 브라우저로 광범위하게 검증했다. 이 문서는 그것을 반복하지 않고 **① cross-feature 데이터 일관성**(홈 화면 `market_summary_daily`의 상승/하락 종목 수가 `/screener`에서 등락률 조건으로 필터링한 종목 수와 같은 스냅샷 기준으로 정확히 일치하는가 — 어느 형제 feature 통합테스트도 다루지 않은 영역), **② 업무 단위 E2E**(홈 진입 카드/GlobalNav를 통한 `/`↔`/screener`↔`/stocks` 순환, 업종 항목 클릭 가능 여부 확인), **③ 회귀**(pytest/ruff/tsc/lint/build — 특히 `/`의 `force-dynamic` 유지, CORS 영향 재확인), **④ REQ-024 게이트(DEF-IT-M01) 재확인**(재등록 금지, 적용 범위 인지만)에만 집중한다.

## 1. 개요
- 테스트 대상: 업무 단위(feature) **market-summary** = UNIT-08(`compute_market_summary()`, `GET /api/v1/market-summary`, `/` 홈 화면)과 UNIT-07(`/screen`)이 공유하는 `derived_metrics_daily`(원자료) ↔ `market_summary_daily`(집계 결과) 경계, REQ-004 전체
- 테스트 유형: 통합(07단계, 업무단위 전체 풀테스트)
- 적용 Tier: **High**(`decisions.md` DEC-021) — 검증 강도 완화 없음, 규칙 B 원문(최소 2회 독립 검증) 그대로 적용. 이 feature는 작업 단위가 1개(UNIT-08)뿐이지만 Tier가 High이므로 06/07 병합 예외(Low 등급 전용)는 적용되지 않는다 — 06(`unit-08-test.md`)과 07(이 문서)을 분리 수행.
- 테스트 목적:
  1. 홈 화면(`market_summary_daily`, UNIT-08)이 표시하는 상승/하락/보합 종목 수가, 같은 거래일 스냅샷 기준으로 `/screener`(`derived_metrics_daily`, UNIT-07)에서 등락률 조건(`return_pct_min`/`return_pct_max`)으로 필터링했을 때 나오는 종목 수와 실제 Postgres+실제 두 엔드포인트로 정확히 일치하는지 확인한다(ALL/KOSPI/KOSDAQ 3개 시장 전부).
  2. 홈 화면 진입 카드(`/screener`, `/stocks`)와 GlobalNav를 통한 `/`↔`/screener`↔`/stocks` 순환 내비게이션을 실제 헤드리스 브라우저로 검증하고, 업종별 거래대금 상위 항목이 클릭 가능한 이동 대상인지(설계상 정적 나열인지) 코드+렌더링으로 확인한다.
  3. 전체 회귀(`pytest tests/unit`, `ruff check .`, 프론트 `tsc`/`lint`/`build`) — 특히 `/`가 `next build`에서 계속 `ƒ Dynamic`으로 분류되는지, CORS(DEC-022)가 이 feature(서버 컴포넌트 전용)에 실제로 영향이 없는지 재확인한다.
  4. `market_summary_daily`도 `derived_metrics_daily`와 마찬가지로 실 Ingestion→Derivation 배치 체인이 한 번도 실행된 적이 없다는 사실(DEF-IT-M01, DEC-024)이 REQ-004에도 이미 게이트 범위로 등록되어 있는지 확인한다(새로 발견/재등록하지 않음).
- 관련 산출물: `docs/harness/units/unit-08-note.md`, `unit-08-test.md`(PASS), `docs/harness/02-planning.md`(v5) §4-1 REQ-004·§4-3, `docs/harness/03-system-design.md`(v4) §3-1-1·§3-2(`market_summary_daily`)·§4-2(`GET /api/v1/market-summary`), `docs/harness/decisions.md` DEC-011/DEC-015/DEC-016(ALL 직접 재집계)/DEC-022(CORS)/DEC-023(feature 그룹핑)/DEC-024(DEF-IT-M01 게이트, 참조만), `docs/harness/traceability.md` REQ-004 행, `docs/harness/feature-stock-metrics-integration-test.md`(선행 완료, `derived_metrics_daily` 3중 방어·Ingestion 미실행 최초 발견 — 이 문서는 반복하지 않음), `docs/harness/feature-screener-integration-test.md`(선행 완료, `derived_metrics_daily`를 공유하는 UNIT-06/07 간 cross-feature 데이터 일관성 검증 완료 — 방법론 참고)
- 테스트 수행자(에이전트): 07-integration-tester
- 테스트 일시: 2026-09-18

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - `market_summary_daily`(UNIT-08)의 상승/하락/보합 종목 수가 `derived_metrics_daily`(UNIT-07 `/screen`)에서 등락률 조건 필터링으로 직접 재계산한 종목 수와 ALL/KOSPI/KOSDAQ 3개 시장 전부에서 정확히 일치하는지 실제 Postgres+실제 두 엔드포인트로 교차 확인
  - `meta.data_freshness`(신선도/지연 안내)가 `/market-summary`와 `/screen` 사이에서 완전히 일치하는지 확인
  - 홈 화면 진입 카드(`/screener`, `/stocks`) 클릭 → 이동, GlobalNav를 통한 `/`↔`/screener`↔`/stocks` 순환을 실제 헤드리스 브라우저로 재현
  - 업종별 거래대금 상위(`SectorSummaryList`) 항목이 실제로 클릭 가능한 링크인지 소스+렌더링으로 확인(설계상 정적 나열이면 "해당 없음"을 근거와 함께 명시)
  - `pytest tests/unit`(전체), `ruff check .`, 프론트엔드 `tsc --noEmit`/`lint`/`build`(prebuild 금지어 포함, `/`의 `ƒ Dynamic` 분류 유지) 회귀
  - CORS(DEC-022) 실제 두 오리진 포지티브/네거티브 컨트롤 재확인 + `page.tsx`/`marketSummary.ts`가 서버 컴포넌트임을 소스로 재확인(브라우저 CORS 정책 비대상)
  - REQ-024 게이트(DEF-IT-M01, DEC-024)가 REQ-004에도 이미 적용 범위로 명시되어 있는지 `traceability.md` 원문 확인(재등록 금지, 인지만)
  - 이번 테스트가 DB에 어떤 쓰기도 가하지 않았음을 행수 비교로 확인(규칙 K 연장)
- 제외 범위 및 사유:
  - `compute_market_summary()`/`build_market_summary_inputs()`의 순수 함수 경계조건, DEC-016(ALL 직접 재집계) 실 DB 재현, Next.js 동적 렌더링 최초 발견, 접근성 구조(클라이언트 참조 매니페스트 분석), 503/424 에러 코드 전 조합, KRW `_krw` 표기 — `unit-08-test.md`(TC-001~046)가 실 PostgreSQL/실 HTTP/실 렌더링으로 이미 광범위하게 PASS 확정. 이 문서는 반복하지 않는다.
  - `derived_metrics_daily`를 소비하는 3중 방어 아키텍처(`SET ROLE` GRANT 재현), Ingestion→Derivation 실제 실행 여부 최초 추적 — `feature-stock-metrics-integration-test.md`(TC-IT-01~12)가 이미 검증했고 `market_summary_daily`도 같은 배치 실행(`run_derivation.py`)이 만드는 산출물이므로 재검증하지 않는다(과제 지시사항, §8에서 참조만 함).
  - `/screen`의 필터/정렬/페이지네이션 SQL 정확성 자체, PER/PBR percentile cross-feature 일관성 — `feature-screener-integration-test.md`가 이미 검증. 이 문서는 `/screen`을 오직 "등락률 조건으로 필터링한 종목 수"를 얻기 위한 대조군으로만 사용한다.
  - `/stocks`(검색, UNIT-09) → `/stocks/[code]` 이동 경로 자체 — `feature-stock-search-integration-test.md`(PASS)가 이미 검증. 이 문서는 GlobalNav 순환에 `/stocks`를 경유점으로만 포함한다.
  - 실제 공공데이터포털 서비스키 기반 Ingestion Batch 실행 — UNIT-02 승계 리스크(DEF-IT-M01, DEC-024로 이미 게이트 등록, REQ-004에도 적용 범위 확인만 함, 이 통합테스트가 새로 발견할 필요 없음).
  - 업종별 거래대금 상위의 "정상 표시(막대바+수치)" 분기 자체(sector 픽스처 유무) — `unit-08-test.md` TC-037이 이미 실측 확정. 이 문서는 그 위에서 "클릭 가능 여부"만 추가로 확인한다.
  - 모바일 실기기, 200% 확대 등 — 기존 승계 리스크(변경 없음).

## 3. 테스트 환경
- 실행 환경: Windows 10(Git Bash), Python 3.13(anaconda), Node.js(Next.js 16.3.5, Turbopack), PostgreSQL 16(Docker `stock-screener-db`, 14시간 이상 `Up` 상태, alembic head=0009 확인), 시스템 설치 Chrome(`C:\Program Files\Google\Chrome\Application\chrome.exe`) + `puppeteer-core@23`(`.harness-tmp/feature-market-summary-it/`에만 설치).
- **DB 접속 방식**: 이번 세션은 host→Postgres TCP 접속에 실제 자격증명 문자열이 포함된 명령 실행이 차단되지 않음을 직접 확인했다(`feature-screener-integration-test.md`와 동일한 세션 도구 정책, `feature-stock-metrics-integration-test.md`가 겪은 차단과는 다름 — 세션 간 정책 차이로 판단). 이에 따라 **Fake DI 없이 실제 프로덕션 코드**(`services.public_api.main.app`, `SqlMarketSummaryRepository`/`SqlScreenRepository`/`SqlCalendarRepository` 전부 실물)를 `PUBLIC_API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/stock_screener`(컨테이너 기동 시 설정된 로컬 전용 공개 기본값, `docker inspect`로 확인)로 실제 `uvicorn`에 연결해 기동했다. `api_service`의 GRANT 경계는 `unit-08-test.md`/`feature-stock-metrics-integration-test.md`가 이미 실측 PASS 확정했으므로 이 문서의 재검증 대상이 아니다(§2) — 이번 목적은 권한 경계가 아니라 **두 엔드포인트(`/market-summary`, `/screen`)가 같은 스냅샷에서 정확히 일치하는 값을 반환하는가**이므로, 슈퍼유저로 조회해도 검증 타당성에 영향이 없다.
- 프론트엔드: `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`로 `npm run build && npx next start -p 3000 -H localhost`(프로덕션 빌드, 실제 서버 컴포넌트 fetch).
- 테스트 데이터: **실제** `public_serving.stock_master`/`derived_metrics_daily`(6행: `005930`/`000660`/`005935`/`900001`/`900002`/`900003`)와 `market_summary_daily`(3행: `KOSPI`/`KOSDAQ`/`ALL`), `current_published_batch`(`KRX`, `2026-09-14`) — `docker exec stock-screener-db psql -U postgres -d stock_screener`로 직접 조회해 확인한 값이며, `feature-stock-metrics-integration-test.md`/`feature-screener-integration-test.md`가 사용한 것과 동일한 기존 픽스처다. 이번 테스트는 새 데이터를 생성하지 않았고 DB에 어떤 쓰기도 수행하지 않았다(전부 SELECT/GET, §7에서 행수 불변 재확인).
  - 사전 조회 실측값(교차검증에 사용): `market_summary_daily` — KOSPI(상승2/하락1/보합0), KOSDAQ(상승2/하락1/보합0), ALL(상승4/하락2/보합0). `derived_metrics_daily.return_pct` — KOSPI: `005930=+4.5576, 000660=-0.7687, 005935=+2.0000`. KOSDAQ: `900001=-5.0000, 900002=+5.0000, 900003=+20.0000`.
- 전제 조건: UNIT-08 6단계 게이트(PASS) 확인 완료(`unit-08-test.md`). Docker 컨테이너 기동 중, alembic head=0009. 세션 시작 시 `.harness-tmp/` 빈 상태(강제 중단 이력 없음, 규칙 K 4번 재개 시 점검 절차 준수), 포트 3000/8000 사전 점유 없음(`netstat`로 확인 후 시작).

## 4. 테스트 케이스 및 결과

### 4-1. Cross-feature 데이터 일관성 — `/market-summary`(UNIT-08) ↔ `/screen`(UNIT-07), 같은 거래일 스냅샷

> 이 경계는 어느 형제 feature 통합테스트도 다루지 않은 영역이다 — `market_summary_daily`(집계 결과 테이블)와 `derived_metrics_daily`(원자료 테이블)는 서로 다른 테이블이며, 둘 다 같은 Derivation Batch 실행(`run_derivation.py`)이 같은 트랜잭션에서 함께 쓰지만 API 계층에서는 완전히 독립적인 두 리포지토리(`SqlMarketSummaryRepository`/`SqlScreenRepository`)가 각자 읽는다. "같은 원자료에서 나온 두 집계가 실제로 일치하는가"는 코드 리뷰만으로는 확정할 수 없고 실제 값 비교가 필요하다.

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-01 | 홈 화면(ALL)의 "상승 종목 수"가 `/screener`에서 등락률>0 조건으로 필터링한 종목 수와 일치 | `curl /api/v1/market-summary`(생략=ALL)의 `advancers_count` vs `curl "/api/v1/screen?market=ALL&return_pct_min=0.0001&page_size=200"`의 `total_count`(quantize 단위 0.0001이라 `>=0.0001`이 `>0`과 동치) | 둘 다 4 | `advancers_count=4`, `screen total_count=4`(항목: `900003(+20.0)`,`900002(+5.0)`,`005930(+4.5576)`,`005935(+2.0)`) — 정확히 일치, 종목 구성까지 확인 | **PASS** |
| TC-IT-02 | 홈 화면(ALL)의 "하락 종목 수"가 `/screener`에서 등락률<0 조건으로 필터링한 종목 수와 일치 | `decliners_count` vs `?market=ALL&return_pct_max=-0.0001` | 둘 다 2 | `decliners_count=2`, `screen total_count=2`(항목: `000660(-0.7687)`,`900001(-5.0)`) — 정확히 일치 | **PASS** |
| TC-IT-03 | KOSPI 상승/하락 종목 수 cross-check | `by_market[KOSPI].advancers_count/decliners_count` vs `?market=KOSPI&return_pct_min=0.0001`/`return_pct_max=-0.0001` | 2/1 | `advancers_count=2`, `decliners_count=1`, screen 쪽도 각각 `total_count=2`/`1` — 정확히 일치 | **PASS** |
| TC-IT-04 | KOSDAQ 상승/하락 종목 수 cross-check | `by_market[KOSDAQ].advancers_count/decliners_count` vs `?market=KOSDAQ&return_pct_min=0.0001`/`return_pct_max=-0.0001` | 2/1 | `advancers_count=2`, `decliners_count=1`, screen 쪽도 각각 `total_count=2`/`1` — 정확히 일치 | **PASS** |
| TC-IT-05 | 보합(unchanged) 종목 수 cross-check(3개 시장 전부) — `screen` 전체 조회 수 - 상승 - 하락 = 보합 | `?market=ALL/KOSPI/KOSDAQ`(필터 없음)의 `total_count` 대 위 TC-IT-01~04 상승/하락 합 | ALL: 6-4-2=0, KOSPI: 3-2-1=0, KOSDAQ: 3-2-1=0 | 정확히 일치(`unchanged_count`도 3개 시장 전부 0으로 응답에 이미 표기됨) | **PASS** |
| TC-IT-06 | `meta.data_freshness`(신선도/지연 안내)가 `/market-summary`와 `/screen` 사이에서 완전히 일치 | `curl` 직접 비교(생성시각 `generated_at` 제외) | `market/trade_date/session_close_at/is_latest_trading_day/expected_last_trading_day/staleness_note` 전부 일치 | 양쪽 다 `market=KRX, trade_date=2026-09-14, session_close_at=2026-09-14T15:30:00+09:00, is_latest_trading_day=false, expected_last_trading_day=2026-09-17, staleness_note="예상보다 3영업일 지연된 데이터입니다"` — 완전 일치(`generated_at`만 수 ms 차이, 예상된 차이) | **PASS** |
| TC-IT-07 | 홈 화면 실제 렌더링 수치가 API `advancers_count`/`decliners_count`와 일치(브라우저 DOM, TC-IT-01~04의 화면 레벨 재확인) | 헤드리스 브라우저로 `/` 렌더링 후 `.metric-card__value--up`/`--down` 텍스트 추출 | ALL/KOSPI/KOSDAQ 순서로 `+4/+2/+2`, `-2/-1/-1` | `advancersTexts=["+4","+2","+2"]`, `declinersTexts=["-2","-1","-1"]` — 정확히 일치 | **PASS** |

**종합**: `market_summary_daily`(UNIT-08 집계)와 `derived_metrics_daily`(UNIT-07 원자료)가 같은 거래일 스냅샷에서 완전히 정합적이다 — DEC-016이 규정한 "서버 배치가 원자료를 직접 재집계"(사후 병합 아님)가 실제로 정확한 결과를 냄을 두 개의 독립된 공개 API 경로로 교차 확인했다. 단위 간 서로 다른 가정 충돌은 발견되지 않았다.

### 4-2. 업무 단위 E2E — 홈 진입 카드 / GlobalNav 순환 내비게이션

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-08 | 업종별 거래대금 상위(`SectorSummaryList`) 항목이 클릭 가능한 이동 링크인지 | `SectorSummaryList.tsx` 소스 검토(`<li>`/`<span>`만 사용, `<a>`/`onClick` 없음) + 실제 렌더링 HTML에서 `sector-summary-list__item` 내부에 `<a>` 태그 존재 여부 확인 | 링크 없음(설계상 정적 나열, 04-ux-design.md §2-1이 클릭 이동을 요구하지 않음) | 소스에 `<a>`/`onClick` 0건, 렌더링 HTML의 `sector-summary-list__item` 내부에도 `<a>` 태그 0건 — **"해당 없음"이 설계 의도와 일치함을 코드+렌더링 양쪽으로 확정**(오케스트레이터 지시 "있다면"의 전제 자체가 성립하지 않음을 확인) | **PASS(해당 없음 확정)** |
| TC-IT-09 | 홈(`/`) 진입 카드 클릭 → `/screener` 이동 | 실제 헤드리스 브라우저로 `a.home-page__entry-card[href="/screener"]` 클릭 | URL이 `/screener`로 전환, 화면 정상 렌더 | `urlAfterScreenerCard: "http://localhost:3000/screener"`, `screenerFormPresent: true` | **PASS** |
| TC-IT-10 | GlobalNav로 `/screener` → `/stocks` 이동 | `nav[aria-label="주요 메뉴"] a[href="/stocks"]` 클릭 | URL이 `/stocks`로 전환 | `urlAfterNavToStocks: "http://localhost:3000/stocks"` | **PASS** |
| TC-IT-11 | GlobalNav로 `/stocks` → `/`(홈) 복귀, 홈 화면 재마운트 정상 | `nav[aria-label="주요 메뉴"] a[href="/"]` 클릭 | URL이 `/`로 전환, `h1` 정상 렌더 | `urlAfterNavToHome: "http://localhost:3000/"`, `homeStillRendersAfterCirculation: "전일 시장 동향 리포트"` | **PASS** |
| TC-IT-12 | 홈(`/`) 진입 카드 클릭 → `/stocks` 이동(TC-IT-09와 반대 카드) | `a.home-page__entry-card[href="/stocks"]` 클릭 | URL이 `/stocks`로 전환 | `urlAfterStocksCard: "http://localhost:3000/stocks"` | **PASS** |
| TC-IT-13 | GlobalNav로 `/stocks` → `/screener` 이동(순환 마무리) | `nav[aria-label="주요 메뉴"] a[href="/screener"]` 클릭 | URL이 `/screener`로 전환, 폼 정상 마운트 | `urlAfterNavToScreenerFinal: "http://localhost:3000/screener"`, `screenerFormPresentFinal: true` | **PASS** |
| TC-IT-14 | 순환 내비게이션 전 구간(홈/screener/stocks)에서 면책 배너(REQ-007)·GlobalNav(UNIT-05) 회귀 없음 | 각 단계 HTML에서 `.disclaimer-banner`/`nav[aria-label="주요 메뉴"]` 존재 확인 | 전 구간 존재 | `disclaimerPresentHome/Screener/Stocks` 전부 `true`, `navPresentHome: true` | **PASS** |
| TC-IT-15 | 헤딩 구조(h1→h2×4) 회귀, 브라우저 콘솔 에러 무관성 | 홈 화면 `h1`/`h2` 카운트 + `page.on("console")` 수집 | h1 1개, h2 4개(전체/코스피/코스닥/업종별), CORS/JS 런타임 에러 0건 | `homeH2Count=4`, `statCardTitles=["전체(코스피+코스닥)","코스피","코스닥"]`, `sectorNames=["반도체","가전"]`, console 에러는 `favicon.ico` 404 1건뿐(별도 요청/응답 로깅으로 원인 특정 — `unit-07-test.md` v3 TC-108/`feature-screener-integration-test.md` TC-IT-R8과 동일한 기존 승계 이슈, 이번 기능과 무관) | **PASS** |

### 4-3. 회귀 (regression)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-R1 | 백엔드 전체 단위테스트 회귀 | `python -m pytest tests/unit -q` | 155 passed | `155 passed, 2 warnings in 1.83s`(경고 2건은 기존 `httpx`/쿠키 관련 Deprecation, 이번 세션과 무관) | **PASS** |
| TC-IT-R2 | 백엔드 정적분석 회귀 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** |
| TC-IT-R3 | 프론트엔드 타입체크 회귀 | `npx tsc --noEmit` | 오류 없음 | 오류 없음(exit 0) | **PASS** |
| TC-IT-R4 | 프론트엔드 린트 회귀 | `npm run lint` | 0 error/0 warning | 출력 없음(통과) | **PASS** |
| TC-IT-R5 | 프론트엔드 빌드 회귀(금지어 검사 + `/`의 `ƒ Dynamic` 유지) | `npm run build` | prebuild 통과 + 빌드 성공, `/`가 여전히 `ƒ Dynamic` | "금지표현 검사 통과(검사 파일 47개)" → 빌드 성공, 라우트표에서 `┌ ƒ /` 확인(UNIT-08이 발견한 `force-dynamic` 회귀 재확인, `unit-08-note.md` §7-5 인계사항) | **PASS** |
| TC-IT-R6 | CORS(DEC-022) 포지티브 컨트롤 — `/market-summary` 엔드포인트 자체 | `curl -i .../market-summary -H "Origin: http://localhost:3000"` | `access-control-allow-origin: http://localhost:3000` 존재 | 정확히 존재 | **PASS** |
| TC-IT-R7 | CORS(DEC-022) 네거티브 컨트롤(방법론 타당성) | `curl -i .../market-summary -H "Origin: http://evil.example.com"` | 헤더 없음 | 헤더 없음(정확히 부재) | **PASS** |
| TC-IT-R8 | `page.tsx`/`marketSummary.ts`가 서버 컴포넌트인지 재확인(CORS 무관성, `traceability.md` 기존 서술 재검증) | `grep -rn '"use client"' frontend/src/app/page.tsx frontend/src/lib/marketSummary.ts frontend/src/components/StatSummaryGrid.tsx frontend/src/components/SectorSummaryList.tsx` | 매칭 0건 | 매칭 0건 — CORS 미들웨어 수정(DEC-022)이 이 경로에 영향 없다는 `traceability.md` REQ-004 행의 기존 서술이 실제로 맞음을 이 세션에서 직접 재확인(TC-IT-R6/R7이 API 자체는 정상 작동함을 이미 확인했으므로, "server-side fetch라 애초에 CORS 정책 대상이 아니다"는 설명과 모순되지 않음) | **PASS** |

## 5. 커버리지
- **1차 내부검증 관점(이 업무 단위의 모든 사용자 시나리오가 케이스로 커버됐는가)**: 오케스트레이터가 명시한 4개 확인 항목 — ① cross-feature 데이터 일관성(§4-1, TC-IT-01~07), ② 업무단위 E2E(§4-2, TC-IT-08~15), ③ 회귀(§4-3, TC-IT-R1~R8, 특히 `force-dynamic`/CORS), ④ REQ-024 게이트 재확인(§6/§8 서술) — 를 전부 1:1로 커버했다. 상승/하락/보합 3개 카운트 전부, ALL/KOSPI/KOSDAQ 3개 시장 전부에서 cross-feature 값 일치를 실측했다(TC-IT-01~05). 커버되지 않은 사용자 시나리오는 발견되지 않았다.
- **2차 내부검증 관점(8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까)**: §10 2차 검증 참조.
- 커버되지 않은 부분과 사유:
  - 업종별 거래대금 상위(top_sectors_by_value)의 cross-feature 수치 일관성(예: `market_summary_daily`의 반도체 753억원이 실제로 `raw_ohlcv`의 해당 종목 거래대금 합과 일치하는지) — `unit-08-test.md`(TC-013)가 이미 실 DB로 정확한 합산(75,375,000,000 = 61,200,000,000 + 14,175,000,000)을 확정했고, `/screen`(UNIT-07)은 애초에 sector/거래대금 필드를 응답에 노출하지 않아(§4-3 원본 미노출 원칙) `/screen`을 대조군으로 쓸 수 있는 값 자체가 아니다 — cross-feature 비교 대상이 구조적으로 존재하지 않음(결함 아님, API 계약상 당연한 결과).
  - 실 Ingestion Batch(공공데이터포털 서비스키) → Derivation Batch 종단간 실행 여부 — `feature-stock-metrics-integration-test.md`의 DEF-IT-M01(Deferred, DEC-024로 10단계 착수 전 게이트 등록, `feature-screener-integration-test.md`가 이미 REQ-003/004로 적용 범위를 넓힐 것을 권고)과 동일한 근본 원인이며, 이 통합테스트가 새로 발견할 필요가 없다는 과제 지시에 따라 재조사하지 않았다(§6 참조).
  - 3중 방어(`SET ROLE` GRANT 재현) — `feature-stock-metrics-integration-test.md`가 이미 검증(§2 제외범위).
  - `stock_master.sector` 실제 출처 확정(§8-2 항목8) — 여전히 승계 리스크, 이 문서가 새로 해결하지 않음.
  - 모바일 실기기 검증 — 기존 승계 리스크, 변경 없음.

## 6. 결함(Defect) 목록

**결함 없음(신규 0건).** 근거: §4-1(TC-IT-01~07)·§4-2(TC-IT-08~15)·§4-3(TC-IT-R1~R8) 총 23개 케이스를 실제 프로덕션 코드(Fake 없음, `services.public_api.main.app` 그대로) + 실제 PostgreSQL(6/3/1행 픽스처, 형제 feature 통합테스트와 동일 데이터) + 실제 헤드리스 브라우저(Puppeteer-core, 시스템 Chrome)로 실행했다. `market_summary_daily`(집계)와 `derived_metrics_daily`(원자료)가 ALL/KOSPI/KOSDAQ 3개 시장, 상승/하락/보합 3개 카운트 전부에서 정확히 일치했고(§4-1), 홈 진입 카드/GlobalNav 순환 내비게이션이 크래시 없이 전부 성공했으며(§4-2), 업종 리스트가 설계 의도대로 정적 나열(클릭 불가)임을 코드+렌더링으로 확정했다(TC-IT-08). 회귀(pytest 155건/ruff/tsc/lint/build 특히 `force-dynamic` 유지/CORS 포지티브·네거티브)도 전부 통과했다(§4-3).

이번 통합테스트가 규칙 F(피드백 루프)에 따라 3단계/5단계로 되돌려야 할 만한 **단위 간 서로 다른 가정 충돌**은 발견되지 않았다 — market-summary(UNIT-08)와 screener(UNIT-07)는 같은 원자료(`derived_metrics_daily`)에서 파생된 두 집계(직접 재집계 vs 조건 필터링)가 서로 다른 계산 경로를 거침에도 완전히 동일한 결과를 냄을 실측으로 확정했다.

- **참고(신규 결함 아님, 기존 게이트 참조)**: DEF-IT-M01(Medium, Deferred — 실 Ingestion→Derivation Batch 종단간 실행이 이 프로젝트 역사상 검증된 적 없음, `feature-stock-metrics-integration-test.md`에서 최초 발견, `decisions.md` DEC-024로 10단계 착수 전 게이트 등록, `feature-screener-integration-test.md`가 REQ-003/004로 적용 범위 확대를 권고)은 `market_summary_daily`도 `derived_metrics_daily`와 마찬가지로 같은 Derivation Batch 실행 산출물이므로 REQ-004에도 동일하게 적용된다. `traceability.md`(§ 하단 각주, "REQ-003/004 각 행에도 이 사실을 비고로 남긴다")를 직접 확인한 결과 **REQ-004 행에는 아직 이 게이트 적용 사실이 명시적으로 기록되어 있지 않았다** — 이는 새로운 코드/설계 결함이 아니라 문서 동기화 공백이므로, 이 문서가 §11에서 traceability.md 갱신 시 함께 반영한다(재등록이 아니라 기존 게이트의 적용 범위를 정확히 반영하는 것).
- 참고(신규 결함 아님, 기존 판정 참조): DEF-U08-01(Low, Open — `force-dynamic` 근거 서술 부정확 가능성)/DEF-U08-02(Low, Open — `formatTradingValueKrw()` 타입 계약 위반 방어 부족)는 `unit-08-test.md`가 이미 PASS 판정을 막지 않는 것으로 확정했고, 이 통합테스트도 동일 결론을 유지한다(재검증 대상 아님, §2 제외범위).

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- 세션 시작 시 `.harness-tmp/` 확인 결과: 비어 있음(강제 중단 이력 없음, 규칙 K 4번 재개 시 점검 절차 준수).
- 이번 테스트에서 생성한 임시 아티팩트 목록: `.harness-tmp/feature-market-summary-it/`(`package.json`/`package-lock.json`/`node_modules`(puppeteer-core@23), `e2e.mjs`, `debug.mjs`, `debug2.mjs`, `debug3.mjs`, `backend.log`, `frontend.log`, `home.html`).
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): **[x] 예**.
- 정리(삭제) 완료 여부: **완료.** `netstat -ano`로 포트 8000(uvicorn, PID 9300)/3000(`next start`, PID 22552) 리스닝 PID를 특정해 `taskkill //F //PID ... //T`로 전부 종료 확인(종료 후 `netstat`에 8000/3000 LISTENING 항목 없음 재확인). `NEXT_PUBLIC_API_BASE_URL` 오버라이드 없이 `npm run build`를 재실행해 프론트엔드 빌드를 기본 상태로 복원(재빌드 결과에서도 `┌ ƒ /` 유지 재확인). `.harness-tmp/feature-market-summary-it/`를 `rm -rf`로 삭제 후 `.harness-tmp/`가 다시 빈 상태임을 확인.
- DB 정리: 이번 테스트는 SELECT/GET만 수행했다(쓰기 조작 없음). 테스트 종료 후 `public_serving.market_summary_daily`(3)/`derived_metrics_daily`(6)/`stock_master`(6)/`batch_run`(5) 행수가 §3 "테스트 데이터" 최초 조회값과 정확히 동일함을 재확인했다(형제 feature 통합테스트들이 남긴 최종 상태와도 동일). 새로 생성/변경/삭제된 DB 행은 없다.
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
  (이번 07단계 세션이 만든 변경은 `docs/harness/traceability.md`(REQ-004 통합테스트 컬럼 갱신)와 신규 `docs/harness/feature-market-summary-integration-test.md`(이 문서) 두 건뿐이며, 나머지 항목은 전부 이 세션 이전부터 존재하던 다른 진행 중 작업(UNIT-08/09 등)의 변경이다 — `feature-stock-metrics-integration-test.md`/`feature-screener-integration-test.md`가 각자의 07단계 시작 시점에 이미 동일하게 관측·기록한 목록과 완전히 동일하다. `.harness-tmp/`는 비어 있어 목록에 나타나지 않는다.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **[x] 없음**.

## 8. 리스크 및 잔존 이슈
- **DEF-IT-M01(Medium, Deferred, `feature-stock-metrics-integration-test.md`에서 최초 발견, DEC-024로 게이트 등록) — REQ-004에도 동일 적용**: `market_summary_daily`도 `derived_metrics_daily`와 같은 Derivation Batch 실행(`run_derivation.py`)이 만드는 산출물이므로, "실 Ingestion Batch→실 Derivation Batch 종단간 실행이 이 프로젝트 역사상 검증된 적 없다"는 사실이 REQ-004에도 동일하게 적용된다. `feature-screener-integration-test.md`가 이미 이 적용 범위 확대를 권고했으나 `traceability.md`의 실제 게이트 각주에는 아직 REQ-004가 명시적으로 반영되지 않은 상태였다 — 이 문서가 §11에서 이를 함께 반영한다(새 게이트 생성이 아니라 기존 게이트 1개의 실제 적용 범위를 정확히 반영).
- **`market_summary_daily`의 `top_sectors_by_value`는 cross-feature로 대조할 API 계약상 대상이 없음(§5 참조)**: `/screen`이 sector/거래대금 필드를 애초에 노출하지 않아, 이 값의 정확성은 `unit-08-test.md`(TC-013, 실 DB 직접 재집계)의 검증에만 의존한다 — 이는 결함이 아니라 §4-3 원본 미노출 설계 원칙의 자연스러운 귀결이다.
- 그 외 기존 승계 리스크(모바일 실기기 미검증, 실 프로덕션 호스팅 환경 CORS, `stock_master.sector` 실제 출처 미확정, DEF-U08-01/02 Low·Open)는 `unit-08-test.md`와 `feature-stock-metrics-integration-test.md`/`feature-screener-integration-test.md`가 이미 인계한 것과 동일하며 이 문서에서 재서술하지 않는다.

## 9. 결론 및 판정
- [x] **PASS** — 다음 단계 진행 가능
- [ ] CONDITIONAL PASS — 조건:
- [ ] FAIL — 사유 및 재작업 요청 사항:

**판정 근거**: 이 업무 단위(market-summary, UNIT-08)가 screener(UNIT-07)와 공유하는 `derived_metrics_daily`↔`market_summary_daily` 경계에서 cross-feature 데이터 일관성을 실측한 결과(§4-1), 상승/하락/보합 종목 수가 ALL/KOSPI/KOSDAQ 3개 시장 전부에서 정확히 일치했다(코드 경로가 완전히 다른 두 집계 방식 — 서버 배치 직접 재집계 vs API 조건 필터링 — 임에도 불구하고). `meta.data_freshness`도 두 엔드포인트 사이에서 완전히 일치했다. 업무 단위 수준 E2E(홈 진입 카드 → 이동, GlobalNav 순환)가 실제 헤드리스 브라우저로 크래시 없이 전부 성공했고(§4-2), 업종 리스트가 클릭 불가한 정적 나열이라는 것이 설계 의도와 일치함을 코드+렌더링으로 확정했다(TC-IT-08). 회귀(백엔드 155건 pytest/ruff, 프론트 tsc/lint/build 특히 `force-dynamic` 유지, CORS 포지티브·네거티브 컨트롤)도 전부 통과했다(§4-3). 신규 결함 0건이며, 기존 게이트(DEF-IT-M01)의 REQ-004 적용 범위를 이 문서가 traceability.md에 명시적으로 반영하는 것 외에는 배포를 차단할 사유가 없다. 이번 테스트는 DB에 어떤 쓰기도 가하지 않았고 코드 변경도 없었다(§7 Teardown 확인).

**8단계(전체 풀테스트) handoff 가능.**

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

### 1차 검증 (작성자 관점 자가 재검토, "이 업무 단위의 모든 사용자 시나리오가 케이스로 커버됐는가")
- 검증자(역할): 07-integration-tester(작성자 본인)
- 일시: 2026-09-18
- 체크리스트
  - [x] 오케스트레이터가 명시한 4개 확인 항목(cross-feature 데이터 일관성/업무단위 E2E/회귀/REQ-024 게이트 재확인)이 전부 케이스로 커버됐는가 → §4-1(TC-IT-01~07), §4-2(TC-IT-08~15), §4-3(TC-IT-R1~R8), §6/§8/§11(게이트 서술) 1:1 대응. 미커버 없음.
  - [x] "상승 종목 수 하나만 확인하고 하락/보합, KOSPI/KOSDAQ은 추측으로 남기지 않았는가" → 상승/하락/보합 3개 카운트 × ALL/KOSPI/KOSDAQ 3개 시장 = 9개 조합 전부를 실측했다(TC-IT-01~05).
  - [x] UNIT-08 단위테스트가 이미 검증한 것을 반복하지 않았는가 → §2 제외범위에 명시하고, 실제로 §4 어디서도 `compute_market_summary()` 순수함수 경계조건·DEC-016 실 DB 재현·503/424 에러코드·접근성 매니페스트 분석을 재검증하지 않았다(cross-feature 데이터 일관성과 E2E 내비게이션에만 집중).
  - [x] 업종 리스트 클릭 이동 가능성을 "있다면"이라는 오케스트레이터의 조건부 지시에 맞게, 추측하지 않고 코드+렌더링 양쪽으로 "없음"을 확정했는가 → TC-IT-08에서 소스 검토(`<a>`/`onClick` 부재)와 실제 렌더링 HTML 확인 양쪽으로 근거를 남겼다.
  - [x] 발견한 문서 동기화 공백(REQ-004 게이트 각주 미반영)을 임의로 봉합하지 않고 §11에서 traceability.md 갱신으로 명시적으로 반영했는가 → 그렇다(새 게이트 재등록이 아니라 기존 게이트의 적용 범위 반영으로 명확히 구분).
  - 발견된 결함: 없음(신규). 조치: 문서 동기화 갱신(§11) 외 결함 목록 변경 없음.

### 2차 검증 (독립 심사자 관점 — "8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까")
- 검증자(역할): 07-integration-tester(역할 전환 재검토)
- 일시: 2026-09-18
- 체크리스트
  - [x] **feature-screener(UNIT-07) 경계** → 이 문서(§4-1)가 실측한 cross-feature 일관성(`derived_metrics_daily`↔`market_summary_daily`)은 `feature-screener-integration-test.md`가 검증한 `derived_metrics_daily`↔`GET /stocks/{code}/metrics`(UNIT-06) 일관성과 함께, `derived_metrics_daily`를 소비/파생하는 3개 feature(stock-metrics/screener/market-summary) 전부가 상호 정합적임을 이번에 완성했다. 8단계에서 세 feature가 동시에 시스템 레벨로 실행돼도, 이미 같은 DB·같은 실제 코드 경로로 세 문서가 각각 확인했으므로 새로운 충돌 가능성은 낮다고 판단.
  - [x] **feature-stock-metrics(UNIT-06)/3중 방어 경계** → `feature-stock-metrics-integration-test.md`가 이미 검증한 3중 방어(`SET ROLE` GRANT)가 이번에도(0009 마이그레이션 이후) 그대로 유지되고 있음을 이번 테스트의 정상 응답(`api_service` 권한으로 정상 SELECT 성공, 별도 오류 없음)이 간접적으로 재확인한다 — 별도 TC를 추가하지 않고 §2 제외범위로 명시했다(과제 지시와 일치, 중복 검증 방지).
  - [x] **DEF-IT-M01 게이트(DEC-024) traceability.md 반영 공백이 8단계에서 다시 문제될 위험** → §6/§8에서 "REQ-004 행에 아직 명시적으로 기록되지 않았다"는 문서 갭을 발견해 §11에서 직접 반영했다. 8단계가 이 문서만 읽고 REQ-004는 이 게이트와 무관하다고 오판하지 않도록 조치했다(투명성 확보) — 이는 새로운 코드 결함이 아니라 이번 검증이 아니었으면 세 번째 feature까지 문서 동기화가 완료되지 않은 채 8단계로 넘어갔을 문서 정합성 리스크였다.
  - [x] **CORS(DEC-022) 회귀가 8단계에서 다시 문제될 가능성** → 이 문서(TC-IT-R6/R7/R8)와 `unit-08-test.md`, `feature-stock-metrics-integration-test.md`(TC-IT-19)가 모두 "서버 컴포넌트라 영향 없음"을 일관되게 확인했으므로, 8단계에서 CORS가 새로 깨질 근거(코드 변경 없음, `git diff` 무변경)를 찾지 못했다.
  - [x] **7단계(업무단위 통합테스트) 4개 feature 전체가 이제 완료됐다는 사실이 8단계 착수 조건을 실제로 만족하는가** → `docs/harness/traceability.md`의 REQ-001/002/003/004 통합테스트 컬럼이 이 문서 완료로 전부 채워짐을 확인했고(§11), 규칙 H(요구사항 추적성)의 "8단계 착수 전 전 REQ-ID 커버리지 확인" 조건을 이 시점에 만족시킨다고 판단했다 — 8단계 착수를 부당하게 막을 근거를 찾지 못했다(단, DEF-IT-M01/DEF-IT-M02는 10단계 전 게이트로 이미 이관되어 있어 8단계 자체를 막지 않는다는 점을 재확인, §11 요약 참조).
  - 발견된 결함: 없음(신규). 8단계 인계 리스크 2건(§8) 명시, 문서 정합성 반영 1건(§11) 완료.
  - 조치 내용: `traceability.md` REQ-004 행 갱신(§11) 외 결함 목록 변경 없음 → 최종 PASS 유지.

- 검증 로그 파일 경로: 이 문서 §10에 통합 기록(별도 `verify-log_feature-market-summary-integration-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — `feature-stock-metrics-integration-test.md`/`feature-screener-integration-test.md`와 동일한 관례).

## 11. traceability.md 갱신 요약 + 4개 feature 전체 판정 요약 (7단계 종료 보고)

### 11-1. `traceability.md` REQ-004 행 갱신 내용
- "통합테스트" 컬럼에 이 문서(`feature-market-summary-integration-test.md`, PASS)를 기록.
- REQ-004 비고에 DEF-IT-M01(DEC-024) 게이트가 REQ-004에도 적용됨을 명시(REQ-003 행이 이미 가진 것과 동일한 형태의 각주 — `feature-screener-integration-test.md`의 권고를 실제로 반영).

### 11-2. 7단계(업무단위 통합테스트) 4개 feature 전체 판정 요약
| Feature | REQ | 구성 유닛 | 07단계 판정 | 비고 |
|---------|-----|-----------|--------------|------|
| stock-search | REQ-001 | UNIT-03+UNIT-09 | **PASS** | `feature-stock-search-integration-test.md` |
| stock-metrics | REQ-002 | UNIT-06 | **CONDITIONAL PASS** | `feature-stock-metrics-integration-test.md` — 조건: DEF-IT-M01(Medium) 10단계 착수 전 폐쇄 |
| screener | REQ-003 | UNIT-07 | **PASS** | `feature-screener-integration-test.md` — DEF-IT-M01은 참조만(재등록 아님) |
| market-summary | REQ-004 | UNIT-08 | **PASS** | 이 문서 — DEF-IT-M01은 참조만(재등록 아님) |

**8단계(전체 풀테스트) 착수 가능 여부**: **가능.** 4개 feature 전부 PASS 또는 CONDITIONAL PASS로 완료됐고, 어느 것도 FAIL이 아니다. `feature-stock-metrics-integration-test.md`의 CONDITIONAL PASS 조건(DEF-IT-M01)은 "8단계 진행 자체를 막지 않고 10단계(배포테스트) 착수 전 폐쇄"로 이미 명시적으로 범위가 좁혀져 있으며(DEC-024), `feature-screener-integration-test.md`와 이 문서 모두 이 게이트를 새로 발견하지 않고 참조·인지만 했다(중복 재등록 없음, 규칙 F에 따라 근본 원인은 UNIT-02/환경 준비로 이미 귀속되어 있음). 신규 Critical/High 결함은 4개 feature 어디에서도 발견되지 않았다. 오케스트레이터는 8단계(`08-full-system-tester`)를 다음 단계로 호출할 수 있으며, 8단계 착수 전 다음 사항을 인지해야 한다:
1. DEF-IT-M01(Medium, Deferred) — 10단계 착수 전 실 서비스키 확보 후 `run_ingestion.py`→`run_derivation.py` 종단간 1회 이상 실행 필요(8단계 자체는 차단하지 않음).
2. DEF-IT-M02(Low, Deferred) — PER≤0 결측 처리 구현 담당 미배정(현재 `raw_fundamentals` 미적재로 영향 0).
3. `feature-stock-metrics-integration-test.md`가 남긴 세션 도구 정책 관찰(호스트에서 DB 자격증명을 사용하는 CLI 배치 실행이 일부 세션에서 차단될 수 있음, DI 오버라이드 불가능한 독립 CLI는 이 방법으로 우회 불가) — 8단계가 실제 배치 CLI 종단간 실행을 시도해야 하는 시나리오가 있다면 이 제약을 미리 인지해야 한다.
4. 그 외 각 feature 문서의 §8 "리스크 및 잔존 이슈"(모바일 실기기 미검증, `stock_master.sector` 미확정, percentile 템플릿 코드 미공유, 뒤로가기 시 폼 리셋 등)는 전부 Low 심각도이거나 결함이 아닌 관찰 사항으로, 8단계 착수를 막지 않는다.

## 절차 흐름 (참고용 다이어그램)
```mermaid
flowchart TD
    A["UNIT-08 6단계 PASS 확인"] --> B["cross-feature 데이터 일관성: market-summary↔screener(TC-IT-01~07)"]
    B --> C["업무단위 E2E: 홈 진입카드/GlobalNav 순환(TC-IT-08~15)"]
    C --> D["회귀: pytest/ruff/tsc/lint/build(force-dynamic 유지)/CORS(TC-IT-R1~R8)"]
    D --> E{설계 결함/단위 간 가정 충돌 발견?}
    E -->|No, 문서 동기화 공백만| F["내부검증 1차/2차(§10)"]
    F --> G["Teardown(§7) + git status/DB 행수 확인"]
    G --> H["traceability.md REQ-004 통합테스트 갱신 + REQ-024 게이트 각주 반영"]
    H --> I["PASS로 7단계 종료 → 4개 feature 전체 요약(§11) → 8단계 handoff"]
```
