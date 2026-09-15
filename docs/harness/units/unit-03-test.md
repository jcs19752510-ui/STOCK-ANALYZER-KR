# 테스트 결과서 (Test Result Report) — UNIT-03

> 버전: v1(최초이자 최종). 5단계 산출물(`unit-03-note.md`)의 자체 보고("79개 테스트 pass", "GRANT/`updated_at` 이번엔 처음부터 반영", "실 PostgreSQL로 마이그레이션/GRANT/종단간 검증 완료")를 **신뢰의 근거로 삼지 않고**, UNIT-01/UNIT-02 6단계와 동일한 원칙으로 전부 독립 재현했다. 특히 코디네이터가 지시한 5개 항목(①gov API 필드 근거 원문 재대조, ②GRANT/`updated_at` 재현, ③`listing_date` nullable의 REQ-001 영향, ④`market` 필터 스펙 일치·검색 엣지케이스, ⑤UNIT-01/02 회귀)을 전부 실제로 재현해 확인했다.

## 1. 개요
- 테스트 대상: **UNIT-03 (종목 마스터 조회/검색, REQ-001)** — `shared/market_types.py`, `shared/db_models/public_serving.py`(`StockMaster` 모델), `db/alembic/versions/0005_create_public_serving_stock_master.py`, `scripts/seed_stock_master.py`, `services/public_api/{api,db,schemas}/stocks.py`, `services/ingestion_batch/gov_data_client.py`(UNIT-02 파일 확장 — `fetch_stock_master_snapshot()` 신규, `_fetch_raw_items()` 리팩터링)
- 테스트 유형: 단위(Unit)
- 테스트 목적: `unit-03-note.md` §4 인수 조건(AC-1~AC-6)이 실제로 충족되는지 독립 재검증하고, 코디네이터가 명시적으로 지시한 5개 확인 항목을 재현 가능한 형태로 확인하는 것.
- 관련 산출물: `docs/harness/03-system-design.md`(v4, PASS) §1-2/§3-1/§3-1-1/§3-2/§3-5/§4-2, `docs/harness/04-ux-design.md`(v3, PASS) §1-3/§2-3, `docs/harness/units/unit-03-note.md`(5단계 산출물), `docs/harness/units/unit-01-test.md`(v4, DEF-003/004 교훈 원본), `docs/harness/units/unit-02-test.md`(gov API 공식 스펙 교차검증 TC-021 원본)
- 테스트 수행자(에이전트): 06-unit-tester
- 테스트 일시: 2026-09-15

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope): AC-1~AC-6 전체 1:1 추적, 코디네이터 지시 5개 항목, 5단계 게이트1(정적분석)/게이트2(코드리뷰 체크리스트) 통과 여부의 독립 재확인, 위험 판단에 따른 AC 외 경계값/예외 입력 추가 테스트(`query`에 SQL LIKE 와일드카드 문자·SQL 인젝션 시도 문자열, `market` 대소문자, 교차 알파벳 검색, 마이그레이션 완전 초기화 후 재구성).
- 제외 범위 및 사유:
  - **실 서비스키로 `fetch_stock_master_snapshot()` 종단검증**: UNIT-02와 동일하게 유효 서비스키 미보유(코디네이터 확인). 대신 공식 Swagger 메타데이터로 필드 존재/설명을 교차검증했다(아래 TC-013/014).
  - **상장폐지 자동 감지 정책**: REQ-001에 명시 요구가 없어 5단계가 의도적으로 범위에서 제외했고, 이번 6단계도 새 요구로 추가하지 않는다. 다만 재실행 시 `is_active`가 무조건 `true`로 재설정되는 부수 동작은 위험 기반으로 확인했다(TC-034, §6 DEF-007).
  - **`sector`/`listing_date` 실제 값 채우기**: 출처 미확정 상태 유지가 설계서 §8-2 항목8과 일관됨을 확인하는 것까지만 범위(TC-045/046), 새 출처 조사는 이번 유닛 범위 밖.
  - **실제 컨테이너/cron 배포, 부하/동시성 테스트**: 10단계 영역.
  - **`MAX_SEARCH_RESULTS=100` 상한 자체의 경계값(정확히 101건 삽입 등)**: 설계서가 정의하지 않은 내부 방어 상수이며 단순 `LIMIT` 절이라 구현 위험이 낮다고 판단해 실측 우선순위에서 제외(코드 리뷰로 로직만 확인).

## 3. 테스트 환경
- OS/런타임: Windows 10 (Git Bash), Python 3.13.9(anaconda), pytest, ruff. (주의: `python3` 별칭은 Windows Store 스텁으로 연결되어 실패하므로 반드시 `python`을 사용해야 함 — 이번 세션에서 직접 겪은 환경 함정, 기록해 둔다.)
- DB: 로컬 Docker 컨테이너 `stock-screener-db`(`postgres:16-alpine`, 포트 5432, DB `stock_screener`), 역할 `migrator`/`batch_worker`/`api_service`(비밀번호 `devpass`, UNIT-01부터 재사용). 세션 시작 시 `docker ps`로 `Up 5시간` 상태 확인.
- 네트워크: `https://www.data.go.kr/data/15094808/openapi.do`(공식 Swagger 메타데이터, 인증 없이 200 OK)에 curl로 직접 접근해 사용.
- 테스트 데이터: 세션 시작 시 `public_serving.stock_master` 0행, `reference.market_calendar` 730행, `raw_internal.raw_ohlcv`/`public_serving.batch_run` 0행 확인 후 시작(UNIT-02가 남긴 상태와 일치). **주의(투명성 공개)**: TC-027(마이그레이션 완전 재구성 검증)을 위해 `alembic downgrade base`를 실행하는 과정에서 `reference.market_calendar`(730행)가 스키마 자체와 함께 일시적으로 삭제되는 부작용이 발생했다 — 이는 이번 6단계의 검증 행위 자체가 유발한 것이며 UNIT-01/02 코드의 결함이 아니다(downgrade의 정상 동작). 발견 즉시 `scripts/load_calendar.py data/calendar/2026.example.yaml`로 730행을 원상 복구했고, 복구 후 재확인했다(TC-027 절차 및 결과 참조). 이후 모든 검증은 원상 복구된 상태에서 진행했고, 세션 종료 시점에도 `market_calendar`=730행, `stock_master`=0행, `raw_ohlcv`/`batch_run`=0행으로 최종 정리했다.
- 전제 조건: `ALEMBIC_DATABASE_URL`/`BATCH_DATABASE_URL`/`PUBLIC_API_DATABASE_URL` 환경변수를 `devpass`로 직접 설정해 사용(코드/설정 파일에 커밋하지 않음).

