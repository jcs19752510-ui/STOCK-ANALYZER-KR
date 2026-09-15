# 테스트 결과서 (Test Result Report) — UNIT-02

> 버전: v1(최초이자 최종). 5단계 산출물(`unit-02-note.md`)의 자체 보고("59개 테스트 pass", "raw_internal 권한 분리 확인", "실 서비스키 없이 게이트웨이 오류만 실측")를 **신뢰의 근거로 삼지 않고**, UNIT-01 재검증 때와 동일한 원칙으로 전부 독립 재현했다.

## 1. 개요
- 테스트 대상: **UNIT-02 (데이터 수집/적재 파이프라인, REQ-011)** — `services/ingestion_batch/*`(`gov_data_client.py`, `circuit_breaker.py`, `run_ingestion.py`, `repository.py`, `batch_run_repository.py`, `calendar_lookup.py`, `models.py`, `core/config.py`), `db/alembic/versions/0003_create_public_serving_batch_run.py`, `db/alembic/versions/0004_create_raw_internal_ohlcv_fundamentals.py`, `shared/db_models/public_serving.py`
- 테스트 유형: 단위(Unit) — 파이프라인 6단계
- 테스트 목적: `unit-02-note.md` §4 인수 조건(AC-1~AC-6)이 실제로 충족되는지 독립 재검증하고, 코디네이터가 명시적으로 지시한 5개 확인 항목(①GRANT/`api_service` 접근 거부 직접 재현, ②"API 키 없이 검증 못함" 정직성 및 목/픽스처가 실제 공식 스펙과 일치하는지, ③raw_fundamentals 범위 축소의 정확성, ④재시도/서킷브레이커 실동작, ⑤UNIT-01 `get_last_trading_day()` 재사용 회귀)를 확인하는 것.
- 관련 산출물: `docs/harness/03-system-design.md`(v4, PASS) §1-2/§1-3/§2-2/§3-2/§5-4, `docs/harness/02-planning.md`(v3) §9 UNIT-02, `docs/harness/units/unit-02-note.md`(5단계 산출물), `docs/harness/units/unit-01-test.md`(v4, 최종 — DEF-003 교훈 원본)
- 테스트 수행자(에이전트): 06-unit-tester
- 테스트 일시: 2026-09-15

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope): AC-1~AC-6 전체 1:1 추적, 코디네이터 지시 5개 항목, 5단계 게이트1(정적분석)/게이트2(코드리뷰 체크리스트) 통과 여부의 독립 재확인, 위험 판단에 따른 AC 외 경계값/예외 입력 추가 테스트(빈 문자열 서비스키, 잘못된 CLI 인자, 페이지네이션 미배선으로 인한 PARTIAL 분기, 실 시간 기반 백오프 측정).
- 제외 범위 및 사유:
  - **실제 유효 서비스키로 정상 시세 응답 수신 종단검증**: 유효 키 미보유(코디네이터 확인). 대신 실 엔드포인트에 무효 키로 직접 호출해 게이트웨이 오류 경로는 실측 재현했고, 정상 응답 파싱 로직은 (a) 목 기반 단위테스트, (b) data.go.kr 공식 스펙 메타데이터(아래 TC-021) 교차검증으로 대체했다. 실 키 확보 시 재검증 필수(리스크로 이관).
  - **PER/PBR 실제 적재 로직 자체**: 5단계가 의도적으로 구현하지 않았음(§0-3). 이 유닛의 인수 조건(AC-1~AC-6)에도 raw_fundamentals 적재는 포함되어 있지 않으므로 "미구현 검증 대상 없음"이 정확한 서술이지 "테스트 누락"이 아니다. 다만 이 범위 축소의 근거 자체는 아래 TC-022에서 검증했다(→ DEF-005 발견, §6 참조).
  - **실제 컨테이너/cron 배포**: 10단계(배포테스트) 영역, `unit-02-note.md` §3에서도 명시.
  - **NXT 데이터 커버리지, 호출 한도 실측치**: `decisions.md` DEC-010 승계, 실 키 미보유로 이번에도 확인 불가(5단계와 동일 제약, 재확인 불필요).

