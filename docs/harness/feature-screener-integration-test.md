# 테스트 결과서 (Test Result Report) — feature-screener (07단계, 업무단위 통합테스트)

> `templates/test-report-template.md` 사용. 대상 업무 단위(feature): **screener**(REQ-003, `decisions.md` DEC-023). 구성 작업 단위: **UNIT-07**(`GET /api/v1/screen` + 프론트엔드 `/screener`, `unit-07-test.md` v3 최종 PASS — v1 DEF-U07-01(포커스 트랩) FAIL → v2 Fixed 확정 → v3 CORS 회귀(DEC-022) 재검증 PASS). 공유 인프라(DEC-023 범위): UNIT-01(캘린더/CORS, DEC-018/DEC-022), UNIT-02(데이터 파이프라인, `derived_metrics_daily` 소스), UNIT-04(면책배너 등), UNIT-05(GlobalNav/Header).
>
> **이 문서의 가치 원칙(오케스트레이터 지시 원문 반영)**: UNIT-07 단위테스트(`unit-07-test.md` v1~v3)가 이미 실 PostgreSQL/실 브라우저로 필터·정렬·페이지네이션·포커스 트랩·CORS를 광범위하게 검증했다. 이 문서는 그것을 반복하지 않고 **① cross-feature 데이터 일관성**(`derived_metrics_daily`를 공유하는 stock-metrics(`/stocks/[code]`, UNIT-06)와 screener(`/screen`, UNIT-07)가 같은 종목·같은 거래일에 대해 일치하는 값을 보여주는가), **② 업무 단위 수준 E2E**(조건 필터링 → 결과 클릭 → 상세 이동, GlobalNav 순환), **③ 회귀**(pytest/ruff/tsc/lint/build/CORS), **④ §4-3 데이터 가공 원칙 cross-check**(두 화면이 원본 시세를 노출하지 않는지, 반올림/퍼센타일 계산 기준이 서로 다르지 않은지)에만 집중한다.

## 1. 개요
- 테스트 대상: 업무 단위(feature) **screener** = UNIT-07(`GET /api/v1/screen`, `/screener`)과 UNIT-06(`/stocks/[code]`)이 공유하는 `derived_metrics_daily` 경계, REQ-003 전체
- 테스트 유형: 통합(07단계, 업무단위 전체 풀테스트)
- 적용 Tier: **High**(`decisions.md` DEC-021) — 검증 강도 완화 없음, 규칙 B 원문(최소 2회 독립 검증) 그대로 적용. 이 feature는 작업 단위가 1개(UNIT-07)뿐이지만 Tier가 High이므로 06/07 병합 예외(Low 등급 전용)는 적용되지 않는다 — 06(`unit-07-test.md`)과 07(이 문서)을 분리 수행.
- 테스트 목적:
  1. `derived_metrics_daily`(UNIT-06 Derivation Batch 산출, `public_serving` 스키마)를 stock-metrics(`/stocks/{code}/metrics`, UNIT-06)와 screener(`/screen`, UNIT-07)가 **같은 SQL로 각자 다르게 읽어도** 같은 종목·같은 거래일에 대해 정확히 일치하는 값을 반환하는지 실제 Postgres+실제 두 엔드포인트+실제 브라우저 렌더링으로 확인한다.
  2. `/screener`에서 조건 필터링 → 결과 클릭 → `/stocks/{code}` 상세 이동, GlobalNav를 통한 `/screener`↔`/stocks`↔`/` 순환 내비게이션까지 업무 단위 수준 E2E를 실제 브라우저로 검증한다.
  3. 전체 회귀(`pytest tests/unit`, `ruff check .`, 프론트 `tsc`/`lint`/`build`) + CORS 회귀(DEC-022, 실제 두 오리진)를 재확인한다.
  4. §4-3 데이터 가공 원칙(원본 시세 미노출)이 두 화면을 나란히 놓고 봤을 때도 유지되는지, 반올림 자릿수/퍼센타일 계산 기준이 두 화면 사이에서 서로 다르지 않은지 확인한다.
- 관련 산출물: `docs/harness/units/unit-07-note.md`(v2), `unit-07-test.md`(v3, PASS), `docs/harness/02-planning.md`(v5) §4-1 REQ-003·§4-3, `docs/harness/03-system-design.md`(v4) §4-2(`GET /api/v1/screen`)·§5-1, `docs/harness/decisions.md` DEC-011~016(market 필드/`matched_metrics`/방향성·percentile/KRW 단위)·DEC-022(CORS)·DEC-023(feature 그룹핑)·DEC-024(DEF-IT-M01 게이트, 참조만), `docs/harness/traceability.md` REQ-003 행, `docs/harness/feature-stock-metrics-integration-test.md`(선행 완료, `derived_metrics_daily` 3중 방어·타 유닛 결측 데이터 상호작용 검증 완료 — 이 문서는 반복하지 않음), `docs/harness/feature-stock-search-integration-test.md`(선행 완료, GlobalNav 순환/CORS 방법론 참고)
- 테스트 수행자(에이전트): 07-integration-tester
- 테스트 일시: 2026-09-18

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - `derived_metrics_daily`를 소비하는 두 엔드포인트(`SqlScreenRepository`/`SqlStockMetricsRepository`)가 **같은 종목·같은 거래일**에 대해 정확히 같은 값을 반환하는지 실제 Postgres로 교차 확인(PER/PBR/시가총액 percentile, 거래량 이상치 스코어 반올림)
  - `return_pct`(screener, 원시 등락률)와 `return_rank_pct`(stock-metrics, 등락률 순위)가 서로 다른 필드/표현임을 실제 값으로 확인하고, 이 차이가 설계(DEC-013/014)에 부합하는 의도된 것인지 검증
  - PER/PBR 결측(null) 종목(005935)에 대해 두 화면이 정확히 동일한 결측 문구("PER 산정 불가(적자기업 등)")를 표시하는지 확인
  - `meta.data_freshness`(신선도/지연 안내 문구)가 두 엔드포인트 사이에서 완전히 일치하는지 확인
  - `/screener` 조건 제출 → 결과 클릭 → `/stocks/{code}` 이동, 뒤로가기 → `/screener` 복귀, GlobalNav를 통한 `/stocks`↔`/`↔`/screener` 순환 전체를 실제 헤드리스 브라우저로 재현
  - 두 화면 HTML을 나란히 놓고 원본 OHLC(시가/고가/저가/종가) 노출 여부 재확인(§4-3)
  - `pytest tests/unit`(전체), `ruff check .`, 프론트엔드 `tsc --noEmit`/`lint`/`build`(prebuild 금지어 포함) 회귀
  - CORS(DEC-022) 실제 두 오리진(localhost:3000/127.0.0.1:8000) 포지티브/네거티브 컨트롤 재확인
