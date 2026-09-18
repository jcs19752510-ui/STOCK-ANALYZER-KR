# UNIT-08 구현 노트 — 전일(직전 거래일) 시장 동향 리포트

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-17
- 대상 REQ: REQ-004 (Should have)
- 입력: `docs/harness/02-planning.md`(v5) §4-3, §9 UNIT-08 / `docs/harness/03-system-design.md`(v4) §3-1-1, §3-2(`market_summary_daily`), §4-2(`GET /market-summary`), §5-1 / `docs/harness/04-ux-design.md`(v3) §1-1 Flow A, §2-1, §5, §6 / `docs/harness/decisions.md` DEC-011/DEC-015/DEC-016 / `unit-05-note.md`(GlobalNav/Header), `unit-06-note.md`(Derivation Batch 패턴), `unit-07-note.md`(EmptyState/공통 컴포넌트 관례)

---

## 0. 이 유닛 착수 전 확인한 것

- `03-system-design.md` §1-2: "Derivation Batch... 시장 요약 통계(REQ-004)를 계산해 public_serving에 쓴다"는 이미 UNIT-06/07이 구현한 `services/derivation_batch/run_derivation.py`(단일 배치 실행)의 **같은 실행 흐름 안에서** REQ-004를 마저 구현하라는 지시로 읽었다. 새 배치 프로세스를 별도로 만들지 않았다.
- `market_summary_daily.market`은 `ALL` 값을 포함해 3종(§3-1-1)이라 기존 `listed_market` ENUM(KOSPI/KOSDAQ 2값, 0005)을 재사용하지 않고 별도 ENUM(`market_summary_market`)을 신설했다 — 재사용하면 `stock_master`/`derived_metrics_daily`가 가질 수 없는 `ALL` 값이 섞여 들어가 §3-1-1 표준 참조표 원칙과 상충한다.
- `ALL` 행은 DEC-016에 따라 KOSPI+KOSDAQ 사후 합산이 아니라, Derivation Batch가 그날 거래된 전 종목(`day_metrics`)을 그대로 `compute_market_summary()`에 넘겨 직접 재집계한다. 실제로 로컬 PostgreSQL로 KOSPI 전용 픽스처(KOSDAQ 종목 0개)를 넣고 검증해, `ALL` 행이 KOSPI 행과 별도로 독립 계산됨(우연히 같은 값이 나오는 것이지 합산 코드 경로를 타지 않음)을 코드 경로 상에서 확인했다(`build_market_summary_inputs()`가 KOSPI/KOSDAQ/ALL 세 서브셋을 각각 `compute_market_summary()`에 독립 호출).
- `stock_master.sector` 출처는 여전히 미확정(03-system-design.md §8-2 항목8, UNIT-03/06/07이 이미 승계한 리스크) — 이번 유닛도 이를 새로 해결하지 않는다. `top_sectors_by_value` 집계는 `sector`가 있는 종목만 대상으로 하고, 전부 `sector=None`인 현재 상태에서는 빈 리스트를 반환하도록 구현했다(값을 지어내지 않음). 프론트엔드는 이를 04-ux-design.md §2-1이 정의한 "부분 실패(업종 데이터만 없음)" 상태(`"업종 정보를 준비 중입니다"`)로 표시한다.

---

## 1. 구현 범위

### 1-1. 백엔드 — Derivation Batch 확장 (REQ-004)

- `db/alembic/versions/0009_create_public_serving_market_summary_daily.py` — `public_serving.market_summary_daily` 테이블 + `market_summary_market` ENUM(KOSPI/KOSDAQ/ALL) 신설, GRANT(batch_worker rw / api_service r)를 같은 리비전에 포함(DEF-003 교훈).
- `shared/db_models/public_serving.py` — `MarketSummaryDaily` ORM 모델 추가(원본 시세 컬럼 없음, §4-3).
- `services/derivation_batch/compute.py` — `compute_market_summary()`(순수 함수, DB 의존 없음): 상승/하락/보합 카운트(`return_pct` 결측 종목은 셋 중 어디에도 미포함), 업종별 거래대금 상위(최대 5개, `sector=None`인 종목은 집계 제외), 총 거래대금(전 종목 합산)을 계산한다.
- `services/derivation_batch/raw_models.py` — `raw_ohlcv_table` 프로젝션에 `trading_value` 컬럼을 추가했다(기존에는 `close`/`volume`만 있었음 — REQ-004 집계에 필요).
- `services/derivation_batch/repository.py` — `fetch_trading_values()`(원본 거래대금 조회), `fetch_sector_map()`(`stock_master.sector` 조회), `upsert_market_summary()`(KOSPI/KOSDAQ/ALL 3행 upsert) 추가.
- `services/derivation_batch/run_derivation.py` — `build_market_summary_inputs()` 신설, `run_once()`가 `derived_metrics_daily` upsert 직후(같은 트랜잭션) 시장 요약도 함께 계산·저장하도록 확장. `validation_passed` 여부와 무관하게 항상 기록한다(`derived_metrics_daily`와 동일 원칙 — 실제 서빙 여부는 `current_published_batch` 포인터가 별도로 결정).