## 3. 테스트 환경
- OS/런타임: Windows 10 (Git Bash), Python 3.13, pytest, ruff.
- DB: 로컬 Docker 컨테이너 `stock-screener-db`(`postgres:16-alpine`, 포트 5432, DB `stock_screener`), 역할 `migrator`(SUPERUSER)/`batch_worker`/`api_service`(비밀번호 `devpass`, UNIT-01부터 재사용). 세션 시작 시 `docker ps`로 `Up 5시간` 상태 확인.
- 네트워크: 실제 인터넷 접속 가능 확인 — `https://apis.data.go.kr/...getStockPriceInfo`(공공데이터포털 실 엔드포인트), `https://www.data.go.kr/data/15094808/openapi.do`(동일 서비스 공식 Swagger/OpenAPI 메타데이터 페이지, 인증 없이 200 응답)에 curl로 직접 접근해 사용.
- 테스트 데이터: 이번 세션 시작 시 `raw_internal.raw_ohlcv`/`public_serving.batch_run` 0행, `reference.market_calendar` 730행(UNIT-01이 남겨둔 상태) 확인 후 시작. 각 시나리오 사이 `migrator` 계정으로 `TRUNCATE`(batch_worker는 DELETE 권한이 없어 migrator로 수행 — 아래 TC-018 참고), 세션 종료 시 원상 복구(0행/0행/730행) 확인.
- 전제 조건: `ALEMBIC_DATABASE_URL`/`BATCH_DATABASE_URL` 환경변수를 `devpass`로 직접 설정해 사용(코드/설정 파일에 커밋하지 않음).

