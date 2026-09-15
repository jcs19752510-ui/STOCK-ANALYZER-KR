# UNIT-03 구현 노트 — 종목 마스터 조회/검색 (코스피/코스닥)

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-15
- 포함 REQ: REQ-001 (종목 마스터 조회/검색 — 코스피/코스닥 상장 종목명·코드 검색)
- 입력: `docs/harness/03-system-design.md`(v4, PASS) §1-1(3중 방어)·§1-2(Ingestion Batch만 외부 데이터 소스와 통신)·§3-1(스키마별 역할 매트릭스)·§3-1-1(market 필드 표준화)·§3-2(`public_serving.stock_master`)·§3-5(초기 시드 데이터)·§4-1(공통 envelope/에러 코드)·§4-2(`GET /api/v1/stocks`), `docs/harness/04-ux-design.md`(v3, PASS) §2-3(종목 검색 화면), `docs/harness/units/unit-01-note.md`/`unit-01-test.md`(DEF-003/DEF-004 교훈), `docs/harness/units/unit-02-note.md`(공공데이터포털 API 조사 결과)
- 의존성: UNIT-02(`services/ingestion_batch/gov_data_client.py` 재사용·확장), UNIT-01(`shared/calendar_service`, `reference.market_calendar` 재사용)

---

## 0. 핵심 이슈 — 종목 마스터 데이터 출처 조사 결과 (필독)

코디네이터 지시에 따라, 설계서가 명시하지 않은 "종목 마스터(종목코드/종목명/상장시장) 시드 데이터의 실제 출처"를 상상으로 채우지 않고 먼저 조사했다.

**조사 결과**: 03-system-design.md §3-5는 "`stock_master`(상장 종목 목록)는 배포 전 1회성 시드 스크립트로 적재한다"고만 서술하고, 이 데이터를 어디서 가져오는지는 명시하지 않았다(설계 공백). 그런데 UNIT-02가 이미 조사·연동한 공공데이터포털 "금융위원회_주식시세정보"(`GetStockSecuritiesInfoService`, `getStockPriceInfo`) 오퍼레이션의 응답 필드 목록에 `itmsNm`(종목명)·`mrktCtg`(시장구분)가 **이미 포함되어 있음을 확인했다**(`services/ingestion_batch/gov_data_client.py` 모듈 docstring, UNIT-02가 data.go.kr 공개 문서를 근거로 이미 기재해 둔 목록이며, `tests/unit/test_gov_data_client.py`의 `_item()` 픽스처에도 이 두 필드가 이미 존재했다 — 다만 UNIT-02는 OHLCV 파싱에만 이 필드를 안 썼을 뿐, 존재 자체는 이미 문서화되어 있었다).

**결론 및 결정 근거**:
1. 새로운 외부 API를 추가로 조사·도입하지 않는다. 이미 REQ-011로 채택되어 상업적 이용 조건(약관 상충 이슈, `decisions.md` DEC-004)까지 검토된 동일 데이터 소스를 재사용하는 것이, 새 소스를 도입해 약관을 처음부터 다시 검토하는 것보다 안전하고 일관적이다.
2. 03-system-design.md §1-2 "Ingestion Batch만 외부 데이터 소스와 통신한다" 원칙을 지키기 위해, 새 HTTP 호출 코드를 별도 모듈에 만들지 않고 `services/ingestion_batch/gov_data_client.py`의 `GovDataPortalClient`에 메서드를 추가하는 방식을 택했다(아래 §1-1).
3. 이 판단은 사용자에게 규칙 A로 되물을 사안이 아니라고 판단했다 — 새 소스를 조사하는 것과 기존 소스를 재사용하는 것 사이의 트레이드오프가 실질적으로 갈리지 않는다(기존 소스 재사용 쪽이 명백히 더 안전하고 저위험이며, 03-system-design.md §8-2 항목8이 `sector` 필드에 대해 이미 채택한 "출처 미확정 시 새 소스를 성급히 들이지 않고 필요한 범위만 확정한다"는 태도와 일관된다). 다만 **이 결정은 근거와 함께 기록해 두는 것이 맞다고 판단해** 아래 "설계서 대비 편차" §2-1에 상세히 남긴다.
4. `mrktCtg`의 실제 표기(한글 "코스피"/"코스닥" vs 영문 "KOSPI"/"KOSDAQ")는 실 서비스키가 없어 실측하지 못했다(UNIT-02와 동일한 근본 한계 — §2-6 참조). 두 표기를 모두 방어적으로 처리하도록 구현했다.

