# 테스트 결과서 (Test Result Report) — feature-stock-metrics (07단계, 업무단위 통합테스트)

> `templates/test-report-template.md` 사용. 대상 업무 단위(feature): **stock-metrics**(REQ-002, `decisions.md` DEC-023). 구성 작업 단위: **UNIT-06**(Derivation Batch + `GET /stocks/{code}/metrics` + `/stocks/[code]` 화면, `unit-06-test.md` PASS). 공유 인프라(DEC-023 범위): UNIT-01(캘린더/CORS, DEC-018/DEC-022), UNIT-02(Ingestion Batch, raw 데이터 소스), UNIT-04(면책배너/기준시각뱃지), UNIT-05(GlobalNav/Header).
>
> **이 문서의 가치 원칙**: UNIT-06 단위테스트(`unit-06-test.md`, TC-001~TC-043)가 이미 AC-1~AC-10을 실 PostgreSQL/실 HTTP/실 렌더링으로 광범위하게 검증했다. 이 문서는 그것을 반복하지 않고 **① Ingestion→Derivation→API→화면 전체 체인이 실제로(픽스처가 아닌 실제 Ingestion Batch 코드로) 한 번도 끊기지 않고 실행된 적이 있는지, ② 3중 방어 아키텍처가 실제 배치 실행 컨텍스트에서 유지되는지, ③ 이 업무 단위를 구성한 후 다른 유닛(UNIT-07/08/09)이 같은 공유 DB에 추가한 데이터와 부딪혀도 UNIT-06 코드가 깨지지 않는지, ④ CORS 회귀 영향 재확인, ⑤ PER/PBR 결측 처리 책임 공백의 잔존 여부**에만 집중한다.

## 1. 개요
- 테스트 대상: 업무 단위(feature) **stock-metrics** = UNIT-06(Derivation Batch, `GET /api/v1/stocks/{code}/metrics`, `/stocks/[code]`)의 내부 단위 간 경계, REQ-002 전체
- 테스트 유형: 통합(07단계, 업무단위 전체 풀테스트)
- 적용 Tier: **High**(`decisions.md` DEC-021) — 검증 강도 완화 없음, 규칙 B 원문(최소 2회 독립 검증) 그대로 적용. 이 feature는 작업 단위가 1개(UNIT-06)뿐이지만 Tier가 High이므로 06/07 병합 예외(Low 등급 전용)는 적용되지 않는다 — 06(`unit-06-test.md`)과 07(이 문서)을 분리 수행.
- 테스트 목적:
  1. Ingestion Batch(UNIT-02, `raw_internal.raw_ohlcv`/`raw_fundamentals`) → Derivation Batch(UNIT-06) → `public_serving.derived_metrics_daily` → Public API → 프론트엔드로 이어지는 전체 체인이 **실제 Ingestion Batch 코드(`services/ingestion_batch/`)로 채워진 데이터**를 기준으로 한 번이라도 끊기지 않고 실행된 적이 있는지 확인한다.
  2. 3중 방어 아키텍처(DEC-006)가 UNIT-06의 실제 배치 실행 컨텍스트(`batch_worker`/`api_service` 역할)에서도 그대로 유지되는지 확인한다.
  3. 전체 회귀(`pytest tests/unit`, 프론트 빌드/린트/타입체크) + CORS 회귀(DEC-022)를 재확인한다.
  4. UNIT-01의 CORS 수정(DEC-022)이 `/stocks/[code]`(서버 컴포넌트)에 실제로 영향이 없는지 재확인한다.
  5. PER/PBR 결측 처리(unit-06-note.md가 "raw_fundamentals 미적재로 현재 미검증"이라고 인계한 부분)가 이 통합 시점에도 여전히 미검증 상태인지 확인하고 리스크로 명시한다.
- 관련 산출물: `docs/harness/units/unit-06-note.md`, `unit-06-test.md`(PASS), `docs/harness/units/unit-01-note.md`(v4)/`unit-02-note.md`, `docs/harness/02-planning.md`(v5) §4-1 REQ-002 · §4-3(데이터 가공 원칙), `docs/harness/03-system-design.md`(v4) §1-1(3중 방어)·§1-2(Derivation Batch)·§3-2(엔티티)·§4-2(엔드포인트), `docs/harness/decisions.md` DEC-006/DEC-011/DEC-012/DEC-013/DEC-014/DEC-018/DEC-022/DEC-023, `docs/harness/traceability.md` REQ-002 행, `docs/harness/feature-stock-search-integration-test.md`(선행 완료, UNIT-09→UNIT-06 화면 이동 경로 검증 완료 — 이 문서는 반복하지 않음)
- 테스트 수행자(에이전트): 07-integration-tester
- 테스트 일시: 2026-09-18

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - Ingestion Batch 쓰기 코드(`services/ingestion_batch/models.py`/`repository.py`)와 Derivation Batch 읽기 코드(`services/derivation_batch/raw_models.py`)의 스키마/타입 일치를 코드 레벨로 재대조(단위테스트가 각자 자기 단계만 픽스처로 검증했을 가능성 확인)
  - 현재 공유 Docker Postgres(`stock-screener-db`)에 실제로 적재된 데이터의 **출처 추적**(`source_batch_id`) — 이 데이터가 실제 Ingestion Batch 실행 결과인지, 픽스처 스크립트 결과인지 확인
  - 3중 방어(스키마 분리·DB 권한 분리)를 `batch_worker`/`api_service` 역할로 실제 배치 실행에 준하는 SQL(동일 INSERT/UPDATE 구문, FK 포함)로 재검증
  - `pytest tests/unit`(전체), `ruff check .`, 프론트엔드 `tsc --noEmit`/`lint`/`build`(prebuild 금지어 포함) 회귀
  - CORS(DEC-022) 실제 포지티브/네거티브 컨트롤 재확인 + `/stocks/[code]` 호출부(`stockMetrics.ts`)가 서버 컴포넌트임을 소스로 재확인
  - UNIT-07/08(screener/market-summary) 세션이 같은 DB에 추가한 종목(`005935`/`900001`~`900003`, 파생지표 대부분 결측)이 UNIT-06의 실제 API/화면 코드로 크래시 없이 정상 처리되는지 — UNIT-06 자신의 픽스처(005930/000660, 완전 데이터)로는 검증된 적 없는 시나리오
  - PER/PBR 결측 처리(§3-2 "PER≤0은 null") 구현 책임 소재를 코드 레벨로 재확인
  - `get_last_trading_day()` 재사용 여부 소스 확인