## 4. 테스트 케이스 및 결과

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-001 | (AC-6) 정적분석 독립 재실행 | 저장소 루트 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** | 5단계 자체 보고와 별개로 직접 재실행 |
| TC-002 | (AC-6) 전체 단위테스트 스위트 독립 재실행 | 상동 | `python -m pytest tests/unit -q` | 59 passed | `59 passed, 1 warning in 1.38s` | **PASS** | |
| TC-003 | (AC-6 세부) 파일별 테스트 수 분해 검증 | 상동 | `pytest -v` 결과를 파일별로 집계 | UNIT-01 36건(`test_calendar_file.py` 10 + `test_last_trading_day.py` 20 + `test_public_api.py` 6) + UNIT-02 23건(`test_gov_data_client.py` 13 + `test_circuit_breaker.py` 6 + `test_run_ingestion.py` 4) = 59 | 정확히 일치(10/20/6/13/6/4) | **PASS** | note의 "36+23=59" 분해 주장이 숫자 조작이 아님을 확인 |
| TC-004 | (AC-1) 정상 응답, item 리스트 파싱 | MockTransport | `test_fetch_ohlcv_success_single_item_as_list` 등 13건 pytest 실행 | 전부 pass | 전부 pass(TC-002에 포함) | **PASS** | |
| TC-005 | (AC-1) items="" → 0건, 예외 아님 | 상동 | `test_fetch_ohlcv_zero_results_returns_empty_list` | `records=[]`, 예외 없음 | 확인됨 | **PASS** | |
| TC-006 | (AC-1) resultCode≠00 → 즉시 실패(재시도 없음) | 상동 | `test_fetch_ohlcv_business_error_result_code_not_00_raises_immediately` | `GovDataApiError(retryable=False)`, 호출 1회 | 확인됨 | **PASS** | |
| TC-007 | (AC-1) 게이트웨이 XML 오류 → 즉시 실패 | 상동 | `test_fetch_ohlcv_gateway_xml_auth_error_non_retryable` | 호출 1회, retryable=False | 확인됨 | **PASS** | |
| TC-008 | (AC-1) 게이트웨이 JSON 오류(실측 회귀) → 즉시 실패 | 상동 | `test_fetch_ohlcv_gateway_json_auth_error_non_retryable` | 호출 1회, retryable=False | 확인됨 | **PASS** | TC-020/TC-021이 이 테스트의 전제(실측 형태)가 실제인지 별도로 재검증 |
| TC-009 | (AC-1) 재시도 대상 게이트웨이 오류(22) → 4회 호출, 백오프 1/2/4s(모의 sleep) | 상동 | `test_fetch_ohlcv_gateway_xml_rate_limit_error_retryable_then_raises` | `call_count==4`, `sleeps==[1,2,4]` | 확인됨 | **PASS** | 모의 sleep 기준. 실제 시간 경과는 TC-023에서 별도 검증 |
| TC-010 | (AC-1) HTTP 5xx → 재시도 후 실패 / HTTP 4xx(게이트웨이 아님) → 즉시 실패 | 상동 | `test_fetch_ohlcv_http_500_retries_then_raises_client_error`, `test_fetch_ohlcv_http_400_raises_immediately_without_retry` | 5xx: 4회 호출 후 실패 / 4xx: 1회 호출 즉시 실패 | 확인됨 | **PASS** | |
| TC-011 | (AC-1) 타임아웃 재시도 후 실패, 일시 실패 후 회복 | 상동 | `test_fetch_ohlcv_timeout_retries_then_raises`, `test_fetch_ohlcv_recovers_after_transient_failure` | 타임아웃 재시도 소진 후 실패 / 2회차 성공 시 정상 반환 | 확인됨 | **PASS** | |
| TC-012 | (AC-1) basDt 불일치·필수 필드 누락 → 명시적 실패 | 상동 | `test_fetch_ohlcv_bas_dt_mismatch_raises`, `test_fetch_ohlcv_missing_required_field_raises` | `GovDataClientError` | 확인됨 | **PASS** | |
| TC-013 | (AC-2) 서킷브레이커 6개 시나리오(임계치 미만/이상/스트릭 끊김/SUCCESS·PARTIAL 모두/빈 이력/초과 지속) | pytest | `pytest tests/unit/test_circuit_breaker.py -v` | 6건 전부 pass, 로직이 설계서 §5-4("연속 실패 일수" 기준, 요청 차단 아님)와 일치 | 6건 pass, 코드 리뷰로 요청 차단 로직이 없음(알림 신호만 냄) 확인 | **PASS** | |
| TC-014 | (AC-3) `--trade-date` 지정 시 캘린더 조회 생략 | pytest | `test_override_short_circuits_calendar_lookup`(빈 `FakeCalendar`로도 성공해야 함) | override 값 그대로 반환 | 확인됨 | **PASS** | |
| TC-015 | (AC-3) 미지정 시 UNIT-01 `get_last_trading_day()` 재사용 계산 | pytest + 코드 정적 확인 | `test_no_override_uses_calendar` + `python -c "from shared.calendar_service import get_last_trading_day; ...; print(inspect.getsourcefile(...))"` | 테스트 pass, 소스 파일이 `shared/calendar_service/last_trading_day.py`(UNIT-01 원본)로 확인되어 재구현이 아님 | 테스트 pass, `getsourcefile` 결과 `shared\calendar_service\last_trading_day.py` 확인 | **PASS** | 코디네이터 지시 ⑤ — 재사용 회귀 확인 완료 |
| TC-016 | (AC-3) 캘린더 공백/무결성 위반 전파 | pytest | `test_calendar_gap_raises_ingestion_run_error`, `test_calendar_integrity_error_propagates` | `IngestionRunError` / `CalendarDataError` 그대로 전파 | 확인됨 | **PASS** | |
| TC-017 | (AC-4) 전체 downgrade→upgrade 사이클, 스키마/GRANT 재구성 확인(독립 재현) | `alembic_version=0004`(head) | `alembic downgrade 0002` → `\dn`으로 두 스키마 완전 제거 확인 → `alembic upgrade head` → `\dn`/`\dp`로 재생성 확인 | downgrade 시 `public_serving`/`raw_internal` 완전 제거, upgrade 시 정확히 복원 | downgrade 후 `\dn` 결과 `public`/`reference` 2개만 남음(제거 확인) → upgrade 후 4개 스키마 복원, `\dp public_serving.batch_run`→`batch_worker=arw`,`api_service=r`, `\dp raw_internal.raw_ohlcv`/`raw_fundamentals`→`batch_worker=arw`만 존재·`api_service` 행 자체 없음 | **PASS** | 5단계 note의 검증을 신뢰하지 않고 이번 세션에서 처음부터 재실행(UNIT-01 v4와 동일 원칙) |
| TC-018 | (AC-4, 코디네이터 지시 ①) `api_service`로 `raw_internal` 직접 접근 시도 | TC-017 이후 head 상태 | `docker exec ... psql -U api_service -d stock_screener -c "SELECT * FROM raw_internal.raw_ohlcv;"` 및 `raw_fundamentals` 동일 시도 | `permission denied for schema raw_internal`(테이블 접근 이전에 스키마 USAGE 자체가 거부) | 두 테이블 모두 정확히 `ERROR: permission denied for schema raw_internal`(종료코드 1) | **PASS** | proxy 스키마가 아니라 **실제 `raw_internal.raw_ohlcv`/`raw_fundamentals`에 직접** 접근 시도 — UNIT-01 v3가 대역(proxy)으로만 검증했던 것을 이번에 실제 대상으로 확정 |
| TC-019 | (AC-4 추가, 위험 기반) `api_service`가 `public_serving.batch_run`에 INSERT 시도(읽기 전용이어야 함) | 상동 | `INSERT INTO public_serving.batch_run (...) VALUES (...)` as `api_service` | `permission denied for table batch_run`(SELECT만 허용, 쓰기 거부) | `ERROR: permission denied for table batch_run` | **PASS** | AC-4에 명시되지 않았으나 "api_service=r"의 실제 의미(쓰기 불가)를 별도로 확인한 위험 기반 추가 케이스 |
| TC-020 | (코디네이터 지시 ②) 게이트웨이 오류 실측 재현(독립) | 인터넷 접속 | `curl`로 실 엔드포인트에 무효 키로 `resultType=json`/`xml` 두 경우 직접 호출(5단계와 다른 시각에 재현) | HTTP 403 + JSON 봉투(`resultType=json`), HTTP 403 + XML 봉투(기본값) | 정확히 일치(`{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"errMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR",...,"returnReasonCode":"30"}}}` 및 동일 필드의 XML) | **PASS** | note §0-2의 실측 주장을 이번 세션에서 별도로 재현해 "우연한 1회성 관찰"이 아님을 확인 |
| TC-021 | (코디네이터 지시 ②, 핵심) 정상 응답 파싱 가정이 **실제 공식 스펙**과 일치하는지 교차검증 | 인터넷 접속 | `https://www.data.go.kr/data/15094808/openapi.do`(이 서비스의 공식 OpenAPI/Swagger 메타데이터, 인증 없이 200 OK로 공개) 원문을 가져와 응답 스키마 필드명을 정규식으로 추출·대조 | `gov_data_client.py`/테스트가 가정한 필드(`response.header.{resultCode,resultMsg}`, `response.body.{numOfRows,pageNo,totalCount,items.item}`, item 필드 `basDt,srtnCd,isinCd,itmsNm,mrktCtg,clpr,mkp,hipr,lopr,trqu,trPrc,lstgStCnt,mrktTotAmt`)가 공식 문서와 정확히 일치해야 함(상상으로 지어낸 필드가 아님) | 공식 Swagger 원문에서 위 필드 전부 정확히 발견됨(예: `"resultCode":{"type":"string",...}`, `"body":{"type":"object","properties":{"numOfRows":...}}`, item 하위에 `mkp/hipr/lopr/clpr/trqu/trPrc/basDt/srtnCd/isinCd/itmsNm/mrktCtg/lstgStCnt/mrktTotAmt` 전부 확인) | **PASS** | **이번 6단계가 직접 발견한 검증 경로**: 5단계는 "공개 문서 근거"라고만 서술했으나 어떤 문서인지 URL을 명시하지 않았다. 이 문서(공식 Swagger)를 6단계가 직접 찾아 필드 단위로 대조해, "상상으로 지어낸 가짜 스펙이 아님"을 문서적으로 확정했다 |
| TC-022 | (코디네이터 지시 ③) raw_fundamentals 범위 축소 근거 정밀 검증 | TC-021과 동일 문서 | TC-021에서 추출한 `getStockPriceInfo` 응답 필드 목록에 PER/PBR/시가총액 관련 필드가 있는지 확인 | note는 "PER/PBR/**시가총액**을 이 오퍼레이션이 제공하는지 확인 못함"이라고 서술 | 공식 스펙에 **PER/PBR 필드는 없음**(범위 축소 근거 정확) — 그러나 **`mrktTotAmt`(시가총액=종가×상장주식수) 필드는 이 오퍼레이션에 실제로 존재함**(note가 "확인 못함"으로 뭉뚱그린 것과 다름) | **PASS(조건부) — DEF-005 발견** | AC 자체를 충족하는 데는 영향 없음(raw_fundamentals 적재는 AC 범위 밖). 다만 note/traceability의 서술 정확도 문제로 DEF-005 등록(§6) |
| TC-023 | (코디네이터 지시 ④) 재시도 백오프가 **실제 시간**으로도 동작하는지(모의 sleep이 아닌 실측) | 없음(순수 코드) | `time.sleep`을 대체하지 않은 기본 `GovDataPortalClient`에 MockTransport(503→503→200)를 연결해 `time.monotonic()`으로 실제 경과 시간 측정 | 1초+2초=약 3초 실제 지연 후 3번째 호출에서 성공 | `call_count=3`, `elapsed=3.0초`(허용범위 2.8~4.5초) | **PASS** | 5단계 테스트는 전부 `sleep=lambda s: None`으로 모의 처리해 "백오프 값이 맞다"만 확인했지 "실제로 그만큼 대기하는가"는 검증하지 않았음 — 이번에 실제 시간으로 별도 확인 |
| TC-024 | (코디네이터 지시 ④) 서킷브레이커 3일 연속 실패 시 실제 CLI가 고위험 알림을 실제로 출력하는지(종단간, 실 네트워크+실 DB) | `BATCH_DATABASE_URL` 설정, `GOV_DATA_PORTAL_SERVICE_KEY=DUMMY-INVALID-KEY`, DB 초기화(0행) | 실 엔드포인트(`apis.data.go.kr`)를 향해 `python -m services.ingestion_batch.run_ingestion --trade-date 2026-09-11`를 **3회 연속 실행**(Fake 없음, 실제 네트워크 호출) | 1~2회차: 일반 실패 메시지만. 3회차: `[고위험 알림] ... 3일 연속 실패했습니다 ...` stderr 출력 + `batch_run` 3행 모두 FAILED | 정확히 일치. 3회차에서만 `[고위험 알림] Ingestion Batch가 3일 연속 실패했습니다. 운영자 수동 개입이 필요합니다(§5-4).` 출력 확인, `batch_run` 3행 모두 `FAILED` | **PASS** | note는 Fake 클라이언트로만 서킷브레이커를 검증했음(§7). 이번엔 **실제 CLI 프로세스 + 실제 네트워크 + 실제 DB**로 종단간 재현해 5단계보다 넓은 범위로 확정 |
| TC-025 | (AC-5) `--dry-run`, `BATCH_DATABASE_URL` 미설정 → 종료코드 1 | env 미설정 | `python -m services.ingestion_batch.run_ingestion --dry-run` | 종료코드 1 + 안내 메시지 | `[실패] 환경변수 BATCH_DATABASE_URL이 설정되지 않았습니다...`, exit 1 | **PASS** | |
| TC-026 | (AC-5) `--dry-run`, DB URL 설정 + 서비스키 없음 → 종료코드 0 | `BATCH_DATABASE_URL` 설정 | `python -m services.ingestion_batch.run_ingestion --dry-run` | 종료코드 0 + 설정 요약(서비스키 "미설정" 표시) | exit 0, 요약 출력에 `GOV_DATA_PORTAL_SERVICE_KEY: 미설정(dry-run이라 허용)` | **PASS** | |
| TC-027 | (AC-5) `--dry-run` 아님 + 서비스키 미설정 → 종료코드 1 | 상동 | `python -m services.ingestion_batch.run_ingestion --trade-date 2026-09-11`(키 unset) | 종료코드 1 + 안내 메시지 | `[실패] 환경변수 GOV_DATA_PORTAL_SERVICE_KEY가 설정되지 않았습니다...`, exit 1 | **PASS** | |
| TC-028 | (AC-5) Fake 클라이언트 + 실 DB: 정상 응답 2건 삽입 | DB 0행 | `run_once()`를 실제 `batch_worker` 세션 + Fake(2건 레코드) 클라이언트로 직접 호출(스크립트 기반, note와 별도 재현) | `raw_ohlcv` 2행, `batch_run` 1행(SUCCESS, validation_passed=true) | 정확히 일치(`raw_ohlcv`=2행, `batch_run`=1행 SUCCESS/true) | **PASS** | |
| TC-029 | (AC-5) 동일 종목 재수집(가격변경) idempotent upsert | TC-028 이후 | 동일 종목 코드, `close`/`volume` 변경한 값으로 재실행 | 중복 오류 없이 UPDATE, 총 행 수 그대로(2행) | `close`가 70500→72500으로 갱신, `volume`도 갱신, 총 행 수 2 유지(중복 오류 없음) | **PASS** | |
| TC-030 | (AC-5) 응답 0건 → FAILED + "+1영업일 지연" 안내 | DB 초기화 | 0건 반환 Fake 클라이언트로 `run_once()` | `raw_ohlcv` 변화 없음, `batch_run` 1행 FAILED, error_summary에 "영업일" 문구 포함 | `ohlcv_count=0`, `batch_run`=1행 FAILED, error_summary="...+1영업일 지연 특성상 아직 배포되지 않았을 가능성..." | **PASS** | |
| TC-031 | (AC-5) 3회 연속 API 오류(Fake) → circuit_breaker.evaluate `is_open=True` | DB 초기화 | Fake 오류 클라이언트로 `run_once()` 3회 연속 호출 후 `recent_ingest_statuses`+`evaluate` | `batch_run` 3행 FAILED, `is_open=True, consecutive_failures=3` | 정확히 일치 | **PASS** | (TC-024가 이를 실 네트워크 CLI로 한 번 더 독립 재현) |
| TC-032 | (위험 기반 추가, AC 범위 밖) PARTIAL 분기 — totalCount와 실제 수신 건수 불일치(페이지네이션 미배선 시나리오) | DB 초기화 | Fake 클라이언트가 `total_count=3`, `records`는 1건만 반환 | `status="PARTIAL"`, `validation_passed=false`, error_summary에 수신/totalCount 불일치 안내 | `PARTIAL`, `validation_passed=f`, `error_summary="수신 1건 / API totalCount 3건 — 일부 누락 가능성"` | **PASS** | note §3이 "종목 수 1000 초과 시 페이지네이션 미배선"을 알려진 미완성으로 남겼는데, 그 상황이 실제로 조용한 데이터 손실이 아니라 명시적 PARTIAL로 귀결되는지 위험 기반으로 직접 확인 |
| TC-033 | (경계값/예외 입력) CLI `--trade-date`에 잘못된 형식 값 | 없음 | `--trade-date not-a-date` | argparse가 명시적으로 실패(0/1이 아닌 별도 종료코드) | `error: argument --trade-date: invalid <lambda> value: 'not-a-date'`, exit 2 | **PASS** | 규칙 상 "명백히 위험한 예외 입력"으로 범위 밖이어도 직접 확인 |
| TC-034 | (경계값/예외 입력) 빈 문자열(`""`) 서비스키 | `GOV_DATA_PORTAL_SERVICE_KEY=""` | `--trade-date` 지정, `--dry-run` 아님 | 빈 문자열도 "미설정"과 동일하게 취급되어 명시적 실패해야 함(조용히 빈 키로 API 호출 금지) | `[실패] 환경변수 GOV_DATA_PORTAL_SERVICE_KEY가 설정되지 않았습니다...`, exit 1 | **PASS** | `os.environ.get()`의 빈 문자열은 falsy이므로 `not service_key` 검사가 정확히 걸러냄을 확인 |
| TC-035 | (권한 경계, AC-4 연장) `batch_worker`의 DELETE 권한 부재 확인 | head 상태 | 검증 스크립트에서 `batch_worker`로 `DELETE FROM raw_internal.raw_ohlcv` 시도(정리용으로 최초 작성했다가 발견) | GRANT문에 DELETE가 없으므로(`SELECT, INSERT, UPDATE`만) 거부되어야 함 | `permission denied for table raw_ohlcv` — 이후 정리는 `migrator`의 `TRUNCATE`로 전환 | **PASS** | 의도하지 않게 발견한 부수 확인: "batch_worker=arw"가 문자 그대로 append/read/write만 의미하고 delete는 없다는 것이 실제로 강제됨을 재확인(최소권한 원칙 준수) |