### 1-2. 백엔드 — Public API (REQ-004, REQ-009)

- `services/public_api/schemas/market_summary.py` — `SectorSummary`/`MarketSummaryItem`/`MarketSummaryData`(원본 시세 필드 없음, §4-3).
- `services/public_api/db/market_summary_repository.py` — 읽기 전용 리포지토리(`api_service` 권한 경계와 일관).
- `services/public_api/api/market_summary.py` — `GET /api/v1/market-summary`. `market` 생략 시 기본값 `ALL`, `by_market`에 KOSPI/KOSDAQ 세부 포함(§4-2). 사용자 식별 파라미터 없음(REQ-009 — `date`/`market`만 받음, UNIT-04/06/07이 이미 확립한 관례 그대로 유지). 에러 매핑은 UNIT-06/07의 `metrics.py`/`screen.py`와 동일한 패턴(424/503/400)을 그대로 따랐다.
- `services/public_api/main.py` — 라우터 등록.

### 1-3. 프론트엔드 — 홈 화면 (`/`, 04-ux-design.md §2-1)

- `frontend/src/lib/types.ts` — `SectorSummary`/`MarketSummaryItem`/`MarketSummaryData` 타입 추가.
- `frontend/src/lib/marketSummary.ts` — 서버 컴포넌트 fetch 클라이언트(`stockMetrics.ts`와 동일 패턴). `market` 파라미터는 항상 생략(단일 호출 패턴, Q7/DEC-016).
- `frontend/src/lib/formatKrw.ts` — 총 거래대금 억/조 단위 변환(`formatTradingValueKrw`).
- `frontend/src/components/StatSummaryGrid.tsx`, `frontend/src/components/SectorSummaryList.tsx` — 신규 공통 컴포넌트(04-ux-design.md §4).
- `frontend/src/app/page.tsx` — UNIT-04가 남긴 임시 플레이스홀더를 실제 화면으로 교체. UNIT-05가 만든 `GlobalNav`/`Header`(공통 레이아웃)는 그대로 재사용했다(신규 헤더/내비 없음).
- `frontend/src/content/copy.ko.json` — `home` 섹션 신설.
- `frontend/src/app/globals.css` — 홈 화면 전용 클래스 추가(`.home-page__*`, `.stat-summary-*`, `.sector-summary-list*`).

---

## 2. 설계서 대비 편차 및 확인 필요 사항 (사유 포함)

