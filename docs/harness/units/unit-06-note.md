# UNIT-06 구현 노트 — 종목별 가공 지표 요약 조회 기능 (Derivation Batch 최초 구현)

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-16
- 포함 REQ: REQ-002(종목별 가공 지표 요약 — 등락률 순위·이동평균 대비 괴리율·거래량 이상치 스코어·PER/PBR/시가총액 백분위)
- 입력: `docs/harness/03-system-design.md`(v4, PASS) §1-1(3중 방어)·§1-2(Derivation Batch 정의)·§1-3(배포 단위)·§3-1-1(market 두 축)·§3-2(`derived_metrics_daily`/`current_published_batch`, percentile 계산식·결측치 처리 원칙)·§3-4(`meta.data_freshness`)·§4-1/§4-2(공통 envelope, `GET /stocks/{code}/metrics`)·§4-3(응답 화이트리스트), `docs/harness/04-ux-design.md`(v3, PASS) §2-4(종목 상세 MetricCard 그룹)·§1-4(Flow D 에러 매핑)·§4(공통 컴포넌트 명세)·§5(접근성), `docs/harness/units/unit-02-note.md`(raw_internal 스키마, PER/PBR 미확인 상태)·`unit-03-note.md`(stock_master)·`unit-04-note.md`(DisclaimerBanner/DataFreshnessBadge)·`unit-05-note.md`(GlobalNav/Header 셸, `/stocks` 플레이스홀더)
- 의존성: UNIT-02(raw_internal 원본 적재 — 실제로는 비어 있음, 아래 §0 참조), UNIT-03(종목마스터), UNIT-04(면책배너/기준시각뱃지), UNIT-05(UI셸/GlobalNav)

---

## 0. 이 유닛의 성격 — 처음으로 Derivation Batch를 구현하고, raw_ohlcv가 실제로 비어 있는 상태를 그대로 다뤘다

이 유닛은 03-system-design.md §1-2가 "유일하게 raw→public 경계를 넘나드는 지점"이라고 못박은 **Derivation Batch**(`services/derivation_batch/`)를 이 프로젝트에서 처음 구현한다. §4-3(기획서) 데이터 가공 원칙(원본 시세 재게시 금지)의 실질적 구현체가 바로 이 컴포넌트이므로, 아래 두 가지를 각별히 신경 써서 구현·검증했다.

1. **public_serving으로 나가는 값이 실제로 가공된 값인지**: `derived_metrics_daily`에는 open/high/low/close/volume 원문 컬럼 자체가 존재하지 않는다(스키마 레벨 1차 방어). `per_raw`/`pbr_raw`/`market_cap_raw_krw`는 스크리닝 필터링(UNIT-07)을 위해 DB 컬럼으로는 존재하지만, `GET /stocks/{code}/metrics` 응답 Pydantic 스키마(`services/public_api/schemas/metrics.py`)에는 이 세 필드를 아예 선언하지 않았다 — 필드 자체가 없으므로 실수로 직렬화될 코드 경로가 없다(§4-3 화이트리스트 원칙의 타입 레벨 강제).
2. **`return_rank_pct` 방향성과 PER/PBR/시가총액 percentile 계산**: 03-system-design.md v3 §3-2가 확정한 공식(표준경쟁순위 `RANK()` → `rank/total_count*100`, 반올림 1자리)을 `services/derivation_batch/compute.py`에 그대로 구현했고, `return_pct`는 내림차순(값이 클수록 상위 → 낮은 percentile), PER/PBR은 오름차순(낮을수록 상위), 시가총액은 내림차순(클수록 상위)으로 각각 정확히 구현했다. §4 인수조건과 §7 로컬 검증 로그에 실제 계산 결과를 남겼다.

**코디네이터 지시 대응(raw_internal.raw_ohlcv에 실제 데이터가 없는 문제)**: UNIT-02는 공공데이터포털 실 서비스키를 보유하지 않아 `raw_internal.raw_ohlcv`/`raw_fundamentals`에 실제로 적재된 행이 0건이다(`unit-02-note.md` §0). 이 유닛은 이 사실을 그대로 인정하고 다음 두 가지를 분리해서 검증했다(상상 데이터로 실제 운영 동작을 속이지 않기 위함).

- **(a) "데이터 없음" 정상 처리 자체**는 실제 운영 상태 그대로(빈 `raw_internal`/`stock_master`) 로컬 Docker PostgreSQL로 검증했다 — 실제 상상이 섞이지 않은, 있는 그대로의 검증이다.
- **(b) 가공 로직 자체의 정확성**은 명시적으로 "테스트 픽스처"라고 표시한 합성 데이터(`scripts/dev_seed_fixture_metrics.py`, 신규 커밋 — 개발자 로컬 전용, 운영 파이프라인 아님)를 직접 적재해 검증했다. 이 스크립트로 만든 값은 전부 합성이며, 실제 삼성전자/SK하이닉스의 시세가 아니다(종목명에도 "(테스트픽스처)"를 명시).

---

## 1. 구현 범위

### 1-1. Derivation Batch (`services/derivation_batch/`, 신규)

- `compute.py`: DB 의존성이 전혀 없는 순수 계산 함수.
  - `compute_return_pct(close_today, close_prev)`: 당일 등락률(%). 전일 종가 없음(신규 상장 등) → `None`.
  - `compute_ma_gap_pct(closes_including_today, window)`: N일 이동평균 대비 괴리율("이격도" 표준 정의 — 당일 종가 포함 평균 대비). 데이터 부족(window 미만) → `None`.
  - `compute_volume_anomaly_score(today_volume, baseline_volumes, window=20)`: (당일 거래량 - 평균)/표준편차. 기준선은 **당일을 제외한** 직전 20거래일(표본표준편차). 데이터 부족 또는 표준편차 0 → `None`.
  - `rank_percentile(pairs, *, descending)`: 03-system-design.md §3-2 공식 그대로(표준경쟁순위, 동률은 같은 순위+다음 순위 skip). `descending=True`(등락률/시가총액)·`False`(PER/PBR).