> 표에 없는 5단계 note §6 코드 리뷰 체크리스트 4개 항목(설계서 일치/에러처리 누락 없음/입력검증/시크릿 하드코딩 없음/범위 외 변경 없음)은 위 TC들과 코드 직독(§ "코드 리뷰 재확인" 아래)으로 교차 검증했다.

### 코드 리뷰 재확인 (게이트 2 독립 재검증)
- `services/ingestion_batch/gov_data_client.py`, `run_ingestion.py`, `repository.py`, `models.py`, `config.py`, `calendar_lookup.py`, `batch_run_repository.py`, `circuit_breaker.py`, 마이그레이션 0003/0004 전체를 직접 읽고 확인:
  - 예외를 삼키는 `except: pass` 류 코드 없음(전부 명시적 재발생 또는 `batch_run.FAILED` 기록으로 귀결).
  - 시크릿 하드코딩 없음: `.env.example`에 `CHANGE_ME`만 존재, `devpass`는 로컬 1회성 값으로 코드/설정에 없음(검증 세션에서도 환경변수로만 주입).
  - `volume`/`trading_value`가 `models.py`·마이그레이션 0004 양쪽 모두 `BigInteger`로 되어 있음을 직접 확인(note가 주장한 "구현 중 발견한 32비트 INTEGER 버그를 즉시 수정" 결과물이 실제로 반영돼 있음 — TC-028/029가 실제 큰 값(`870000000000`, `999999999999`)으로 삽입/갱신에 성공한 것으로 간접 재확인).
  - UNIT-01 산출물(`shared/calendar_service/`, `services/public_api/`, `scripts/load_calendar.py`, 0001/0002 마이그레이션)에 대한 diff 없음(파일 내용이 UNIT-01 v4 최종본과 동일 — `get_last_trading_day` 소스 위치가 여전히 `shared/calendar_service/last_trading_day.py`인 것으로 간접 확인, TC-015).