## 4. 테스트 케이스 및 결과

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-001 | (AC-6) 정적분석 독립 재실행 | 저장소 루트 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** | |
| TC-002 | (AC-6) 전체 단위테스트 스위트 독립 재실행 | 상동 | `python -m pytest tests/unit -q` | 79 passed | `79 passed, 1 warning in 1.28s` | **PASS** | |
| TC-003 | (AC-6 세부) 신규 3개 파일 테스트 수 분해 검증 | 상동 | `pytest tests/unit/test_gov_data_client.py tests/unit/test_seed_stock_master.py tests/unit/test_public_api.py -v` | `test_gov_data_client.py` 21건(기존 13+신규 8), `test_seed_stock_master.py` 6건, `test_public_api.py` 12건(기존 6+신규 6) = 39건, 기존 UNIT-01/02 40건과 합쳐 79건 | 정확히 21/6/12=39건 전부 PASS, 전체 스위트 79건과 일치 | **PASS** | note의 "20건 신규"(§4 AC-6)와 달리 실제로는 39건 중 20건이 UNIT-03 신규(gov 8+seed 6+public_api 6), 나머지 19건은 UNIT-01/02 기존 코드가 같은 파일에 이미 있던 것 — 숫자 자체(79건, 신규 20건)는 note와 일치함을 확인 |
| TC-004 | (AC-1) 기존 `fetch_ohlcv` 13건 무수정 회귀 | pytest | TC-003 목록에서 `test_fetch_ohlcv_*` 13개 케이스만 필터링해 개별 확인 | 전부 PASS, UNIT-02 테스트 파일과 동일한 함수명/단언 | 13건 전부 PASS(TC-003에 포함), 함수명 UNIT-02 원본과 동일 | **PASS** | 리팩터링(`_fetch_raw_items()` 추출)이 관찰 가능한 동작을 바꾸지 않았음을 재확인 |
| TC-005 | (AC-1) `fetch_stock_master_snapshot` 정상 파싱(list) | pytest | `test_fetch_stock_master_snapshot_success_list` | `stock_code/name/market` 정확히 파싱 | 확인됨(`005930`/`테스트종목`/`KOSPI`) | **PASS** | |
| TC-006 | (AC-1) 한글 시장구분(`코스닥`) 매핑 | pytest | `test_fetch_stock_master_snapshot_maps_korean_market_category` | `market=="KOSDAQ"` | 확인됨 | **PASS** | |
| TC-007 | (AC-1) 코스피/코스닥 외 값(코넥스) 필터링, totalCount 원본 유지 | pytest | `test_fetch_stock_master_snapshot_filters_out_non_kospi_kosdaq` | 예외 없이 조용히 제외, `total_count`는 API 원본(2) 유지, `records`는 1건만 | 확인됨(`total_count=2`, `records`=1건) | **PASS** | |
| TC-008 | (AC-1) 단일 dict→list 정규화, basDt 불일치, 필수필드 누락, 빈 종목명, 게이트웨이 오류 공유 | pytest | 나머지 4개 신규 케이스 | 전부 명시적 `GovDataClientError`/정상 처리 | 전부 확인됨 | **PASS** | |
| TC-009 | (AC-2) `--trade-date` 지정 시 캘린더 조회 생략 | pytest | `test_override_short_circuits_calendar_lookup`(빈 `FakeCalendar`) | override 값 그대로 반환 | 확인됨 | **PASS** | |
| TC-010 | (AC-2) 미지정 시 `get_last_trading_day` 재사용 계산 | pytest + 코드 정적 확인 | `test_no_override_uses_calendar` + `python -c "from shared.calendar_service import get_last_trading_day; import inspect; print(inspect.getsourcefile(get_last_trading_day))"` | 테스트 pass, 소스 파일이 `shared/calendar_service/last_trading_day.py`(UNIT-01 원본)로 확인 | 테스트 pass, `getsourcefile` 결과 `shared\calendar_service\last_trading_day.py` | **PASS** | 코디네이터 지시 ⑤ — 재사용 회귀 확인 |
| TC-011 | (AC-2) 캘린더 공백 → `SeedStockMasterError`, 단일/복수 페이지 정확 호출, `MAX_PAGES` 상한 초과 시 실패 | pytest | 나머지 4개 케이스 | 명시적 실패/정확한 호출 횟수 | 전부 확인됨(`client.calls==[1]`, `[1,2]`, `MAX_PAGES` 초과 시 raise) | **PASS** | |
| TC-012 | (AC-3) `GET /stocks` 6건(정상/빈결과/market 전달/query 공백 400/query 누락 400/market 허용값밖 400) | pytest | `test_search_stocks_*` 6건 | 전부 note §4 AC-3 서술과 일치 | 전부 확인됨(`repo.calls==[("삼성","ALL")]` 등) | **PASS** | |
| TC-013 | (코디네이터 지시 ①, 핵심) `itmsNm`/`mrktCtg`가 gov API에 실제로 존재하는지 **6단계가 직접** 공식 Swagger로 재대조 | 인터넷 접속 | `curl https://www.data.go.kr/data/15094808/openapi.do` 원문에서 `itmsNm`/`mrktCtg` 필드 존재·타입 정규식 추출(unit-02-test.md TC-021과 별도로, 이번엔 UNIT-03이 실제로 주장한 두 필드만 표적 재확인) | 두 필드 모두 `{"type":"string"}`로 스키마에 존재해야 함(상상으로 지어낸 필드가 아님) | 정확히 존재(`"itmsNm":{"type":"string",...}`, `"mrktCtg":{"type":"string",...}`) — note가 "UNIT-02 문서화 근거로 재사용"이라고 주장한 것이 실제로 원문에 기반함을 확인 | **PASS** | note는 "UNIT-02가 이미 문서화해 뒀다"고만 서술했는데, 6단계가 그 원 출처(공식 Swagger)까지 다시 거슬러 올라가 재확인함 — "문서가 문서를 인용"하는 정도로 그치지 않았다 |
| TC-014 | (코디네이터 지시 ①, 추가 발견) `mrktCtg`의 실제 표기 형식이 한글/영문 중 무엇인지 공식 스펙에 서술이 있는지 확인 | TC-013과 동일 문서 | `mrktCtg` 필드의 `description` 텍스트 전문 추출 | note/§2-6은 "실측 못해 두 표기 모두 방어적으로 처리"라고 서술 | 공식 스펙 `description`에 **"주식의 시장 구분 (KOSPI/KOSDAQ/KONEX 중 1)"**이라고 **영문 표기로 명시**되어 있음을 발견 — 이는 실제 응답 실측은 아니지만(여전히 실 키로 검증되지 않음), note가 "전혀 단서가 없다"는 뉘앙스로 서술한 것보다 근거가 더 있었음 | **PASS(정보 보완)** | 코드는 이미 한글/영문 양쪽을 방어적으로 처리하므로 기능적으로는 문제 없음(불필요할 수 있는 한글 매핑이 있어도 해가 되지 않음) — 결함은 아니고, note/traceability 서술 정확도를 보완하는 발견(unit-02-test.md DEF-005와 같은 성격) |
| TC-015 | (규칙B 2차 관점) 기존 UNIT-02 `_item()` 픽스처에 `itmsNm`/`mrktCtg`가 실제로 이미 존재했는지 정황 확인 | `tests/unit/test_gov_data_client.py` 코드 열람 | `_item()` 헬퍼와 기존 `test_fetch_ohlcv_*` 13건이 이 두 필드를 사용하지 않고도 통과함을 확인(필드가 있어도 무해하게 무시됨) | 필드가 존재해도 기존 OHLCV 파싱 로직·테스트에 영향 없음 | 확인됨 — `_item()`에 두 필드가 포함돼 있으나 `_parse_item()`은 이를 읽지 않음, 13건 전부 PASS | **PASS** | git 이력이 없는 저장소(전부 untracked)라 "UNIT-02 당시 이미 있었는지"를 커밋 diff로 직접 증명할 수는 없었다(한계로 남김) — 대신 공식 스펙 대조(TC-013)로 "그 필드들이 실존하고 상상이 아니다"는 더 중요한 질문에 답했다 |
| TC-016 | (코디네이터 지시 ②, AC-4) 완전 초기화 후 처음부터 재구성 — 5단계 자체 검증 신뢰하지 않음 | `alembic_version=0005`(head), 검증 시작 전 `stock_master`=0/`market_calendar`=730/`raw_ohlcv`=0 확인 | `alembic downgrade base` → `\dn`으로 전 스키마 제거 확인 → `alembic upgrade head`(0001~0005) → `\dn`/`\d public_serving.stock_master`로 재생성 확인 | downgrade 시 전 스키마 제거, upgrade 시 정확히 복원(컬럼/타입/PK 포함) | downgrade 후 `\dn` 결과 `public` 1개만 남음(완전 제거) → upgrade 후 4개 스키마 복원, `stock_master` 7개 컬럼(`stock_code, name, market, sector, listing_date, is_active, updated_at`) 타입/NOT NULL/기본값까지 설계서와 일치 | **PASS** | **부작용 발견**: 이 downgrade가 `reference.market_calendar`(730행)도 함께 삭제함 — §3 "테스트 데이터"에 투명하게 기록하고 즉시 복구(TC-027) |
| TC-017 | (코디네이터 지시 ②) GRANT가 우연이 아니라 마이그레이션 자체의 동작인지 확인 | TC-016 직후 head 상태 | `\dp public_serving.stock_master` | `batch_worker=arw`, `api_service=r` (0005가 GRANT를 포함하므로) | 정확히 `migrator=arwdDxt/migrator`, `batch_worker=arw/migrator`, `api_service=r/migrator` | **PASS** | DEF-003이 재발하지 않았음(완전 재구성 후에도 GRANT가 자동으로 붙음) |
| TC-018 | (코디네이터 지시 ②) `api_service`의 쓰기 거부를 3종(INSERT/UPDATE/DELETE) 전부 실제로 시도 | TC-017 이후 | `api_service` 계정으로 `INSERT INTO public_serving.stock_master ...`, 기존 행 대상 `UPDATE ... SET name=...`, `DELETE FROM ...` 각각 시도 | 3종 모두 `permission denied for table stock_master`, `SELECT`는 정상(빈 결과) | 3종 모두 정확히 `ERROR: permission denied for table stock_master`(SELECT는 0건으로 정상 응답) | **PASS** | note는 INSERT만 실측했음(§7) — 6단계가 UPDATE/DELETE까지 범위를 넓혀 재현(UNIT-01 v4가 UPDATE/INSERT/DELETE로 범위를 넓힌 것과 동일한 원칙 적용) |
| TC-019 | (위험 기반 추가, AC-4 연장) `batch_worker`의 DELETE 권한 부재 확인 | 상동 | `batch_worker` 계정으로 `DELETE FROM public_serving.stock_master WHERE stock_code='035720'` 시도(GRANT문이 `SELECT, INSERT, UPDATE`만 명시) | `permission denied for table stock_master`(DELETE 권한 없음) | 정확히 거부됨 | **PASS** | unit-02-test.md TC-035와 같은 원칙 — "arw"가 문자 그대로 append/read/write만이고 delete는 없음을 재확인. 뒷정리는 `migrator`로 수행 |
| TC-020 | (AC-4 정확한 문구 재현) `alembic downgrade 0004` 단일 스텝 → `stock_master` 테이블/`listed_market` ENUM만 제거, `batch_run`/기존 ENUM은 그대로 | head 상태 | `alembic downgrade 0004` → `\dt public_serving.*`, `\dT public_serving.*` | `stock_master` 테이블 없음, `listed_market` ENUM 없음, `batch_run`/`batch_run_type`/`batch_run_status`는 그대로 존재 | 정확히 일치(`\dt`에 `batch_run`만 남음, `\dT`에 `batch_run_status`/`batch_run_type`만 남음) | **PASS** | AC-4가 명시한 정확한 커맨드(`downgrade 0004`)로 별도 재현 — TC-016(base까지 전부 초기화)보다 좁은 범위지만 note의 문구와 1:1 대응 |
| TC-021 | (AC-4) `alembic upgrade head` 재적용 시 오류 없이 복원 및 GRANT 자동 재적용 | TC-020 직후 | `alembic upgrade head` → `\dp public_serving.stock_master`, `SELECT COUNT(*)` | 오류 없이 복원, `batch_worker=arw`/`api_service=r` 재적용, 데이터는 0행(다운그레이드로 비워졌으므로) | 정확히 일치, `market_calendar`는 730행 그대로 유지(이번엔 0004까지만 내려갔다가 다시 올라와 `reference` 스키마 자체는 건드리지 않음을 확인) | **PASS** | |
| TC-022 | (AC-5) `upsert_stock_master()`를 `batch_worker`로 직접 호출해 신규 2종목(KOSPI/KOSDAQ 각 1) 삽입 | `stock_master` 0행 | `batch_worker` 세션으로 `INSERT`(직접 SQL, 초기 데이터 준비) 후 확인 | `005930`(KOSPI)/`035720`(KOSDAQ) 2건 삽입 | 확인됨 | **PASS** | |
| TC-023 | (AC-5, 코디네이터 지시 ②) 동일 종목명 변경 후 재호출 → `updated_at` 실제 갱신, 변경되지 않은 행은 그대로 | TC-022 이후 | Python 스크립트로 `upsert_stock_master(session, [StockMasterSnapshotRecord(stock_code="035720", name="카카오(변경됨)", market="KOSDAQ")])` 직접 호출(2초 sleep 후), 실행 전/후 `updated_at` 비교 | `035720`의 `updated_at`만 갱신, `005930`은 그대로 | `035720`: `16:39:13.940665`→`16:40:01.406921`(갱신), `005930`: `16:39:13.940665`(불변) | **PASS** | **note와 다른 오염값(카카오, note는 삼성전자)으로 독립 재현** — 우연한 통과가 아님을 확인(코디네이터 지시 ②) |
| TC-024 | (위험 기반 추가) `sector`(범위 외 컬럼) upsert 시 보존 여부 + `is_active` 재동기화 동작 | TC-023 이후 | `migrator`로 `035720`의 `sector='IT'`, `is_active=false`로 직접 UPDATE → 동일 레코드로 `upsert_stock_master()` 재호출 | `set_`에 `sector`가 없으므로 `sector`는 `'IT'`로 보존되어야 함. `is_active`는 `set_`에 `True`가 고정값으로 있으므로 재동기화되어 `true`로 복귀 | 정확히 일치: `sector='IT'` 유지, `is_active`가 `false`→`true`로 자동 복귀 | **PASS(부수 발견 — §6 DEF-007)** | note가 "상장폐지 자동 감지 안 함"만 서술하고, "소스에 재등장하면 수동으로 내린 `is_active=false`가 자동으로 되돌아간다"는 반대 방향 동작은 문서화하지 않았음 — 운영 리스크로 기록 |
| TC-025 | (AC-5, 코디네이터 지시 ④) `GET /api/v1/stocks?query=<종목명 일부>` 실 API 종단간(대소문자/부분일치) | `api_service` 자격증명, `TestClient(app)`, `stock_master`에 `005930`(삼성전자, KOSPI)/`005935`(삼성전자우, KOSPI)/`035720`(카카오, KOSDAQ) | `query=삼성` | 부분일치로 2건(`삼성전자`, `삼성전자우`) 반환 | 정확히 2건 반환 | **PASS** | |
| TC-026 | (AC-5) `query=005930`(코드 완전일치) | 상동 | `query=005930` | `005930` 1건만 반환(코드도 검색 대상) | 정확히 1건 | **PASS** | |
| TC-027 | (AC-5) 코드 부분일치(`query=005`) | 상동 | `query=005` | `005930`/`005935` 2건(코드 prefix 부분일치) | 정확히 2건 | **PASS** | |
| TC-028 | (AC-5, 코디네이터 지시 ④) `market` 파라미터로 실제 필터링 확인 | 상동 | `query=카카오&market=KOSPI`(다른 시장) / `query=카카오&market=KOSDAQ`(정확한 시장) | 전자는 빈 배열, 후자는 1건(`카카오`) | 전자 `[]`, 후자 `[{"stock_code":"035720",...}]` | **PASS** | 3단계 v3가 확정한 `market`(KOSPI\|KOSDAQ\|ALL, 기본 ALL) 스펙(03-system-design.md §4-2 표, line 390)과 정확히 일치 |
| TC-029 | (AC-5) `market` 생략 시 기본값 `ALL` 실동작 | 상동 | `query=삼성`(market 파라미터 없음) | 코스피/코스닥 구분 없이 매칭(둘 다 KOSPI이긴 하나, 파라미터 부재 자체가 오류 없이 처리돼야 함) | 200 OK, 2건 정상 반환(400 아님) | **PASS** | |
| TC-030 | (AC-5) `is_active=false` 종목이 검색 결과에서 제외되는지 실제 쿼리로 확인 | `005935`를 `is_active=false`로 UPDATE | `query=삼성` 재호출 | `005930`(활성) 1건만 반환, `005935`(비활성) 제외 | 정확히 1건만 반환(`005935` 제외 확인) | **PASS** | 이후 원복 |
| TC-031 | (AC-5) 빈 값 `query`/공백만/파라미터 누락/허용값 밖 `market`을 실제 서버 응답으로 재확인 | 상동 | `query=""`, `query="   "`, `query` 자체 생략, `market=NASDAQ` 4가지 | 전부 400 `INVALID_PARAMETER` | 전부 정확히 400 `INVALID_PARAMETER` | **PASS** | |
| TC-032 | (위험 기반, 코디네이터 지시 ④ "엣지케이스") `market` 값 대소문자 구분(`kospi`, `all` 소문자) | 상동 | `market=kospi`, `market=all` | 설계서 §4-2가 `KOSPI\|KOSDAQ\|ALL`(대문자)만 명시하므로 소문자는 허용값 밖 → 400 | 둘 다 정확히 400 `INVALID_PARAMETER` | **PASS** | 대소문자 무관 허용이 스펙에 없으므로 엄격 검증이 올바른 동작 — 결함 아님 |
| TC-033 | (위험 기반, 코디네이터 지시 ④ "특수문자") `query="%"` — SQL LIKE 와일드카드 문자 그대로 입력 | 상동 | `query=%` | (기댓값 판단 필요) 종목명/코드에 `%`가 포함된 데이터가 없으므로 "결과 없음"이 사용자의 직관적 기대에 가까움 | **실제로는 3건 전체(삼성전자/삼성전자우/카카오)가 반환됨** — `pattern=f"%{query}%"`이 `"%%%"`가 되어 사실상 전체 매칭 | **FAIL(엣지케이스, §6 DEF-006)** | `services/public_api/db/stock_repository.py`가 사용자 입력을 SQL LIKE 패턴에 이스케이프 없이 그대로 삽입 — SQL 인젝션은 아니지만(파라미터 바인딩, TC-035로 별도 확인) 검색 의미상 오동작 |
| TC-034 | (위험 기반) `query="_"` — LIKE 단일문자 와일드카드 | 상동 | `query=_` | 위와 동일 이유로 "결과 없음"이 직관적 기대 | 3건 전체 반환(`_`가 아무 1문자와 매치되는 와일드카드로 해석됨) | **FAIL(엣지케이스, TC-033과 동일 원인, §6 DEF-006)** | |
| TC-035 | (보안 회귀 확인, 위험 기반) `query`에 SQL 인젝션 시도 문자열(`'; DROP TABLE stock_master; --`) | 상동 | 해당 문자열을 `query`로 전달 | 인젝션 실행 안 됨(SQLAlchemy 파라미터 바인딩), 단순히 매칭 없음 → 빈 배열, 테이블 존재 유지 | 200 OK, `data=[]`, 이후 `stock_master` 테이블/데이터 이상 없음 확인 | **PASS** | TC-033/034가 SQL 인젝션이 아니라 "LIKE 와일드카드 의미론" 문제임을 대조 확인하는 근거 — 파라미터 바인딩 자체는 안전 |
| TC-036 | (위험 기반) 교차 알파벳 검색(`query="samsung"`, 실제 데이터는 한글 "삼성전자") | 상동 | `query=samsung` | 결과 없음(음역/번역 매칭 요구가 설계서/AC에 없음) | `data=[]` | **PASS** | 결함 아님 — 스펙에 없는 기능을 요구하지 않는 것이 맞는 동작 |
| TC-037 | (설계 대조, 코디네이터 지시 ④) `GET /stocks` 계약이 03-system-design.md v3 확정 스펙과 정확히 일치하는지 원문 대조 | 03-system-design.md 열람 | §4-2 표(line 390) `GET /api/v1/stocks?query=` 행 원문과 `services/public_api/api/stocks.py`/`schemas/stocks.py` 코드 대조 | `query`(필수, 부분일치)/`market`(선택, KOSPI\|KOSDAQ\|ALL, 기본 ALL)/응답 `{stock_code,name,market}` 정확히 일치해야 함 | 코드가 설계서 문구와 정확히 일치(코드/스키마/에러코드 모두) | **PASS** | 상상이 아니라 설계서 원문과 1:1 대조 완료 |
| TC-038 | (코디네이터 지시 ③) `listing_date` nullable 처리가 REQ-001/04-ux-design §2-3과 충돌하는지 원문 대조 | 04-ux-design.md §2-3(line 226~264), 요구사항 매핑표(line 434) 열람 | "종목 검색" 화면 요구사항 매핑표 원문에서 `GET /stocks` 응답 중 실제로 화면에 필요한 필드 확인 | 표에 "종목명, 코드, 시장구분"만 명시되어 있어야 함(상장일 없음) | 정확히 "종목명, 코드, 시장구분"만 명시(line 434), `listing_date`/`sector` 언급 없음 | **PASS** | `listing_date` nullable 처리가 REQ-001 핵심 화면 기능을 막지 않음을 설계 문서 원문으로 확정(추측 아님) |
| TC-039 | (코디네이터 지시 ③, 설계서 대비 편차 확인) 03-system-design.md §3-2 `stock_master` 표 원문에서 `listing_date` 정의 재확인 | 03-system-design.md 열람(line 203~207) | `listing_date` 행 원문 확인 | `date` 타입만 명시, nullable 여부는 표기 없음(모호) | 정확히 "listing_date \| date \| 상장일"만 기재, NOT NULL 명시 없음 | **PASS(편차 확인, 결함 아님)** | 설계서가 nullable을 명시적으로 배제하지 않았으므로 5단계의 "상상으로 채우지 않고 nullable 처리" 결정이 설계서와 충돌하지 않는다고 판단(TC-038의 화면 요구사항 미사용과 결합해 REQ-001 완료 판정에 영향 없음으로 최종 결론) |
| TC-040 | (규칙 F 관점) `sector`/`listing_date`가 향후 UNIT-06(REQ-002, `derived_metrics_daily`)에 영향 주는지 설계서 §3-2 `derived_metrics_daily` 정의 확인 | 03-system-design.md §3-2 열람 | `derived_metrics_daily`가 `stock_master`의 `sector`/`listing_date`를 참조하는지 확인 | 참조하지 않아야 영향 없음 | `derived_metrics_daily`는 `stock_code`만 참조하고 `sector`/`listing_date`를 직접 사용하지 않음(홈 화면의 업종 통계는 `market_summary_daily.top_sectors_by_value`가 별도 담당 — line 433이 이미 "출처 미확정, 별개 리스크"로 명시) | **PASS** | UNIT-06~08 착수를 막는 결함이 아님을 확인 |
| TC-041 | (범위 외 변경 확인) `gov_data_client.py` 외 UNIT-02 산출물에 "UNIT-03" 마커나 의도치 않은 수정이 있는지 | `services/ingestion_batch/` 전체 | `grep -rl "UNIT-03\|unit-03"` | `gov_data_client.py` 1개 파일에서만 발견되어야 함 | 정확히 `gov_data_client.py` 1개 파일에서만 발견 | **PASS** | `models.py`/`repository.py`/`run_ingestion.py`/`batch_run_repository.py`는 UNIT-03 착수 근거가 코드에 남아있지 않음(회귀 없음) |
| TC-042 | (범위 외 변경 확인) `shared/db_models/__init__.py` diff 검토 | 코드 열람 | 파일 전문 확인 | `StockMaster` export 추가 외 다른 변경 없어야 함 | `Base, BatchRun, StockMaster, MarketCalendar` export만 존재, 최소 변경 확인 | **PASS** | |
| TC-043 | (코디네이터 지시 ⑤, 회귀) `pytest tests/unit`(79건)·`ruff check .` 재실행 결과가 UNIT-01(36건)+UNIT-02(23건)+UNIT-03(20건)=79건과 정확히 일치 | TC-002/003 | 파일별 카운트 재분해 | 36+23+20=79 | `test_calendar_file.py`10 + `test_last_trading_day.py`20 + `test_public_api.py`(기존)6 = 36(UNIT-01), `test_gov_data_client.py`(기존)13 + `test_circuit_breaker.py`6 + `test_run_ingestion.py`4 = 23(UNIT-02), `test_gov_data_client.py`(신규)8 + `test_seed_stock_master.py`6 + `test_public_api.py`(신규)6 = 20(UNIT-03) → 36+23+20=79 | **PASS** | |
| TC-044 | (코디네이터 지시 ⑤, 회귀) UNIT-01/02가 검증한 DB 권한 경계가 이번 완전 재구성 후에도 유지되는지 | TC-016 완전 재구성 이후 | `\dp reference.market_calendar`, `\dp raw_internal.raw_ohlcv`(api_service 행 없음) 재확인 | `reference`: `batch_worker`/`api_service` 둘 다 권한 존재, `raw_internal`: `api_service` 권한 자체 없음(0002/0004 그대로) | 정확히 일치, 0002/0004의 GRANT 문구가 이번 재구성에서도 그대로 재현됨 | **PASS** | UNIT-03 작업이 UNIT-01/02의 권한 모델을 훼손하지 않음을 확인 |