---

## 1. 구현 범위

### 1-1. `GovDataPortalClient` 확장 (`services/ingestion_batch/gov_data_client.py`, UNIT-02 파일 확장)

- **리팩터링(동작 보존)**: 기존 `fetch_ohlcv()`의 네트워크 요청/재시도/백오프/게이트웨이 오류 분류 로직을 `_fetch_raw_items()`(원시 item 목록 + totalCount 반환)로 추출했다. `fetch_ohlcv()`는 이 공통 로직을 호출한 뒤 OHLCV 필드만 파싱하도록 변경했고, **외부에서 관찰 가능한 동작(예외 종류, 재시도 횟수, 반환값)은 전혀 바꾸지 않았다** — UNIT-02가 이미 작성한 13개 테스트(`tests/unit/test_gov_data_client.py`)를 리팩터링 전/후 그대로(수정 없이) 실행해 전부 pass함을 확인했다(아래 §7 로그 참조). 정적 분석 검토 이유: 새 메서드가 추가로 필요한 네트워크 계층 로직(재시도/백오프/오류분류, 약 60줄)을 그대로 복제하면 향후 두 곳에서 따로 수정해야 하는 유지보수 부담이 생기므로, 동작 보존 리팩터링이 단순 복제보다 안전하다고 판단했다.
- **신규 메서드 `fetch_stock_master_snapshot(trade_date, *, page_no, num_of_rows)`**: `_fetch_raw_items()`를 재사용해 같은 오퍼레이션을 호출하고, `srtnCd`/`itmsNm`/`mrktCtg`/`basDt`를 파싱해 `StockMasterSnapshotRecord(stock_code, name, market)`를 만든다.
  - `mrktCtg` 값이 `_MARKET_CATEGORY_TO_LISTED_MARKET`(한글/영문 양쪽 매핑)에 없으면(코넥스 등) 해당 item을 **예외 없이 건너뛴다**(REQ-001이 코스피/코스닥으로 범위를 한정했으므로).
  - `basDt` 불일치, 필수 필드 누락, 빈 종목명은 `GovDataClientError`로 명시적 실패(기존 `_parse_item`과 동일한 원칙).
- 신규 값 객체: `StockMasterSnapshotRecord`, `StockMasterFetchResult`.

### 1-2. 데이터 모델 / 마이그레이션

- `shared/db_models/public_serving.py`에 `StockMaster` 모델 추가(`listed_market_enum` 신설 — `raw_ohlcv`/`market_calendar`의 `market_session` ENUM(KRX/NXT)과 물리적으로 다른 ENUM으로 분리해 §3-1-1 "market 두 축 혼용 금지" 원칙을 DB 레벨에서도 강제).
- `shared/market_types.py`(신규): `ListedMarket`/`ListedMarketFilter` 타입과 허용값 튜플을 한 곳에 정의. 향후 UNIT-06~08(`derived_metrics_daily`/`market_summary_daily`)도 이 축을 공유하므로, Q1(설계서 §3-1-1)이 이미 한 번 겪은 "market 필드 의미 중복"이 코드 레벨에서 재발하지 않도록 미리 공용화했다.
- `db/alembic/versions/0005_create_public_serving_stock_master.py`: `stock_master` 테이블 + GRANT를 **같은 리비전에 포함**(DEF-003 교훈 적용). `batch_worker`=SELECT/INSERT/UPDATE, `api_service`=SELECT. `public_serving` 스키마 자체의 USAGE GRANT는 0003에서 이미 양쪽에 부여되어 있어 재부여하지 않았다.
- `updated_at` 컬럼: **설계서 §3-2의 `stock_master` 컬럼 목록에는 없으나**, 코디네이터 지시(DEF-004 재발 방지)에 따라 `reference.market_calendar`와 동일한 패턴으로 추가했다(§2-2 편차 참조).

### 1-3. 시드 스크립트 (`scripts/seed_stock_master.py`, 신규)