- `raw_models.py`: `raw_internal.raw_ohlcv`/`raw_fundamentals`에 대한 **읽기 전용 최소 프로젝션**(`sqlalchemy.Table`, 전체 ORM 모델 재선언 아님). §1-3 "shared: raw 데이터 모델 코드 없음" 원칙에 따라 이 서비스 전용 모듈에 둔다. **로컬 실 PostgreSQL 검증 중 `market` 컬럼을 평범한 `String`으로 선언했다가 실제 ENUM(`reference.market_session`) 비교에서 `UndefinedFunction`(연산자 없음) 오류가 실제로 발생하는 결함을 발견해, `reference.market_session` ENUM을 재사용하도록 즉시 수정했다**(§7 로그 참조 — Fake 기반 단위테스트로는 절대 발견할 수 없었던 실제 인프라 결함).
- `repository.py`: `fetch_active_stocks`(stock_master 활성 종목), `fetch_ohlcv_window`(종목당 최근 41행 — MA20(당일 포함 20) + 거래량 기준선(당일 제외 20) 양쪽을 충족하는 최소 윈도), `fetch_fundamentals_map`, `upsert_derived_metrics`(`ON CONFLICT DO UPDATE`), `publish_current_batch`(검증 통과 시에만 포인터 갱신).
- `batch_run_repository.py`: `run_type='derive'` 고정 사본(§1-3 서비스별 독립 배포 단위 원칙, `unit-02-note.md` §2-3과 동일한 의도적 최소 중복).
- `core/config.py`: `BATCH_DATABASE_URL` 재사용(Ingestion Batch와 동일 `batch_worker` role).
- `run_derivation.py`: CLI 진입점.
  - `resolve_target_trade_date()`: `run_ingestion.py`와 동일한 패턴(수동 지정 우선, 없으면 `get_last_trading_day(market="KRX", ...)`).
  - `compute_stock_day_metrics()`: 종목별 원본 시세 윈도(내림차순) + fundamentals를 받아 지표를 계산한다. **`window[0].trade_date != target_date`(그날 시세 자체가 없음 — 거래정지 등)이면 이 종목을 이번 배치 결과에서 완전히 제외**한다(개별 필드 결측과는 다른 케이스 — §2 편차 1 참조).
  - `build_derivation_inputs()`: 개별 종목 지표 + 코스피/코스닥 통합 전체 종목 기준 백분위(§3-2)를 합쳐 `DerivedMetricsInput` 목록을 만든다.
  - **검증 규칙 확정(§5-4 "결측 비율 임계치(예: 5%)"의 구체적 수치화)**: 당일 처리된 종목 중 `return_pct`가 `None`인 비율이 5%를 초과하면 `validation_passed=False`로 기록하고 `current_published_batch` 포인터를 갱신하지 않는다(이전 정상 데이터가 계속 서빙됨, §3-2/§5-3). **최초 1회 배치처럼 전종목이 "전일 데이터 없음" 상태이면 이 임계치를 자연스럽게 넘어 발행이 보류된다** — 결함이 아니라 "명시적 실패 원칙"의 의도된 결과다(§7 로그로 실제 재현 확인).
  - 모든 실행 경로(캘린더 미확인/활성 종목 없음/원본 시세 0건/검증 통과·실패)에서 정확히 1개의 `batch_run` 행을 기록한다(run_ingestion.py와 동일 원칙).

### 1-2. 데이터 모델 / 마이그레이션

- `shared/db_models/public_serving.py`에 `DerivedMetricsDaily`/`CurrentPublishedBatch` 모델 추가. `derived_metrics_daily.market`은 `listed_market` ENUM(상장시장, 0005 재사용) — `per_raw`/`pbr_raw`/`market_cap_raw_krw`는 DB 컬럼으로 존재하되 API 응답 화이트리스트에서 항상 제외(§4-3).
- **설계 공백 보완**: `current_published_batch.market`의 축(상장시장 vs 거래소 세션)을 설계서 §3-2가 명시하지 않았다. `meta.data_freshness.market`(§3-4)이 거래소 세션 구분이고 이 포인터가 "그 세션 배치가 어디까지 발행됐는지"를 가리키는 것이 자연스러워, `reference.market_session` ENUM(KRX/NXT, 0001 재사용)으로 확정했다 — unit-03-note.md §0("종목 마스터 시드 출처" 설계 공백을 사용자 재질문 없이 직접 확정한 것)과 동일한 성격의 판단이라 규칙 A 대상으로 격상하지 않았다(§2 편차 2 참조).
- `db/alembic/versions/0006_create_public_serving_derivation_tables.py`: 두 테이블 생성 + GRANT를 같은 리비전에 포함(DEF-003 교훈 적용). `batch_worker`=SELECT/INSERT/UPDATE, `api_service`=SELECT.

### 1-3. `SqlCalendarRepository`를 `shared/calendar_service/`로 승격 (unit-02-note.md 권고 이행)

`unit-02-note.md` §2-3은 `services/public_api/db/calendar_repository.py`와 `services/ingestion_batch/calendar_lookup.py`에 동일 로직이 의도적으로 중복돼 있음을 기록하며 "**세 번째로 필요해지면(UNIT-06~08의 Derivation Batch 등) `shared/calendar_service/`로 승격하는 것을 권고한다**"고 명시했다. 이번 유닛(Derivation Batch)이 바로 그 세 번째 필요 시점이라, 새 사본을 또 만드는 대신 실제로 승격했다.