1. **"탭 또는 병기 카드" 중 병기 카드(정적 나열)를 선택했다.** 04-ux-design.md §2-1은 "코스피/코스닥 탭 또는 병기 카드로 `by_market[]`을 표시"라고 명시적으로 두 방식을 모두 허용했다(설계가 구현자에게 선택권을 준 지점이지, 해석이 갈리는 모호함이 아니다). 탭 전환 UI는 `role="tab"`/키보드 화살표 이동/포커스 관리를 새로 구현해야 하는데, 이 화면에 그런 인터랙티브 요소를 요구하는 별도 근거가 없어(과설계 방지) 정적 병기 카드를 택했다. 부수 효과로 UNIT-07이 겪은 포커스 트랩류 결함(DEF-U07-01)의 위험 유형 자체를 구조적으로 피할 수 있었다 — 아래 §6 접근성 사전 점검 참조.
2. **`GET /market-summary`의 응답 스키마 필드 표현 방식**: 03-system-design.md §4-2는 "market=KOSPI/KOSDAQ 명시 요청 시 `by_market` 필드 없음"이라고 서술하지만, 이 코드베이스는 다른 모든 옵셔널 필드(`DataFreshness.session_close_at`/`staleness_note`, envelope의 `error`/`data`)를 "필드 생략"이 아니라 "필드는 항상 존재하되 값이 `null`"로 일관되게 구현해 왔다. 이 설계 문구를 문자 그대로(필드 자체를 응답 JSON에서 제거) 구현할지, 코드베이스 관례(필드 존재 + `null`)를 따를지는 실질적으로 응답 스키마가 달라지는 갈림길이었으나, **API 소비자가 실제로 존재하는 곳(UNIT-08 홈 화면)은 항상 `market` 생략(=ALL) 호출만 사용하므로 이 차이가 실제 소비 코드 경로에 영향을 주지 않고**, 코드베이스 전체의 필드 표현 일관성이 개별 엔드포인트 설계 문구보다 유지보수 관점에서 더 중요하다고 판단해 후자(null 표현)를 택했다. 사용자 질문으로 격상하지 않은 이유: 이는 REQ-004의 기능적 동작이나 사업적 의미를 바꾸지 않는 순수 스키마 표현 방식 결정이며, `unit-06-note.md`(§2, `current_published_batch.market` 축 결정)·`unit-01-test.md`(DEC-017/018) 등 이 저장소가 이미 여러 차례 채택한 "설계 완성도/구현 세부 사안은 개발자가 직접 확정하고 근거를 남긴다" 관행과 동일한 성격이다.
3. **`market_summary_daily` 행이 발행된 거래일에 없는 경우 0으로 채우지 않고 503 SERVICE_UNAVAILABLE을 반환한다.** 03-system-design.md는 이 케이스(발행 포인터는 있는데 요약 행이 없는 경우)를 명시적으로 다루지 않는다. Derivation Batch가 `derived_metrics_daily`와 시장 요약을 같은 트랜잭션에서 항상 함께 쓰므로 정상 운영에서는 발생하지 않지만, 혹시 발생하면 "상승 0/하락 0"처럼 실제 값과 구별되지 않는 0을 반환하는 것은 REQ-006 투명성 원칙(사용자가 지연/이상 여부를 스스로 알 수 있어야 함)에 반한다고 판단해 명시적 실패로 처리했다(`services/public_api/api/market_summary.py`의 `_require_summary()`).
4. **총 거래대금 억/조 변환 로직 중 "1조 미만" 구간의 표기 방식은 04-ux-design.md §2-1에 예시가 없다.** "1억 단위로 나눈 값을 억원으로" 표현을 그대로 연장 적용해 정수 억원(예: "530억원")으로 표시했다(존재하지 않는 예시를 지어내지 않고 설계 원문 문구를 그대로 확장 적용).
5. **§2-1 본문(총 거래대금을 "요약 통계 그리드"와 별개 문단으로 서술)과 §4 컴포넌트 카탈로그(`StatSummaryGrid` = "상승/하락/보합 종목 수 등") 사이의 서술 불일치**: §4는 "등"이라는 표현으로 총 거래대금까지 포괄하는 것으로 읽을 수 있어, 별도의 "총 거래대금 카드" 컴포넌트를 새로 만들지 않고 `StatSummaryGrid`의 각 카드에 4번째 행(총 거래대금)으로 포함시켰다. §4(공식 컴포넌트 카탈로그)를 §2-1 본문 서술보다 우선했다.

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터 및 향후 운영자용)

1. **업종별 거래대금 상위(§2-1 "업종 정보를 준비 중입니다" 상태)는 `stock_master.sector`가 채워지기 전까지 실제로 데이터가 있는 상태를 검증할 방법이 없다.** 이번 유닛도 §8-2 항목8을 새로 해결하지 않았으므로, `SectorSummaryList`의 "정상 표시(막대바 + 수치)" 분기는 합성 픽스처로 `sector` 값을 직접 채워야만 검증 가능하다(로컬 확인 시 `stock_master.sector`를 수동 UPDATE 후 재확인 — 아래 §7 참조).
2. **`market_summary_daily` 발행 지연/캘린더 미확인/서비스 불가 3종 에러 코드가 실제 배치 미실행 상태(신규 서비스 최초 배치 실패)에서 프론트 EmptyState로 정확히 이어지는지**는 이번 유닛에서 `current_published_batch` 포인터를 직접 삭제/복구하며 실측했다(§7 로그 참조) — 정상 동작 확인됨. 다만 실제 신규 서비스 최초 배치 실패 시나리오(배치가 단 한 번도 성공한 적 없는 상태)는 별도로 재확인할 가치가 있다(현재는 "한 번 발행된 뒤 포인터만 지운" 상태로 흉내냈을 뿐).
3. **실 서비스키 기반 Ingestion Batch가 아직 검증되지 않아(UNIT-02 승계 리스크)**, `raw_ohlcv.trading_value`가 실제 공공데이터포털 응답 필드와 정확히 매핑되는지는 이번에도 실측하지 못했다(§2-2 v3 확정 사항 — 단위는 KRW로 이미 확정되어 있으나 실 API 응답 검증은 여전히 UNIT-02의 미해결 범위).