- `load_calendar.py`(UNIT-01)와 동일한 CLI 관례(`--dry-run`, 환경변수 기반 설정, 명시적 실패)를 따른다.
- `--trade-date` 미지정 시 `run_ingestion.py`(UNIT-02)와 동일하게 `get_last_trading_day(market="KRX", ...)`로 자동 계산(캘린더 재사용, 코드 중복 없음 — `shared.calendar_service` import).
- `fetch_all_records()`: `totalCount` 기준으로 페이지를 반복 호출해 전 종목을 수집한다(안전 상한 `MAX_PAGES=10` × `PAGE_SIZE=1000` = 10,000종목, 실제 규모 약 2,500종목 대비 충분한 여유). run_ingestion.py는 실 데이터 규모를 확인하지 못해 페이지네이션 배선을 보류했지만(unit-02-note.md §3), 이 스크립트는 전 종목 목록이 반드시 필요하므로 처음부터 배선했다.
- `upsert_stock_master()`: `(stock_code)` 충돌 시 `name`/`market`/`is_active`/`updated_at`만 갱신한다. **DEF-004 재발 방지**: Core `INSERT ... ON CONFLICT DO UPDATE` 경로에서는 모델 컬럼의 `onupdate=func.now()`가 트리거되지 않으므로(`load_calendar.py`가 이미 겪은 것과 동일한 함정), `set_`에 `"updated_at": func.now()`를 명시적으로 포함했다. 이 유닛 착수 시점부터 이 함정을 알고 있었기 때문에 UNIT-01처럼 결함으로 발견된 뒤 수정하는 과정을 거치지 않고 처음부터 반영했다(실 PostgreSQL로 재현 검증 완료, §7 참조).
- `public_serving.batch_run`에 실행 이력을 남기지 않는다(`batch_run_type` ENUM이 `'ingest'`/`'derive'`만 허용하며, 이 스크립트는 둘 중 어느 것도 아니라고 판단 — 새 ENUM 값 추가는 이번 유닛 범위를 벗어난 스키마 변경이라 하지 않았다).

### 1-4. Public API (`GET /api/v1/stocks`)

- `services/public_api/schemas/stocks.py`: `StockSearchItem(stock_code, name, market)` — 설계서 §4-2 응답 요약과 동일.
- `services/public_api/db/stock_repository.py`: `SqlStockSearchRepository.search(query, market)` — `name ILIKE` OR `stock_code ILIKE`(대소문자 무시 부분일치), `market` 필터(`ALL`이면 미적용), `is_active=true`만 대상, `stock_code` 오름차순 정렬(설계서 §4-2 v3가 `/screen`에 이미 확정한 "동률/정렬 결정성 확보를 위해 stock_code 오름차순" 관례를 재사용), 내부 안전 상한 `MAX_SEARCH_RESULTS=100`(§2-3 편차 참조, API 파라미터로 노출하지 않음).
- `services/public_api/api/stocks.py`: `GET /api/v1/stocks?query=&market=`. `query` 필수(빈 값/공백만인 경우 400 `INVALID_PARAMETER`), `market` 선택(기본 `ALL`, 허용값 외 400). 응답은 `meta.data_freshness` 없이(REQ-006이 요구하는 "시세/스크리닝/리포트" 화면 범위 밖 — `02-planning.md` §5 KPI 문구 참조) `meta.disclaimer`/`generated_at`만 포함.
- `services/public_api/main.py`에 라우터 등록.

---

## 2. 설계서 대비 편차 및 확인 필요 사항 (사유 포함)