- `shared/calendar_service/sql_repository.py`(신규): 실제 구현.
- `services/public_api/db/calendar_repository.py`, `services/ingestion_batch/calendar_lookup.py`: 이 모듈을 재노출(re-export)하는 얇은 래퍼로 축소 — **기존 import 경로를 전혀 바꾸지 않아** `run_ingestion.py`/`scripts/seed_stock_master.py`/`services/public_api/api/calendar.py`를 수정할 필요가 없었다.
- 리팩터링 전 79개 테스트를 **수정 없이** 재실행해 전부 통과함을 확인했다(§7 로그).

### 1-4. Public API — `GET /api/v1/stocks/{code}/metrics` (REQ-002)

- `services/public_api/schemas/metrics.py`: `StockMetricsData` — 원본/원시값 필드를 아예 선언하지 않는다(§4-3).
- `services/public_api/data_freshness.py`(신규): `meta.data_freshness` 구성 공통 헬퍼. 이 엔드포인트가 처음으로 "요청한 거래일이 최신인지, 며칠 지연됐는지"를 실제로 계산해야 해서 신설했다 — `staleness_note`에 정확한 지연 영업일수를 넣기 위해 캘린더를 하루씩 스캔하는 `count_trading_days_strictly_after()`를 두되, 상한(60일) 초과 시 숫자 없는 일반 문구로 안전하게 대체한다(추측 숫자 지어내지 않음). UNIT-07/08도 동일한 신선도 판단이 필요하므로 재사용 가능하게 분리했다.
- `services/public_api/db/metrics_repository.py`: `get_stock`/`get_current_published_trade_date`/`get_metrics` — 읽기 전용.
- `services/public_api/api/metrics.py`: 라우터 본체. 로직/에러 매핑 근거는 아래 §2에 상세 기록.
- `main.py`에 라우터 등록.

### 1-5. 프론트엔드 — `/stocks/[code]` (04-ux-design.md §2-4)

UNIT-05가 만든 `GlobalNav`/`Header`/루트 레이아웃(`RootLayout` → `DisclaimerBanner`/`Footer`/`SkipLink`)을 그대로 상속한다(새 헤더/네비게이션을 만들지 않음). UNIT-04가 만든 `DataFreshnessBadge`를 **처음으로 실 데이터에 연결**했다.

- `frontend/src/lib/stockMetrics.ts`(신규): 서버 컴포넌트 전용 fetch 클라이언트. HTTP 상태가 아니라 서버가 내려준 `error.code`를 그대로 결과에 실어 반환(§3-4 "프론트가 판단하지 않는다" 원칙을 에러 처리에도 확장 적용).
- `frontend/src/lib/errorMapping.ts`(신규): `error.code` → 화면 표시 방식(`EmptyState`/`ErrorState`) 매핑, 04-ux-design.md §1-4 Flow D 표 그대로.
- `frontend/src/lib/formatPercent.ts`(신규): "+/-" 부호·상승/하락 텍스트 포맷터(§3-1 접근성 원칙).
- `frontend/src/components/MetricCard.tsx`, `ValuationMetricCard.tsx`(신규): §2-4/§4 `MetricCard` 명세(정상/결측/산정불가 상태).
- `frontend/src/components/ErrorState.tsx`, `EmptyState.tsx`, `LoadingSkeleton.tsx`(신규): §4 공통 컴포넌트 최초 구현(이번 유닛이 실제로 쓰는 변형만 — §2 편차 4 참조).
- `frontend/src/app/stocks/[code]/page.tsx`(신규): 종목 상세 화면 본체(비동기 서버 컴포넌트, `fetch` 기반).
- `frontend/src/app/stocks/[code]/loading.tsx`(신규): Next.js `loading.tsx` 관례로 §2-4 "헤더 + 카드 5개 스켈레톤" 구현.
- `frontend/src/app/stocks/[code]/not-found.tsx`(신규): 404 STOCK_NOT_FOUND 전용 화면("종목 검색으로 돌아가기" CTA).
- `frontend/.env.example`(신규): `NEXT_PUBLIC_API_BASE_URL`.

---

## 2. 설계서 대비 편차 및 확인 필요 사항 (사유 포함)