## 5. 커버리지
- AC-1~AC-6 전 항목 1:1 매핑 완료(TC-004~TC-031, 위 표의 "비고"에서 대응 AC 명시). 커버리지 100%.
- 추가로 AC에 없는 위험 기반 케이스 6건(TC-018 실접근 시도, TC-019 쓰기권한 경계, TC-020/021 실측·공식스펙 교차검증, TC-023 실시간 백오프, TC-024 실 네트워크 종단간, TC-032 PARTIAL, TC-033/034 예외입력, TC-035 부수 발견)을 자체적으로 추가해 5단계보다 넓게 검증했다.
- 커버되지 않은 부분: 실 서비스키로 정상 응답 수신(§2 제외범위 참조, 5단계와 동일한 환경 제약), 페이지네이션 자동 순회 배선(note가 이미 "명시적 미완성"으로 공표한 항목이며 AC 범위 밖), NXT/호출한도 실측.

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도 | 상태 | 조치 내용 |
|----|------|-----------|--------|------|-----------|
| DEF-005 | `unit-02-note.md` §0-3/§2-6 및 `traceability.md` REQ-011 비고가 "PER/PBR/**시가총액**을 이 오퍼레이션이 제공하는지 확인 못했다"고 뭉뚱그려 서술하나, 이번 6단계가 공식 Swagger 메타데이터(TC-021/022)를 직접 대조한 결과 **시가총액(`mrktTotAmt` = 종가×상장주식수)은 `getStockPriceInfo`가 실제로 제공하는 필드로 확인됨**. PER/PBR은 확인대로 미제공이 맞음. | TC-021/TC-022 절차 그대로 재현: `https://www.data.go.kr/data/15094808/openapi.do` 응답 본문에서 item 스키마 하위 `mrktTotAmt` 필드 존재 확인 | Low | **Open(코드 결함 아님, 문서 정확도 이슈 — 6단계 권한 범위 내 문서 시정으로 처리)** | 코드 변경 불필요(AC 범위 밖, 어떤 인수 조건도 위반하지 않음). `traceability.md` REQ-011 비고를 이번 6단계가 직접 정정(§8 참조)했고, `unit-02-note.md`는 5단계 산출물이라 이번 6단계가 직접 고치지 않고 원문 그대로 보존한 뒤 이 결함 기록으로 정확한 사실관계를 남긴다. 후속 유닛(raw_fundamentals 실 적재 착수 시)이 이 사실을 참고해 "시가총액은 getStockPriceInfo로 채울 수 있고 PER/PBR만 별도 소스가 필요하다"는 전제로 재설계하면 범위를 더 좁혀 시작할 수 있다(권고, 강제 아님) |