1. **[설계 공백 보완] 종목 마스터 시드 데이터 출처를 UNIT-02 데이터 소스 재사용으로 확정**: §0 참조. 03-system-design.md §3-5는 "1회성 시드 스크립트로 적재한다"고만 하고 출처를 명시하지 않았다. 새 API를 조사하지 않고 기존 REQ-011 소스를 재사용하기로 결정했다(근거: 이미 상업적 이용 조건이 검토된 소스 재사용이 새 소스 도입보다 저위험, §1-2 "Ingestion Batch만 외부 통신" 원칙 준수 용이).
2. **[설계서에 없는 컬럼 추가] `stock_master.updated_at`**: 코디네이터의 명시적 지시(DEF-004 재발 방지)에 따라 설계서 §3-2에 없는 컬럼을 추가했다. `reference.market_calendar`의 기존 패턴과 동일하게 구현(server_default=now(), Core upsert의 `set_`에 명시적 포함).
3. **[구현 세부 결정] `stock_master.listing_date`를 nullable로 구현**: 설계서 §3-2 표는 `listing_date`를 `date`(nullable 표기 없음)로 정의하지만, 이번에 채택한 데이터 소스(`getStockPriceInfo` 일별 시세 스냅샷)는 상장일 정보를 제공하지 않는다. 상상으로 값을 채우지 않는다는 원칙(코디네이터 지시)에 따라 nullable로 구현하고 현재는 항상 `NULL`로 둔다 — 이는 설계서 §8-2 항목8이 `sector`(업종 분류, 출처 미확정)에 대해 이미 적용한 것과 동일한 처리 원칙이다. REQ-001의 핵심 화면(04-ux-design.md §2-3 종목 검색: 종목명+코드+시장 뱃지만 노출)은 `listing_date`를 쓰지 않으므로 이 결측이 REQ-001 기능을 막지 않는다. 별도 출처가 확인되면 채우는 것을 후속 과제로 남긴다.
4. **[구현 세부 결정] `is_active` 필터링 및 자동 상장폐지 미감지**: 검색 결과에서 `is_active=false` 종목을 제외하도록 구현했다(REQ-001이 "상장 종목" 검색으로 범위를 한정하므로). 다만 이 스크립트는 응답에 없는(=상장폐지 가능성이 있는) 기존 종목의 `is_active`를 자동으로 `false`로 전환하지 않는다 — REQ-001에 상장폐지 자동 감지 요구가 없고, 잘못된 자동 비활성화가 더 위험하다고 판단했다. 상장폐지 처리가 필요해지면 운영자가 수동으로 갱신해야 한다(운영 절차 문서화 필요 — 확인 필요 항목).
5. **[방어적 구현, API 계약 확장 아님] `MAX_SEARCH_RESULTS=100` 내부 상한**: 설계서 §4-2는 `/stocks`에 페이지네이션 파라미터를 정의하지 않았다. 짧은 검색어가 대량의 결과를 반환할 가능성(공개 무인증 엔드포인트)에 대비해 API 파라미터를 추가하지 않고 리포지토리 내부 상수로만 상한을 뒀다 — 새 계약을 만들지 않으면서 방어적으로만 동작한다.
6. **[UNIT-02와 동일한 미검증 한계 승계] `mrktCtg` 실제 값 형식 미확인**: 실 서비스키가 없어 `mrktCtg`가 한글("코스피"/"코스닥")로 오는지 영문("KOSPI"/"KOSDAQ")으로 오는지 실측하지 못했다. 두 표기를 모두 매핑하도록 방어적으로 구현했다(`_MARKET_CATEGORY_TO_LISTED_MARKET`). 실 키 확보 후 재검증 필요.
7. **[리팩터링, 범위 내 최소 변경] `GovDataPortalClient` 내부 구조 변경**: `fetch_ohlcv()`의 네트워크 계층을 `_fetch_raw_items()`로 추출했다(§1-1). UNIT-02가 이미 작성한 테스트를 수정 없이 그대로 재실행해 회귀 없음을 확인했다(§7). 이 리팩터링은 "곁다리 리팩터링"이 아니라 이번 유닛의 핵심 요구(같은 오퍼레이션에서 다른 필드를 파싱)를 코드 중복 없이 구현하기 위한 필수 변경이라고 판단했다.

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터 및 향후 운영자용)

- **실 서비스키로 `fetch_stock_master_snapshot()` 재검증(최우선)**: `itmsNm`/`mrktCtg`가 실제로 문서와 동일한 형식으로 오는지, `mrktCtg`가 한글/영문 중 어느 쪽인지 실 키 확보 후 재검증 필요(§2-6). UNIT-02가 남긴 것과 동일한 성격의 과제다.
- **`upsert_stock_master()`의 실제 upsert 동작**: PostgreSQL 전용 `ON CONFLICT` 구문이라 SQLite로 대체 검증할 수 없다 — 이번 유닛은 로컬 Docker PostgreSQL로 직접 실행해 검증했다(§7). 6단계도 실 DB로 독립 재현할 것을 권고한다(UNIT-01/02에서 이미 이런 방식으로 DEF-003/004급 결함을 발견한 전례가 있음).
- **상장폐지 자동 감지 정책**: §2-4 참조. 현재는 수동 운영 절차로 남아 있다. REQ-001에 명시 요구가 없어 이번 범위에서 자동화하지 않았으나, 운영이 시작되면 정책을 확정해야 한다.
- **`sector`/`listing_date` 출처**: 여전히 미확정이다(설계서 §8-2 항목8과 동일 상태 유지, `listing_date`는 이번에 동일 문제로 추가 확인됨). REQ-001 핵심 기능에는 영향 없음.
- **호출 한도(rate limit)**: UNIT-02와 동일하게 실 키 발급 후 재확인 필요.
- **페이지네이션 상한(`MAX_PAGES=10`)**: 실제 종목 수가 10,000을 넘지 않는 한 문제없으나, 실 서비스키로 최초 실행 시 실제 페이지 수를 확인해 상한이 여유로운지 재확인 권고.
- **실제 컨테이너/운영 실행 미검증**: 이 스크립트는 로컬 CLI 실행(`--dry-run` 및 upsert 로직 직접 호출)까지만 검증했다. 실제 배포 환경에서의 1회성 실행 절차 문서화는 10단계 배포테스트 영역이다.