> 표에 없는 5단계 note §6 코드 리뷰 체크리스트 4개 항목(설계서 일치/에러처리 누락 없음/입력검증/시크릿 하드코딩 없음/범위 외 변경 없음)은 위 TC들(특히 TC-037/041/042)과 아래 "코드 리뷰 재확인"으로 교차 검증했다.

### 코드 리뷰 재확인 (게이트 2 독립 재검증)
- `shared/market_types.py`, `shared/db_models/public_serving.py`, `db/alembic/versions/0005_*.py`, `scripts/seed_stock_master.py`, `services/public_api/{api,db,schemas}/stocks.py`, `services/ingestion_batch/gov_data_client.py` 전체를 직접 읽고 확인:
  - 예외를 삼키는 `except: pass` 류 코드 없음(전부 명시적 재발생 또는 400/1 종료코드로 귀결).
  - 시크릿 하드코딩 없음: DB 접속 정보/서비스키 모두 환경변수(`BATCH_DATABASE_URL`/`PUBLIC_API_DATABASE_URL`/`GOV_DATA_PORTAL_SERVICE_KEY`)로만 주입, 검증 세션에서도 셸 환경변수로만 `devpass` 주입(코드/설정 파일에 커밋 없음).
  - SQL 인젝션 방지: `stock_repository.py`가 SQLAlchemy `select()`/파라미터 바인딩만 사용, 문자열 조합 없음(TC-035로 실측 확인). 단 **LIKE 와일드카드 문자 자체를 이스케이프하지 않는 것은 별개 문제**로 DEF-006에 등록(§6).
  - 5단계 게이트2 체크리스트 4항목 중 "설계서/디자인서 일치"는 TC-037/038/039로, "범위 외 변경 없음"은 TC-041/042로 대체 불가능한 방식(원문 대조·정적 grep)으로 재확인했다 — note의 자체 체크(✅ 표시)를 그대로 믿지 않았다.