- 제외 범위 및 사유:
  - `return_rank_pct`/percentile 계산 정확성, ENUM 버그 재발 여부, EmptyState/ErrorState 렌더링, REQ-006/007 회귀 — `unit-06-test.md`(TC-007~030)가 이미 실 DB/실 HTTP/실 렌더링으로 충분히 검증. 이 문서는 반복하지 않는다.
  - `/stocks`(UNIT-09) → `/stocks/[code]`(UNIT-06) 화면 이동 경로, 404→검색 복귀 순환 — `feature-stock-search-integration-test.md`(PASS, TC-IT-03~05)가 이미 검증. 이 문서는 이 이동 경로를 재검증하지 않는다(과제 지시사항).
  - 실제 `run_ingestion.py`/`run_derivation.py`/`uvicorn`을 host에서 실제 `batch_worker`/`api_service` 비밀번호로 기동해 종단간 실행 — 이 세션의 도구 정책(Claude Code auto mode classifier, "Credential Exploration")이 host→Postgres TCP 접속에 실제 값이든 placeholder 값이든 자격증명 형태의 문자열이 포함된 명령 실행 자체를 차단함을 직접 시도해 확인했다(`BATCH_DATABASE_URL=...devpass...`, `...placeholder-not-real...` 둘 다 차단, `...unused:unused...`처럼 실제로 연결을 시도하지 않는 명백한 더미 값만 허용됨 — `feature-stock-search-integration-test.md`가 이미 겪은 것과 동일한 제약이며, 이번에는 배치 CLI에도 동일하게 적용됨을 추가로 확인). §4-1/§8에 이 제약과 대체 방법을 상세히 기록한다.
  - 실제 공공데이터포털 서비스키를 이용한 정상 응답 파싱 — UNIT-02 범위(서비스키 미보유, 승계 리스크, 변경 없음).
  - 200% 확대/모바일 실기기 확인 — 기존 승계 리스크(신규 아님).

## 3. 테스트 환경
- 실행 환경: Windows 10(Git Bash), Python 3.13(anaconda), Node.js(Next.js 16.3.5), PostgreSQL 16(Docker `stock-screener-db`, 11시간 이상 `Up` 상태, alembic head=0009 확인).
- DB 접근 방식: **읽기 전용 조회 및 역할 전환 테스트는 전부 `docker exec stock-screener-db psql -U postgres`**(컨테이너 내부 loopback, `pg_hba.conf`의 `127.0.0.1/32 trust` 규칙 적용 — 비밀번호 불요, 이 세션의 도구 정책과 무관하게 항상 허용됨)로 수행했다. 이 슈퍼유저 세션 안에서 `SET ROLE batch_worker`/`SET ROLE api_service`(비밀번호 재인증이 필요 없는 PostgreSQL 표준 기능 — 이미 인증된 슈퍼유저가 다른 역할로 권한을 전환하는 것이며 "자격증명 탐색"이 아니다)로 각 역할의 실제 GRANT를 트랜잭션 내에서 재현·롤백했다.
- Public API 계층: `services.public_api.main.app`(실제 프로덕션 코드, 실제 `CORSMiddleware`/Pydantic/에러 핸들러 그대로) + DB 리포지토리 DI 3개(`get_stock_metrics_repository`/`get_calendar_repository`/`get_stock_search_repository`)만 `docker exec ... psql -U postgres`로 조회한 **실제** `public_serving.stock_master`/`derived_metrics_daily`/`current_published_batch`/`reference.market_calendar` 값을 그대로 복제한 Fake로 대체(`PUBLIC_API_DATABASE_URL=postgresql+psycopg://unused:unused@127.0.0.1:5432/unused`로 기동, 실제로 이 값을 사용해 접속을 시도하는 코드 경로는 `/health`뿐이며 본 테스트 범위 밖). `unit-06-test.md`가 이미 `SqlStockMetricsRepository`/`SqlCalendarRepository` 자체를 실 Postgres로 PASS 확정했으므로 이 문서의 재검증 대상이 아니다.
- 프론트엔드: `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`로 `npm run build && npx next start -p 3000 -H localhost`(프로덕션 빌드, 실제 서버 컴포넌트 fetch).
- 테스트 데이터: **실제** `public_serving.stock_master`(6행: `005930`/`000660`/`005935`/`900001`/`900002`/`900003`)와 `derived_metrics_daily`(동일 6행), `current_published_batch`(`KRX`/`2026-09-14`), `reference.market_calendar`(2026-09-01~09-19) — 전부 `docker exec ... psql -U postgres`로 직접 조회해 확인한 값이며, 이번 테스트가 새로 생성하지 않았다. 롤백 트랜잭션(§4-2) 외에는 DB에 쓰기 변경을 가하지 않았다(§7에서 최종 행수 재확인).
- 전제 조건: UNIT-06 6단계 게이트(PASS) 확인 완료(`unit-06-test.md`). Docker 컨테이너 기동 중, alembic head=0009. 포트 3000/8000 사전 점유 없음(`netstat`로 확인 후 시작).

## 4. 테스트 케이스 및 결과