1. **[구현 세부 결정] 그날 원본 시세 자체가 없는 종목은 배치 결과에서 완전히 제외**: §3-2 결측치 처리 원칙은 "계산 불가능한 *필드*는 null"이라고 서술하지만, "그날 이 종목 자체가 거래되지 않아 원본 행이 아예 없는 경우"는 명시하지 않았다. 이 유닛은 이를 개별 필드 결측과 구분해, 그런 종목은 애초에 `derived_metrics_daily`에 행 자체를 쓰지 않기로 결정했다(`run_derivation.py` `compute_stock_day_metrics()` 참조). 근거: 결측치 처리 원칙의 취지("계산 못 하는 값을 0/임의값으로 속이지 않는다")를 지키려면, "그날 데이터가 아예 없음"과 "데이터는 있는데 일부 지표만 못 만듦"을 섞으면 오히려 혼란을 유발한다고 판단했다.
2. **[설계 공백 보완] `current_published_batch.market`의 축을 거래소 세션(KRX/NXT)으로 확정**: §1-2 참조. 설계서 §3-2 표가 명시하지 않은 부분을 `meta.data_freshness.market`과의 정합성 근거로 직접 확정했다(unit-03-note.md §0과 동일한 성격의 판단 — 사용자 재질문 대상이 아니라고 판단).
3. **[API 계약 확장 아님, 구현 세부 결정] "종목은 존재하나 요청 거래일의 파생 지표 행이 없음"을 전용 에러 코드로 만들지 않음**: 03-system-design.md §4-1 에러 표는 이 케이스(신규 상장 직전/거래정지일 조회 등)를 다루지 않는다. 새 에러 코드를 추가하는 것은 API 계약 변경(설계서 수정 필요)이라고 판단해, 대신 §3-2 결측치 처리 원칙("0/대체값 금지, null 유지")을 행 단위로 확장 적용해 **전 지표 필드가 `null`인 200 응답**을 반환하도록 구현했다(`services/public_api/api/metrics.py` 주석 참조). 04-ux-design.md §2-4의 "개별 지표 결측 카드만 데이터 부족 표시" 규칙이 그대로 재사용되어 화면도 자연스럽게 대응한다.
4. **[구현 세부 결정] `date` 쿼리 파라미터는 "최신" 판단(=`current_published_batch` 포인터)을 우회한다**: 명시적으로 날짜를 지정하면 검증 통과 여부와 무관하게 `derived_metrics_daily`를 직접 조회한다(단, 신선도 계산용 캘린더 확인은 여전히 수행 — 424/503 로직 그대로 적용). "최신" 조회만 발행 포인터로 보호하고, 명시적 날짜 조회는 디버깅/과거 조회 목적으로 그 게이팅을 우회하는 것이 합리적이라고 판단했다.
5. **[04-ux-design.md §4 명세 축소, 사유 명시] `ErrorState`는 4개 변형 중 3개만 구현**: §4 표는 `ErrorState` 변형으로 `network`/`calendar-not-confirmed`/`not-found`/`rate-limited` 4개를 나열하지만, `not-found`(404)는 Next.js의 `notFound()` + 라우트 전용 `not-found.tsx`로 구현했다(프레임워크 관용구가 "종목 검색으로 돌아가기" CTA가 있는 전체 화면 대체를 더 안전하게 구현한다고 판단, `noindex` 메타 태그도 자동 부여됨). `EmptyState`도 §4가 나열한 4개 변형(`no-query`/`no-search-result`/`no-screen-result`/`no-data-yet`) 중 이번 유닛이 실제로 쓰는 `no-data-yet` 하나만 구현했다 — 나머지는 검색/스크리닝 화면(UNIT-06 검색 UI 확장 여지 또는 UNIT-07)이 필요할 때 추가해야 한다(unit-05-test.md가 지적한 "임시 텍스트 패턴을 그대로 승격시키지 말 것" 원칙과 동일하게, 쓰지 않는 변형을 미리 만들지 않았다).
6. **[프레임워크 문서화된 트레이드오프, 알아둘 것] `notFound()`의 HTTP 상태 코드가 200으로 응답됨(소프트 404)**: `/stocks/[code]/loading.tsx`가 있어 Next.js 16이 이 라우트를 자동으로 Suspense 경계로 감싸는데, 이 경우 `notFound()`가 던져지는 시점에는 이미 응답 스트리밍이 200으로 시작된 뒤라 상태 코드를 바꿀 수 없다(Next.js 16 공식 문서 `not-found.md` "Status codes" 절에 명시된 알려진 트레이드오프 — 코드 결함이 아님). `<meta name="robots" content="noindex">`는 자동으로 부여되어 검색엔진 노출은 방지된다. 04-ux-design.md는 이 화면에 특정 HTTP 상태 코드를 못박지 않았으므로 기능 요구사항 위반은 아니지만, **HTTP 상태 코드 정확성이 중요하다면 `loading.tsx`를 제거해 로딩 스켈레톤과 맞바꿔야 한다** — 이 트레이드오프는 사업적 판단이 필요하다고 보아 여기 명시적으로 남긴다(§3 참조).

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터 및 향후 운영자용)

- **[최우선] `raw_fundamentals` 실제 적재 전까지 PER/PBR/시가총액 백분위는 항상 `null`이다**: UNIT-02가 이 테이블에 실제로 값을 넣지 않으므로(§0-3), 현재 시스템 상태에서 `GET /stocks/{code}/metrics`는 `per_percentile`/`pbr_percentile`/`market_cap_percentile`이 항상 `null`이다. 이는 이 유닛의 결함이 아니라 UNIT-02의 알려진 범위 제한이 그대로 흘러들어온 것이다 — `raw_fundamentals` 적재 로직이 추가되면 자동으로 채워진다(코드 변경 불필요, 이미 LEFT JOIN 방식으로 구현).
- **404 소프트 상태 코드(§2 편차 6)**: 실제 HTTP 상태가 200으로 응답되는 것이 6단계/9단계(보안/SEO 관점)에서 허용 가능한지 판단 필요. 필요 시 `loading.tsx` 제거 여부를 코디네이터가 결정해야 한다.
- **PER/PBR/시가총액 percentile의 실제 방향성 재검증**: 이번 유닛은 픽스처(§0-b) 2종목으로만 검증했다(오름차순/내림차순 각각 1쌍 비교). 실제 코스피+코스닥 전 종목 규모(약 2,500개)에서 동률 처리·경계값(전부 동일 PER 등)이 예상대로 동작하는지는 재현되지 않았다 — `rank_percentile()`의 동률 케이스는 단위테스트(`test_derivation_compute.py`)로 별도 검증했으나, 실 DB 대량 데이터로는 미검증.
- **거래량 이상치 스코어의 표본표준편차 vs 모표준편차 선택**: `compute.py`가 `statistics.stdev`(n-1, 표본표준편차)를 채택했다(§1-1 참조). 설계서가 명시하지 않은 구현 세부 결정이며, 모표준편차(`pstdev`)를 쓰면 값이 근소하게 달라진다 — 실사용 데이터로 어느 쪽이 더 적절한 "이상치" 감도를 주는지는 운영 관찰 후 재검토가 필요할 수 있다.
- **Derivation Batch 실제 cron 스케줄링**: 이번 유닛은 CLI 실행까지만 검증했다(`python -m services.derivation_batch.run_derivation`). Ingestion Batch 완료 후 어느 시점에 Derivation Batch를 트리거할지(직렬 실행 순서, 재시도 정책)는 설계서 §7-2에 명시되지 않았고, 10단계 배포테스트 영역으로 남긴다.
- **실제 컨테이너/배포 미검증**: 로컬 CLI/로컬 Docker PostgreSQL/로컬 `uvicorn`+`next start`까지만 검증했다. 실제 컨테이너 이미지 빌드, 4개 서비스 간 배포 순서는 검증 범위 밖이다.