---

## 4. 인수 조건 (Acceptance Criteria) — 6단계 테스터용

**AC-1 (GovDataPortalClient 확장, 리팩터링 회귀 없음)** `pytest tests/unit/test_gov_data_client.py`가 전부 pass(21건):
  - 기존 13건(UNIT-02, `fetch_ohlcv` 관련) 전부 **수정 없이** pass — 리팩터링이 동작을 바꾸지 않았음을 확인
  - `fetch_stock_master_snapshot()` 신규 8건: 정상 파싱(list/단일 dict 정규화), 한글 시장구분(`코스닥`) 매핑, 코스피/코스닥 외 값(코넥스) 필터링(예외 아님, totalCount는 원본 유지), `basDt` 불일치 실패, 필수 필드 누락 실패, 빈 종목명 실패, 게이트웨이 오류 공유 경로 확인

**AC-2 (시드 스크립트 순수 로직)** `pytest tests/unit/test_seed_stock_master.py`가 전부 pass(6건):
  - `--trade-date` 지정 시 캘린더 조회 없이 그 값 사용
  - 미지정 시 `get_last_trading_day(market="KRX", ...)`로 계산
  - 캘린더 데이터 공백 → `SeedStockMasterError`
  - 단일 페이지로 충분하면 1회만 호출
  - 여러 페이지 필요 시 `totalCount` 기준으로 정확히 필요한 만큼만 반복 호출
  - `MAX_PAGES` 상한 도달 시 `SeedStockMasterError`

**AC-3 (Public API `/stocks`)** `pytest tests/unit/test_public_api.py`가 전부 pass(12건, 기존 6건 + 신규 6건):
  - 정상 검색 성공(`market` 생략 시 리포지토리에 `"ALL"`로 전달됨을 확인)
  - 결과 없음 → 빈 배열, 200
  - `market` 파라미터가 리포지토리에 그대로 전달됨
  - `query`가 공백만 → 400 `INVALID_PARAMETER`, 리포지토리 호출 안 됨
  - `query` 자체가 없음(필수 파라미터 누락) → 400 `INVALID_PARAMETER`
  - `market`이 허용값 밖 → 400 `INVALID_PARAMETER`, 리포지토리 호출 안 됨

**AC-4 (마이그레이션, 실 PostgreSQL로 검증 완료)**
  - `ALEMBIC_DATABASE_URL=<migrator> alembic upgrade head`(0001~0005) 성공 → `public_serving.stock_master` 테이블/`listed_market` ENUM 생성 확인
  - `\dp public_serving.stock_master` → `batch_worker=arw`, `api_service=r`
  - `api_service` 계정으로 `INSERT INTO public_serving.stock_master ...` → `permission denied for table stock_master`(SELECT는 성공)
  - `alembic downgrade 0004` → `stock_master` 테이블/ENUM 제거, `alembic upgrade head`로 재적용 시 오류 없이 복원 및 GRANT 자동 재적용

**AC-5 (시드 → 조회 종단 검증, 실 PostgreSQL)**
  - `upsert_stock_master()`를 `batch_worker`로 직접 호출해 신규 2종목(KOSPI/KOSDAQ 각 1) 삽입 확인
  - 동일 종목명 변경 후 재호출 → 내용 갱신 + `updated_at` 실제 갱신(`pg_sleep`으로 시간차 확인, DEF-004 회귀 없음), 변경되지 않은 다른 행의 `updated_at`은 그대로임을 함께 확인
  - `api_service` 계정으로 `GET /api/v1/stocks?query=<종목명 일부>` 호출 → 정상 검색 결과 반환(대소문자/부분일치 확인)
  - `market` 파라미터로 필터링 시 다른 시장 종목이 제외됨을 실제 쿼리로 확인
  - `is_active=false`로 갱신한 종목이 검색 결과에서 제외됨을 확인
  - 빈 값 `query`/허용값 밖 `market` → 400, 실제 서버 응답으로 확인