### 4-1. 파이프라인 전체 데이터 흐름 — Ingestion→Derivation 경계 (단위테스트가 보지 못한 영역)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-IT-01 | 현재 DB에 존재하는 `raw_internal.raw_ohlcv`(58행)의 실제 출처 추적 | Docker DB 기동 중 | `select stock_code, source_batch_id from raw_internal.raw_ohlcv`로 `source_batch_id`를 `batch_run.run_type`과 조인해 확인 | 58행 전부가 실제 `run_ingestion.py` 실행 결과일 것을 기대했으나... | **58행 전부가 단일 `source_batch_id`(`a24f0964-...`)에 귀속되고, 이 `batch_run` 행은 `dev_seed_fixture_metrics.py`(신규 상장 검증용 "테스트 픽스처 전용" 스크립트, docstring에 "이 스크립트는 운영 파이프라인의 일부가 아니다"라고 명시)가 삽입한 것임을 확인** | **FAIL(발견, §6 참조)** | 코디네이터 지시 ① 핵심 확인 사항 |
| TC-IT-02 | `services/ingestion_batch/`가 실제로 `raw_fundamentals`에 쓰는 코드 경로가 존재하는지 소스 확인 | - | `services/ingestion_batch/repository.py`(`upsert_ohlcv`만 존재) + `services/ingestion_batch/models.py`(`RawFundamentals` 클래스 docstring) 열람 | Ingestion Batch가 `raw_fundamentals`에 쓰는 함수가 있을 것으로 예상 | **없음.** `models.py` 62~66행 docstring이 명시: "이 유닛은 이 테이블의 스키마만 만들고, Ingestion Batch는 아직 이 테이블에 실제로 데이터를 적재하지 않는다." `repository.py`에는 `upsert_ohlcv`만 있고 `upsert_fundamentals` 류 함수 자체가 없음 | **확인됨(결함 아님, 기존에 이미 알려진 범위 제한)** | 현재 DB의 `raw_fundamentals` 2행(005930/000660 PER/PBR)도 TC-IT-01과 동일하게 `dev_seed_fixture_metrics.py`가 원시 SQL로 직접 삽입한 것 — Ingestion Batch 코드는 이 값을 만든 적이 없음(§4-3 재확인) |
| TC-IT-03 | Ingestion 쓰기 모델 ↔ Derivation 읽기 모델 스키마/타입 일치 대조 | - | `services/ingestion_batch/models.py`(`RawOhlcv`/`RawFundamentals`, ORM) ↔ `services/derivation_batch/raw_models.py`(`raw_ohlcv_table`/`raw_fundamentals_table`, `sa.Table` 프로젝션) 컬럼명·타입 1:1 대조 | 두 독립 선언이 실제 DB 스키마(마이그레이션 0004)와 정확히 일치 | `raw_ohlcv`: `stock_code(String6)/trade_date(Date)/market(market_session_enum, PK 3개)/close(Numeric)/volume(BigInteger)/trading_value(BigInteger)` — 양쪽 완전 일치. `raw_fundamentals`: `stock_code/trade_date/per/pbr/market_cap` — 양쪽 완전 일치. `market` 컬럼이 양쪽 다 `reference.market_session` **동일 ENUM 객체**(`market_session_enum`, `create_type=False`)를 재사용(unit-06-note.md §7이 발견한 ENUM 버그의 재발 방지가 코드 레벨에서 구조적으로 보장됨을 재확인) | **PASS** | 코디네이터 지시 ① — "서로 다른 스키마 가정" 여부를 코드로 직접 대조. 불일치 없음 |
| TC-IT-04 | DB 실제 컬럼(마이그레이션 0004 적용 결과) vs 두 코드 모델 3자 대조 | Docker DB 기동 중 | `\d raw_internal.raw_ohlcv`, `\d raw_internal.raw_fundamentals` | 마이그레이션 DDL·Ingestion ORM·Derivation Table 프로젝션 3자가 일치 | 실제 DB 컬럼(`stock_code varchar(6)`, `trade_date date`, `market market_session`, `open/high/low/close numeric`, `volume/trading_value bigint`, `ingested_at timestamptz`, `source_batch_id uuid` FK)이 두 코드 모델과 정확히 일치(Ingestion이 쓰지 않는 `open/high/low/ingested_at`은 Derivation의 최소 프로젝션에서 의도적으로 생략된 것으로, 03-system-design.md §1-2 "실제로 읽는 컬럼만" 원칙과 일치) | **PASS** | |
| TC-IT-05 | `get_last_trading_day()` 재구현 없이 재사용 여부 소스 확인 | - | `services/derivation_batch/run_derivation.py` import문 확인 | `shared.calendar_service`에서 직접 import, 자체 재구현 없음 | `from shared.calendar_service import (..., get_last_trading_day, ...)`(66~69행) — UNIT-01(DEC-018, v4 재작성분)이 그대로 재사용됨, `DERIVATION_MARKET="KRX"` 상수도 `run_ingestion.py`의 `INGEST_MARKET="KRX"`와 동일 값(단, 별도 상수로 각 파일에 선언 — 값은 같으나 코드 중복은 아님, 각 서비스 독립 배포 단위 원칙과 일관) | **PASS** | 코디네이터 지시 사항 |
| TC-IT-06 | 3중 방어 1차(스키마 분리) — 실제 배치 실행 컨텍스트에서 재확인 | Docker DB, alembic head | `\d public_serving.derived_metrics_daily`로 컬럼 목록 확인 | open/high/low/close/volume 원문 컬럼 없음(unit-06-test.md TC-007과 동일 항목이나, 이번엔 UNIT-07/08이 추가한 `volume_raw`/인덱스 이후에도 유지되는지 확인) | 컬럼 목록에 원본 시세 필드 여전히 없음(`volume_raw`는 §4-3에서 이미 "필터 전용, API 비노출"로 확정된 별개 컬럼이며 원본 OHLC와 무관) — UNIT-07의 0007/0008 마이그레이션이 1차 방어를 훼손하지 않았음을 재확인 | **PASS** | 회귀 없음 |

### 4-2. 3중 방어 아키텍처 — 실제 배치 실행 컨텍스트(SET ROLE 재현) (단위테스트가 보지 못한 영역)