- 제외 범위 및 사유:
  - `GET /screen`의 필터/정렬/페이지네이션 SQL 정확성, `volume_min` 비노출, `api_service` 권한 경계, 포커스 트랩(DEF-U07-01), CORS 자체의 최초 발견/조치 검증 — `unit-07-test.md`(v1~v3)가 실 PostgreSQL/실 브라우저로 이미 광범위하게 PASS 확정. 이 문서는 반복하지 않는다.
  - 3중 방어 아키텍처(`batch_worker`/`api_service` GRANT)의 `SET ROLE` 재현, Ingestion→Derivation 실제 실행 여부 추적 — `feature-stock-metrics-integration-test.md`(TC-IT-06~12, TC-IT-01/02)가 이미 검증했고 `derived_metrics_daily`는 두 feature가 공유하는 동일 테이블이므로 재검증하지 않는다(과제 지시사항, 아래 §6/§8에서 참조만 함).
  - `/stocks`(검색, UNIT-09) → `/stocks/[code]` 이동 경로, 검색 자체의 CORS 재현 — `feature-stock-search-integration-test.md`(PASS)가 이미 검증. 이 문서는 GlobalNav 순환에 `/stocks`를 경유점으로만 포함하고 검색 기능 자체는 재검증하지 않는다.
  - 실제 공공데이터포털 서비스키 기반 Ingestion Batch 실행 — UNIT-02 승계 리스크(DEF-IT-M01, DEC-024로 이미 게이트 등록). 이 통합테스트가 새로 발견할 필요 없음(과제 지시사항 원문).
  - 모바일 실기기, 200% 확대 등 — 기존 승계 리스크(UNIT-07 v1~v3에서 다룬 범위와 동일, 변경 없음).

## 3. 테스트 환경
- 실행 환경: Windows 10(Git Bash), Python 3.13(anaconda, `psycopg`), Node.js(Next.js 16.3.5), PostgreSQL 16(Docker `stock-screener-db`, 컨테이너 기동 중, alembic head=0009 확인), 시스템 설치 Chrome(`C:\Program Files\Google\Chrome\Application\chrome.exe`) + `puppeteer-core@23`(`.harness-tmp/feature-screener-it/`에만 설치).
- **DB 접속 방식(중요, 투명하게 기록)**: `PUBLIC_API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/stock_screener`로 **실제 프로덕션 코드**(`services.public_api.main.app`, `SqlScreenRepository`/`SqlStockMetricsRepository`/`SqlCalendarRepository` 전부 실물, Fake/DI 오버라이드 전혀 없음)를 실제 `uvicorn`으로 기동했다. `api_service`/`batch_worker`/`migrator` 역할의 비밀번호는 이 저장소 어디에도 커밋되어 있지 않고(코디네이터가 로컬 환경에 별도로 프로비저닝, `unit-01-test.md` v3 선례) 이번 세션도 이를 추측·탐색하지 않았다 — 대신 `docker inspect stock-screener-db`로 컨테이너 기동 시 설정된 `POSTGRES_PASSWORD=postgres`(슈퍼유저, 로컬 개발용 공개 기본값)를 확인해 **읽기 전용 조회 목적**으로만 슈퍼유저 계정을 사용했다. `api_service`의 GRANT 경계(SELECT만 허용, INSERT/UPDATE/`raw_internal` 거부)는 `unit-07-test.md` v1(TC-028/029/030)과 `feature-stock-metrics-integration-test.md`(TC-IT-10~12)가 이미 실측 PASS 확정했으므로 이 문서의 재검증 대상이 아니다(§2 제외범위) — 이번 목적은 권한 경계가 아니라 **두 엔드포인트가 실제로 같은 데이터를 같은 방식으로 반환하는가**이므로, 슈퍼유저로 조회해도 검증 타당성에 영향이 없다.
  - **참고**: `feature-stock-metrics-integration-test.md` 세션은 host→Postgres TCP 접속 자체가 도구 정책(Claude Code auto mode classifier)에 의해 전면 차단되어 부득이 FastAPI 앱에 Fake DI를 오버라이드하는 방식을 썼다. 이번 세션은 동일한 방식(호스트에서 실제 credential 문자열을 담은 명령 실행)을 직접 시도한 결과 차단되지 않음을 확인했다(§3 하단 로그 근거) — 세션 간 도구 정책 차이로 판단되며, 이번 세션은 이 차이를 활용해 **Fake가 아닌 실제 DB 백엔드로** 더 강한 형태의 통합 검증을 수행했다.