---

## 4. 인수 조건 (Acceptance Criteria) — 6단계 테스터용

**AC-1 (가공 계산 로직, 순수 함수, DB 불필요)** `pytest tests/unit/test_derivation_compute.py`가 전부 pass(14건):
  - `return_pct`: 정상/음수/전일 종가 없음(None)/전일 종가 0(None)
  - `ma_gap_pct`: 정상 계산(당일 포함 윈도), 데이터 부족(None), window 슬라이스 밖 데이터 무시 확인
  - `volume_anomaly_score`: 정상(양수), 데이터 부족(None), 표준편차 0(None)
  - `rank_percentile`: 빈 리스트, 내림차순 worked example(03-system-design.md §3-2 예시와 동일 공식), 오름차순(PER/PBR류), 동률 표준경쟁순위(1,1,3 패턴)

**AC-2 (Derivation Batch 오케스트레이션 순수 로직)** `pytest tests/unit/test_run_derivation.py`가 전부 pass(12건):
  - `resolve_target_trade_date`: override 우선, 캘린더 기반 계산, 캘린더 공백 시 `DerivationRunError`, 캘린더 무결성 위반 시 `CalendarDataError` 전파(run_ingestion.py와 동일 계약)
  - `compute_stock_day_metrics`: 당일 시세 없음(None), 빈 윈도(None), IPO 첫날(return_pct만 None, 나머지 계산), fundamentals 결합 정상 반영
  - `build_derivation_inputs`: 2종목 교차 백분위 계산 정확성(return/PER/시가총액 방향성 각각 검증)
  - `_validation_passed`: 5% 이하 통과, 전종목 결측 실패, 빈 목록 실패

**AC-3 (Public API `/stocks/{code}/metrics`)** `pytest tests/unit/test_public_api.py`의 `test_get_stock_metrics_*` 7건 전부 pass:
  - 정상 조회(최신, `is_latest_trading_day=true`)
  - 종목 없음 → 404 `STOCK_NOT_FOUND`
  - 발행된 데이터 없음(날짜 생략) → 503 `DATA_PIPELINE_STALE`
  - 캘린더 미확인 → 424 `CALENDAR_NOT_CONFIRMED`
  - 종목은 있으나 그 날짜 지표 행 없음 → 200 + 전 지표 필드 `null`
  - 명시적 `date`가 발행 포인터보다 과거 → 200 + `is_latest_trading_day=false` + `staleness_note`에 정확한 지연 영업일수 포함
  - 잘못된 날짜 형식 → 400 `INVALID_PARAMETER`

**AC-4 (기존 회귀 없음, `SqlCalendarRepository` 승격)**
  - `pytest tests/unit -q` **112건** 전부 pass(기존 79건 + 이번 유닛 33건: compute 14 + run_derivation 12 + metrics API 7). 기존 79건은 리팩터링 후에도 **수정 없이** 통과.

**AC-5 (마이그레이션, 실 PostgreSQL로 검증 완료)**
  - `ALEMBIC_DATABASE_URL=<migrator> alembic upgrade head`(0001~0006) 성공 → `derived_metrics_daily`/`current_published_batch` 테이블 생성 확인
  - `\dp public_serving.derived_metrics_daily`, `\dp public_serving.current_published_batch` → 둘 다 `batch_worker=arw`, `api_service=r`
  - `alembic downgrade 0005` → 두 테이블 완전히 제거, `alembic upgrade head`로 재적용 시 오류 없이 복원

**AC-6 (Derivation Batch, 실 PostgreSQL — "데이터 없음" 정상 처리, 실제 운영 상태 그대로)**
  - `stock_master`/`raw_ohlcv`가 실제로 비어 있는 상태에서 `python -m services.derivation_batch.run_derivation --trade-date <임의 날짜>` 실행 → 종료 코드 1, "활성 종목이 없습니다" 메시지, `batch_run` 1행(FAILED) 기록
  - `stock_master`에 종목 2개만 넣고(raw_ohlcv는 그대로 빔) 재실행 → 종료 코드 1, "원본 시세 데이터가 하나도 없습니다" 메시지, `batch_run` 1행(FAILED) 기록

**AC-7 (Derivation Batch, 실 PostgreSQL + 명시적 테스트 픽스처 — 가공 로직 정확성)**
  - `python scripts/dev_seed_fixture_metrics.py` + `python -m services.derivation_batch.run_derivation --trade-date 2026-09-14` → 종료 코드 0(`SUCCESS`)
  - `derived_metrics_daily`에 2행 생성, 상승 종목(005930)의 `return_rank_pct`=50.0(2종목 중 1등), 하락 종목(000660)=100.0, `ma5_gap_pct`/`ma20_gap_pct` 부호가 픽스처의 상승/하락 추세와 일치, 마지막날 거래량 급증시킨 005930의 `volume_anomaly_score`가 뚜렷하게 양수(600대)
  - `current_published_batch`에 `market='KRX', trade_date='2026-09-14'` 포인터 생성 확인