## 5. 커버리지
- AC-1~AC-6 전 항목 1:1 매핑 완료(TC-001~TC-012, 표의 "비고"에서 대응 AC 명시). 커버리지 100%.
- 코디네이터 지시 5개 항목 전부 매핑: ①TC-013/014/015, ②TC-016~TC-024, ③TC-038/039/040, ④TC-025~TC-037, ⑤TC-002/003/043/044.
- AC에 없는 위험 기반 케이스 11건을 자체적으로 추가(TC-019 DELETE 권한 경계, TC-024 sector 보존/is_active 재동기화, TC-032 market 대소문자, TC-033/034 LIKE 와일드카드 특수문자 — **결함 발견**, TC-035 SQL 인젝션 회귀, TC-036 교차 알파벳, TC-041/042 범위 외 변경 확인, TC-020/021 AC-4 정확 문구 재현).
- 커버되지 않은 부분: 실 서비스키로 `fetch_stock_master_snapshot()` 정상 응답 수신(§2 제외범위, UNIT-02와 동일한 환경 제약), `MAX_SEARCH_RESULTS=100` 경계값 실측, 부하/동시성.

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도 | 상태 | 조치 내용 |
|----|------|-----------|--------|------|-----------|
| DEF-006 | `services/public_api/db/stock_repository.py`의 `pattern = f"%{query}%"`가 사용자 입력의 SQL LIKE 와일드카드 문자(`%`, `_`)를 이스케이프하지 않아, 사용자가 `query="%"` 또는 `query="_"`를 입력하면 부분일치 검색 의도와 달리 **전체 종목이 매칭**된다(SQL 인젝션은 아님 — TC-035로 파라미터 바인딩 안전성 별도 확인). | TC-033/TC-034 그대로 재현: `GET /api/v1/stocks?query=%25`(URL 인코딩된 `%`) 또는 `query=_` 호출 시 `stock_master`에 있는 모든 활성 종목이 반환됨 | Low | **Open** | AC-3/AC-5의 어떤 불릿도 위반하지 않고(둘 다 이 케이스를 명시하지 않음), 03-system-design.md §4-2도 이스케이프를 요구하지 않아 배포를 차단할 사유는 아니다. 다만 공개 무인증 검색 엔드포인트의 입력 검증 원칙(보안담당자 관점)상 바람직하지 않으므로, 후속 유닛(또는 이번 유닛 재작업 시)에 `query.replace("%", r"\%").replace("_", r"\_")` 후 `escape="\\"` 옵션을 `ilike`에 전달하는 수정을 권고한다. `MAX_SEARCH_RESULTS=100` 상한이 있어 DoS로 이어지지는 않는다(피해 범위 제한적 — Low 유지 근거). |
| DEF-007 | `scripts/seed_stock_master.py`의 `upsert_stock_master()`가 매 upsert마다 `is_active`를 무조건 `True`로 재설정한다(코드 자체는 note가 의도한 대로 동작하나, note는 "상장폐지 자동 미감지"만 서술했고 **"운영자가 수동으로 `is_active=false` 처리한 종목이 소스에 재등장하면 다음 시드 실행 시 자동으로 다시 `true`로 복귀한다"는 반대 방향 동작은 문서화하지 않았다**). | TC-024 그대로 재현: 임의 종목을 `is_active=false`로 수동 설정 → 동일 종목 코드로 `upsert_stock_master()` 재호출 → `is_active`가 `true`로 복귀 | Low | **Open(문서화 미비, 코드 결함 아님)** | REQ-001 AC 위반 아님(자동 상장폐지 감지는애초에 요구되지 않음). 다만 "수동 개입이 다음 배치로 덮어써질 수 있다"는 운영 리스크이므로, `unit-03-note.md` §2-4(설계서 대비 편차) 또는 향후 운영 절차 문서에 이 반대 방향 동작을 명시할 것을 권고(5단계 재작업 강제까지는 아님 — unit-02-test.md DEF-005와 동일한 처리 수준: 문서 정확도 이슈로 인계). |