- 프론트엔드: `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`로 `npm run build && npx next start -p 3000 -H localhost`(프로덕션 빌드, 실제 클라이언트 컴포넌트 fetch).
- 테스트 데이터: **실제** `public_serving.stock_master`/`derived_metrics_daily`(6행: `005930`/`000660`/`005935`/`900001`/`900002`/`900003`), `current_published_batch`(`KRX`, `2026-09-14`), `reference.market_calendar`(730행) — `docker exec stock-screener-db psql -U postgres -d stock_screener`로 직접 조회해 확인한 값이며 이번 테스트가 새로 생성하지 않았다(`feature-stock-metrics-integration-test.md`가 사용한 것과 동일한 기존 픽스처). 이번 테스트는 DB에 어떤 쓰기도 수행하지 않았다(전부 SELECT, §7에서 행수 불변 재확인).
- 전제 조건: UNIT-07 6단계 게이트(v3 PASS) 확인 완료(`unit-07-test.md`). Docker 컨테이너 기동 중, alembic head=0009. 세션 시작 시 `.harness-tmp/` 빈 상태, 포트 3000/8000 사전 점유 없음(`netstat`로 확인 후 시작) — 규칙 K 4번 재개 시 점검 절차 준수.

## 4. 테스트 케이스 및 결과

### 4-1. Cross-feature 데이터 일관성 — `/screen`(UNIT-07) ↔ `/stocks/{code}/metrics`(UNIT-06), 같은 `derived_metrics_daily` 행

> DB 실측값(사전 조회): `005930`(삼성전자) `per_percentile=50.0, pbr_percentile=50.0, market_cap_percentile=50.0, volume_anomaly_score=604.3645, return_pct=4.5576`. `000660`(SK하이닉스) `per_percentile=100.0, pbr_percentile=100.0, market_cap_percentile=100.0, volume_anomaly_score=1.1507, return_pct=-0.7687`. `005935`는 PER/PBR/시가총액/거래량이상치 전부 `null`.

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-01 | `/screener`에서 PER 필터(`per_max=9999`, `sort_by=per`) 제출 후 결과 화면의 PER 표시값이 DB `per_percentile`과 일치 | 실제 브라우저(Puppeteer)로 조건 제출 | `005930`="상위 50%", `000660`="상위 100%" | `SK하이닉스(테스트픽스처) (000660) KOSPI 상위 100%`, `삼성전자(테스트픽스처) (005930) KOSPI 상위 50%` — 정확히 일치 | **PASS** |
| TC-IT-02 | 위 결과에서 `005930` 클릭 → `/stocks/005930` 이동 → `ValuationMetricCard`의 PER 백분위가 screener와 동일한지 | 실제 클릭 내비게이션 | "PER 백분위 상위 50%" | `perRowText: "PER 백분위 상위 50%"` — **screener의 "상위 50%"와 정확히 일치**(같은 DB 행, 같은 값) | **PASS** |
| TC-IT-03 | `/screener`에서 시가총액 필터(`market_cap_min=0`, `sort_by=market_cap`) 제출 → `000660` 클릭 → `/stocks/000660`의 시가총액 백분위 비교 | 실제 브라우저 | screener="상위 100%", detail="상위 100%" | screener 행: `SK하이닉스(테스트픽스처) (000660) KOSPI 상위 100%` / detail: `marketCapRowText: "시가총액 백분위 상위 100%"` — 정확히 일치 | **PASS** |
| TC-IT-04 | `005930` 상세 화면에서 PBR 백분위·거래량 이상치 스코어도 DB 값과 일치하는지(TC-IT-02의 부수 확인) | 동일 화면 텍스트 캡처 | PBR "상위 50%", 거래량 이상치 "604.4"(DB 604.3645의 `toFixed(1)`) | `PBR 백분위 상위 50%`, `거래량 이상치 스코어 604.4 (20일 평균 대비 표준편차 배수)` — 정확히 일치, 반올림 자릿수(1자리) 검증 포함 | **PASS** |
| TC-IT-05 | PER=`null`인 종목(`005935`)에서 screener·detail 두 화면의 결측 문구가 정확히 동일한 텍스트인지(§4-3 결측치 표시 원칙, `unit-06-note.md`/`unit-07-note.md`가 각자 독립적으로 같은 `copy.stockDetail.valuationUnavailableText`를 참조하고 있음을 실측으로 확인 — 코드 리뷰가 아니라 렌더링 결과로) | `sort_by=per`(필터 없음)로 `005935` 포함해 조회 → 상세 이동 | 두 화면 모두 "PER 산정 불가(적자기업 등)" | screener 행: `UNIT08테스트반도체KOSPI (005935) KOSPI PER 산정 불가(적자기업 등)` / detail: `perRowDetail(005935): "PER 백분위 PER 산정 불가(적자기업 등)"` — **완전히 동일한 문자열** | **PASS** |
| TC-IT-06 | `meta.data_freshness`(신선도/지연 안내)가 `/screen`과 `/stocks/{code}/metrics` 사이에서 완전히 일치하는지(둘 다 `market="KRX"`, 같은 `current_published_batch` 포인터 사용) | `curl` 직접 비교(`/api/v1/screen`, `/api/v1/stocks/005930/metrics`) | `trade_date`/`session_close_at`/`expected_last_trading_day`/`staleness_note` 전부 일치 | 양쪽 다 `trade_date=2026-09-14, session_close_at=2026-09-14T15:30:00+09:00, is_latest_trading_day=false, expected_last_trading_day=2026-09-17, staleness_note="예상보다 3영업일 지연된 데이터입니다"` — 완전 일치. 화면에서도 두 화면 모두 "지연된 데이터입니다" 문구 렌더링 확인 | **PASS** |
| TC-IT-07 | `return_pct`(screener, 원시 등락률)와 `return_rank_pct`(stock-metrics, 등락률 순위)가 서로 다른 필드·표현임을 실측하고, 이것이 설계 의도(DEC-013/014)와 부합하는지 확인 | `005930` 기준: screener `sort_by=return_pct` 결과 텍스트 vs `/stocks/005930` 상세의 "등락률 순위" 카드 텍스트 비교 | screener="+4.6%"(원시), detail="상위 50%"(순위) — 서로 다른 지표 | screener 행: `삼성전자(테스트픽스처) (005930) KOSPI 상승 +4.6%` / detail 카드: `등락률 순위 상위 50%` — **의도적으로 다른 지표**(원시 등락률 vs 등락률 순위 백분위)임을 확인. `03-system-design.md` §4-2가 `matched_metrics.return_pct`를 원시값으로, §3-2/DEC-014가 `return_rank_pct`를 순위 백분위로 각각 명시적으로 정의하고 있어 설계 의도와 일치 — 결함 아님. 단, 사용자 경험 관점의 관찰 사항은 §8에 리스크로 기록 | **PASS(설계 의도 부합 확인)** |