**AC-6 (정적 분석)**
  - `python -m ruff check .` 오류 0건
  - `python -m pytest tests/unit -q` **79건**(기존 59건 + 이번 유닛 20건: gov_data_client 8건, seed_stock_master 6건, public_api 6건) 전부 pass

---

## 5. 게이트 1 — 정적 분석/린트 결과

- 이 프로젝트는 UNIT-01/02에서 `pyproject.toml`에 `ruff` 설정을 이미 도입했다(건너뛴 것이 아니라 기존 설정을 그대로 적용).
- `python -m ruff check .` 최종 확인: **All checks passed!**(신규 결함 0건)
- mypy/black 등은 UNIT-01/02와 동일하게 아직 도입하지 않았다(이 프로젝트 전체 범위, 이번 유닛에서 새로 결정한 사항 아님).

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — §3-1-1(market 두 축 분리 — 새 ENUM `listed_market`로 물리적 강제), §3-2(`stock_master` 컬럼 정의, 편차 2건은 §2에 사유 명시), §3-5(1회성 시드 스크립트), §4-2(`GET /stocks?query=&market=` 파라미터/응답 형태), 04-ux-design.md §2-3(종목명+코드+시장 뱃지만 노출)을 그대로 구현했다. 설계서가 명시하지 않은 부분(시드 데이터 출처)은 상상으로 채우지 않고 §0에 조사 근거와 함께 결정을 기록했다.
- [x] **에러 처리가 누락된 경로가 없는가(예외를 삼키고 무시하는 코드 없음)** — `gov_data_client.py`(신규 파싱 함수도 기존 `_parse_item`과 동일하게 필수 필드/날짜 불일치/빈 값을 명시적으로 거부), `seed_stock_master.py`(캘린더 미확인/API 오류/응답 0건/예기치 못한 예외 전부 0이 아닌 종료 코드로 명시적 실패), `api/stocks.py`(빈 query/허용값 밖 market을 400으로 명시적 거부, `RequestValidationError`도 공통 핸들러로 처리).
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — API 경계: `query` 공백 검증, `market` 화이트리스트 검증. 외부 API 응답 경계: `_parse_stock_master_item`이 필수 필드 누락/날짜 불일치/빈 종목명을 검증하고, 매핑에 없는 시장구분 값은 안전하게 제외(예외 상황과 "범위 밖" 상황을 구분해 처리). DB 쓰기는 `batch_worker`만 가능(권한 경계), 검색 쿼리는 SQLAlchemy 파라미터 바인딩만 사용(문자열 조합 없음, SQL 인젝션 방지).
- [x] **하드코딩된 시크릿/자격증명이 없는가** — DB 접속 정보(`BATCH_DATABASE_URL`/`PUBLIC_API_DATABASE_URL`)와 서비스키(`GOV_DATA_PORTAL_SERVICE_KEY`) 모두 환경변수로만 주입(`services/ingestion_batch/core/config.py` 재사용, 새 설정 모듈을 만들지 않음). 로컬 검증에 사용한 `devpass`는 코디네이터가 미리 세팅한 로컬 1회성 Docker 컨테이너 값이며 코드/설정 파일에 커밋하지 않았다.
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — UNIT-01 산출물(`shared/calendar_service/`, `scripts/load_calendar.py`, 마이그레이션 0001/0002)과 UNIT-02 산출물(`run_ingestion.py`, `repository.py`, `models.py`, 마이그레이션 0003/0004)은 전혀 수정하지 않았다. `gov_data_client.py`의 변경은 §1-1/§2-7에서 사유를 명시한 최소 범위(동작 보존 리팩터링 + 신규 메서드 추가)로 한정했고, 기존 13개 테스트를 수정 없이 재실행해 회귀 없음을 확인했다. `public_serving.py`(shared)에 새 모델 1개만 추가했고 기존 `BatchRun` 모델은 손대지 않았다.

---