- **그 외 결함 없음.** 근거: TC-001~TC-044(총 44개 테스트 케이스, AC-1~AC-6 100% 커버 + 코디네이터 지시 5개 항목 + 위험 기반 추가 11건)를 실행해 정상 경로(TC-005,009,012,022,025~029)·경계값(TC-007,011,020,021,024,032)·예외 입력(TC-008,011,031,033~036)·권한 경계(TC-018,019,044)를 모두 포함해 확인했고, "실행해보니 에러 없음"이 아니라 매 케이스마다 기대 결과(AC/설계서 원문 근거)와 실제 결과(쿼리/응답 캡처)를 대조했다. DEF-006/007을 제외한 모든 케이스가 기대와 실제가 일치했다.

## 7. 리스크 및 잔존 이슈
- **DEF-006(LIKE 와일드카드 미이스케이프)**: 위 §6 참조. 배포 차단 사유는 아니나 후속 개선 권고.
- **DEF-007(is_active 자동 재동기화 문서화 미비)**: 위 §6 참조. 운영 절차 문서화 시 반영 필요.
- **실 서비스키 미보유**: `itmsNm`/`mrktCtg`가 실제 응답에서 정확히 이 형식으로 오는지, `mrktCtg`가 실제로 영문(KOSPI/KOSDAQ)으로 오는지(TC-014가 공식 스펙 설명문에서 영문 표기 근거를 찾았으나 실측은 아님)는 여전히 미확인 — 실 키 확보 시 최우선 재검증 필요(UNIT-02와 동일한 승계 리스크).
- **`sector`/`listing_date` 출처 미확정**: REQ-001 핵심 기능(TC-038/039로 확인)에는 영향 없으나, UNIT-06 이후 업종 통계(`market_summary_daily.top_sectors_by_value`)가 `sector`를 필요로 하게 되면 그때 반드시 재검토 필요(설계서 §8-2 항목8 승계).
- **`MAX_SEARCH_RESULTS=100` 실측 미검증**: 로직 검토로는 안전(단순 `LIMIT`)하나 실제 100건 초과 데이터로 잘림 동작을 확인하지 않았다.
- **6단계 검증 행위 자체의 부작용**: `alembic downgrade base` 재현 중 `reference.market_calendar` 730행이 일시 삭제되었다가 복구됨(§3 참조) — 향후 6단계가 유사 완전 재구성 검증을 할 때는 검증 전후로 반드시 캘린더 데이터 건수를 스냅샷/복구하는 절차를 표준화할 것을 제안한다(운영 관점 권고, 이번 유닛 자체의 결함은 아님).