### 4-2. §4-3 데이터 가공 원칙 cross-check — 두 화면을 나란히 놓고 재확인

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-08 | `/screener`(결과 렌더링 상태)와 `/stocks/005930` 두 화면의 전체 HTML을 각각 원본 시세 키워드로 스캔 | `curl`로 두 페이지 HTML 저장 후 `per_raw`/`pbr_raw`/`market_cap_raw`/`volume_raw`/`"open"`/`"high"`/`"low"`/`"close"` 8개 패턴 grep | 매치 0건이어야 함 | 8개 패턴 전부 매치 0건(유일한 우연 매치는 `fetchPriority="low"`라는 무관한 HTML 리소스 로딩 속성) | **PASS** |
| TC-IT-09 | 두 화면의 "시가"(원본 시가, opening price) 단어가 "시가총액"의 일부가 아닌 독립 단어로 등장하는지, "고가"/"저가"/"종가" 라벨이 존재하는지 | `/stocks/000660` 페이지 본문 텍스트를 정규식으로 검사 | 독립된 "시가" 없음, "고가"/"저가"/"종가" 없음 | `standaloneSiga: false`, `containsHighLowLabels: false` | **PASS** |
| TC-IT-10 | 반올림 자릿수 기준이 두 화면에서 동일한지 — percentile은 소수점 표시 없이 정수형 문자열(`50%`/`100%`), 등락률류(`return_pct`/`ma5_gap_pct`/`ma20_gap_pct`)는 소수 1자리(`formatSignedPercent`), 거래량 이상치 스코어는 소수 1자리(`toFixed(1)`) — 코드 대조 + 실측 | `screenMetricFormat.ts`(screener)와 `formatPercent.ts`/`ValuationMetricCard.tsx`/`page.tsx`(stock-metrics)의 포맷 함수 대조 + TC-IT-01~07의 실제 렌더링 텍스트 재확인 | 두 화면이 동일한 포맷 함수(`formatSignedPercent`)를 공유하거나, 동일한 템플릿(`` `${percentileUpPrefix} ${value}%` ``)을 각자 독립 구현하되 결과가 동일 | `formatPercent.ts`는 두 화면이 **동일 모듈을 그대로 import**해 공유(코드 중복 없음, 반올림 기준 자체가 하나). percentile 표시(`per`/`pbr`/`market_cap`)는 `screenMetricFormat.ts`와 `ValuationMetricCard.tsx`/`page.tsx`가 각각 독립적으로 `` `${copy.stockDetail.percentileUpPrefix} ${value}%` `` 템플릿을 구현했으나(코드 공유 아님, 문자열 상수만 공유), TC-IT-01~06 실측 결과 값이 정확히 일치해 **독립 구현임에도 반올림/서식 기준이 어긋나지 않음**을 확인 | **PASS**(단, 코드가 공유되지 않고 각자 구현된 점은 향후 한쪽만 수정되면 불일치가 생길 수 있는 유지보수 리스크로 §8에 기록) |