**AC-8 (Public API, 실 PostgreSQL + AC-7 데이터 — 종단간)**
  - `api_service` 자격증명으로 `GET /api/v1/stocks/005930/metrics` → 200, AC-7 계산값과 일치, `data_freshness.is_latest_trading_day=false`(실제 시스템 날짜 기준 지연 감지) + `staleness_note`에 정확한 지연 영업일수
  - `GET /api/v1/stocks/999999/metrics` → 404 `STOCK_NOT_FOUND`
  - `current_published_batch` 행을 임시로 지운 뒤 `date` 생략 조회 → 503 `DATA_PIPELINE_STALE`, 같은 상태에서 `?date=2026-09-14` 명시 조회는 여전히 200(발행 포인터 우회 확인)
  - `api_service`로 `raw_internal.raw_ohlcv` 직접 SELECT 시도 → `permission denied for schema raw_internal`(1차/2차 방어 회귀 없음), `derived_metrics_daily`에 INSERT 시도 → `permission denied`

**AC-9 (프론트엔드, 실제 프로덕션 빌드 + 실행 중인 백엔드 — 종단간)**
  - `npm run build && npm run start`(frontend) + `uvicorn services.public_api.main:app`(backend, `NEXT_PUBLIC_API_BASE_URL` 연결) 상태에서 `GET /stocks/005930` → AC-7/AC-8 값이 정확히 렌더링됨(등락률 순위/5일·20일 이평 대비/거래량 이상치 스코어/밸류에이션 3종), `DataFreshnessBadge`의 지연 경고 문구까지 실제 화면에 표시
  - `GET /stocks/999999` → 커스텀 404 화면("요청하신 종목 정보를 찾을 수 없습니다" + "종목 검색으로 돌아가기")
  - `current_published_batch` 없는 상태에서 `GET /stocks/005930` → `EmptyState`("표시할 데이터가 아직 없습니다. 서비스 데이터 준비 중입니다.")
  - 위 세 화면 모두에 `disclaimer-banner`/`GlobalNav`가 정상적으로 함께 렌더링됨(레이아웃 상속 회귀 없음)

**AC-10 (정적 분석)**
  - `python -m ruff check .` 오류 0건
  - `cd frontend && npx tsc --noEmit && npm run lint && npm run build`(prebuild 금지어 린트 포함) 전부 통과, 라우트에 `/stocks/[code]`(Dynamic) 정상 포함

---

## 5. 게이트 1 — 정적 분석/린트 결과

- **백엔드**: `pyproject.toml`의 `ruff` 설정(UNIT-01부터 기존) 그대로 적용. `python -m ruff check .` → **All checks passed!**(PEP 695 제네릭 문법으로 `rank_percentile`을 작성해 UP047 경고 해소 — `pyproject.toml`이 이미 `UP046`(클래스 제네릭)만 예외 처리하고 함수 제네릭은 예외 대상이 아니었으므로 그대로 준수).
- **프론트엔드**: `eslint.config.mjs`(UNIT-04부터 기존, `jsx-a11y` 포함) → `npm run lint` 0 error/0 warning. `npx tsc --noEmit` 통과. `npm run build`의 `prebuild`(금지어 린트) → 검사 파일 25개, 위반 0건.
- 설정이 없어서 건너뛴 검사는 없다.

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — §1-2(Derivation Batch가 raw_internal만 읽고 public_serving에만 씀), §3-2(`return_rank_pct`/percentile 계산식 그대로, 결측치 null 유지), §4-3(원본/원시값 필드가 응답 스키마에 아예 없음, DB 컬럼도 스크리닝용으로만 존재), 04-ux-design.md §2-4(MetricCard 5종, 원본 캔들차트 없음), §1-4(에러 코드별 화면 매핑)를 그대로 구현했다. 설계서가 명시하지 않은 부분(§2 편차 1·2·3·4)은 상상으로 채우지 않고 근거와 함께 직접 확정했다.
- [x] **에러 처리가 누락된 경로가 없는가(예외를 삼키고 무시하는 코드 없음)** — Derivation Batch의 모든 실행 경로(캘린더 미확인/활성종목 없음/원본시세 0건/검증실패/예기치 못한 예외)가 명시적으로 `batch_run`에 기록되고 0이 아닌 종료 코드로 알린다(run_ingestion.py와 동일 원칙). Public API는 계산 불가 상황을 전부 명시적 에러 코드(404/424/503×2)로 응답하며, 프론트엔드는 fetch 실패/JSON 파싱 실패/서버 에러를 전부 `try/catch`로 잡아 `ErrorState`로 전환한다(조용히 크래시하거나 빈 화면을 보여주지 않음).
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — API 경계: `code`(path)는 리포지토리 조회 실패 시 404로 명시 처리, `date`(query)는 FastAPI/Pydantic이 형식을 검증하고 실패 시 공통 핸들러가 400으로 변환(기존 패턴 재사용). DB 경계: 모든 쿼리가 SQLAlchemy 파라미터 바인딩만 사용(문자열 조합 없음). 프론트엔드 경계: `stockMetrics.ts`가 서버 응답의 `data`/`meta.data_freshness` 존재 여부를 검증하고, 형식이 예상과 다르면 `INVALID_RESPONSE` 에러로 명시 처리한다(신뢰하고 그대로 사용하지 않음).
- [x] **하드코딩된 시크릿/자격증명이 없는가** — `BATCH_DATABASE_URL`/`PUBLIC_API_DATABASE_URL`/`NEXT_PUBLIC_API_BASE_URL` 전부 환경변수로만 주입. 신규 `scripts/dev_seed_fixture_metrics.py`도 `services.derivation_batch.core.config.get_settings()`(환경변수 기반)를 재사용하며 DB 자격증명을 코드에 넣지 않았다. 로컬 검증에 사용한 `devpass`는 이전 유닛들이 이미 세팅해 둔 로컬 1회성 Docker 컨테이너 값이며 어떤 소스 파일에도 커밋하지 않았다(쉘 환경변수로만 주입, `grep -rn devpass`로 소스 코드에 없음을 확인).
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — `SqlCalendarRepository` 승격(§1-3)은 `unit-02-note.md`가 명시적으로 권고한 "세 번째 필요 시점" 조건을 충족해 수행한 것이며, 기존 79개 테스트를 수정 없이 재실행해 회귀 없음을 확인했다(곁다리가 아니라 이번 유닛의 필요(3번째 서비스의 캘린더 조회)에 의해 정당화되는 최소 범위 변경). UNIT-01~05 산출물 중 이 승격과 무관한 다른 코드(예: `stock_master` 검색 로직, `GlobalNav`/`Header` 자체)는 전혀 수정하지 않았다. `market_summary_daily`(REQ-004, UNIT-08 소관)나 스크리닝 엔드포인트(REQ-003, UNIT-07 소관)는 만들지 않았다. `/stocks`(검색 목록, REQ-001 프론트엔드)는 이번 유닛 범위가 아니므로 UNIT-05의 플레이스홀더를 그대로 두었다(§7 "알려진 시퀀싱 공백" 참조).