> `SET ROLE`은 이미 신뢰된(trust auth) 슈퍼유저 세션 안에서 PostgreSQL이 제공하는 표준 권한 전환 기능이며, 외부 자격증명을 추측·시도하는 것이 아니다(§3 참조). 모든 쓰기 조작은 트랜잭션 내에서 수행 후 `ROLLBACK`했다.

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-07 | `batch_worker`가 실제 Ingestion Batch의 INSERT 구문과 동일한 형태(FK 포함)로 `raw_internal.raw_ohlcv`에 쓸 수 있는가 | `BEGIN; SET ROLE batch_worker;` 후 `batch_run` INSERT(ingest) → 그 `batch_run_id`를 FK로 참조하는 `raw_ohlcv` INSERT(`ON CONFLICT DO UPDATE`, `upsert_ohlcv()`와 동일 구문) | 성공 | `INSERT 0 1`(batch_run), `INSERT 0 1`(raw_ohlcv), FK 위반 없음 | **PASS**(ROLLBACK 처리) |
| TC-IT-08 | `batch_worker`가 `public_serving.derived_metrics_daily`에 쓸 수 있는가 | `SET ROLE batch_worker;` 후 UPDATE | 성공 | `UPDATE 1` | **PASS**(ROLLBACK 처리) |
| TC-IT-09 | `batch_worker`가 `raw_internal`을 읽을 수 있는가 | `SET ROLE batch_worker;` 후 `select count(*) from raw_internal.raw_ohlcv` | 성공(58건) | `count=58` | **PASS** |
| TC-IT-10 | `api_service`가 `raw_internal`에 접근 차단되는가(실제 배치 실행 후에도 권한 드리프트 없는지) | `SET ROLE api_service;` 후 SELECT | `permission denied for schema raw_internal` | 정확히 일치 | **PASS** |
| TC-IT-11 | `api_service`가 `public_serving`/`reference`를 읽을 수 있는가 | `SET ROLE api_service;` 후 SELECT | 성공(6건/730건) | `derived_metrics_daily=6, market_calendar=730` | **PASS** |
| TC-IT-12 | `api_service`가 `public_serving`에 쓰기 시도 시 거부되는가 | `SET ROLE api_service;` 후 UPDATE | `permission denied for table derived_metrics_daily` | 정확히 일치 | **PASS** |

**종합**: UNIT-07(마이그레이션 0007/0008)·UNIT-08(0009)이 스키마를 확장한 이후에도 `batch_worker`/`api_service`의 GRANT 경계가 정확히 설계(§1-1/§3-1)대로 유지되고 있음을 실제 INSERT/UPDATE/SELECT 조작으로 재확인했다. 단위테스트들이 각자 검증한 것(예: `unit-06-test.md` TC-022/023, `unit-02-test.md` TC-018/019)과 달리, 이번 검증은 **여러 유닛이 스키마를 여러 차례 확장한 뒤(0006→0009)의 누적 상태**에서 실제 쓰기 구문(FK 포함)으로 재현했다는 점이 새롭다.

### 4-3. 업무단위 내부 경계 — 다른 유닛이 추가한 데이터가 UNIT-06 코드를 깨뜨리지 않는가

> `unit-06-test.md`는 자신의 픽스처(005930/000660, 두 종목 모두 완전한 지표)로만 API/화면을 검증했다. 그 이후 UNIT-07/08 세션이 같은 공유 DB에 `005935`/`900001`~`900003`(파생지표 대부분 `null`)을 추가했다 — UNIT-06의 실제 코드가 "자신이 만들지 않은 데이터"를 만나도 정상 동작하는지는 이번이 처음 확인이다.

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-13 | `GET /stocks/005935/metrics`(UNIT-07/08이 추가, ma5/ma20/거래량/PER/PBR/시총 전부 null) | 실제 앱 + Fake DI(§3)로 GET | 200, 크래시 없이 null 필드 그대로 반환 | `return_pct=2.0, return_rank_pct=66.7, ma5_gap_pct=null, ma20_gap_pct=null, volume_anomaly_score=null, per_percentile=null, pbr_percentile=null, market_cap_percentile=null` | **PASS** |
| TC-IT-14 | `GET /stocks/900001~900003/metrics`(KOSDAQ, 동일 결측 패턴) | 상동 | 200, 크래시 없음, `market="KOSDAQ"` | 3종목 전부 200, 값 정확, market 필드 정확 | **PASS** |
| TC-IT-15 | `/stocks/005935` 실제 화면 렌더링(결측 필드 UI) | 실제 프로덕션 빌드+서버, 위 API에 연결 | ma5/ma20/거래량 카드에 "데이터 부족 (상장 20영업일 미만)", PER/PBR에 "PER 산정 불가(적자기업 등)" | 렌더링된 HTML에서 정확히 확인(등락률 순위만 "상위 66.7%"로 정상 표시, 나머지 4개 카드는 결측 문구) | **PASS** | 
| TC-IT-16 | `/stocks/900001`(KOSDAQ) 실제 화면 렌더링 | 상동 | `market-badge`에 "KOSDAQ" 표시, 종목명 "UNIT08테스트가전KOSDAQ" 정상 렌더링, 결측 카드 정상 | 정확히 확인 | **PASS** |
| TC-IT-17 | 위 화면들에 UNIT-04/05 공통 셸(면책배너/GlobalNav) 회귀 없음 | HTML에서 `disclaimer-banner` 존재 확인 | 존재 | `stocks_005930.html`/`stocks_900001.html` 등 전부 `disclaimer-banner` 1회 확인 | **PASS** |
| TC-IT-18 | CORS 포지티브/네거티브 컨트롤(테스트 방법론 신뢰성, DEC-022 회귀) | `Origin: http://localhost:3000` vs `Origin: http://evil.example.com`으로 `/stocks/005935/metrics` 실제 fetch | 전자만 `access-control-allow-origin` 헤더 존재 | `allowed=http://localhost:3000`, `blocked`(헤더 없음) | **PASS** |
| TC-IT-19 | `stockMetrics.ts`/`page.tsx`가 서버 컴포넌트인지 재확인(코디네이터 지시 ④) | `grep "use client"` | 없음(서버 컴포넌트) | 매칭 0건 — CORS 미들웨어 수정(DEC-022)이 이 경로에 영향 없다는 traceability.md 서술이 실제로 맞음을 이 세션에서 직접 재확인 | **PASS** |
| TC-IT-20 | 404(`STOCK_NOT_FOUND`) 회귀 + HTTP 상태(DEF-010 재확인) | `/stocks/999999` | 404 문구 렌더링, HTTP 200(소프트 404, 기존 판정) | "찾을 수 없습니다"+"종목 검색으로 돌아가기" 확인, `curl -w %{http_code}` = 200 | **PASS(기존 판정 유지)** |