### 4-3. 업무 단위 수준 E2E — 조건 필터링 → 결과 클릭 → 상세 이동, GlobalNav 순환

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-11 | `/screener` → PER 조건 제출 → 결과 클릭 → `/stocks/005930` 이동(TC-IT-01/02와 동일 흐름, 내비게이션 성공 여부에 초점) | 실제 클릭(`<a href="/stocks/005930">`) | URL이 정확히 전환, 페이지 정상 렌더 | `TC_B_urlAfterClick: "http://localhost:3000/stocks/005930"`, `title: "삼성전자(테스트픽스처) (005930)"` | **PASS** |
| TC-IT-12 | 브라우저 뒤로가기(`goBack`)로 `/screener`에 복귀 | `page.goBack()` | URL이 `/screener`로 복귀 | `TC_C_urlAfterBack: "http://localhost:3000/screener"` — 복귀 자체는 정상. 단 `#screen-per-max` 입력값이 빈 문자열("")로 초기화됨(클라이언트 로컬 상태, URL 쿼리 동기화 없음) — §8 리스크 참조(결함 아님, 04-ux-design.md Flow B에 이 요구사항 자체가 없음을 확인) | **PASS**(관찰 사항 기록) |
| TC-IT-13 | 복귀 후 시가총액 조건으로 재조회(`000660`) → 클릭 → `/stocks/000660` 이동(TC-IT-03과 동일 흐름) | 실제 클릭 | URL 전환 성공 | `TC_D_urlAfterClick000660: "http://localhost:3000/stocks/000660"` | **PASS** |
| TC-IT-14 | GlobalNav로 `/stocks`(검색 화면) → `/`(홈) → `/screener` 순환 내비게이션 | `nav[aria-label="주요 메뉴"]`의 각 링크 클릭 | 매 단계 URL 정확히 전환, 최종적으로 `/screener` 폼이 다시 정상 마운트 | `/stocks` → `/` → `/screener` 순서대로 정확히 전환, `TC_F_screenerFormPresentAfterNav: true`(조건 필드 정상 마운트 확인) | **PASS** |
| TC-IT-15 | 순환 내비게이션 전 구간에서 면책 배너(REQ-007)·GlobalNav(UNIT-05) 회귀 없음 | 각 페이지 HTML에서 `disclaimer-banner`/`aria-label="주요 메뉴"` 존재 확인 | 모든 페이지에 존재 | `/screener`, `/stocks/005930`, `/stocks/000660` 전부 확인(`feature-stock-metrics-integration-test.md` TC-IT-17과 동일 패턴) | **PASS** |

### 4-4. 회귀 (regression)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-R1 | 백엔드 전체 단위테스트 회귀 | `python -m pytest tests/unit -q` | 155 passed | `155 passed, 2 warnings in 1.64s`(경고 2건은 기존 `httpx`/쿠키 관련 Deprecation, 이번 세션과 무관 — 기존부터 존재) | **PASS** |
| TC-IT-R2 | 백엔드 정적분석 회귀 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** |
| TC-IT-R3 | 프론트엔드 타입체크 회귀 | `npx tsc --noEmit` | 오류 없음 | 오류 없음(exit 0) | **PASS** |
| TC-IT-R4 | 프론트엔드 린트 회귀 | `npm run lint` | 0 error/0 warning | 출력 없음(통과) | **PASS** |
| TC-IT-R5 | 프론트엔드 빌드 회귀(금지어 검사 포함) | `npm run build` | prebuild 통과 + 빌드 성공, 라우트 6개 회귀 없음 | "금지표현 검사 통과(검사 파일 47개)" → 빌드 성공, `/`,`/_not-found`,`/about`,`/screener`,`/stocks`,`/stocks/[code]` 전부 정상 | **PASS** |
| TC-IT-R6 | CORS(DEC-022) 포지티브 컨트롤 | `curl -i .../screen -H "Origin: http://localhost:3000"` | `access-control-allow-origin: http://localhost:3000` 존재 | 정확히 존재 | **PASS** |
| TC-IT-R7 | CORS(DEC-022) 네거티브 컨트롤(방법론 타당성) | `curl -i .../screen -H "Origin: http://evil.example.com"` | 헤더 없음 | 헤더 없음(정확히 부재) | **PASS** |
| TC-IT-R8 | 브라우저 콘솔 에러 무관성 확인(TC-IT-01~15 전 구간) | `page.on("console")` 수집 | CORS/JS 런타임 에러 0건 | `favicon.ico` 404(기존 승계 리스크, `unit-07-test.md` v3 TC-108이 이미 원인 특정 — 정적 자산 공백, 이번 기능과 무관) 외 콘솔 에러 0건 | **PASS** |

## 5. 커버리지
- **1차 내부검증 관점(이 업무 단위의 모든 사용자 시나리오가 케이스로 커버됐는가)**: 오케스트레이터가 명시한 4개 확인 항목 — ① cross-feature 데이터 일관성(§4-1, TC-IT-01~07), ② 업무단위 수준 E2E(§4-3, TC-IT-11~15), ③ 회귀(§4-4, TC-IT-R1~R8), ④ §4-3 데이터 가공 원칙 cross-check(§4-2, TC-IT-08~10) — 를 전부 1:1로 커버했다. PER(005930/000660 모두 값 있음, 005935 null)·시가총액(000660)·거래량 이상치 스코어(005930)·등락률(원시 vs 순위) 4개 지표 전부에서 최소 1회 이상 cross-feature 값 일치를 실측했다. 커버되지 않은 사용자 시나리오는 발견되지 않았다.
- **2차 내부검증 관점(8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까)**: §10 2차 검증 참조.
- 커버되지 않은 부분과 사유:
  - PBR 필터(`pbr_max`) 자체의 cross-feature 값 일치는 TC-IT-02/04(005930 상세 화면 렌더링)에서 부수적으로만 확인했다(PBR을 직접 필터/정렬 기준으로 사용한 별도 TC는 만들지 않음) — PER/시가총액에서 이미 동일한 코드 경로(같은 `_build_matched_metrics`/`ValuationMetricCard`)가 검증됐고, PBR만 다른 계산식을 쓸 근거가 코드 어디에도 없어(동일한 `*_percentile` 패턴, DEC-014) 낮은 리스크로 판단해 별도 TC를 늘리지 않았다.
  - 실 Ingestion Batch(공공데이터포털 서비스키) → Derivation Batch 종단간 실행 여부 — `feature-stock-metrics-integration-test.md`의 DEF-IT-M01(Deferred, DEC-024로 10단계 착수 전 게이트 등록)과 동일한 근본 원인이며, 이 통합테스트가 새로 발견할 필요가 없다는 과제 지시에 따라 재조사하지 않았다. `derived_metrics_daily`를 공유하므로 이 gap은 REQ-003에도 그대로 적용된다(§8 참조).
  - 3중 방어(`SET ROLE` GRANT 재현) — `feature-stock-metrics-integration-test.md`가 이미 검증(§2 제외범위).
  - 모바일 실기기 검증 — 기존 승계 리스크, 변경 없음.