- **그 외 결함 없음.** 근거: TC-001~TC-035(총 35개 테스트 케이스, AC-1~AC-6 100% 커버 + 위험 기반 추가 8건)가 전부 PASS이며, 정상 경로(TC-004,014,025~029)·경계값(TC-009,022,032,035)·예외 입력(TC-006~008,010~012,016,025,027,033,034)·권한 경계(TC-018,019,035)를 모두 포함해 확인했다. "실행해보니 에러 없음"이 아니라 매 케이스마다 기대 결과(코드/AC 근거)와 실제 결과(쿼리/출력 캡처)를 대조했다.

## 7. 리스크 및 잔존 이슈
- **실 서비스키 미보유**: 정상 응답 파싱 로직은 목/픽스처(공식 스펙 필드명과 TC-021로 교차검증 완료) 기반으로만 검증됐고, 실제 API 트래픽으로 종단 검증되지 않았다. 실 키 발급 즉시 `run_ingestion.py --trade-date <실제 과거 거래일>`로 재검증 필수(5단계·6단계 공통 권고).
- **한도초과/일시오류 코드(22, 05)의 재시도 대상 분류가 미검증 가정**: 실 트래픽으로 이 코드들이 실제로 발생하는지 확인하지 못했다(무효 키로는 코드 30만 재현 가능). 6단계도 이 부분은 재현하지 못했다 — 실 키 확보 후 회귀 대상으로 별도 관찰 필요.
- **DEF-005(시가총액 소스 확인 가능)**: 위 §6 참조. 후속 유닛의 설계 참고사항으로 인계.
- **페이지네이션 미배선**: note가 이미 공표한 명시적 미완성이며, 이번 검증(TC-032)으로 "조용한 데이터 손실이 아니라 PARTIAL로 명시적 귀결"됨을 확인했으므로 데이터 정합성 리스크는 낮으나, 종목 수 1000 초과 시(코스피+코스닥 약 2,500개) 실제로는 매일 PARTIAL이 발생할 것이 거의 확실하다 — **후속 유닛 착수 전 반드시 배선 완료 필요**(운영 관점에서는 사실상 필수 후속 작업이지 선택 사항이 아님을 강조).
- **cron 실제 배포/스케줄링 시각 미확정**: 10단계 영역, note §2-2/§3 승계.