---

## 7. 로컬 동작 확인 요약 (실행 로그 근거)

- `python -m ruff check .` → **All checks passed!**
- `python -m pytest tests/unit -q` → **112 passed**(기존 79건 + 이번 유닛 33건: `test_derivation_compute.py` 14 + `test_run_derivation.py` 12 + `test_public_api.py`(metrics) 7)
- **`SqlCalendarRepository` 승격 회귀 확인**: 승격 전/후 기존 79개 테스트를 그대로(수정 없이) 재실행해 전부 통과 확인.
- **로컬 Docker `stock-screener-db`(기존 `migrator`/`batch_worker`/`api_service` 계정 재사용)**:
  - `alembic upgrade head`(0001~0006) → `derived_metrics_daily`/`current_published_batch` 생성 확인. `\dp`로 `batch_worker=arw`/`api_service=r` 확인.
  - `alembic downgrade 0005` → 두 테이블 제거 → `upgrade head` 재적용 → 정상 복원(GRANT 자동 재적용 포함).
  - **실제 "데이터 없음" 경로 검증(상상 아님, 실제 빈 상태 그대로)**: (1) `stock_master`/`raw_ohlcv` 완전히 빈 상태에서 `run_derivation.py --trade-date 2026-09-14` 실행 → "활성 종목이 없습니다" 종료 코드 1, `batch_run`(FAILED) 1행 기록 확인. (2) `stock_master`에 종목 2개만 삽입(`raw_ohlcv`는 그대로 빔) → "원본 시세 데이터가 하나도 없습니다" 종료 코드 1, `batch_run`(FAILED) 1행 기록 확인.
  - **실제 결함 발견 및 즉시 수정**: (2) 실행 중 `psycopg.errors.UndefinedFunction: operator does not exist: reference.market_session = character varying` 발생 — `raw_models.py`의 `market` 컬럼을 `sa.String`으로 잘못 선언한 것이 원인. `reference.market_session` ENUM으로 수정 후 재실행해 정상 동작 확인(이 오류 자체도 `batch_run`에 FAILED로 정확히 기록되어 있었음 — 명시적 실패 원칙이 실제 버그 상황에서도 그대로 동작함을 부수적으로 확인).
  - **테스트 픽스처로 가공 로직 검증(명확히 구분)**: `python scripts/dev_seed_fixture_metrics.py`(합성 종가/거래량/PER/PBR/시가총액 2종목 25거래일) → `run_derivation.py --trade-date 2026-09-14` → `[완료] status=SUCCESS`. 실제 조회 결과: 005930(상승 추세, 마지막날 거래량 급증) `return_pct=4.5576, return_rank_pct=50.0, ma5_gap_pct=3.9446, ma20_gap_pct=6.7616, volume_anomaly_score=604.3645, per_percentile=50.0, market_cap_percentile=50.0`; 000660(하락 추세) `return_pct=-0.7687, return_rank_pct=100.0, ma5_gap_pct=-0.8657, ma20_gap_pct=-2.4792, volume_anomaly_score=1.1507, per_percentile=100.0, market_cap_percentile=100.0` — 방향성 전부 기대와 일치. `current_published_batch(market='KRX', trade_date='2026-09-14')` 생성 확인.
  - **재현성 확인**: 위 픽스처 데이터를 전부 정리(`TRUNCATE`/`DELETE`)한 뒤 커밋된 `scripts/dev_seed_fixture_metrics.py`를 다시 실행해 동일한 결과가 재현됨을 확인(스크래치패드 임시 스크립트가 아니라 저장소에 커밋된 스크립트로 재현 가능함을 검증).
  - **Public API 종단간(실 PostgreSQL + `api_service` 자격증명, `TestClient`)**: `GET /stocks/005930/metrics` → 200, 위 계산값과 정확히 일치, `is_latest_trading_day=false`(실제 시스템 날짜 2026-09-16 기준 진짜로 1영업일 지연됨 — mock 없이 실시간 계산이 실제로 맞음을 우연히 실증), `staleness_note="예상보다 1영업일 지연된 데이터입니다"`. `GET /stocks/000660/metrics?date=2026-09-14` → 200, 명시적 날짜 조회 정상. `GET /stocks/999999/metrics` → 404 `STOCK_NOT_FOUND`. `current_published_batch` 행을 임시로 지운 뒤 재조회 → 503 `DATA_PIPELINE_STALE`, 같은 상태에서 `?date=2026-09-14` 조회는 여전히 200(발행 포인터 우회 확인) — 이후 `run_derivation.py` 재실행으로 포인터 복원. `api_service`로 `derived_metrics_daily`에 INSERT 시도 → `permission denied for table derived_metrics_daily`. `api_service`로 `raw_internal.raw_ohlcv` SELECT 시도 → `permission denied for schema raw_internal`(1차/2차 방어 회귀 없음).
  - **프론트엔드 종단간(실제 프로덕션 빌드 + 실행 중인 실 백엔드)**: `cd frontend && npm run build && npm run start`(포트 3000) + `uvicorn services.public_api.main:app`(포트 8000, `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`)로 두 서버를 동시 기동. `curl http://localhost:3000/stocks/005930` → 렌더링된 HTML에 "삼성전자(테스트픽스처) (005930)", 지표 카드 5종(등락률 순위 상위 50%, 5일 이평 대비 +3.9%(상승, 색상 클래스 적용), 20일 이평 대비 +6.8%, 거래량 이상치 스코어 604.4, 밸류에이션 PER/PBR/시가총액 백분위 각 상위 50%)이 정확히 표시됨을 확인. `DataFreshnessBadge`의 지연 경고("⚠ 예상보다 1영업일 지연된 데이터입니다")도 실제 화면에 표시됨. `curl http://localhost:3000/stocks/999999` → 커스텀 404 화면("요청하신 종목 정보를 찾을 수 없습니다" + "종목 검색으로 돌아가기") 확인(단, HTTP 상태는 200 — §2 편차 6 참조). `current_published_batch` 삭제 상태에서 `curl http://localhost:3000/stocks/005930` → `EmptyState`("표시할 데이터가 아직 없습니다. 서비스 데이터 준비 중입니다.") 확인. 세 화면 모두 `disclaimer-banner`/`GlobalNav` 마크업이 함께 렌더링됨을 확인(레이아웃 상속 회귀 없음).
  - **정리**: 검증 후 `derived_metrics_daily`/`current_published_batch`를 `TRUNCATE`하고, `raw_ohlcv`/`raw_fundamentals`/`stock_master`/`batch_run`(ingest/derive)에서 픽스처 종목(`005930`/`000660`) 관련 행만 삭제했다. `reference.market_calendar`(730행)는 그대로 유지. 최종 상태를 재쿼리해 `stock_master`/`raw_ohlcv`/`derived_metrics_daily`/`current_published_batch` 전부 0건, `market_calendar`만 730건임을 확인 — 다음 세션(UNIT-07/08 또는 6단계)이 "실제로는 데이터가 없는 상태"에서 이어서 검증할 수 있게 남겼다.
  - 두 dev 서버(`uvicorn`, `next start`)는 검증 후 프로세스를 종료했다.