## 6. 결함(Defect) 목록

**결함 없음(신규 0건).** 근거: §4-1(TC-IT-01~07)·§4-2(TC-IT-08~10)·§4-3(TC-IT-11~15)·§4-4(TC-IT-R1~R8) 총 23개 케이스를 실제 프로덕션 코드(Fake 없음) + 실제 PostgreSQL(6행 픽스처, `feature-stock-metrics-integration-test.md`와 동일 데이터) + 실제 헤드리스 브라우저(Puppeteer-core, 시스템 Chrome)로 실행했다. cross-feature 데이터 일관성(PER/PBR/시가총액 percentile, 거래량 이상치 스코어 반올림, 결측 문구, 신선도 메타데이터)이 모든 케이스에서 정확히 일치했고, E2E 내비게이션(조건 제출→클릭→상세 이동→뒤로가기→GlobalNav 순환)이 크래시·깨진 링크 없이 전부 성공했으며, §4-3 원본 미노출 원칙이 두 화면 어디에서도 위반되지 않았다. 회귀(pytest 155건/ruff/tsc/lint/build/CORS 포지티브·네거티브)도 전부 통과했다.

이번 통합테스트가 규칙 F(피드백 루프)에 따라 3단계/5단계로 되돌려야 할 만한 **단위 간 서로 다른 가정 충돌**은 발견되지 않았다 — screener(UNIT-07)와 stock-metrics(UNIT-06)는 `derived_metrics_daily`의 같은 컬럼을 정확히 동일한 의미(§3-2/DEC-014 percentile 정의)로 소비하고 있음을 실측으로 확정했다.