---

## 4. 인수 조건 (Acceptance Criteria) — 6단계 테스터용

**AC-1 (Derivation Batch, REQ-004 핵심 로직)**
- `compute_market_summary()`가 `return_pct`가 `None`인 종목을 상승/하락/보합 어디에도 포함하지 않는다.
- `sector=None`인 종목은 `top_sectors_by_value` 집계에서 제외되지만 `total_trading_value_krw`에는 포함된다.
- `top_sectors_by_value`는 거래대금 내림차순 최대 5개만 반환한다.
- `build_market_summary_inputs()`가 만드는 `ALL` 입력은 KOSPI/KOSDAQ 결과의 사후 합산이 아니라 전체 종목 목록을 독립적으로 재집계한 결과다(코드 경로상 `compute_market_summary()`가 KOSPI/KOSDAQ/ALL 세 번 독립 호출됨 — `run_derivation.py`의 `market_subsets` 순회 확인).
- 원본 시세 종목당 거래대금이 있는데 `trading_value_by_code`에 없는 종목(데이터 정합성 이상)은 조용히 0 대체되지 않고 집계에서 제외된다.

**AC-2 (Public API — `GET /api/v1/market-summary`)**
- `market` 생략 시 기본값 `ALL`이며 응답에 `by_market`(KOSPI/KOSDAQ) 배열이 포함된다.
- `market=KOSPI`/`KOSDAQ` 명시 요청 시 해당 시장 객체만 반환되고 `by_market`은 `null`이다(필드 자체는 존재 — §2 편차 항목2 참조).
- `market=NASDAQ` 등 허용값 외 요청은 400 `INVALID_PARAMETER`.
- 캘린더 미확인 시 424 `CALENDAR_NOT_CONFIRMED`, 발행된 데이터가 없으면 503 `DATA_PIPELINE_STALE`.
- 발행 포인터는 있는데 해당 (trade_date, market)의 `market_summary_daily` 행이 없으면 503 `SERVICE_UNAVAILABLE`(0으로 대체하지 않음).
- 원본 시세 필드(open/high/low/close/volume)나 원본 거래대금(`trading_value`)이 응답 어디에도 존재하지 않는다(§4-3).
- 사용자 식별 파라미터(`user_id` 등)가 없고, 동일 쿼리에 다른 `Authorization`/쿠키를 붙여도 응답이 동일하다(REQ-009 — UNIT-04가 확립한 블랙박스 검증 패턴 재사용 권장).

**AC-3 (프론트엔드 — 홈 화면)**
- `/`가 `next build` 결과에서 정적(`○ Static`)이 아니라 동적(`ƒ Dynamic`)으로 분류된다 — `export const dynamic = "force-dynamic"` 없이는 이 Next.js 버전에서 빌드 시점 스냅샷으로 굳어짐을 실측했다(§7 로그 참조, 회귀 시 반드시 재확인 필요).
- 정상 응답 시 `DataFreshnessBadge`, `StatSummaryGrid`(전체+코스피+코스닥 3장), `SectorSummaryList`, 진입 카드 2개(조건 스크리닝/종목 검색)가 렌더링된다.
- `top_sectors_by_value`가 빈 배열이면 `SectorSummaryList`가 "업종 정보를 준비 중입니다"를 표시한다(막대 리스트 대신).
- `is_latest_trading_day=false`이면 배지 아래 지연 경고가 표시된다.
- 424/503(DATA_PIPELINE_STALE)/네트워크 오류 시 각각 `ErrorState(calendar-not-confirmed)`/`EmptyState(no-data-yet)`/`ErrorState(network)`로 전체 콘텐츠가 대체된다.
- 면책 배너(REQ-007)·`GlobalNav`(REQ-013)는 UNIT-04/05의 공통 레이아웃을 그대로 상속하며 이 화면에서 별도 구현/우회가 없다.
- 헤딩 구조가 `h1`(페이지 제목) → `h2`(요약 카드 3장 각각의 제목 + 업종 섹션 제목) 순으로 건너뜀 없이 이어진다.