## 7. 로컬 동작 확인 요약 (실행 로그 근거)

- `python -m pytest tests/unit -q` → **79 passed**(UNIT-01+02 59건 + 이번 유닛 20건: `test_gov_data_client.py` +8, `test_seed_stock_master.py` +6, `test_public_api.py` +6)
- `python -m ruff check .` → **All checks passed!**
- 로컬 Docker `stock-screener-db`(기존 `migrator`/`batch_worker`/`api_service` 계정 재사용):
  - `alembic upgrade head`(0001~0005) → `public_serving.stock_master` 테이블/`listed_market` ENUM 생성 확인(`\d public_serving.stock_master`).
  - `\dp public_serving.stock_master` → `batch_worker=arw`, `api_service=r` 확인(DEF-003 교훈 적용 결과 실증).
  - `api_service` 계정으로 `INSERT INTO public_serving.stock_master ...` → `permission denied for table stock_master` 확인(SELECT는 0건으로 정상 응답, 2차 방어 실동작 확인).
  - `upsert_stock_master()`를 `batch_worker` 세션으로 직접 호출 → 삼성전자(KOSPI)/카카오(KOSDAQ) 2건 삽입 확인.
  - `pg_sleep(2)` 후 삼성전자 종목명을 변경해 재호출 → 해당 행의 `updated_at`이 `16:29:29`→`16:29:48`로 **실제 갱신**되고, 변경하지 않은 카카오 행의 `updated_at`은 그대로임을 쿼리로 확인(DEF-004 재발 방지 검증).
  - 실 API(`api_service` 자격증명)로 `TestClient(app)`을 통해 `GET /api/v1/stocks` 종단간 호출: `query=삼성` → `삼성전자우`(KOSPI) 반환, `query=005930&market=KOSDAQ` → 빈 배열(시장 필터 정확히 동작), `query=카카오` → `카카오`(KOSDAQ) 반환, `GET /health` → `{status: ok, db: ok}`.
  - `query`를 공백만으로 호출 → 400 `INVALID_PARAMETER`. `market=NASDAQ` → 400 `INVALID_PARAMETER`. `query` 파라미터 자체 누락 → 400 `INVALID_PARAMETER`.
  - 카카오 행을 `is_active=false`로 갱신 후 재검색 → 결과에서 제외됨을 확인, 이후 `is_active=true`로 복원.
  - `scripts/seed_stock_master.py --dry-run`: `BATCH_DATABASE_URL` 미설정 시 종료 코드 1, 설정 시 종료 코드 0(서비스키 없어도 통과). `GOV_DATA_PORTAL_SERVICE_KEY` 미설정 + `--dry-run` 아님 → 종료 코드 1 + 안내 메시지.
  - 검증 후 `public_serving.stock_master`는 `TRUNCATE`로 정리했고, `alembic downgrade 0004`→`upgrade head` 사이클로 마이그레이션 자체의 재현성(GRANT 자동 재적용 포함)도 별도로 확인했다. 최종적으로 `stock_master`는 빈 테이블, `reference.market_calendar`(730건)/`raw_internal.raw_ohlcv`(0건)는 UNIT-02가 남긴 상태 그대로 유지해 다음 세션(UNIT-04 등)이 이어서 쓸 수 있게 했다.

---

## 8. 다음 단계

이 노트 작성 및 `traceability.md` 갱신 완료 후, 6단계(단위테스트, `06-unit-tester`)를 UNIT-03 대상으로 호출해야 한다. 6단계는 특히 다음을 독립적으로 재검증할 것을 권고한다:
1. 이 노트의 자체 검증(특히 GRANT/`updated_at` 갱신)을 신뢰하지 않고 실 PostgreSQL로 처음부터 재현.
2. `gov_data_client.py` 리팩터링이 UNIT-02의 기존 동작을 정말로 하나도 바꾸지 않았는지, 재시도/게이트웨이 오류 시나리오를 추가로 스윕.
3. `mrktCtg` 매핑(한글/영문 방어)과 코넥스 등 범위 외 값 필터링이 실제로 예외를 던지지 않고 조용히 건너뛰는지.
4. §2(설계서 대비 편차) 6건, 특히 `listing_date` nullable 처리와 상장폐지 자동 미감지가 REQ-001의 "완료" 판정에 영향을 주는 결함인지 아니면 후속 과제로 남겨도 되는지 판단.