## 8. 결론 및 판정
- [x] **PASS** — 다음 단계(07 통합테스트) 진행 가능.
  - AC-1~AC-6 전 항목 독립 재검증 완료(TC-001~TC-012).
  - 코디네이터 지시 5개 항목 전부 확인 완료:
    - ① gov API 필드 근거: `itmsNm`/`mrktCtg`가 "상상"이 아니라 data.go.kr 공식 Swagger 원문(TC-013)에 실제로 존재함을 6단계가 직접 재확인했고, `mrktCtg` 값 형식이 영문(KOSPI/KOSDAQ/KONEX)이라는 추가 근거(TC-014)까지 발견했다(정보 보완, note 서술보다 근거가 더 있었음 — 결함 아님).
    - ② GRANT/`updated_at`: 완전 초기화(`downgrade base`) 후 처음부터 재구성해 GRANT가 우연이 아님을 재확인(TC-016/017), `api_service`의 INSERT/UPDATE/DELETE 3종 전부 재현(TC-018, note는 INSERT만), `updated_at`을 note와 다른 오염값(카카오)으로 독립 재현해 갱신/불변을 동시에 확인(TC-023) — **DEF-003/DEF-004급 재발 없음** 확정.
    - ③ `listing_date` nullable: 03-system-design.md §3-2 원문(TC-039)과 04-ux-design.md §2-3 요구사항 매핑표 원문(TC-038)을 직접 대조해 REQ-001 핵심 기능과 충돌하지 않음을 추측이 아닌 문서 근거로 확정.
    - ④ `market` 필터 스펙 일치·검색 엣지케이스: 03-system-design.md §4-2 원문과 코드가 정확히 일치함을 확인(TC-037)했고, 빈 문자열/공백/파라미터 누락/허용값 밖/대소문자(TC-031/032)뿐 아니라 **LIKE 와일드카드 특수문자(TC-033/034)에서 실제 결함(DEF-006)을 발견**했다 — "테스트가 결함을 놓칠 뻔한" 지점을 위험 기반 케이스 확장으로 잡아냈다.
    - ⑤ 회귀: `pytest tests/unit`(79건)·`ruff check .` 독립 재실행(TC-002/003/043), UNIT-01/02의 DB 권한 경계가 완전 재구성 후에도 유지됨을 확인(TC-044), `gov_data_client.py` 외 UNIT-02 산출물에 범위 외 변경 없음 확인(TC-041/042).
  - 결함 2건(DEF-006, DEF-007) 모두 **Low, Open** — AC 위반 없음, 배포 차단 사유 아님(unit-02-test.md DEF-005와 동일한 처리 수준). 후속 유닛/운영 문서화 과제로 인계.
  - `traceability.md`의 REQ-001 "단위테스트" 컬럼을 이 문서로 갱신(§9 아래 별도 반영 완료).