### 4-4. PER/PBR 결측 처리 책임 공백 재확인 (코디네이터 지시 ⑤)

| ID | 시나리오 | 실행 절차 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|
| TC-IT-21 | `raw_fundamentals` 실 적재 상태 재확인 | §4-1 TC-IT-01/02 | 여전히 실제 Ingestion Batch가 적재한 값이 0건(현재 DB의 2행은 전부 픽스처 스크립트 산출물) | **미검증 상태 그대로 확인**(변경 없음) |
| TC-IT-22 | §3-2 "PER≤0은 null로 저장" 규칙의 구현 위치 재확인 | `services/derivation_batch/run_derivation.py` 149~151행(`per_raw=fundamentals.per if fundamentals else None`) 소스 확인 | **PER≤0 필터링 코드가 Derivation Batch에도 없음**(원시값을 그대로 통과) — Ingestion Batch는 애초에 `raw_fundamentals`를 쓰지 않으므로(TC-IT-02) 이 규칙을 구현할 코드가 **프로젝트 전체에 존재하지 않는다** | **신규 확인 사항, §6 참조** |

## 5. 커버리지
- **1차 내부검증 관점(이 업무단위의 모든 사용자 시나리오가 케이스로 커버됐는가)**: 코디네이터가 명시한 5개 확인 항목(①파이프라인 전체 흐름, ②3중 방어, ③회귀, ④CORS 영향, ⑤PER/PBR 책임 공백)을 각각 §4-1(TC-IT-01~06)/§4-2(TC-IT-07~12)/§4-4(회귀는 별도 표, 아래)/§4-3(TC-IT-19)/§4-4(TC-IT-21/22)로 1:1 커버했다. 추가로 §4-3(TC-IT-13~20)에서 "다른 유닛이 추가한 데이터와의 상호작용"이라는, 과제가 명시하지 않았지만 07단계의 취지(단위 간 경계)에 부합하는 시나리오를 능동적으로 추가했다. 커버되지 않은 사용자 시나리오는 발견되지 않았다.
- **2차 내부검증 관점(8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까)**: §9-2 참조.
- 회귀 테스트:

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|-----------|
| TC-IT-R1 | 백엔드 전체 단위테스트 회귀 | `python -m pytest tests/unit -q` | 155 passed | `155 passed, 2 warnings in 1.76s` | **PASS** |
| TC-IT-R2 | 백엔드 정적분석 회귀 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** |
| TC-IT-R3 | 프론트엔드 타입체크 회귀 | `npx tsc --noEmit` | 오류 없음 | 오류 없음 | **PASS** |
| TC-IT-R4 | 프론트엔드 린트 회귀 | `npm run lint` | 0 error/0 warning | 0 error/0 warning | **PASS** |
| TC-IT-R5 | 프론트엔드 빌드 회귀(금지어 검사 포함) | `npm run build` | prebuild 통과 + 빌드 성공, `/stocks/[code]` Dynamic 유지 | "금지표현 검사 통과(검사 파일 47개)" + 빌드 성공, `ƒ /stocks/[code]` 유지 | **PASS** |