---

## 5. 게이트 1 — 정적 분석/린트 결과

이 프로젝트는 정적 분석/린트 설정이 **있다** (건너뛰지 않음).

- 백엔드: `python -m ruff check .` → `All checks passed!`
- 백엔드: `python -m pytest tests/unit -q` → `127 passed`(신규 실패 없음, 회귀 없음 — 이번 유닛은 신규 테스트 파일을 추가하지 않았다. 단위테스트 작성은 6단계 책임이며, 5단계는 로컬 최소 동작 확인만 수행했다. 아래 §7 참조).
- 프론트엔드: `npx tsc --noEmit` → 오류 없음.
- 프론트엔드: `npm run lint`(eslint) → 오류 없음.
- 프론트엔드: `npm run build`(prebuild 금지어 린트 포함) → "금지표현 검사 통과 (검사 파일 43개)" + 빌드 성공.

---

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — §2에 편차 5건을 사유와 함께 기록했고, 나머지는 03/04단계 문서를 그대로 따랐다(엔드포인트 파라미터/에러코드/응답 필드명, `market_summary_daily` 스키마, `StatSummaryGrid`/`SectorSummaryList`/`EmptyState`/`ErrorState`/`DataFreshnessBadge` 재사용 등).
- [x] **에러 처리가 누락된 경로가 없는가** — 400/424/503(DATA_PIPELINE_STALE)/503(SERVICE_UNAVAILABLE, 캘린더 이상 및 신규: 요약 행 정합성 이상) 4갈래 모두 코드로 구현하고 실제 HTTP 요청으로 재현 확인(§7). 예외를 삼키는 `except: pass`류 코드 없음(`ruff` B 규칙 통과로도 교차 확인).
- [x] **입력값 검증이 시스템 경계에서 이뤄지는가** — `market` 쿼리 파라미터는 FastAPI `Query` + 화이트리스트(`VALID_LISTED_MARKET_FILTERS`) 검증, `date`는 Pydantic 타입 강제(`date_type`, 잘못된 형식은 자동 400). 프론트엔드는 사용자 입력을 받지 않는 화면(홈)이라 별도 입력 검증 대상이 없다.
- [x] **하드코딩된 시크릿/자격증명이 없는가** — 코드에 시크릿 없음. 로컬 검증 중 만든 `.env`(임시 DB 비밀번호)는 검증 완료 후 삭제했고(`git status` 확인, 애초에 `.gitignore`에 이미 등록되어 있었음), 어떤 커밋에도 포함되지 않았다.
- [x] **신규 외부 의존성이 있다면 실존 여부를 확인했는가** — 신규 패키지 의존성 추가 없음(기존 SQLAlchemy/FastAPI/Pydantic만 사용, `postgresql.JSONB`도 SQLAlchemy 내장).
- [x] **범위를 벗어난 변경이 섞여 있지 않은가** — `git status --porcelain` 결과가 이번 유닛 파일(REQ-004 관련 신규/수정)로만 구성됨을 확인. UNIT-06/07의 기존 파일 중 `services/derivation_batch/raw_models.py`(컬럼 1개 추가)만 최소 확장했고, 그 외 기존 로직/필드는 손대지 않았다(회귀 테스트 127건 전부 통과로 확인).

---

## 7. 로컬 동작 확인 요약 (실행 로그 근거)

Docker Desktop이 기동 중이었고 UNIT-01~07이 써온 로컬 PostgreSQL 컨테이너(`stock-screener-db`)가 이미 살아있어(다른 프로젝트 세션이 준비해 둔 것), 이를 그대로 재사용해 **실제 PostgreSQL로 최소 동작 확인을 수행했다**(전면 검증은 6단계 책임).