## 9. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

### 1차 검증 (작성자 관점 자가 재검토)
- 검증자(역할): 06-unit-tester(작성자 본인)
- 일시: 2026-09-15
- 체크리스트
  - [x] AC-1~AC-6 각 불릿에 대응하는 TC가 존재하는가 → note §4와 1:1 대조 완료(TC-001~TC-012 매핑표 참조), 누락 없음.
  - [x] 예상 결과가 실제로 명세(AC/설계서 원문)에 근거하는가 → TC-037/038/039/040은 코드가 아니라 설계서/UX문서 원문을 직접 인용해 기댓값을 정했다(추측 아님).
  - [x] "실행해보니 에러 없음"이 아니라 기대-실제를 비교했는가 → 전 TC에 "예상 결과"/"실제 결과" 열을 분리 기재, 특히 TC-033/034는 "에러가 안 났다"는 이유로 PASS 처리하지 않고 결과 건수(3건 전체 반환)가 기대(0건)와 다름을 근거로 **FAIL 처리 후 DEF-006 등록**했다.
  - [x] 코디네이터 지시 5개 항목 전부 커버했는가 → §8에서 5개 항목별로 대응 TC 명시.
  - 발견된 결함: 위 §6 DEF-006/DEF-007.
  - 조치 내용: 두 결함 모두 AC 범위 밖·Low 심각도로 판단해 코드를 직접 수정하지 않고(6단계 권한 범위) 결함 기록으로 남기고 5단계/운영 인계 대상으로 명시했다. → v1(최종)로 확정.