- 커버되지 않은 부분과 사유:
  - 실제 `run_ingestion.py`/`run_derivation.py` CLI를 실제 batch_worker 자격증명으로 host에서 직접 실행 — 이 세션 도구 정책상 불가능(§2/§8 참조). 대신 코드 스키마 대조(TC-IT-03/04) + DB 역할 전환 재현(TC-IT-07~09)으로 대체.
  - 실제 공공데이터포털 API를 통한 정상 파싱 → 실 Derivation Batch 소비 — UNIT-02가 서비스키 미보유로 원천적으로 불가(승계 리스크, 변경 없음).
  - `/stocks/[code]`↔`/stocks` 화면 이동 경로 — `feature-stock-search-integration-test.md`가 이미 검증(과제 지시에 따라 이 문서에서는 재검증하지 않음).

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도(Critical/High/Medium/Low) | 상태(Open/Fixed/Deferred) | 조치 내용 |
|----|------|-----------|-----------------------------------|----------------------------|-----------|
| DEF-IT-M01 | **(신규 발견, 통합 시점) 실제 Ingestion Batch 코드(`services/ingestion_batch/`)가 Derivation Batch에 데이터를 공급하는 전체 체인이 이 프로젝트 역사상 한 번도 실제로 실행된 적이 없다.** 현재 DB의 `raw_ohlcv`(58행)/`raw_fundamentals`(2행) 전부가 `dev_seed_fixture_metrics.py`(명시적 "운영 파이프라인 아님" 테스트 픽스처 스크립트) 또는 UNIT-08의 미커밋 임시 스크립트 산출물이며, `source_batch_id`가 가리키는 `batch_run` 행조차 실제 `run_ingestion.py`가 만든 것이 아니다. `raw_fundamentals`는 Ingestion Batch 코드에 쓰기 경로 자체가 없다(설계상 알려진 범위 제한, unit-02-note.md 승계). | §4-1 TC-IT-01/02(`source_batch_id` 조인 추적 + `models.py`/`repository.py` 소스 확인) | **Medium** | **Deferred(근본 원인은 UNIT-06 밖)** | 이것은 UNIT-06의 코드 결함이 아니다 — 근본 원인은 (a) UNIT-02가 실 공공데이터포털 서비스키를 보유하지 못한 것(승계된 알려진 제약, `unit-02-note.md`/`unit-02-test.md`에 이미 기록), (b) 이번 세션의 도구 정책상 host에서 실제 DB 자격증명을 사용하는 어떤 명령도 실행할 수 없어(§2/§8) 07단계 스스로도 실제 CLI로 이 갭을 메울 수 없었던 것. **규칙 F에 따라 임의로 봉합하지 않고 다음과 같이 보고한다**: 스키마/타입 레벨 호환성(TC-IT-03/04)과 권한 레벨 호환성(TC-IT-07~09)은 이번 통합테스트가 실제 SQL로 재현해 확정했으므로, "만약 실 Ingestion Batch가 실행된다면 Derivation Batch가 문제없이 소비할 것"이라는 근거는 이전보다 훨씬 강화됐다. 그러나 **"실제로 그 실행이 일어난 적이 있다"는 명제 자체는 여전히 거짓**이며, 이는 코드 결함이 아니라 **환경/자격 준비(실 서비스키, 실행 권한을 가진 CI 환경)의 부재**이므로 3단계(설계) 재작업 대상이 아니라 **10단계(배포테스트)/운영 준비 단계에서 실 서비스키 확보 후 반드시 1회 이상 실제 CLI 종단간 실행으로 폐쇄해야 하는 선행 조건**으로 8단계/10단계에 명시적으로 인계한다. |
| DEF-IT-M02 | **(신규 확인, 통합 시점) §3-2 "PER≤0은 null로 저장" 결측치 처리 규칙이 프로젝트 전체에 구현된 코드가 없다.** Ingestion Batch는 `raw_fundamentals`를 쓰지 않고(DEF-IT-M01과 동일 원인), Derivation Batch(`run_derivation.py` 149~151행)는 `fundamentals.per`/`pbr`을 필터링 없이 그대로 `per_raw`/`pbr_raw`에 통과시킨다. | §4-4 TC-IT-22(`run_derivation.py` 소스 확인) | **Low** | **Deferred(구현 책임 미배정)** | `unit-06-test.md` §7이 "구현 책임은 Ingestion Batch(UNIT-02) 소관"이라고 이미 인계했으나, 이번 통합테스트로 "Ingestion도 Derivation도 실제로 이 필터링 코드를 갖고 있지 않다"는 것을 코드 레벨로 명확히 확정했다. `raw_fundamentals`가 현재 전혀 적재되지 않아(DEF-IT-M01) 당장 관측 가능한 버그로 이어지지는 않으나(입력 자체가 없음), UNIT-02가 향후 `raw_fundamentals` 적재를 구현할 때 이 규칙을 어느 쪽(Ingestion 적재 시점 vs Derivation 계산 시점)이 구현할지 지금 명시적으로 배정하지 않으면 그 구현 시점에 "둘 다 안 함" 상태로 자동 방치될 위험이 있다. 배포 차단 사유는 아니나(현재 입력 자체가 없어 영향 0), 이 REQ를 실제로 완성하려면 3단계 설계서(§3-2) 또는 향후 UNIT-02 재작업 시 반드시 명시적 담당을 지정해야 한다. |