1. **마이그레이션**: `alembic upgrade head`(0009 적용) → `\d public_serving.market_summary_daily`로 컬럼/PK/FK 확인, `information_schema.role_table_grants`로 GRANT(`batch_worker`: SELECT/INSERT/UPDATE, `api_service`: SELECT) 확인. `alembic downgrade 0008` → `upgrade head` 왕복도 재현해 스키마+ENUM+GRANT가 마이그레이션 자체의 동작임을 확인(DEF-003 교훈 준수).
2. **Derivation Batch 종단간**: UNIT-06이 만든 `scripts/dev_seed_fixture_metrics.py`(KOSPI 종목 2개, KOSDAQ 0개 픽스처)로 시딩 후 `python -m services.derivation_batch.run_derivation --trade-date 2026-09-14` 실행 → `status=SUCCESS`. `market_summary_daily`를 직접 조회해 KOSPI(상승1/하락1/보합0/총거래대금 5,418,400,000,000원), KOSDAQ(전부 0), ALL(KOSPI와 동일값이지만 독립 재집계 경로로 계산됨)을 확인. 총 거래대금 수치를 수동 계산(78,000원×60,000,000주 + 142,000원×5,200,000주 = 5,418,400,000,000원)과 대조해 정확히 일치함을 확인했다.
3. **Public API 종단간**: `uvicorn services.public_api.main:app`을 실 DB에 연결해 기동 후 `curl`로 `/api/v1/market-summary`(생략=ALL, `by_market` 포함)와 `?market=KOSPI`(단일 객체, `by_market: null`) 양쪽 응답을 실측 확인. `current_published_batch`의 KRX 행을 일시 삭제해 503 `DATA_PIPELINE_STALE`을 재현한 뒤 원상복구, 재복구 후 정상 응답 재확인.
4. **프론트엔드 종단간**: `npm run build && npm run start`로 실제 프로덕션 빌드를 실 백엔드에 연결해 홈 화면 렌더링 결과(HTML)를 curl로 직접 확인 — 배너/스킵링크/GlobalNav/`h1`/`DataFreshnessBadge`(지연 경고 포함, 실제로 3영업일 지연 상태였음)/`StatSummaryGrid` 3장(수치 일치)/`SectorSummaryList`의 "업종 정보를 준비 중입니다"(sector가 전부 `null`이므로)/진입 카드 2개까지 전부 확인. `NEXT_PUBLIC_API_BASE_URL`을 존재하지 않는 포트로 바꿔 네트워크 오류 → `ErrorState(network)` 렌더링도 확인. `current_published_batch` 삭제 상태에서 `EmptyState(no-data-yet)` 렌더링도 확인.
5. **`next build` 정적/동적 분류 실측**: 최초 구현 시 `/`가 `○ Static`으로 분류되는 것을 직접 발견했다 — `cache: "no-store"` fetch만으로는 이 Next.js 버전(`frontend/AGENTS.md` 경고대로 관행과 다름)에서 라우트가 동적으로 전환되지 않고, Request-time API가 없으면 빌드 시점 스냅샷이 굳어진다는 것을 `node_modules/next/dist/docs/01-app/02-guides/caching-without-cache-components.md`로 확인했다. `export const dynamic = "force-dynamic"`을 추가해 `ƒ Dynamic`으로 전환됨을 재빌드로 확인했다 — 이 확인이 없었다면 배치가 갱신돼도 홈 화면이 최초 빌드 시점 데이터로 영구 고정되는 실사용 결함으로 이어졌을 것이다.
6. **회귀**: `pytest tests/unit -q`(127 passed), `ruff check .`, `tsc --noEmit`, `npm run lint`, `npm run build` 전부 최종적으로 통과 재확인.

**정리(Teardown)**: 로컬 검증에 사용한 DB 롤 비밀번호(`localdevpass`, 로컬 Docker 전용, 외부 노출 없음)와 `.env`/`frontend/.env.local`(둘 다 `.gitignore` 등록 대상)은 검증 종료 후 삭제했다. `market_summary_daily`/`derived_metrics_daily`/`current_published_batch`에 남은 테스트 픽스처 데이터(`005930`/`000660`)는 UNIT-06 스크립트 docstring이 이미 문서화한 정리 SQL(`TRUNCATE ...`)로 정리하려 했으나, 이번 세션의 실행 환경 정책(파괴적 로컬 작업에 대한 자동 승인 거부)에 막혀 **직접 삭제하지 못했다**. 이 데이터는 로컬 Docker 전용 비운영 합성 픽스처이며 실제 서비스 데이터나 커밋된 코드에는 전혀 영향이 없다(스키마/코드는 git으로 추적되고 이 DB 컨테이너는 로컬 검증 전용). 6단계 또는 운영자가 필요 시 아래 SQL로 정리할 수 있다:
```sql
TRUNCATE public_serving.market_summary_daily, public_serving.derived_metrics_daily, public_serving.current_published_batch CASCADE;
DELETE FROM raw_internal.raw_ohlcv WHERE stock_code IN ('005930','000660');
DELETE FROM raw_internal.raw_fundamentals WHERE stock_code IN ('005930','000660');
DELETE FROM public_serving.stock_master WHERE stock_code IN ('005930','000660');
DELETE FROM public_serving.batch_run WHERE run_type IN ('ingest','derive');
```