### 2차 검증 (독립 심사자 관점 — "오늘 처음 이 문서를 받아본 심사자")
- 검증자(역할): 06-unit-tester(역할 전환 재검토)
- 일시: 2026-09-15
- 체크리스트
  - [x] 1차에서 지적된 항목이 실제로 반영되었는가 → DEF-006/007 모두 §6에 재현 절차·심각도·상태·조치가 빠짐없이 기재됨을 재확인.
  - [x] 엣지 케이스가 누락되지 않았는가 → "5단계가 gov API 필드 존재를 상상으로 판단한 게 아닌가"라는 의심에서 출발해, note가 인용한 UNIT-02의 근거를 다시 UNIT-02 원 출처(공식 Swagger)까지 거슬러 올라갔다(TC-013). 이 과정에서 "note가 서술 안 한 추가 정보"(mrktCtg 영문 표기 근거, TC-014)까지 찾아냈다 — 검증자가 "note를 검증"하는 데 그치지 않고 "note의 근거의 근거"까지 확인한 것이 이 문서의 핵심 가치다.
  - [x] "이 테스트를 통과했다고 07 통합테스트에 넘겨도 되는가" → `query=%`/`query=_` 케이스를 처음에는 "AC 범위 밖이니 생략해도 되지 않나"라고 넘어갈 뻔했으나, 오케스트레이터가 명시적으로 "검색 로직의 엣지케이스(특수문자)"를 요구했으므로 되짚어 실행했고 실제 결함(DEF-006)을 찾았다 — **이것이 "테스트 자체가 결함을 놓칠 뻔한" 사례**: AC-3/AC-5 문면만 따라갔다면 이 결함은 07 통합테스트로 그대로 넘어갔을 것이다.
  - [x] 되돌리기 어려운 결정(마이그레이션 downgrade)에 대한 근거가 명시되어 있는가 → §3에 `downgrade base`가 `market_calendar`를 일시 삭제한 부작용과 복구 절차를 투명하게 기록했다(감추지 않음).
  - [x] 보안/성능/운영 관점에서 명백히 위험한 내용이 없는가 → SQL 인젝션은 파라미터 바인딩으로 안전함을 별도 케이스(TC-035)로 재확인해, DEF-006이 "인젝션"이 아니라 "검색 의미론 오동작"임을 명확히 구분했다(과잉 심각도 부여도, 과소평가도 하지 않음).
  - 발견된 결함: 없음(1차에서 발견한 DEF-006/007 외 신규 없음). 다만 §3에 "검증 행위 자체의 부작용"을 투명하게 공개하도록 서술을 보강했다(2차에서 추가).
  - 조치 내용: 서술 보강만 반영, 결함 목록 변경 없음 → 최종(v1).

- 검증 로그 파일 경로: 이 문서(`docs/harness/units/unit-03-test.md`) §9에 통합 기록(별도 `verify-log_unit-03-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — UNIT-01/02 test.md와 동일한 관례를 따름).

## 최종 판정
- [x] PASS (결함 0건이 아니나 전부 Low/Open·AC 비위반으로 배포 비차단, 최소 2회 검증 완료) — 다음 단계(07 통합테스트)로 handoff 가능.