---

## 8. 다음 단계

- 이 노트 작성 및 `traceability.md` 갱신 완료 후, 6단계(단위테스트, `06-unit-tester`)를 UNIT-06 대상으로 호출해야 한다.
- 6단계는 특히 다음을 독립적으로 재검증할 것을 권고한다:
  1. §0/§7의 "데이터 없음 정상 처리" 검증을 신뢰하지 않고 실 PostgreSQL로 직접 재현(빈 `stock_master`/`raw_ohlcv` 양쪽 케이스 모두).
  2. `scripts/dev_seed_fixture_metrics.py`로 만든 픽스처가 실제로 "합성 데이터"이지 실제 시세인 것처럼 오인될 여지가 없는지(종목명에 "(테스트픽스처)" 명시, 코드 주석) 확인하고, 동일 스크립트를 재실행해 계산 결과 재현성을 다시 확인.
  3. `rank_percentile()`/`return_rank_pct` 방향성이 03-system-design.md v3 §3-2 worked example(125/2500*100=5.0)과 정확히 일치하는지 별도 케이스로 재검산.
  4. §2 편차 6(소프트 404)이 이번 유닛의 "완료" 판정에 영향을 주는 결함인지, 아니면 §3에 남긴 대로 코디네이터 판단이 필요한 트레이드오프로 남겨도 되는지 판단.
  5. `SqlCalendarRepository` 승격이 UNIT-01/02/03의 기존 동작을 정말로 하나도 바꾸지 않았는지(특히 `run_ingestion.py`/`seed_stock_master.py`/`api/calendar.py`의 실제 import 해석 경로) 소스 레벨로 재확인.
- **알려진 시퀀싱 공백(범위 외, 인지만 해둘 것)**: 02-planning.md §9 작업 단위 목록에는 REQ-001(종목 검색)의 **프론트엔드** 화면을 명시적으로 배정한 유닛이 없다(UNIT-03은 백엔드 API만 구현했고, UNIT-04/05는 셸/네비게이션까지만 만들었다). 그 결과 `/stocks`(검색 목록) 화면은 여전히 UNIT-05의 플레이스홀더 상태이며, 사용자가 UI만으로 종목 코드를 몰라도 `/stocks/{code}`(이번 유닛)에 도달할 방법이 아직 없다. 이번 유닛은 "포함 REQ: REQ-002"로 명시적으로 범위가 한정되어 있어 이 공백을 메우지 않았다(범위 외 확장 금지 원칙) — 코디네이터가 이 공백을 어느 유닛에 배정할지 결정이 필요하다.