## 8. 결론 및 판정
- [x] **PASS** — 다음 단계(07 통합테스트) 진행 가능.
  - AC-1~AC-6 전 항목 독립 재검증 완료, 결함 0건(문서 정확도 이슈 DEF-005 1건은 코드/AC 위반이 아니므로 배포 차단 사유 아님).
  - 코디네이터 지시 5개 항목 전부 확인 완료: ①GRANT/`api_service` 접근 거부를 실제 `raw_internal.raw_ohlcv`/`raw_fundamentals`에 직접 시도해 재확인(TC-018, UNIT-01 v3의 proxy 검증보다 진전), ②"API 키 없이 검증 못함"이 note에 정직하게 기록되어 있고 목/픽스처가 실제 공식 Swagger 스펙과 필드 단위로 일치함을 확인(TC-021), ③raw_fundamentals 범위 축소는 REQ-011의 의도적 부분 축소이며 그 근거를 정밀 검증해 DEF-005로 정확도를 보완(TC-022, §6), ④재시도/서킷브레이커가 모의 sleep뿐 아니라 실제 시간(TC-023)·실제 네트워크+실제 CLI(TC-024)로도 동작함을 확인, ⑤UNIT-01 `get_last_trading_day()` 재사용이 재구현 없이 그대로임을 소스 파일 경로로 확인(TC-015).
  - `traceability.md`의 REQ-011 "단위테스트" 컬럼을 이 문서로 갱신(§9 아래 별도 반영 완료).