---

## 8. 접근성 사전 점검 (04-ux-design.md §5, 규칙 A/오케스트레이터 지시 대응)

UNIT-07이 겪은 `useFocusTrap` 결함(DEF-U07-01)이 이번 유닛에서 재발하지 않는지 스스로 점검했다.

- **이 화면에는 포커스 트랩이 필요한 인터랙티브 요소가 없다.** §2 편차 항목1에서 서술한 대로 "탭 또는 병기 카드" 중 병기 카드(정적 나열)를 택해, 모달/바텀시트/탭 전환 등 포커스를 가두거나 이동시켜야 하는 컴포넌트를 이번 화면에 전혀 도입하지 않았다. `useFocusTrap`(UNIT-07이 만든 훅)을 이 유닛은 import조차 하지 않는다(`git grep useFocusTrap frontend/src/app/page.tsx frontend/src/components/StatSummaryGrid.tsx frontend/src/components/SectorSummaryList.tsx` → 매치 없음, 직접 확인).
- 유일한 인터랙티브 요소는 표준 `<Link>`(진입 카드 2개, `/screener`·`/stocks`)로, 기존 `a:focus-visible` 전역 스타일(포커스 링)이 그대로 적용되며 별도 JS 포커스 관리가 없다.
- 헤딩 계층(`h1`→`h2`)이 건너뛰지 않음을 실제 렌더링 HTML로 확인(§7-4).
- 색상 단독 의존 금지(§3-1): 상승/하락 카운트는 `+`/`-` 부호와 함께 `<dt>`에 "상승 종목 수"/"하락 종목 수" 텍스트 라벨이 항상 인접해 있어(`ValuationMetricCard.tsx`와 동일한 dt/dd 패턴), 색상 없이도 의미가 전달된다.
- 표(`<table>`)를 새로 도입하지 않아 §5-7 표 시맨틱 요구사항은 해당 사항 없음.
- 결론: 이번 유닛은 헤드리스 브라우저(Puppeteer/CDP) 실측이 필요한 인터랙션 자체가 존재하지 않는다고 판단해 별도로 수행하지 않았다 — 판단 근거는 위 코드 검색 결과(`useFocusTrap` 미사용)와 실제 렌더링 HTML(§7-4)로 남긴다. 6단계가 이 판단에 동의하지 않으면(예: 향후 이 화면에 인터랙션이 추가될 경우) 재검토가 필요하다.

---

## 9. 다음 단계

6단계(단위테스트)가 이 유닛을 독립적으로 재검증해야 한다. 특히:
- 5단계의 로컬 확인(§7)을 신뢰하지 말고 독립 재현할 것(이 저장소의 기존 관행).
- `compute_market_summary()`/`build_market_summary_inputs()`의 경계 조건(전 종목 결측, 동일 거래대금 동률, 6개 이상 업종 존재 시 상위 5개 절단 등)을 픽스처로 직접 검증할 것 — 이번 유닛은 실 DB로 "정상 케이스 1개"만 확인했고 순수 함수 단위테스트는 6단계 몫으로 남겨뒀다.
- `market=KOSPI`/`KOSDAQ` 단일 조회 시 `by_market: null` 표현이 §2 편차 항목2의 판단대로 실사용에 문제가 없는지(현재 소비자는 홈 화면뿐이며 항상 `ALL` 호출) 재확인할 것.
- §3의 "수동 확인 필요" 3건(업종 정상 표시 상태, 신규 서비스 최초 배치 실패, 실 API `trading_value` 필드 매핑)을 인지하고 필요 시 별도 이슈로 인계할 것.