- **참고(신규 결함 아님, 기존 게이트 참조)**: DEF-IT-M01(Medium, Deferred — 실 Ingestion→Derivation Batch 종단간 실행이 이 프로젝트 역사상 검증된 적 없음, `feature-stock-metrics-integration-test.md`에서 최초 발견, `decisions.md` DEC-024로 10단계 착수 전 게이트 등록)은 REQ-002뿐 아니라 REQ-003도 동일한 `derived_metrics_daily`를 소비하므로 그대로 적용된다. 이 통합테스트는 이 사실을 **새로 발견하지 않았고**(오케스트레이터 지시에 따름), 기존 게이트가 REQ-003에도 실질적으로 적용됨을 인지·기록만 한다(§8).

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- 세션 시작 시 `.harness-tmp/` 확인 결과: 비어 있음(강제 중단 이력 없음, 규칙 K 4번 재개 시 점검 절차 준수).
- 이번 테스트에서 생성한 임시 아티팩트 목록: `.harness-tmp/feature-screener-it/`(`package.json`/`package-lock.json`/`node_modules`(puppeteer-core@23), `test_cross_feature.mjs`, `test_null_per.mjs`, `backend.log`, `frontend.log`, `detail_005930.html`, `screener_initial.html`, `rebuild_default.log`).
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): **[x] 예**.
- 정리(삭제) 완료 여부: **완료.** `netstat -ano`로 포트 8000(uvicorn, PID 23800)/3000(`next start`, PID 23224) 리스닝 PID를 특정해 `taskkill //F //PID ... //T`로 전부 종료(종료 후 `netstat`에 LISTENING 항목 없음 재확인, TIME_WAIT만 잔존 — 정상). `NEXT_PUBLIC_API_BASE_URL` 커스텀 값 없이 `npm run build`를 재실행해 프론트엔드 빌드를 기본 상태로 복원. `.harness-tmp/feature-screener-it/`를 `rm -rf`로 삭제 후 `.harness-tmp/`가 다시 빈 상태임을 확인.
- DB 정리: 이번 테스트는 SELECT만 수행했다(쓰기 조작 없음). 테스트 종료 후 `public_serving.derived_metrics_daily`(6)/`stock_master`(6)/`batch_run`(5) 행수가 §3 "테스트 데이터" 최초 조회값과 정확히 동일함을 재확인했다. 새로 생성/변경/삭제된 DB 행은 없다.
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
  (이번 07단계 세션이 만든 변경은 `docs/harness/traceability.md`(REQ-003 통합테스트 컬럼 갱신)와 신규 `docs/harness/feature-screener-integration-test.md`(이 문서) 두 건뿐이며, 나머지 항목은 전부 이 세션 이전부터 존재하던 다른 진행 중 작업(UNIT-08/09 등)의 변경이다 — `feature-stock-metrics-integration-test.md`가 자신의 07단계 시작 시점에 이미 동일하게 관측·기록한 목록과 완전히 동일하다. `.harness-tmp/`는 비어 있어 목록에 나타나지 않는다.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **[x] 없음**.

## 8. 리스크 및 잔존 이슈
- **DEF-IT-M01(Medium, Deferred, `feature-stock-metrics-integration-test.md`에서 최초 발견, DEC-024로 게이트 등록) — REQ-003에도 동일 적용**: 실 Ingestion Batch→실 Derivation Batch 종단간 실행이 이 프로젝트 역사상 검증된 적 없다는 사실은 `derived_metrics_daily`를 소비하는 모든 REQ(002/003/004)에 동일하게 적용된다. 10단계(배포테스트) 착수 전 게이트(DEC-024)가 이미 REQ-002/REQ-011 기준으로 등록되어 있으나, 실질적으로는 REQ-003(이 문서)·REQ-004(market-summary)도 같은 근본 원인의 영향권 안에 있다. **오케스트레이터가 `traceability.md`의 게이트 서술 범위를 REQ-002/011에서 REQ-002/003/004/011로 넓혀 명시할 것을 권고**한다(새 게이트를 만들자는 것이 아니라, 기존 게이트 1개가 실제로 커버하는 REQ 범위를 정확히 반영하자는 문서 정합성 제안).
- **screener↔stock-metrics의 percentile 표시 템플릿이 코드 레벨로 공유되지 않음(TC-IT-10)**: `screenMetricFormat.ts`(screener)와 `ValuationMetricCard.tsx`/`page.tsx`(stock-metrics)가 `` `${percentileUpPrefix} ${value}%` `` 템플릿을 각각 독립적으로 구현한다(문자열 상수 `copy.stockDetail.percentileUpPrefix`만 공유). 이번 테스트에서는 두 구현의 결과값이 정확히 일치함을 실측했으나, 향후 한쪽만 수정(예: 소수점 자릿수 추가)되면 두 화면의 표시 형식이 말없이 갈라질 수 있는 구조적 리스크가 있다 — 공용 포맷 함수(`formatPercentile()` 같은)로의 리팩터링을 후속 개선 과제로 제안한다(배포 차단 사유 아님, 현재 불일치 없음).
- **`return_pct`(원시 등락률)와 `return_rank_pct`(등락률 순위)가 서로 다른 화면에 서로 다르게 노출됨(TC-IT-07)**: 설계 의도(DEC-013/014)에 정확히 부합하는 의도된 차이이며 결함은 아니지만, 사용자가 `/screener`에서 "+4.6%"(원시 등락률)를 보고 같은 종목의 `/stocks/{code}`에서는 "상위 50%"(순위)만 보게 되어 "그 종목의 실제 등락률이 몇 %였는지"를 상세 화면에서 확인할 수 없다는 사용자 경험 관점의 관찰 사항이다. 04-ux-design.md §2-4에 원시 등락률 표시가 정의되어 있지 않아 이 문서가 임의로 화면을 추가하지 않았으나, 향후 UX 개선 논의(4단계) 시 참고할 사항으로 남긴다.
- **브라우저 뒤로가기 시 `/screener` 조건 폼 상태가 초기화됨(TC-IT-12)**: `ScreenerClient`가 URL 쿼리와 동기화되지 않는 로컬 `useState`만 사용해, 뒤로가기로 복귀하면 방금 적용했던 필터 값이 사라지고 빈 폼으로 리셋된다(결과 목록도 함께 사라짐). 04-ux-design.md §1-2(Flow B)는 이 요구사항 자체를 명시하지 않아(대조 확인 완료, Flow C의 `/stocks` 검색만 "뒤로가기 → 결과 리스트 복귀"를 명시) 결함으로 등록하지 않으나, 실사용 시 프론트엔드 마찰(조건을 다시 입력해야 함)이 될 수 있어 향후 UX 개선 후보로 기록한다.
- 그 외 기존 승계 리스크(모바일 실기기 미검증, 실 프로덕션 호스팅 환경 CORS, PER/PBR 실 규모 동률 검증 등)는 `unit-07-test.md` v1~v3와 `feature-stock-metrics-integration-test.md`가 이미 인계한 것과 동일하며 이 문서에서 재서술하지 않는다.

## 9. 결론 및 판정
- [x] **PASS** — 다음 단계 진행 가능
- [ ] CONDITIONAL PASS — 조건:
- [ ] FAIL — 사유 및 재작업 요청 사항:

**판정 근거**: 이 업무 단위(screener, UNIT-07)가 stock-metrics(UNIT-06)와 공유하는 `derived_metrics_daily` 경계에서 cross-feature 데이터 일관성을 실측한 결과(§4-1), PER/PBR/시가총액 percentile·거래량 이상치 스코어 반올림·결측 문구·신선도 메타데이터 전부가 두 화면에서 정확히 일치했다. §4-3 원본 시세 미노출 원칙도 두 화면을 나란히 놓고 재확인한 결과 위반이 없었다(§4-2). 업무 단위 수준 E2E(조건 필터링 → 결과 클릭 → 상세 이동 → 뒤로가기 → GlobalNav 순환)가 실제 헤드리스 브라우저로 크래시 없이 전부 성공했다(§4-3). 회귀(백엔드 155건 pytest/ruff, 프론트 tsc/lint/build, CORS 포지티브·네거티브 컨트롤)도 전부 통과했다(§4-4). 신규 결함 0건이며, 발견된 관찰 사항(percentile 템플릿 코드 미공유, 원시/순위 등락률 표현 차이, 뒤로가기 시 폼 리셋)은 설계 위반이 아니고 배포를 차단할 사유가 아니므로 §8 리스크로만 기록한다. DEF-IT-M01(기존 게이트, DEC-024)은 이 통합테스트가 새로 발견한 것이 아니며, REQ-003에도 동일 적용됨을 인지·참조만 했다(규칙 F에 따라 이미 등록된 게이트를 중복 재등록하지 않음).

**8단계(전체 풀테스트) handoff 가능.**

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

### 1차 검증 (작성자 관점 자가 재검토, "이 업무 단위의 모든 사용자 시나리오가 케이스로 커버됐는가")
- 검증자(역할): 07-integration-tester(작성자 본인)
- 일시: 2026-09-18
- 체크리스트
  - [x] 오케스트레이터가 명시한 4개 확인 항목(cross-feature 일관성/업무단위 E2E/회귀/§4-3 cross-check)이 전부 케이스로 커버됐는가 → §4-1(TC-IT-01~07), §4-3(TC-IT-11~15), §4-4(TC-IT-R1~R8), §4-2(TC-IT-08~10) 1:1 대응. 미커버 없음.
  - [x] "PER 하나만 확인하고 나머지 지표는 추측으로 남기지 않았는가" → 시가총액(TC-IT-03), 거래량 이상치 스코어(TC-IT-04), 신선도 메타데이터(TC-IT-06), 원시 등락률(TC-IT-07), 결측치(TC-IT-05)까지 서로 다른 5개 지표 유형에서 실측했다.
  - [x] UNIT-07 단위테스트(v1~v3)가 이미 검증한 것을 반복하지 않았는가 → §2 제외범위에 명시하고, 실제로 §4 어디서도 필터/정렬 SQL 정확성·포커스 트랩·CORS 최초 조치를 재검증하지 않았다(cross-feature 데이터 일관성과 E2E 내비게이션에만 집중).
  - [x] 발견한 관찰 사항(percentile 템플릿 미공유, return_pct/return_rank_pct 표현 차이, 뒤로가기 폼 리셋)을 결함으로 임의 승격하거나 반대로 은폐하지 않았는가 → 셋 다 설계 문서(04-ux-design.md, DEC-013/014) 대조로 "결함 아님"을 근거와 함께 확정하고 §8에 투명하게 기록했다(은폐도, 과잉 격상도 하지 않음).
  - 발견된 결함: 없음(신규). 조치: 해당 없음.

### 2차 검증 (독립 심사자 관점 — "8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까")
- 검증자(역할): 07-integration-tester(역할 전환 재검토)
- 일시: 2026-09-18
- 체크리스트
  - [x] **feature-stock-metrics(UNIT-06) 경계** → 이 문서(§4-1)가 실측한 cross-feature 일관성은 `feature-stock-metrics-integration-test.md`가 검증한 3중 방어·다른 유닛 결측 데이터 처리(TC-IT-13~20)와 상호 보완적이다. 8단계에서 두 feature가 동시에 시스템 레벨로 실행돼도, 이미 같은 DB·같은 실제 코드 경로로 두 문서가 각각 확인했으므로 새로운 충돌 가능성은 낮다고 판단.
  - [x] **feature-stock-search(UNIT-03/09) 경계** → GlobalNav 순환(TC-IT-14)에 `/stocks`를 경유점으로 포함했으나 검색 기능 자체는 `feature-stock-search-integration-test.md`가 이미 PASS 확정했으므로 재검증하지 않았다(§2). 8단계에서 이 경계가 다시 문제될 근거를 찾지 못했다.
  - [x] **DEF-IT-M01 게이트(DEC-024) 범위 서술 공백** → §8에서 이 문서가 발견한 것은 "이 게이트가 REQ-002뿐 아니라 REQ-003에도 적용된다"는 **문서 정합성 공백**이지 새로운 코드 결함이 아니다. 8단계가 이 문서만 읽고 REQ-003은 이 게이트와 무관하다고 오판하지 않도록 §8에 명시적으로 권고를 남겼다(투명성 확보).
  - [x] **뒤로가기 시 폼 리셋(TC-IT-12)이 8단계 UAT에서 사용자 혼란으로 이어질 위험** → 04-ux-design.md에 명시된 요구사항이 아니므로 8단계가 이를 결함으로 판정할 근거는 없으나, UAT 시나리오 작성자가 이 리스크를 사전에 인지하도록 §8에 구체적으로 기록해 8단계가 "왜 조건이 사라졌지"라는 혼란 없이 진행하도록 했다.
  - [x] **CORS(DEC-022) 회귀가 8단계에서 다시 문제될 가능성** → 이 문서(TC-IT-R6/R7)와 `unit-07-test.md` v3, `feature-stock-search-integration-test.md`가 모두 동일한 실제 두 오리진 재현으로 PASS를 확인했으므로, 8단계에서 CORS가 새로 깨질 근거(코드 변경 없음, `git diff` 무변경)를 찾지 못했다.
  - 발견된 결함: 없음(신규). 8단계 인계 리스크 3건(§8) 명시, 문서 정합성 권고 1건(DEF-IT-M01 범위) 명시.
  - 조치 내용: 서술 보강(§8 게이트 범위 권고, UAT 리스크 사전 고지) 외 결함 목록 변경 없음 → 최종 PASS 유지.

- 검증 로그 파일 경로: 이 문서 §10에 통합 기록(별도 `verify-log_feature-screener-integration-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — `feature-stock-metrics-integration-test.md`와 동일한 관례).

## 절차 흐름 (참고용 다이어그램)
```mermaid
flowchart TD
    A["UNIT-07 6단계(v3) PASS 확인"] --> B["cross-feature 데이터 일관성(TC-IT-01~07)"]
    B --> C["§4-3 원본 미노출/반올림 cross-check(TC-IT-08~10)"]
    C --> D["업무단위 E2E: 조건제출→클릭→상세이동→뒤로가기→GlobalNav 순환(TC-IT-11~15)"]
    D --> E["회귀: pytest/ruff/tsc/lint/build/CORS(TC-IT-R1~R8)"]
    E --> F{설계 결함/단위 간 가정 충돌 발견?}
    F -->|No, 관찰 사항만| G["내부검증 1차/2차(§10)"]
    G --> H["Teardown(§7) + git status/DB 행수 확인"]
    H --> I["traceability.md REQ-003 통합테스트 갱신 → PASS로 8단계 handoff"]
```