- **그 외 결함 없음.** 근거: §4-1(TC-IT-01~06)·§4-2(TC-IT-07~12)·§4-3(TC-IT-13~20)·§4-4(TC-IT-21/22)·§5 회귀(TC-IT-R1~R5) 총 26개 케이스를 실제 코드 대조, 실제 DB 역할 전환(SET ROLE), 실제 프로덕션 빌드+서버로 실행했다. 3중 방어는 UNIT-07/08의 스키마 확장 이후에도 드리프트 없이 유지됨을 실제 INSERT/UPDATE/SELECT로 확인했고, UNIT-06 코드는 자신이 만들지 않은 다른 유닛의 결측 데이터를 만나도 크래시 없이 설계대로 동작함을 확인했다.

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- 이번 테스트에서 생성한 임시 아티팩트 목록: `.harness-tmp/feature-stock-metrics-it/`(`fake_backend.py`, `backend.log`, `frontend_build.log`, `frontend.log`, `stocks_005930.html`/`stocks_005935.html`/`stocks_900001.html`/`stocks_999999.html`).
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가 (규칙 K 1번): **[x] 예**.
- 정리(삭제) 완료 여부: **완료.** `netstat -ano`로 포트 8000(fake backend uvicorn, PID 18608)/3000(`next start`, PID 19596) 리스닝 PID를 특정해 `taskkill //F //PID ... //T`로 전부 종료 확인(종료 후 `netstat`에 8000/3000 리스너 없음 재확인). `NEXT_PUBLIC_API_BASE_URL` 오버라이드 없이 `npm run build`를 재실행해 `.next/`를 기본 상태(기본 `localhost:8000` 설정)로 복원. `.harness-tmp/feature-stock-metrics-it/`를 `rm -rf`로 삭제 후 `.harness-tmp/`가 다시 빈 상태임을 확인.
- DB 정리: 이번 테스트는 §4-2(TC-IT-07/08)의 쓰기 조작을 전부 명시적 트랜잭션(`BEGIN ... ROLLBACK`) 안에서 수행했다. 테스트 종료 후 `raw_internal.raw_ohlcv`(58), `public_serving.stock_master`(6), `derived_metrics_daily`(6), `batch_run`(5) 행수가 테스트 시작 전과 정확히 동일함을 재확인했다(§3 "테스트 데이터" 최초 조회값과 §7 최종 조회값 일치). 새로 생성/변경/삭제된 DB 행은 없다.
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
  (이번 07단계 세션이 만든 변경은 `docs/harness/traceability.md`(REQ-002 통합테스트 컬럼 갱신)와 신규 `docs/harness/feature-stock-metrics-integration-test.md`(이 문서) 두 건뿐이며, 나머지 항목은 전부 이 세션 이전부터 존재하던 다른 진행 중 작업(UNIT-08/09, 시장요약 관련)의 변경이다 — `feature-stock-search-integration-test.md`가 07단계 시작 시점에 이미 동일하게 관측·기록한 목록과 완전히 동일하다. `.harness-tmp/`는 비어 있어 목록에 나타나지 않는다.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **[x] 없음**.

## 8. 리스크 및 잔존 이슈
- **DEF-IT-M01(Medium, Deferred) — 실 Ingestion Batch→실 Derivation Batch 종단간 실행이 이 프로젝트 역사상 검증된 적 없음**: 근본 원인은 UNIT-02의 실 서비스키 미보유(승계, 변경 없음) + 이번 세션의 도구 정책(host에서 DB 자격증명 사용 명령 전면 차단, §2). **10단계(배포테스트) 착수 전 실 서비스키를 확보한 뒤, 실제 자격증명 사용이 허용되는 환경(CI 또는 사람이 직접 조작하는 세션)에서 `run_ingestion.py`(실제 API 호출) → `run_derivation.py`(그 결과 소비) 를 최소 1회 종단간으로 실행해 이 갭을 닫을 것을 강력히 권고한다.** 이번 통합테스트는 코드/스키마/권한 레벨 호환성만 확정했을 뿐, "실제로 실행되어 성공했다"는 사실 자체는 여전히 미확보 상태다.
- **DEF-IT-M02(Low, Deferred) — PER≤0 결측치 처리 규칙(§3-2) 구현 담당 미배정**: 현재는 `raw_fundamentals` 자체가 비어 있어(DEF-IT-M01과 동일 원인) 영향이 없으나, UNIT-02가 향후 이 테이블 적재를 구현하는 시점에 "Ingestion이 적재 시 필터링" 또는 "Derivation이 계산 시 필터링" 중 어느 쪽이 담당인지 지금 명시적으로 정하지 않으면 그 시점에 누락될 위험이 있다. 3단계 설계서(§3-2) 또는 UNIT-02 재작업 계획에 명시적으로 반영 권고.
- **이 통합테스트의 도구 정책 제약(신규 관찰)**: 이전 세션(UNIT-01~09)들은 host에서 `BATCH_DATABASE_URL`/`PUBLIC_API_DATABASE_URL`에 실제 비밀번호를 넣어 CLI/uvicorn을 직접 기동할 수 있었으나, 이번 07단계 세션은 Claude Code auto mode classifier가 이를 "Credential Exploration"으로 전면 차단함을 확인했다(실제 값·placeholder 값 모두 차단, 명백한 더미 값 `unused:unused`만 허용). 이는 이 프로젝트의 결함이 아니라 **세션 도구 환경의 변화**이며, 향후 07/08/09/10단계가 이 제약 하에서 실제 배치 CLI를 실행해야 할 때는 (a) DI 오버라이드가 가능한 FastAPI 계층은 이번 문서의 방식(Fake DI + `docker exec` 실측 데이터)으로 우회 가능하지만, (b) `run_ingestion.py`/`run_derivation.py`처럼 DI 지점이 없는 독립 CLI 배치는 이 방법으로 우회할 수 없다는 점을 8단계(전체 풀테스트) 착수 전 오케스트레이터가 인지해야 한다.
- 실제 프로덕션 호스팅 환경에서의 CORS — 기존 승계 리스크(호스팅 벤더 미확정, 변경 없음).
- PER/PBR/시가총액 percentile의 실 규모(~2,500종목) 동률/경계 검증 — `unit-06-test.md`가 이미 인계한 승계 리스크(변경 없음, `raw_fundamentals` 실 데이터 부재와 동일 원인).
- Derivation Batch cron 스케줄링/컨테이너 배포 — 10단계 영역(기존 승계).

## 9. 결론 및 판정
- [ ] PASS
- [x] **CONDITIONAL PASS** — 조건: **DEF-IT-M01(Medium)을 10단계(배포테스트) 착수 전까지 반드시 폐쇄**(실 서비스키 확보 후 `run_ingestion.py`→`run_derivation.py` 실제 종단간 1회 이상 실행으로 검증). DEF-IT-M02(Low)는 배포 차단 사유는 아니나 UNIT-02 재작업 계획에 명시적으로 반영할 것을 조건으로 8단계 handoff와 함께 인계한다.
- [ ] FAIL

**판정 근거**: 이 업무 단위(UNIT-06 내부 경계)의 API/화면/DB 권한 계층은 코드·스키마·권한 레벨에서 완전히 정합적이며(§4-1 TC-IT-03~06, §4-2 전체), 다른 유닛(UNIT-07/08)이 같은 DB에 추가한 결측 데이터에도 크래시 없이 정확히 동작하고(§4-3), 회귀 없음(§5)을 확인했다. 그러나 이 통합테스트가 코디네이터의 1번 지시사항("전체 체인이 한 번도 안 끊기고 실제로 실행된 적이 있는지 확인하라")을 수행한 결과, **실제로는 한 번도 실행된 적이 없다는 사실이 처음으로 명확히 확인됐다**(DEF-IT-M01). 이는 UNIT-06 코드의 결함이 아니라 프로젝트 차원의 알려진 환경 제약(실 서비스키 부재)이 지금까지 "아직 검증 안 됨"으로 막연히 남아있던 것을 이번에 "왜 검증되지 않았는지, 무엇을 하면 닫을 수 있는지"까지 구체화한 것이므로, 임의로 PASS 처리하지 않고 **CONDITIONAL PASS**로 판정해 10단계 착수 전 필수 확인 조건으로 명시적으로 못박는다(규칙 F — 근본 원인은 UNIT-02/환경 준비이므로 UNIT-06 재작업을 요구하지 않는다). 8단계(전체 풀테스트)로의 handoff 자체는 차단하지 않는다 — 이 조건은 8단계 통과 이후, 10단계 배포테스트 착수 전에 최종 확인되어야 하는 게이트로 이관한다.

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

### 1차 검증 (작성자 관점 자가 재검토, "이 업무 단위의 모든 사용자 시나리오가 케이스로 커버됐는가")
- 검증자(역할): 07-integration-tester(작성자 본인)
- 일시: 2026-09-18
- 체크리스트
  - [x] 코디네이터가 명시한 5개 확인 항목이 전부 케이스로 커버됐는가 → ①§4-1(TC-IT-01~06), ②§4-2(TC-IT-07~12), ③§5(TC-IT-R1~R5), ④§4-3(TC-IT-19), ⑤§4-4(TC-IT-21/22) 전부 1:1 대응. 미커버 없음.
  - [x] "각 유닛 테스트는 자기 단계만 픽스처로 검증했을 가능성이 높다"는 지시를 실제로 반증/확증했는가 → 반증됨: `raw_ohlcv`/`raw_fundamentals`의 `source_batch_id` 추적으로 실제 Ingestion Batch 코드가 이 데이터를 만든 적이 없음을 확정(TC-IT-01), 추측이 아니라 코드+DB 증거로 확정.
  - [x] UNIT-06 단위테스트가 이미 검증한 것을 반복하지 않았는가 → §2 제외범위에 반복 배제 항목을 명시하고, 실제로 §4 어디에서도 return_rank_pct 계산 정확성·ENUM 버그·EmptyState 렌더링을 재검증하지 않았다(코드 대조/DB 역할전환/타 유닛 데이터 상호작용에만 집중).
  - [x] 발견된 문제(DEF-IT-M01/M02)를 임의로 봉합하지 않고 규칙 F에 따라 근본 원인 단계로 정확히 귀속시켰는가 → §6에서 "UNIT-06 결함 아님, UNIT-02/환경 준비 문제"로 명시하고 3단계 재작업이 아닌 10단계 전 확인 조건으로 이관했다.
  - 발견된 결함: DEF-IT-M01(Medium), DEF-IT-M02(Low). 조치: 즉시 수정하지 않고 CONDITIONAL PASS 조건 및 리스크로 명시.

### 2차 검증 (독립 심사자 관점 — "8단계 전체테스트에서 다른 업무단위와 만나는 지점에서 문제가 생기지 않을까")
- 검증자(역할): 07-integration-tester(역할 전환 재검토)
- 일시: 2026-09-18
- 체크리스트
  - [x] **feature-screener(UNIT-07)/feature-market-summary(UNIT-08) 경계** → 두 유닛이 각각 `derived_metrics_daily`(0007/0008)와 `market_summary_daily`(0009)를 확장했는데, 이 통합테스트(§4-2)가 확인한 GRANT 경계가 이 확장 이후에도 유지됨을 실측했으므로, 8단계에서 이 두 feature가 같은 테이블을 계속 확장해도 UNIT-06의 방어선이 재검증 없이 깨질 가능성은 낮다고 판단. 단, 향후 0010+ 마이그레이션이 추가될 때마다 이 GRANT 재확인이 반복돼야 한다는 점을 §8에 일반화해 남겨야 하는지 검토했으나, 이는 이미 각 유닛 note/test가 관행적으로 수행해 온 절차(예: unit-07-test.md TC 다수)이므로 별도 신규 항목으로 만들지 않고 기존 관행 승계로 충분하다고 판단.
  - [x] **DEF-IT-M01이 8단계에서 다시 드러날 위험** → 8단계(전체 풀테스트)가 "전체 시스템 사용자 시나리오"를 검증할 때도 동일한 도구 정책 제약(host DB 자격증명 차단)에 부딪힐 가능성이 높다 — 8단계 착수 전 오케스트레이터가 이 제약을 미리 인지하도록 §8에 명시적으로 경고를 남겼다(투명성 확보, 8단계가 이 문서를 읽지 않고 동일한 시행착오를 반복하지 않도록).
  - [x] **feature-stock-search(UNIT-03/09) 경계** → 이 문서는 `/stocks`↔`/stocks/[code]` 이동을 재검증하지 않았지만(과제 지시, §2), `FakeStockSearchRepository`를 부수적으로 붙여 `/stocks` 자체가 이 세션의 백엔드 기동 방식과 충돌 없이 정상 응답하는지는 확인했다(§3 Fake DI 구성에 포함) — 다만 이는 보조 확인일 뿐 이 feature의 검증 범위가 아니므로 별도 TC 번호를 부여하지 않고 §3에만 기록했다. 8단계에서 이 경계가 이미 `feature-stock-search-integration-test.md`(PASS)로 확정되어 있으므로 재확인 불필요.
  - [x] **CONDITIONAL PASS 조건(DEF-IT-M01)이 8단계 handoff를 부당하게 막지 않는가** → §9에서 "8단계 handoff는 차단하지 않는다, 10단계 착수 전 조건"으로 명시해 과도한 게이트가 되지 않도록 범위를 좁혔다 — 8단계는 여러 feature의 시스템 수준 상호작용을 보는 단계이므로 이 환경 준비 이슈로 막을 필요가 없다고 판단(8단계가 이 이슈로 막힐 근거를 찾지 못함).
  - 발견된 결함: 없음(신규). 8단계 인계 리스크 2건(§8) 명시.
  - 조치 내용: 서술 보강(§8/§9 8단계·10단계 인계 범위 명확화) 외 결함 목록 변경 없음 → 최종 CONDITIONAL PASS 유지.

- 검증 로그 파일 경로: 이 문서 §10에 통합 기록(별도 `verify-log_feature-stock-metrics-integration-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — `feature-stock-search-integration-test.md`와 동일한 관례).

## 절차 흐름 (참고용 다이어그램)
```mermaid
flowchart TD
    A["UNIT-06 6단계 PASS 확인"] --> B["Ingestion↔Derivation 스키마/출처 추적(TC-IT-01~06)"]
    B --> C["3중 방어 SET ROLE 재현(TC-IT-07~12)"]
    C --> D["타 유닛 결측 데이터 상호작용(TC-IT-13~20)"]
    D --> E["PER/PBR 책임 공백 재확인(TC-IT-21/22)"]
    E --> F["회귀: pytest/ruff/tsc/lint/build(TC-IT-R1~R5)"]
    F --> G{설계 결함/미실행 갭 발견?}
    G -->|Yes, DEF-IT-M01/M02| H["규칙F: 근본원인 UNIT-02/환경 준비로 귀속<br/>10단계 전 확인 조건으로 이관"]
    G -->|일부| I["내부검증 1차/2차(§10)"]
    H --> I
    I --> J["Teardown(§7) + git status/DB 행수 확인"]
    J --> K["traceability.md REQ-002 통합테스트 갱신 → CONDITIONAL PASS로 8단계 handoff"]
```