## 9. 내부 검증 (최소 2회, `verification-log-template.md` 사용)
- 1차 검증 결과 요약(작성자 관점 자가 재검토): AC-1~AC-6 커버리지를 note §4와 1:1 대조한 결과 전 항목에 대응 TC가 존재함을 확인. TC-021(공식 스펙 대조)이 "예상 결과가 실제 명세에 근거하는가"를 가장 강하게 뒷받침하는 근거임을 재확인 — 이 문서 없이는 필드명이 진짜인지 재차 신뢰에 의존할 뻔했다. 오탈자/서식 점검 완료.
- 2차 검증 결과 요약(독립 심사자 관점 — "오늘 처음 받아본 심사자"): "5단계도 GRANT 분리를 검증했다는데 6단계가 굳이 또 해야 하나?"라는 질문에 답하기 위해 TC-018/019에서 **테스트 스크립트 대상을 note가 실행한 것과 다른 쿼리(직접 INSERT 시도, DELETE 시도)로 바꿔** 우연한 통과가 아닌지 확인했고, 실제로 TC-035에서 예상 밖의 `DELETE` 거부를 발견해 검증 스크립트 자체를 수정해야 했다(이것이 "테스트 자체가 결함을 놓칠 뻔한" 사례 — 최초 정리 스크립트가 `batch_worker`로 DELETE를 시도했다면 "정리 실패"를 "이상 없음"으로 오판할 뻔했다). 또한 "AC를 통과했다고 07 통합테스트에 넘겨도 되는가"라는 질문에서 페이지네이션 미배선이 실 운영에서는 사실상 매일 발생할 문제임을 재평가해 §7 리스크에 "선택 아닌 필수 후속 작업"으로 격상 서술했다.
- 검증 로그 파일 경로: 이 문서(`docs/harness/units/unit-02-test.md`) §9에 통합 기록(별도 `verify-log_unit-02-test.md` 파일을 분리 생성하지 않고 동일 문서 내 유지 — UNIT-01 test.md와 동일한 관례를 따름). 결함 0건(코드 기준) 확정 전 2회 검증에서 발견된 절차상 이슈(TC-035 계기)는 검증 진행 중 즉시 스크립트를 수정해 반영했으며 결과 표(§4)에 최종본만 반영했다.
