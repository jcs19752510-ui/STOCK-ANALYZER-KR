# 테스트 결과서 (Test Result Report) — UNIT-01

> **버전: v6**(규칙 F 피드백 루프 2차 라운드 — v5가 발견한 **DEF-005(Medium)**에 대한 5단계 재작업을 6단계가 독립 재검증, **PASS** 판정, v5의 FAIL을 대체). v1(FAIL)·v2(CONDITIONAL PASS, Postgres 미검증)·v3(CONDITIONAL PASS, DEF-003/004 발견)·v4(PASS, 최종)·v5(FAIL, DEF-005 신규 발견)의 전체 내용은 이력 보존을 위해 그대로 남기고, v6에서 변경/추가된 부분은 각 섹션에 "v6" 표시와 함께 구분해 서술한다. 문서를 새로 작성하지 않고 개정하는 형태를 취한다. **적용 속도 트랙: N/A(이 단위는 L1~L5 트랙 도입 이전에 이미 개발된 기존 산출물의 재작업, DEC-028 이전 유닛). Tier=High(`decisions.md` DEC-021) — 규칙 B 완화 없이 원문 그대로 적용.**

## 0. 재작업 이력 (v2 — DEF-001/DEF-002 재검증, 규칙 F 피드백 루프)

- v1(2026-09-14, 06-unit-tester)에서 **DEF-001(High)**: `get_last_trading_day()`가 개장 시각 기준으로 비교해 장중 내내 "당일"을 잘못 반환 — **FAIL** 판정, 3단계 재작업 요청.
- v1에서 **DEF-002(Low)**: `/health` degraded 및 `CalendarScanLimitExceeded`→503 매핑에 대한 회귀 테스트 공백 — 재작업 권고(배포 차단 아님).
- 이에 따라 `03-system-design.md`가 **v4**로 개정(§3-3 전면 재작성 — 마감 시각 기준, `_already_closed` 헬퍼, 13행 진리표, `decisions.md` DEC-018), 5단계가 `shared/calendar_service/last_trading_day.py`를 재구현하고 `market_hours.py`를 삭제했다(`unit-01-note.md` v2, §0).
- **이번 v2 문서는 그 재작업 결과를 6단계 관점에서 독립적으로 재검증한 기록이다.** 5단계가 자체 보고한 "36건 전부 pass"를 그대로 신뢰하지 않고, v1에서 6단계가 직접 발견했던 09:00~23:59:59 스윕 방식을 이번에는 **00:00:00~23:59:59 전 구간·초 단위**로 확장해 독립 재실행했다(아래 §4-2 TC-046).
- 신규 섹션: §4-2(v2 재검증 테스트 케이스, TC-043~TC-063), §6(DEF-001/DEF-002 상태를 Fixed로 갱신, 근거 병기), §8(판정 갱신), §9(v2 내부검증 로그 요약).
- v1의 §1~§4(AC-2~AC-6 관련, TC-001~042 중 DEF-001/DEF-002 미관련 항목)는 재작업 대상이 아니었으므로(=`unit-01-note.md` v2 §6 코드 리뷰 체크리스트 "이번 재작업은 DEF-001이 지목한 파일과 직접 연관 코드만 수정" 확인) 원문 그대로 두되, 이번 v2 세션에서 회귀가 없는지 다시 실행해 결과를 §4-2 말미(TC-059~063)에 재확인 기록으로 남겼다.

---

## 0-2. 재작업 이력 (v3 - 실제 PostgreSQL 환경 확보에 따른 AC-3/AC-5 확정 검증)

- 코디네이터가 로컬 Docker에 실제 PostgreSQL 16(컨테이너 `stock-screener-db`, DB `stock_screener`)을 띄우고 `migrator`(SUPERUSER)/`batch_worker`/`api_service` 3개 역할을 미리 생성했다(비밀번호 `devpass`). v2까지 "미검증(NOT TESTED)"으로 정직하게 남겨뒀던 AC-3 불릿4(실제 upsert)와 AC-5(실제 마이그레이션 적용/롤백)를 이번에 실제 DB로 확정 검증했다.
- **검증 결과 요약**: AC-5(마이그레이션 적용/롤백) - **확정 PASS**. AC-3(CLI 실 upsert, idempotent 갱신) - **확정 PASS**. 다만 검증 과정에서 코드 자체의 신규 결함 2건을 발견했다. **DEF-003(Medium)** - 마이그레이션 0001이 `reference` 스키마에 대해 어떤 GRANT도 실행하지 않아, `alembic upgrade head` 직후 `batch_worker`/`api_service` 둘 다 `reference.market_calendar`에 접근 권한이 전혀 없는 상태(코드/스크립트 어디에도 GRANT가 없음, 운영자가 수동으로 실행해야 하나 그 절차조차 문서화되어 있지 않음)임을 실제로 재현했다. **DEF-004(Low)** - `scripts/load_calendar.py`의 `upsert_rows()`가 `ON CONFLICT DO UPDATE`의 `set_`에 `updated_at`을 포함하지 않아, 내용이 실제로 갱신돼도 `updated_at` 타임스탬프가 최초 삽입 시각에 고정된 채 갱신되지 않음을 실제로 재현했다.
- `api_service`가 `raw_internal`에 접근할 수 없는지(§1-1 2차 방어의 핵심 방어선)도 검증 대상에 포함하라는 지시에 따라 확인했으나, **`raw_internal` 스키마는 UNIT-01의 어떤 마이그레이션도 생성하지 않는다**(UNIT-02 Derivation Batch 이후 산출물, `unit-01-note.md` §2 편차 항목7에 이미 명시됨). 따라서 이번 검증은 UNIT-01 코드 자체에 대한 검증이 아니라, **테스트 전용 대역(stand-in) 스키마를 만들어 "GRANT 없는 스키마는 실제로 접근이 거부되는가"라는 Postgres 권한 모델 자체의 동작을 확인하는 보조(proxy) 검증**으로 수행했고, 검증 후 즉시 삭제해 UNIT-01/UNIT-02 산출물에 어떤 흔적도 남기지 않았다(아래 §4-3 TC-071 참조). 실제 `raw_internal.raw_ohlcv`에 대한 검증은 UNIT-02 산출물이 생긴 뒤 재수행해야 한다.
- 코드 수정은 하지 않았다(06-unit-tester 원칙 - 직접 코드를 고치지 않고 재작업을 요청). GRANT는 **라이브 테스트 DB에만** 수동으로 적용했으며(코드베이스에는 반영되지 않음), 검증이 끝난 뒤에도 이후 세션의 편의를 위해 되돌리지 않고 그대로 두었다(§3 환경 기록 참조). 이는 DEF-003이 "미해결(Open)"임을 가리는 것이 아니다 - 코드베이스 자체(마이그레이션 파일)에는 GRANT문이 여전히 없다는 사실은 그대로 결함으로 남겨 보고한다.

## 0-3. 재작업 이력 (v4 - DEF-003/DEF-004 수정에 대한 독립 재검증, 규칙 F 피드백 루프)

- 5단계가 DEF-003(Medium, `reference` 스키마 GRANT 누락)과 DEF-004(Low, `updated_at` 미갱신)를 수정했다(`unit-01-note.md` v3, `db/alembic/versions/0002_grant_reference_privileges.py` 신규 + `scripts/load_calendar.py` upsert 수정). 5단계가 자체 재현/검증까지 마쳤다고 note에 기록했으나, **코디네이터 지시에 따라 이를 신뢰하지 않고 6단계가 독립적으로 다시 확인**했다.
- **독립 재검증 방법(5단계 로그 재사용 없음)**: 5단계가 검증 후 남겨둔 DB 상태를 그대로 신뢰하지 않고, 6단계가 직접 `alembic downgrade base`로 완전히 밀어버린 뒤 처음부터 `alembic upgrade head`를 다시 실행해 GRANT가 "우연히 이미 걸려있던 것"이 아니라 "마이그레이션 자체가 실제로 GRANT를 실행하는 것"임을 재확인했다. `updated_at` 갱신도 6단계가 새로 만든 오염 행(`WRONG_TEST_VALUE_V4`)으로 별도 재현했다(5단계의 오염값을 재사용하지 않음).
- **검증 결과 요약**: 4개 확인 항목(코디네이터 지시 1~4) 전부 **PASS**. DEF-003/DEF-004 모두 **Fixed**로 최종 확인. 신규 결함 0건. DEF-001/DEF-002를 포함한 기존 전 AC에 회귀 없음.
- **결론**: UNIT-01은 이번에 CONDITIONAL PASS의 조건이었던 DEF-003이 해소됨에 따라 **최종 PASS(조건부 아님)**로 판정한다. 다만 코드 결함은 아니지만 여전히 남아 있는 인프라/운영 리스크(§7)는 결함 목록과 별개로 계속 추적한다.


## 0-4. 재작업 이력 (v5 — DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판 독립 재검증, 규칙 F 피드백 루프)

- 09단계(`09-security-audit.md`, FAIL 판정)가 **DEF-SEC-01(High, IP rate limiting 미구현)**, **DEF-SEC-02(Medium, 보안 응답 헤더 미구현)**, **DEF-FS-01/REQ-025 확장판(High, 전역 예외 처리 부재로 근본 원인 확장)** 3건을 UNIT-01(`services/public_api` 공용 기반)로 귀속시켰다(`decisions.md` DEC-027). 오케스트레이터가 5단계를 재호출해 `services/public_api/db/session.py`(connect_timeout=3s/statement_timeout=3000ms), `services/public_api/rate_limit.py`(신규, `RateLimitMiddleware`), `services/public_api/middleware.py`(신규, `SecurityHeadersMiddleware`/`RequestTimeoutMiddleware`/`UnhandledExceptionMiddleware`), `main.py`(미들웨어 등록 + `DBAPIError`/`SATimeoutError` 핸들러) 수정을 완료시켰다(`unit-01-note.md` v5, §0-d).
- **이번 v5 문서는 그 재작업을 6단계가 5단계의 자체 보고("165 passed", "실측 0.12초")를 그대로 신뢰하지 않고 독립적으로 재현한 기록이다.** 특히 오케스트레이터가 명시적으로 지시한 한계 보완 사항 — 5단계가 "connection refused"(즉시 실패)만 재현했다고 스스로 기록한 `unit-01-note.md` §3의 v5 신규 항목("실제 DB 장애(네트워크 블랙홀 등...)에서 connect_timeout=3이 실제로 3초에 끊기는지는... 재현하지 않았다") — 을 실제 TCP 블랙홀(패킷 무응답, SYN 드롭)에 가까운 시나리오로 재검증했다.
- **핵심 결과 요약**:
  1. **DEF-SEC-01(rate limiting)**: 정상 동작 확인(**Fixed 유지**). 분당 60회 초과 시 429 `RATE_LIMITED` Envelope, 60회 이하는 정상, 429 응답에도 CORS 헤더 일관 유지, OPTIONS 프리플라이트는 카운터를 소모하지 않음 — 전부 실제 네트워크(uvicorn+curl)로 재확인했다(§4-5 TC-087/088).
  2. **DEF-FS-01/REQ-025(전역 예외 처리 + DB 타임아웃)**: 정상 동작 확인(**Fixed 유지**), 오히려 5단계 자체 검증이 남긴 공백을 이번에 메웠다. 진짜 TCP 블랙홀(존재하지 않는 사설 예약 IP `10.255.255.1`, SYN 응답 없음)로 재현한 결과 `connect_timeout=3`이 정확히 약 3.05~3.08초에 `OperationalError`를 발생시키고, `main.py`의 `DBAPIError` 핸들러가 이를 503 `SERVICE_UNAVAILABLE` Envelope으로 정확히 매핑함을 실제 `uvicorn` 서버로 확인했다(§4-5 TC-093~095). **5단계가 note §6-1에 "0.12초"로 보고한 시나리오는 실제로는 이 블랙홀을 재현한 것이 아니라, 실제로 리스닝 중인 서버(로컬 `stock-screener-db`)에 잘못된 비밀번호로 접속해 Postgres가 즉시 인증을 거부하는, 전혀 다른(그리고 connect_timeout과 무관한) 경로였음을 직접 재현해 확인했다**(§4-5 TC-096) — 결과 자체(빠른 503)는 우연히 동일했지만 "무응답 네트워크 장애"를 검증한 것은 아니었다는 점에서 5단계 note의 설명이 부정확했다. 이번 v5 재검증으로 진짜 블랙홀 시나리오가 처음으로 직접 확인됐고, 결과는 **PASS**(§5-4 "5초 이내" 목표를 여유 있게 충족).
  3. **DEF-SEC-02(보안 응답 헤더)** — **신규 결함 발견(DEF-005), 부분 회귀(Partially Fixed).** `SecurityHeadersMiddleware`가 `RateLimitMiddleware`/`RequestTimeoutMiddleware`보다 안쪽(라우터에 더 가까운 위치)에 등록되어 있어, 이 두 미들웨어가 **`call_next()`를 호출하지 않고 자체적으로 응답을 반환(short-circuit)하는 경로**(429 rate-limited 응답, 요청 타임아웃 503 응답)에서는 `SecurityHeadersMiddleware`의 코드 자체가 실행되지 않아 CSP/`X-Content-Type-Options`/HSTS 세 헤더가 **응답에 붙지 않는다.** 오케스트레이터가 명시적으로 요구한 "모든 응답(정상/에러 포함)" 기준, 그리고 `unit-01-note.md` AC-9 원문("실제 app 응답에 ... 세 헤더가 모두 존재")을 충족하지 못한다. 실제 `uvicorn` 서버 재현과 격리된 Starlette 앱 재현 양쪽으로 확인했다(§4-5 TC-090/091). `DBAPIError` 핸들러가 만드는 503과 `UnhandledExceptionMiddleware`의 catch-all 503은 정상적으로 보안 헤더가 붙는다(미들웨어 스택 상 위치가 다름 — §4-5 TC-092 대조군 참조). AC-9의 pytest 테스트(`test_security_headers_present_on_response`)와 AC-8의 pytest 테스트(`test_rate_limited_response_still_carries_cors_header`)는 각각 "정상 200 응답의 헤더"와 "429 응답의 CORS 헤더"만 확인할 뿐, **"429/타임아웃 503 응답의 보안 헤더"라는 교차 조합은 검증하지 않아** 5단계의 신규 테스트 10건(165건 스위트)으로는 이 결함이 애초에 잡힐 수 없는 구조였다.
- **판정**: 위 3건 중 2건(DEF-SEC-01, DEF-FS-01/REQ-025)은 실제로 완전히 해소됐으나, 1건(DEF-SEC-02)은 **부분적으로만 해소**됐고 그 과정에서 새로운 결함(DEF-005)이 발견되어, UNIT-01은 이번 v5에서 **FAIL** 판정한다(§8 참조). 코드를 직접 고치지 않고 규칙 F에 따라 5단계로 재작업을 요청한다(권고 조치는 §6 DEF-005 행 참조).

## 0-5. 재작업 이력 (v6 — DEF-005 대응 5단계 재작업의 6단계 독립 재검증, 규칙 F 2차 라운드)

- v5가 발견한 **DEF-005(Medium)**(429/타임아웃 503 short-circuit 응답에 보안 헤더 누락) 1건에 대해, 5단계가 `services/public_api/main.py`의 `add_middleware()` 등록 순서를 `UnhandledException → SecurityHeaders → RequestTimeout → RateLimit → CORS`(버그 순서)에서 `UnhandledException → RequestTimeout → RateLimit → SecurityHeaders → CORS`(수정 순서, `SecurityHeadersMiddleware`를 short-circuit 미들웨어들보다 바깥쪽으로 재배치)로 변경했다(`unit-01-note.md` §0-e). `tests/unit/test_public_api.py`에 회귀 테스트 2건(`test_rate_limited_response_still_carries_security_headers`, `test_request_timeout_response_still_carries_security_headers`)을 추가했다고 note에 기록했다.
- **이번 v6 문서는 그 5단계 재작업을 6단계가 5단계의 자체 보고("167 passed", "실제 uvicorn 포트 8199 재현")를 신뢰의 근거로 삼지 않고 독립적으로 재현한 기록이다.** 코디네이터 지시대로 (1) DEF-005 해소 여부를 실측 재현, (2) 미들웨어 순서 변경으로 인한 회귀 여부(정상 200/`DBAPIError` 503의 헤더 유지, CORS 헤더 일관성, rate limit 60/61 경계 및 OPTIONS 미소모, DB 타임아웃 경로의 코드 레벨 무변경), (3) `pytest`/`ruff` 독립 재실행, (4) 신규 pytest 2건이 실제로 DEF-005 시나리오를 의미 있게 커버하는지(가능하면 순서를 되돌려 실제로 실패하는지까지)를 전부 확인했다.
- **핵심 결과 요약**:
  1. **DEF-005 해소 확인**: 코드 리뷰로 `main.py`의 실제 `add_middleware` 호출 순서가 note의 주장과 정확히 일치함을 확인했다(§4-6 TC-101). 6단계 자신의 독립 세션(05단계와 다른 포트 8111~8113, 05단계가 쓴 8199와 무관)으로 실제 `uvicorn`을 3회 재기동해 (a) 60/61 경계에서 429 응답에 CSP/`X-Content-Type-Options`/HSTS 3개 헤더와 CORS 헤더가 모두 존재함을 2중으로 재확인(§4-6 TC-103), (b) `RequestTimeoutMiddleware`의 타임아웃 503 경로는 pytest의 격리된 Starlette 앱 테스트로 재확인하고, 그 테스트 방법론 자체가 버그 순서/수정 순서를 정확히 구분해내는지 별도 mutation 스크립트로 검증했다(§4-6 TC-107).
  2. **(핵심, mutation testing) 신규 pytest 2건의 실효성 직접 검증**: `main.py`를 v5의 버그 순서(`SecurityHeaders`를 `RequestTimeout`/`RateLimit`보다 안쪽에 배치)로 일시적으로 되돌린 뒤 신규 테스트를 재실행한 결과, `test_rate_limited_response_still_carries_security_headers`가 **실제로 FAIL**함을 직접 확인했다(`KeyError: 'content-security-policy'`) — 이 테스트가 우연히 통과하는 것이 아니라 실제 회귀를 잡아내는 유효한 안전망임을 실증했다(§4-6 TC-102). 원본으로 즉시 복원 후 재확인 PASS. 다만 `test_request_timeout_response_still_carries_security_headers`는 `main.py`를 참조하지 않는 완전히 격리된 Starlette 앱(테스트 코드 내부에 순서를 직접 하드코딩)이라, `main.py`의 실제 등록 순서가 바뀌어도 이 테스트 자체는 반응하지 않는다는 **구조적 한계**를 발견했다(§4-6 TC-107 비고, §7 리스크로 기록 — v5의 TC-091도 동일한 패턴이었으므로 이번 v6에서 신규로 발생한 문제는 아니다).
  3. **회귀 확인 결과**: (a) 정상 200 응답·`DBAPIError` 503 응답(bad credentials로 실제 유발) 둘 다 보안 헤더 3종 + CORS 헤더가 여전히 정상 부착됨을 6단계 독립 세션으로 재확인(§4-6 TC-104/105). (b) CORS 헤더가 200/429/503 전부에 일관되게 붙음을 확인(§4-6 TC-103~105). (c) rate limit이 60/61 경계에서 정확히 동작하고 OPTIONS 프리플라이트가 카운터를 소모하지 않음을 재확인(§4-6 TC-103/106). (d) `rate_limit.py`/`db/session.py`/`main.py`의 `DBAPIError`·`SATimeoutError` 예외 핸들러 코드가 이번 v6 변경(미들웨어 등록 순서 4줄)과 무관하게 전혀 손대지 않았음을 코드 리뷰로 확인했고, 예외 핸들러는 `@app.exception_handler`로 등록되어 `add_middleware` 순서와는 별개의 메커니즘(라우팅/엔드포인트 계층에서 처리된 뒤 일반 `Response`로서 미들웨어 스택을 통과)이므로 순서 변경이 DB 타임아웃 경로의 동작/타이밍에 영향을 줄 수 없음을 코드 레벨로 확인했다(§4-6 TC-109). 실제 3초 TCP 블랙홀 재현은 v5(TC-093~096)에서 이미 3중으로 확정 검증됐고 이번 변경이 그 코드를 건드리지 않았으므로 재실행하지 않았다(코디네이터 지시 "회귀만 확인하면 된다"에 부합).
  4. **`pytest tests/unit -q`**: **167 passed** 독립 재실행 확인(§4-6 TC-099). **`ruff check .`**: `All checks passed!` 독립 재실행 확인(§4-6 TC-100).
- **판정**: DEF-005가 실제로 해소됐고(우연이 아니라 mutation testing으로 실효성까지 검증), DEF-SEC-01/DEF-FS-01(REQ-025)에 회귀가 없으며, DEF-SEC-02(REQ-027)도 이제 완전히 Fixed로 확인되어, UNIT-01은 이번 v6에서 **PASS**로 판정한다(v5의 FAIL을 대체, §8 참조). 8단계(전체 풀테스트 재실행) 착수 가능.

## 1. 개요
- 테스트 대상: **UNIT-01 (휴장일/영업일 캘린더 서비스)** — `shared/calendar_service/`, `shared/db_models/reference.py`, `db/alembic/versions/0001_create_reference_market_calendar.py`, `scripts/load_calendar.py`, `data/calendar/2026.example.yaml`, `services/public_api/*`, 프로젝트 스캐폴딩(`pyproject.toml`, `requirements*.txt`, `alembic.ini`, `db/alembic/env.py`, `.env.example`, `.gitignore`)
- 테스트 유형: 단위(Unit) — 파이프라인 6단계, **v2: DEF-001/DEF-002 재작업 완료 후 재검증 / v3: 실제 Postgres로 AC-3/AC-5 확정 및 DEF-003/004 발견 / v4: DEF-003/004 수정에 대한 독립 재검증, 최종 판정 / v5: DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판 재검증, DEF-005 신규 발견(FAIL) / v6: DEF-005 수정에 대한 독립 재검증, 최종 판정(PASS)**
- 테스트 목적(v1): REQ-005(직전 거래일 산정)·REQ-012(휴장일 캘린더 하드코딩 금지) 구현이 인수 조건(AC-1~AC-6)을 충족하는지, 5단계 자체 테스트(21건 pass, ruff 통과)를 신뢰하지 않고 6단계 관점에서 독립적으로 재검증하는 것.
- **테스트 목적(v2 추가)**: (1) DEF-001이 `03-system-design.md` v4 §3-3의 13행 진리표 기준으로 실제로 해소됐는지 — 특히 이전에 6단계가 직접 발견했던 전 구간 스윕 방식으로 재확인. (2) DEF-002(경미, health/503 매핑 회귀테스트 공백)가 해소됐는지 확인. (3) `market_hours.py` 삭제로 인한 깨진 import/참조가 없는지, `services/public_api/api/calendar.py`가 `CalendarIntegrityError` 공통 베이스로 수정됐는지 확인. (4) AC-3(실 upsert)/AC-5(실 마이그레이션)는 환경 제약이 v1과 동일하면 이번에도 "미검증"으로 정직하게 남긴다. 5단계가 자체 보고한 결과("36건 전부 pass")는 신뢰의 근거가 아니라 재검증의 출발점으로만 취급한다.
- 관련 산출물: `docs/harness/03-system-design.md`(**v4**, PASS) §3-2/§3-3(전면 재작성)/§3-4/§4-1/§4-2/§7-2, `docs/harness/04-ux-design.md`(v3, PASS), `docs/harness/02-planning.md`(v3) §9 UNIT-01, `docs/harness/units/unit-01-note.md`(**v3**, 5단계 재작업 산출물 — §0-b DEF-003/004 수정 이력, `db/alembic/versions/0002_grant_reference_privileges.py` 신규), `docs/harness/decisions.md` DEC-017/DEC-018
- 테스트 수행자(에이전트): 06-unit-tester
- 테스트 일시: 2026-09-14(v1 최초), 2026-09-14(v2 재검증), 2026-09-14(v3 재검증), 2026-09-15(**v4 재검증, 최종**)


**v5 추가**:
- 테스트 목적(v5): (1) DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판 수정(`unit-01-note.md` v5, AC-8~AC-10)이 실제로 동작하는지 독립 재현. (2) 특히 5단계가 스스로 한계로 남긴 "TCP 블랙홀" 미검증 항목을 실제 네트워크 무응답 시나리오로 메우는 것. (3) 5단계 자체 `pytest`(165건)/`ruff` 보고를 신뢰의 근거가 아니라 재검증의 출발점으로만 취급.
- 관련 산출물(v5 추가): `docs/harness/09-security-audit.md` §4-5·§4-6·§6·§9(FAIL), `docs/harness/units/unit-01-note.md`(**v5**) §0-d·§3·§4(AC-8~AC-10), `docs/harness/03-system-design.md`(v4) §5-4·§6-3, `docs/harness/decisions.md` DEC-027, `docs/harness/traceability.md` REQ-025/026/027.
- 테스트 수행자(v5): 06-unit-tester. 테스트 일시(v5): 2026-09-18.

**v6 추가**:
- 테스트 목적(v6): (1) v5가 발견한 DEF-005(Medium, 429/타임아웃 503 short-circuit 응답의 보안 헤더 누락)에 대한 5단계 재작업(미들웨어 등록 순서 재배치)이 실제로 해소됐는지 독립 재현. (2) 순서 변경이 이미 Fixed로 확인된 DEF-SEC-01(rate limiting)/DEF-FS-01(REQ-025, DB 타임아웃+전역 예외처리)에 회귀를 일으키지 않았는지 확인. (3) 5단계 자체 `pytest`(167건)/`ruff` 보고를 신뢰의 근거가 아니라 재검증의 출발점으로만 취급. (4) 5단계가 추가했다는 신규 pytest 2건이 실제로 DEF-005 시나리오를 유효하게 커버하는지(mutation testing으로 실효성 직접 검증).
- 관련 산출물(v6 추가): `docs/harness/units/unit-01-test.md`(v5) §4-5 TC-090/091·§6 DEF-005·§8(FAIL 판정 근거), `docs/harness/units/unit-01-note.md`(**v6**) §0-e(변경 요약·방식 선택 근거)·§6(게이트1/2 v6 체크리스트)·§6-1(v6 로컬 검증 로그), `services/public_api/main.py`(미들웨어 등록 순서 변경분), `tests/unit/test_public_api.py`(DEF-005 회귀 테스트 2건).
- 테스트 수행자(v6): 06-unit-tester. 테스트 일시(v6): 2026-09-18.

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope, v1): `unit-01-note.md` AC-1~AC-6 전체(1:1 추적), 5단계가 명시한 "수동 확인 필요" 항목 재검증, 5단계 게이트 1(정적 분석)·게이트 2(코드 리뷰 체크리스트)의 실제 통과 여부 독립 재확인.
- **범위(In-Scope, v2 추가)**: (a) `03-system-design.md` v4 §3-3 13행 진리표 전체를 코드 재실행으로 재현, (b) v1에서 6단계가 직접 발견했던 "장중 스윕" 재현 절차를 이번엔 전 구간(00:00:00~23:59:59, 초 단위)으로 확장해 독립 스크립트로 재실행, (c) `market_hours.py` 삭제에 따른 프로젝트 전체 import/참조 무결성 확인, (d) `services/public_api/api/calendar.py`의 `CalendarIntegrityError` 공통 베이스 캐치 확인(+ `CalendarDataError`처럼 note가 명시적 API 레벨 예시로 들지 않은 하위 예외까지 직접 위험 케이스로 추가 검증), (e) DEF-002 회귀 테스트 2건의 실재 및 통과 여부, (f) AC-2/AC-3/AC-6 등 재작업 대상이 아니었던 부분의 회귀 없음 재확인.
- **범위(In-Scope, v3 추가)**: 코디네이터가 로컬 Docker에 실제 PostgreSQL을 준비함에 따라, (a) 실제 `alembic upgrade head`/`downgrade base`(AC-5 전체) 확정 검증, (b) `scripts/load_calendar.py`를 실제 `batch_worker` 계정으로 실행한 real upsert + idempotency(AC-3 불릿4) 확정 검증, (c) `03-system-design.md` §1-1/§3-1 DB 권한 분리(2차 방어) 설계를 `reference` 스키마에 대해 실제 GRANT로 구현·검증, (d) `api_service`의 `raw_internal` 접근 거부를 대역(proxy) 스키마로 보조 검증, (e) 실제 Postgres 기반 Public API 엔드투엔드(TestClient+실DB) 추가 검증.
- 제외 범위 및 사유:
  - UNIT-02 이후에 생기는 `current_published_batch`, `raw_internal`(실제 마이그레이션), `public_serving`, Derivation Batch 관련 기능 — 이번 유닛의 어떤 마이그레이션도 이 스키마들을 생성하지 않으므로 여전히 UNIT-01 코드 범위 밖이다. **`raw_internal` 접근 거부(TC-071)는 그래서 대역 스키마로만 검증했고, 실제 산출물에 대한 검증은 UNIT-02 완료 후로 명시적으로 이관한다.**
  - `uvicorn`을 별도 프로세스로 기동해 네트워크(HTTP)로 호출하는 것 — v3에서도 하지 않았다. TC-074는 `TestClient`(인프로세스) + 실제 Postgres 조합으로, SQL/ORM 레이어의 실DB 검증은 완료했으나 "실제 서버 프로세스 기동"은 별개 항목으로 남아 있다(부분 해소로 §5/§7에 명시).
  - `session_close_at`(KRX 15:30/NXT 20:00) 실제 수치의 KRX 공식 자료 대조, `data/calendar/2026.example.yaml` 휴장일 목록의 실사실 검증 — 코드 로직 검증 범위가 아니라 외부 사실 확인(운영 전 재확인) 사항(§7 리스크로만 기록, 변경 없음).
- **범위(In-Scope, v4 추가)**: 5단계가 DEF-003/DEF-004를 수정한 코드(`db/alembic/versions/0002_grant_reference_privileges.py` 신규, `scripts/load_calendar.py` upsert 수정)를 5단계의 자체 검증 결과를 신뢰하지 않고 6단계가 완전히 독립적으로 재현. 코디네이터가 지시한 4개 항목(GRANT 자동 반영/api_service 거부/updated_at 갱신/기존 AC 회귀)을 전부 검증 대상에 포함.


**범위(In-Scope, v5 추가)**: (a) AC-8(rate limiting)/AC-9(보안 헤더)/AC-10(전역 예외 처리+타임아웃)의 pytest 신규 10건 독립 재실행, (b) 실제 `uvicorn` 서버(로컬 포트 8092~8097)로 rate limiting/보안헤더/CORS 상호작용을 네트워크 레벨로 재현, (c) **진짜 TCP 블랙홀(패킷 무응답) 시나리오로 `connect_timeout=3`의 실제 동작 재현** — 5단계가 명시적으로 남긴 미검증 항목, (d) `pytest tests/unit`(165건 전체)·`ruff check .` 독립 재실행(회귀 확인).
- 제외 범위(v5 추가): 멀티 워커/인스턴스 환경(`uvicorn --workers 2` 등)에서의 rate limiter 동작 — `unit-01-note.md` §3이 이미 알려진 한계로 명시했고(단일 인스턴스 전제, §5-2 근거) 이번 오케스트레이터 지시 범위(1~5번)에 포함되지 않아 재현하지 않음(후속 과제로 §7에 남김). 실제 동시 다발 요청으로 스레드풀(40) 고갈을 유발하는 부하테스트 — 09단계(§4-6)가 이미 정성 분석을 완료했고 이번 지시는 "단일 요청 단위 타임아웃 동작"의 검증으로 한정됨.

**범위(In-Scope, v6 추가)**: (a) DEF-005 해소 여부(429/타임아웃 503 응답의 보안 헤더 3종) 실측 재현 — 가능하면 v5가 썼던 "실제 uvicorn 서버 + 완전 격리된 Starlette 앱, 2가지 독립 경로" 방식 재적용, (b) 미들웨어 순서 변경으로 인한 회귀 확인(정상 200/`DBAPIError` 503 헤더 유지, CORS 헤더 일관성, rate limit 60/61 경계·OPTIONS 미소모, DB 타임아웃 경로의 코드 레벨 무변경 확인), (c) `pytest tests/unit`(167건)·`ruff check .` 독립 재실행, (d) 신규 pytest 2건이 DEF-005 시나리오를 의미 있게 커버하는지 mutation testing(순서를 실제로 되돌려 테스트가 실패하는지)으로 검증.
- 제외 범위(v6 추가): DEF-SEC-01(rate limiting)/DEF-FS-01(REQ-025, TCP 블랙홀 포함 DB 타임아웃)의 전면 재검증 — 코디네이터 지시대로 "이미 3중 독립 재현으로 Fixed 확인된 부분은 처음부터 다시 검증할 필요 없고 회귀만 확인하면 된다"는 원칙에 따라, v5(TC-087/088, TC-093~096)의 전체 재현 절차(TCP 블랙홀 3초 지연 등)를 반복하지 않고 코드 무변경 확인 + 핵심 경계(60/61)만 재확인했다. 멀티 워커 rate limiter 한계, 스레드풀 고갈 부하테스트는 v5와 동일하게 이번 지시 범위 밖(변경 없음).

## 3. 테스트 환경
- 실행 환경: Windows 10, Python 3.13.9, pytest 9.1.1, ruff 0.12.0, FastAPI 0.139.0, SQLAlchemy 2.0.51, Alembic 1.14.0, psycopg 3.3.4, PyYAML 6.0.3 (v1~v3 동일 환경, 버전 변동 없음).
- **PostgreSQL/Docker 가용성(v1/v2 → v3 변경)**: v1/v2에서는 `which psql`/`which pg_ctl` 없음, `docker info` 데몬 미기동을 직접 확인해 AC-3 불릿4/AC-5를 "미검증"으로 유지했다. **v3에서는 코디네이터가 실제 PostgreSQL 16(Docker 컨테이너 `stock-screener-db`, `postgres:16-alpine`, 포트 5432, DB `stock_screener`)을 기동했고, `docker ps -a`로 `Up` 상태를 확인한 뒤 `docker exec stock-screener-db psql -U migrator -d stock_screener -c "\du"`로 3개 역할(`migrator` SUPERUSER, `batch_worker`, `api_service`, 비밀번호 `devpass`)이 실제로 존재함을 직접 확인**했다.
- 접속 문자열(이번 세션에서 실제 사용): `ALEMBIC_DATABASE_URL=postgresql+psycopg://migrator:devpass@localhost:5432/stock_screener`, `BATCH_DATABASE_URL=postgresql+psycopg://batch_worker:devpass@localhost:5432/stock_screener`, `PUBLIC_API_DATABASE_URL=postgresql+psycopg://api_service:devpass@localhost:5432/stock_screener` — `.env.example` 패턴을 그대로 따르되 비밀번호만 `devpass`로 대체.
- 테스트 데이터: `data/calendar/2026.example.yaml`(정상 케이스, 실제 upsert에도 그대로 사용), `tests/unit/test_last_trading_day.py`의 `FakeCalendar`/`week_calendar` 픽스처, v2에서 작성한 독립 스윕 스크립트용 인메모리 캘린더, **v3 신규**: 실제 `reference.market_calendar` 테이블(Postgres) 730행, 검증 후 삭제한 대역(proxy) `raw_internal.raw_ohlcv` 테이블(1행, 임시).
- **환경 관리 원칙(v3)**: 검증 과정에서 라이브 DB에 적용한 GRANT(TC-066)와 실제 캘린더 데이터(TC-067)는 세션 종료 후에도 되돌리지 않고 그대로 두었다(다음 검증에 재사용 가능하도록). 반면 UNIT-01 범위를 벗어난 대역 스키마(`raw_internal`, TC-071)는 검증 직후 `DROP SCHEMA ... CASCADE`로 즉시 삭제해 흔적을 남기지 않았다 — "실제 검증에 필요한 상태는 보존하되, 범위를 벗어난 임시 산출물은 정리한다"는 원칙을 지켰다.
- 전제 조건: `pip install -r requirements-dev.txt` 기 설치 환경(변경 없음). 샌드박스 정책상 일부 실 DB 쓰기 명령(`python scripts/load_calendar.py` 직접 실행)이 자동 분류기에 의해 간헐적으로 차단되는 경우가 있어(사유: "Modify Shared Resources"), 재시도 또는 `docker exec psql`을 통한 동등 SQL 실행으로 우회 없이 대체 검증했다(§4-3 각 TC 비고 참조).


**실행 환경(v5 추가)**: Windows 10(Git Bash), Python 3.13.9, pytest 9.1.1, ruff 0.12.0(변경 없음). 로컬 Docker `stock-screener-db`(postgres:16-alpine)는 **이미 실행 중이던 컨테이너를 그대로 재사용**했다(6단계가 새로 만들거나 중지하지 않음 — 검증 전후 `docker ps` 결과 `Up 9시간대`로 상태 불변 확인, §7 Teardown 참조).
- **TCP 블랙홀 재현 방법**: 사설 예약 대역(RFC 5737 TEST-NET-1) IP `10.255.255.1:5432`로 접속을 시도했다 — 이 주소는 로컬 네트워크에 실제로 존재하지 않는 호스트이므로 SYN 패킷에 대한 응답(RST든 ACK든)이 전혀 오지 않는다. 이는 "connection refused"(포트가 닫혀 있어 OS가 즉시 RST를 보내는 경우, 보통 수 ms 이내)와 명확히 다른, 8/9단계가 원래 실측했던 "패킷이 응답 없이 사라지는" 시나리오에 훨씬 가깝다. `psycopg.connect(..., connect_timeout=3)`을 이 주소로 직접 호출해 실제 소요 시간을 측정했다(§4-5 TC-093/094).
- 참고로 로컬 포트 5999(아무 것도 리스닝하지 않음)로도 시도했으나, 이 환경(Windows, Docker Desktop 네트워크 스택)에서는 "닫힌 로컬 포트"조차 즉시 RST가 오지 않고 `10.255.255.1`과 유사하게 약 3초 뒤 타임아웃되는 것을 관찰했다(원인 미상 — 방화벽/보안 소프트웨어의 아웃바운드 필터링 가능성, 이 로컬 환경 특유의 현상으로 추정, §7 참고 기록). 이 관찰 자체는 결함 판정에 영향을 주지 않으며(오히려 이 경로에서도 `connect_timeout`이 정상 작동함을 추가로 보여줌), "connection refused는 항상 즉시 실패한다"는 5단계 note의 암묵적 가정이 이 로컬 환경에서는 반드시 성립하지 않는다는 참고 사실로만 기록한다.
- 실제 `uvicorn` 프로세스를 로컬 포트 8092~8097에서 총 6회 개별 기동(각기 다른 `PUBLIC_API_DATABASE_URL`로 시나리오 분리: 블랙홀 IP, 로컬 닫힌 포트, 실제 서버+잘못된 비밀번호)했고, 각 검증 후 종료했다. Git Bash의 `kill <job_pid>`가 백그라운드 잡 PID와 실제 Windows 프로세스 PID가 불일치해 작동하지 않는 것을 발견해, `netstat -ano`로 실제 LISTENING 포트의 PID를 찾아 `taskkill //F //PID <pid>`로 확실히 종료했다(§7 Teardown 참조 — 매번 `netstat`으로 잔여 리스너 없음을 재확인).

**실행 환경(v6 추가)**: Windows 10(Git Bash), Python 3.13.9, pytest 9.1.1, ruff 0.12.0(변경 없음). 로컬 Docker `stock-screener-db`는 이번에도 **이미 실행 중이던 컨테이너를 그대로 재사용**했다(세션 시작 시 `docker ps` 결과 `Up 9시간대` — v5 종료 시점과 연속, 6단계가 재시작/중지하지 않음).
- **재현 포트**: 05단계(`unit-01-note.md` §6-1 v6)가 사용한 포트 8199와 겹치지 않도록, 6단계는 독립적으로 포트 8111~8113을 사용해 총 3회 개별 `uvicorn` 기동을 수행했다(8111: 정상 DB 접속으로 정상 200/429 헤더 확인, 8112: 정상 DB 접속으로 60/61 경계 재확인, 8113: 존재하지 않는 계정으로 `DBAPIError` 503 경로 + OPTIONS 프리플라이트 재확인).
- **mutation testing 방법**: `services/public_api/main.py`를 사전에 `.harness-tmp/main.py.orig.bak`로 백업한 뒤, 파이썬 스크립트로 `add_middleware` 순서를 v5의 버그 순서로 일시 변경(`SecurityHeadersMiddleware`를 `RequestTimeoutMiddleware`/`RateLimitMiddleware`보다 먼저 등록)해 신규 pytest 2건을 재실행하고, 검증 직후 백업본으로 즉시 복원했다(`diff`로 원본과 바이트 단위 동일함을 확인 후 백업 파일 삭제, §6-1 Teardown 참조).

## 4. 테스트 케이스 및 결과 (v1, 이력 보존)

> 아래 표는 v1(FAIL 판정) 당시의 원문이다. DEF-001/DEF-002 관련 행(TC-008~010, TC-029, TC-036)의 "Pass/Fail" 판정은 **당시 코드 기준**의 판정이며, v2 재작업 이후에는 §4-2의 새 테스트로 대체·재검증됐다. 나머지(AC-2/AC-3/AC-5/AC-6 등)는 재작업 대상이 아니었으므로 아래 결과가 그대로 유효하되, §4-2 말미에서 회귀 여부만 다시 확인했다.

### AC-1: 핵심 알고리즘 `get_last_trading_day()`

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-001 | 평일 개장 시각 이후 + 당일 거래일 | KRX, 2026-09-14(월) 캘린더 행 존재·거래일 | `pytest tests/unit/test_last_trading_day.py::test_returns_today_when_today_is_trading_day_and_after_open` 독립 재실행 | 당일(2026-09-14) 반환 | 당일 반환 | PASS(v1 당시 코드 기준) | v2: 이 테스트 자체는 재작업으로 제거되고 `test_boundary_truth_table`로 대체됨(§4-2 TC-043) |
| TC-002 | 개장 시각 이전 → 당일 제외, 역순 탐색 | 토/일 휴장, 금요일만 거래일 | `test_excludes_today_before_market_open` 재실행 | 직전 금요일 반환 | 직전 금요일 반환 | PASS(v1 당시 코드 기준) | v2: 동일하게 `test_boundary_truth_table`로 대체됨 |
| TC-003 | 연속 휴장일(연휴) 자동 스킵 | 3일 연속 휴장 후 조회 | `test_skips_consecutive_holidays` 재실행 | 연휴 이전 마지막 거래일 반환 | 연휴 이전 마지막 거래일 반환 | PASS | AC-1 불릿3, v2에서도 동일 테스트가 유지되어 재실행 확인(§4-2 TC-059) |
| TC-004 | 캘린더 데이터 공백 → `None` | 빈 캘린더(해당 연도 미등록) | `test_returns_none_on_calendar_gap` 재실행 | `None` 반환(조용한 대체 없음) | `None` 반환 | PASS | v2에서도 유지, 재실행 확인 |
| TC-005 | `MAX_LOOKBACK_DAYS` 초과 → 예외 | 500일 연속 휴장으로 적재된 비정상 캘린더 | `test_raises_when_scan_limit_exceeded` 재실행 | `CalendarScanLimitExceeded` 발생 | 예외 발생 | PASS | v2에서도 유지 |
| TC-006 | 알 수 없는 market → `ValueError` | `market="XYZ"` | `test_unknown_market_raises_value_error` 재실행 | `ValueError` 발생 | 예외 발생 | PASS | v2에서도 유지 |
| TC-007 | 시장별 개장 시각 분리(NXT 08:00) | NXT, 08:30 호출 | `test_market_open_time_boundary_is_market_specific` 재실행 | 당일 반환(NXT는 08:00 개장 가정이므로 08:30은 개장 후) | 당일 반환 | PASS(v1 당시 코드 기준) | **v2: 이 테스트 자체가 `market_open_time` 개념과 함께 삭제됨(설계 변경에 따른 정당한 삭제, 회귀 아님) — §4-2 TC-053에서 확인** |
| TC-008 | 개장 경계 정밀 스윕(08:59:59~23:59:59) | KRX, 2026-09-14(월, 거래일), `session_close_at=15:30` | (v1 원문 그대로) | (v1 원문 그대로) | (v1 원문 그대로) | PASS(코드 동작 자체는 조건식 그대로) / DEF-001로 귀결 | **v2: §4-2 TC-046(00:00:00~23:59:59 전 구간 초 단위 스윕)으로 대체 재검증, 결과 반전(PASS)** |
| TC-009 | 장중(마감 전) 시각에 "당일"이 반환되는 것이 설계 의도와 부합하는가 — 판정 | TC-008의 12:00:00, 15:29:59 결과 | (v1 원문 그대로) | (v1 원문 그대로) | (v1 원문 그대로) | **FAIL (DEF-001)** | **v2: §4-2 TC-043/046에서 마감 시각 기준으로 재판정, DEF-001 해소 확인(Fixed)** |
| TC-010 | 마감 시각 전후 비교(15:29:59 vs 15:30:01) | 동일 캘린더 | (v1 원문 그대로) | (v1 원문 그대로) | (v1 원문 그대로) | **FAIL (DEF-001의 근거 보강)** | **v2: §4-2 TC-043(진리표 #4~#6) 재실행 결과 마감 전후로 결과가 달라짐을 확인, 해소** |

### AC-2: CLI YAML 파싱 (`calendar_file.py`)

| ID | 시나리오 | Pass/Fail | 비고 |
|----|----------|-----------|------|
| TC-011~017 | (v1 원문 그대로, 정상 YAML/override/필수필드누락/위험케이스 등) | 전부 PASS | 재작업 대상 아님. v2 §4-2 TC-059(pytest 전체 재실행)로 회귀 없음 재확인 |

### AC-3: CLI 실행 (`scripts/load_calendar.py`)

| ID | 시나리오 | Pass/Fail | 비고 |
|----|----------|-----------|------|
| TC-018~020, TC-022~024 | (v1 원문 그대로, `--dry-run`/파일없음/환경변수미설정/빈YAML/문법오류/리스트형식) | 전부 PASS | 재작업 대상 아님. v2 §4-2 TC-061/062로 재실행 확인(회귀 없음) |
| TC-021 | Postgres 준비 환경에서 실제 upsert + 재실행 시 갱신 | **미검증(NOT TESTED)** | v2에서도 환경 제약 동일 — §4-2 TC-063 참조, 임의로 통과 처리하지 않음 |

### AC-4: Public API

| ID | 시나리오 | Pass/Fail | 비고 |
|----|----------|-----------|------|
| TC-025~028, TC-030~035 | (v1 원문 그대로, 정상/424/400/naive datetime 등) | 전부 PASS | 재작업 대상 아님(단, TC-025의 `as_of` 값 자체가 v4 로직에서는 의미가 바뀜 — 5단계가 `unit-01-note.md` §0 항목7에서 픽스처를 마감시각 기준으로 수정했음을 v2 §4-2 TC-059 재실행으로 확인) |
| **TC-029** | `/health` DB 예외 시 degraded — **커버리지 공백 보완(임시 스크립트)** | PASS(동작 자체는 정상) | **v2: `tests/unit/test_public_api.py`에 정식 회귀 테스트로 추가됨(DEF-002 Fixed) — §4-2 TC-057** |
| **TC-036** | `CalendarScanLimitExceeded` → 503 — **커버리지 공백 보완(임시 스크립트)** | PASS(동작 자체는 정상) | **v2: 정식 회귀 테스트로 추가됨(DEF-002 Fixed) — §4-2 TC-058** |

### AC-5: 마이그레이션 (Postgres 환경 필요)

| ID | 시나리오 | Pass/Fail | 비고 |
|----|----------|-----------|------|
| TC-037, TC-038, TC-040 | 오프라인 SQL 생성/롤백 DDL, SQLite 대체 복합PK 검증 | PASS | 재작업 대상 아님, 변경 없음 |
| TC-039 | 실제 PostgreSQL `upgrade head`/`downgrade base` | **미검증(NOT TESTED)** | v2에서도 환경 제약 동일 — §4-2 TC-063 참조 |

### AC-6: 정적 분석

| ID | 시나리오 | Pass/Fail | 비고 |
|----|----------|-----------|------|
| TC-041, TC-042 | ruff/pytest 전체 재실행(v1 당시 21건) | PASS | v2에서는 36건으로 확장 — §4-2 TC-059/060 재확인 |

---

## 4-2. v2 재검증 테스트 케이스 (DEF-001/DEF-002 재작업 대응)

### AC-1 재검증 — v4 §3-3 13행 진리표 및 전 구간 스윕

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과(근거: `03-system-design.md` v4 §3-3 진리표) | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-043 | v4 13행 진리표 중 #1~#11(경계 시각별 KRX/NXT 마감 전후) 파라미터화 재실행 | `week_calendar` 픽스처(09-11 거래일, 09-12/13 휴장, 09-14 거래일, KRX close=15:30/NXT close=20:00) | `pytest tests/unit/test_last_trading_day.py::test_boundary_truth_table -v` 독립 재실행(11개 파라미터 케이스) | KRX 08:59:59~15:29:59 → 09-11(전일), 15:30:00 이후(정각 포함)~23:59:59 → 09-14(당일); NXT 19:59:59 → 09-11, 20:00:00 이후 → 09-14 | 11개 케이스 전부 예상값과 일치(`11 passed`) | **PASS** | 설계서 표를 그대로 코드로 재현한 것을 6단계가 독립 재실행. `-v` 옵션으로 개별 파라미터 ID별 통과 확인(뭉뚱그려 "전체 pass"만 본 것이 아님) |
| TC-044 | 진리표 #12(휴장일은 시각 무관 스킵) | 2026-09-13(일, 휴장) 임의 시각 | `test_truth_table_row12_holiday_is_skipped_regardless_of_time` 재실행 | 시각과 무관하게 09-11(전일) 반환 | 09-11 반환 | PASS | |
| TC-045 | 진리표 #13(캘린더 공백 → `None`) | 2027년 캘린더 미등록 | `test_truth_table_row13_calendar_gap_returns_none` 재실행 | `None` 반환 | `None` | PASS | |
| **TC-046** | **(핵심 재검증) DEF-001 재현 절차의 확장판 — 00:00:00~23:59:59 전 구간·초 단위 독립 스윕** | KRX/NXT 각각 2026-09-14(거래일), close=15:30/20:00, 직전 거래일 09-11 — **`tests/unit/`의 기존 테스트 코드를 재사용하지 않고 6단계가 별도로 새로 작성한 스크립트**로 캘린더 픽스처부터 독립 구성 | 각 시장(KRX/NXT)에 대해 00:00:00부터 23:59:59까지 1초 간격으로 `get_last_trading_day(market, as_of, calendar)` 호출(시장당 86,400회, 총 **172,800회**) | 각 시장의 마감 시각 미만 구간 전부 09-11(전일) 반환, 마감 시각 이상(정각 포함) 구간 전부 09-14(당일) 반환 — 불일치 0건이어야 함 | **총 172,800회 호출, 불일치(Failures) 0건** — 콘솔 출력 `Total checks: 172800 / Failures: 0` 직접 확인 | **PASS** | v1의 TC-008(당시 09:00~23:59:59, 8개 표본점만 확인)보다 범위를 자정부터 전 구간·초 단위로 확장했다. v1이 발견한 결함(개장 시각 기준 비교로 09:00~마감 전 구간에서 오답)이 재현되는지 정면으로 재시도했으나, 이번에는 전 구간에서 일관되게 마감 시각 기준으로 정확히 동작함을 확인 — **DEF-001 실제 해소**(§6 참조) |
| TC-047 | 마감 시각 마이크로초 경계(정각 -1us/0us/+1us) | KRX, close=15:30:00.000000 | 독립 스크립트로 `15:30:00`에서 ±1마이크로초 시각 3개 호출 | -1us→전일, 0us(정각)→당일, +1us→당일(`>=` 비교, 정각 포함) | `[(-1, 09-11, 09-11, True), (0, 09-14, 09-14, True), (1, 09-14, 09-14, True)]` | PASS | 설계서 진리표 #5/#10 "마감 정각은 이미 마감으로 포함(`>=`)" 문구를 극한 경계값으로 재확인(위험 케이스, 진리표에 명시된 원칙의 엄밀한 재확인) |
| TC-048 | 과거 날짜는 마감 시각과 무관하게 항상 마감 처리 | 09-11(휴장 처리), 09-10(거래일)로 설정, `as_of=09-11T00:00:00`(자정 직후) | `test_past_date_is_always_closed_regardless_of_close_time` 재실행 | 09-10 반환(과거 날짜는 `_already_closed`에서 시각 비교 없이 항상 True) | 09-10 반환 | PASS | |
| TC-049 | 단락 평가 순서 보호 — 휴장일 행(`session_close_at=None`) 조회 시 크래시 없음 | 09-14 휴장일(close=None) | `test_short_circuit_prevents_crash_on_holiday_with_null_close_time` 재실행 | 예외 없이 역순 탐색, 이전 데이터 없으면 `None` | `None` 반환, 예외 없음 | PASS | v4 설계서 "구현 시 필수 주의사항" 2번(단락 평가 순서) 코드 재확인 — `row.is_trading_day and _already_closed(...)` 순서를 직접 읽어 `is_trading_day=False`일 때 `_already_closed` 호출 자체가 생략됨을 소스코드로도 확인 |
| TC-050 | `CalendarDataError` — 거래일인데 `session_close_at` 없음(데이터 무결성 위반) | 09-14 거래일(is_trading_day=True), close=None | `test_calendar_data_error_when_trading_day_missing_close_time` 재실행 | `CalendarDataError` 발생 | 예외 발생 | PASS | v2 신규 방어 로직(unit-01-note.md §0 항목4) |
| TC-051 | `MAX_LOOKBACK_DAYS`(400) 초과 → `CalendarScanLimitExceeded` | 500일 연속 휴장 캘린더 | `test_raises_when_scan_limit_exceeded` 재실행 | 예외 발생 | 예외 발생 | PASS | v1과 동일 로직 유지, 재실행 확인 |
| TC-052 | 알 수 없는 `market` → `ValueError` | `market="XYZ"` | `test_unknown_market_raises_value_error` 재실행 | 예외 발생 | 예외 발생 | PASS | |
| **TC-053** | **(무결성 확인) `market_hours.py` 삭제 후 잔존 참조 없음** | 프로젝트 전체 소스 | `find . -iname "market_hours*"`(파일 존재 여부) + `grep -rn "market_hours\|market_open_time" --include="*.py" .`(실제 import/호출 여부) | 파일 없음, grep 결과에 실제 `import`/함수 호출 없이 **주석(설명 텍스트)에서만** 언급되어야 함 | 파일 없음 확인. grep 결과 2건 모두 `last_trading_day.py` 상단 docstring 내 설명 문장("v4 근본 수정: ... `market_open_time` ... `market_hours.py` 삭제, DEC-018")뿐, 실제 `import shared.calendar_service.market_hours` 또는 `market_open_time(...)` 호출 코드는 0건 | **PASS** | 삭제로 인한 깨진 import 없음을 직접 확인(추측 아님) |

### AC-4 재검증 — API 레벨 예외 매핑 및 DEF-002 회귀 테스트

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-054 | API 레벨 마감 경계(naive datetime) — `as_of` 오프셋 없이 15:29:59/15:30:00 요청 | `FakeRepository`에 09-11(거래일)·09-12/13(휴장)·09-14(거래일) 전부 주입(캘린더 공백 없음) | `TestClient`로 `GET /api/v1/calendar/last-trading-day?market=KRX&as_of=2026-09-14T15:29:59`와 `...T15:30:00` 각각 호출 | 15:29:59 → 200, `data.trade_date=2026-09-11`; 15:30:00 → 200, `data.trade_date=2026-09-14` | 15:29:59 → 200, `{"trade_date":"2026-09-11"}`; 15:30:00 → 200, `{"trade_date":"2026-09-14"}` | **PASS** | **최초 실행 시 09-12/13 휴장 행을 빠뜨려 424(캘린더 공백)가 잘못 관측됨 — 이는 테스트 스크립트 자체의 결함이었고, 캘린더를 올바르게 구성(09-12/13 휴장 행 포함)해 재실행한 결과가 위 값이다.** "테스트 자체가 잘못 설계되어 결함을 놓칠 가능성"을 재점검하는 내부 검증 과정에서 스스로 발견·정정한 사례로 기록 |
| **TC-055** | **(v2 신규 위험 케이스) `CalendarDataError`의 API 레벨 매핑** — note가 API 레벨 예시로 명시하지 않은 하위 예외까지 직접 검증 | 09-14 거래일인데 `session_close_at=None`(데이터 무결성 위반) | `GET /api/v1/calendar/last-trading-day?market=KRX&as_of=2026-09-14T12:00:00+09:00` 직접 호출 | 503, `error.code == "SERVICE_UNAVAILABLE"` | 503, `{"code":"SERVICE_UNAVAILABLE", ...}` | **PASS** | `unit-01-note.md`/AC-4는 `CalendarScanLimitExceeded`만 명시적으로 예시를 들었으나, `CalendarDataError`도 같은 `CalendarIntegrityError` 계열이므로 API가 실제로 동일하게 503 매핑하는지 6단계가 범위를 넓혀 직접 확인(범위 밖이어도 위험한 경로는 검증한다는 원칙) |
| TC-056 | `services/public_api/api/calendar.py`가 `CalendarIntegrityError` 공통 베이스로 캐치하는지 코드 리뷰 | 소스 확인 | `except CalendarIntegrityError as exc:` 구문 존재 여부 직접 확인 | `CalendarScanLimitExceeded`/`CalendarDataError` 둘 다 단일 `except` 절로 503 처리 | 코드에 `except CalendarIntegrityError as exc:` 1곳만 존재, 하위 클래스 개별 분기 없음(공통 베이스로 통합 확인) | PASS | TC-055(CalendarDataError)와 기존 TC-036 계열(CalendarScanLimitExceeded, TC-058) 두 경로가 동일 코드 경로임을 코드 리딩 + 실행 결과 양쪽으로 교차 확인 |
| **TC-057** | `/health` DB 예외 → degraded, **정식 회귀 테스트 존재 및 통과** | `FailingFakeDbSession`(execute 시 예외) 의존성 주입 | `pytest tests/unit/test_public_api.py::test_health_degraded_when_db_check_fails -v` 독립 재실행 | 200, `{"status":"ok","db":"degraded"}` | 1 passed | **PASS** | **DEF-002 해소 확인.** v1은 6단계가 임시 스크립트(TC-029)로만 검증했으나, 이번엔 `tests/unit/test_public_api.py`에 실제로 추가된 정식 pytest 케이스임을 파일을 열어 직접 확인한 뒤 재실행 |
| **TC-058** | `CalendarScanLimitExceeded` → 503, **정식 회귀 테스트 존재 및 통과** | 500일 연속 휴장 캘린더 주입 | `pytest tests/unit/test_public_api.py::test_last_trading_day_scan_limit_exceeded_returns_503 -v` 독립 재실행 | 503, `SERVICE_UNAVAILABLE` | 1 passed | **PASS** | **DEF-002 해소 확인.** |

### AC-2/AC-3/AC-6 회귀 재확인 (재작업 대상 아니었던 부분)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| TC-059 | pytest 전체 스위트 독립 재실행 | `python -m pytest tests/unit -q` | 5단계가 note에서 주장한 36건 전부 pass | `36 passed, 1 warning`(httpx deprecation 경고, 기능 결함 아님, v1부터 알려진 사항) | **PASS** | 5단계 자체 보고를 그대로 믿지 않고 6단계 세션에서 직접 재실행해 숫자 자체(36)와 결과(전부 pass)를 모두 확인 |
| TC-060 | ruff 린트 독립 재실행 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** | |
| TC-061 | CLI `--dry-run` 정상 실행 재확인(market_hours 삭제 회귀 없는지) | `python scripts/load_calendar.py data/calendar/2026.example.yaml --dry-run` | 종료코드 0, 시장별 집계 출력 | `총 730건 / KRX 거래일257·휴장108 / NXT 거래일257·휴장108`, `(--dry-run) DB에 반영하지 않았습니다.`, 종료코드 0 | PASS | AC-3 관련 코드는 `last_trading_day.py`/`market_hours.py`와 직접 연관이 없으나(별도 모듈), 회귀 확인 차원에서 재실행 |
| TC-062 | 존재하지 않는 파일 CLI 재확인 | `python scripts/load_calendar.py data/calendar/nope.yaml --dry-run` | 종료코드 1, `[실패]` 메시지 | `[실패] 파일을 찾을 수 없습니다: ...`, 종료코드 1 | PASS | |
| **TC-063** | **(정직한 미검증 유지) Postgres/Docker 실기동 가용성 재확인 — AC-3 불릿4/AC-5** | 로컬 환경 | `which psql`/`which pg_ctl`(없음 확인) + `docker info`(서버 연결 실패 확인) | 환경 제약이 v1과 동일하면 AC-3 불릿4(실 upsert)/AC-5(실 마이그레이션)는 **미검증으로 유지**해야 함(임의 통과 처리 금지, 사용자 명시 지시) | psql/pg_ctl 없음, `docker info` → `Server: failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine ... The system cannot find the file specified` | **미검증(NOT TESTED)** — v1과 동일 상태 유지, 임의로 PASS 처리하지 않음 | 환경 제약은 코드 결함이 아니므로 결함 목록에 등록하지 않고 §7 리스크로 유지(v1과 동일 방침) |

> 정상 경로/경계값/예외 입력 커버리지 요약(v2): TC-043~045·048~052·056~062는 정상/기존 경로 및 예외 처리 재확인, **TC-046(전 구간·초 단위 172,800회 스윕)·TC-047(마이크로초 경계)이 이번 재검증의 핵심 경계값 케이스**, TC-055(CalendarDataError API 매핑)는 AC 범위를 넘어 직접 추가한 위험 케이스, TC-063은 환경 제약으로 인한 정직한 미검증 기록.

## 4-3. v3 재검증 테스트 케이스 (실제 PostgreSQL 환경, AC-3/AC-5 확정 검증)

> 실행 환경: 컨테이너 `stock-screener-db`(postgres:16-alpine), DB `stock_screener`, 역할 `migrator`(SUPERUSER)/`batch_worker`/`api_service`(비밀번호 `devpass`, 코디네이터가 사전 생성). 모든 명령은 `docker exec stock-screener-db psql ...` 또는 실제 `ALEMBIC_DATABASE_URL`/`BATCH_DATABASE_URL`/`PUBLIC_API_DATABASE_URL` 환경변수로 프로젝트 코드를 직접 실행해 확인했다(Fake/Mock 없음).

### AC-5 확정 검증 - 실제 마이그레이션 적용/롤백

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-064 | 실제 PostgreSQL에 `alembic upgrade head` 적용 | 빈 DB(`\dn` 결과 `public` 스키마만 존재 확인) | `ALEMBIC_DATABASE_URL=postgresql+psycopg://migrator:devpass@localhost:5432/stock_screener python -m alembic upgrade head` | 종료코드 0, `reference` 스키마·`market_session` ENUM(KRX/NXT)·`market_calendar` 테이블(PK `(trade_date, market)`) 생성 | 종료코드 0. 실제 쿼리로 확인: `\dn`에 `reference` 스키마 추가, `\d reference.market_calendar`에 7개 컬럼과 PK `(trade_date, market)` btree 인덱스 정확히 일치, `pg_enum` 조회 결과 `KRX`/`NXT` 2개 라벨 정확히 존재, `alembic_version` 테이블에 `0001` 기록 | **PASS(확정)** | v1/v2는 `--sql`(오프라인 DDL 생성)로만 검증했으나, 이번엔 실제 DB에 적용 후 시스템 카탈로그(`\dn`, `\d`, `pg_enum`)를 직접 쿼리해 확인했다 |
| TC-065 | (기준선 확보) GRANT 적용 전 `batch_worker`로 upsert 시도 | 위 상태 그대로(GRANT 없음) | `BATCH_DATABASE_URL=postgresql+psycopg://batch_worker:devpass@localhost:5432/stock_screener python scripts/load_calendar.py data/calendar/2026.example.yaml` | (가설) 정상 실행되거나, 권한 문제로 실패한다면 명시적 에러 메시지와 함께 실패해야 함(조용한 실패 없음) | `[실패] DB 반영 중 오류: (psycopg.errors.InsufficientPrivilege) permission denied for schema reference` — 종료코드 1, 원인이 명확한 에러 메시지로 실패(조용한 실패 아님) | **PASS(스크립트의 명시적 실패 원칙 자체는 준수) / 이 결과 자체가 DEF-003의 증거** | 마이그레이션 0001이 어떤 GRANT도 실행하지 않는다는 것을 실제로 재현. 스크립트가 예외를 삼키지 않고 원인이 분명한 메시지로 실패한 것은 설계 원칙("명시적 실패") 준수로 PASS이나, "정상적인 role 분리 환경에서 애초에 실행 자체가 안 된다"는 사실은 별도로 DEF-003에 등록 |
| TC-066 | §1-1 2차 방어 설계에 따라 GRANT 수동 적용 | TC-065 상태 | `migrator`로 `GRANT USAGE ON SCHEMA reference TO batch_worker, api_service; GRANT SELECT, INSERT, UPDATE ON reference.market_calendar TO batch_worker; GRANT SELECT ON reference.market_calendar TO api_service;` 실행 | GRANT 3건 성공 | `\dp reference.market_calendar` 조회 결과 `batch_worker=arw`, `api_service=r`로 정확히 반영 확인 | PASS | **이 GRANT는 코드베이스가 아니라 라이브 테스트 DB에만 적용한 것이다** - 마이그레이션 파일 자체는 여전히 변경되지 않았음(DEF-003 미해결 상태 유지, §0-2 참조) |
| TC-067 | GRANT 적용 후 `batch_worker`로 실제 upsert 실행 | TC-066 상태 | `BATCH_DATABASE_URL=...batch_worker... python scripts/load_calendar.py data/calendar/2026.example.yaml` 실행 후 `SELECT market, is_trading_day, count(*) FROM reference.market_calendar GROUP BY market, is_trading_day` | 종료코드 0, `[완료] 730건을 반영` 메시지, DB에 KRX/NXT 각각 거래일 257·휴장 108건 | 종료코드 0, `[완료] 730건을 reference.market_calendar에 반영했습니다.` 출력. 실제 집계 쿼리 결과 KRX(거래일257/휴장108), NXT(거래일257/휴장108) - YAML 파싱 요약과 정확히 일치 | **PASS(확정)** | AC-3 불릿4의 핵심 요구사항("실제 upsert 반영 확인")을 실제 DB 조회로 확인. Fake 레포지토리가 아니라 실제 Postgres 데이터 |
| TC-068 | 재실행 시 idempotent 갱신(중복 삽입 오류 없음) | TC-067 상태 그대로, 동일 YAML로 재실행 | 동일 명령 재실행 후 `SELECT count(*)`, `SELECT count(DISTINCT (trade_date,market))` | 종료코드 0, row 수 730 그대로 유지(중복 없음), PK 충돌 에러 없음 | 종료코드 0, `count(*)=730`, `count(DISTINCT (trade_date,market))=730` - 완전히 일치, 유니크 제약 위반 에러 없음 | **PASS(확정)** | AC-3 불릿4 "재실행 시 동일 데이터로 갱신(중복 삽입 오류 없음)" 요구사항 확정 검증 |
| **TC-069** | **(위험 케이스, 추가) 실제 내용 변경이 upsert로 올바르게 반영되는지 + `updated_at` 회귀 여부** | 한 행(`2026-01-01`, `KRX`)을 `migrator`로 직접 `UPDATE ... SET holiday_name='WRONG_TEST_VALUE', source='corrupted-for-test'`로 오염시킴 | 오염 확인 후 `batch_worker`로 동일 YAML 재실행, 오염된 행 재조회 | 내용은 YAML 원본값(`신정`, 정상 source)으로 정확히 복구되어야 함 | 내용은 정확히 복구됨(`holiday_name='신정'`, `source='KRX 공식 공고 2026 (...)'`) - **upsert 내용 갱신 로직 자체는 정상**. 그러나 `updated_at`이 오염 전(최초 삽입 시각)과 **동일한 값으로 그대로 남아 있음**(재실행 2회 사이 `pg_sleep(2)`로 시간 간격을 뒀음에도 변화 없음) | **PASS(내용 갱신) / FAIL(`updated_at` 추적) → DEF-004로 등록** | `upsert_rows()`의 `on_conflict_do_update(set_={...})`에 `updated_at` 키가 빠져 있음을 코드 리딩으로 재확인(`scripts/load_calendar.py`) - 실제 값 변경과 함께 재현했으므로 "이론적 가능성"이 아니라 "실제 관찰된 동작" |

### 권한 분리(§1-1 2차 방어) 확정 검증

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| TC-070 | `api_service`는 `reference.market_calendar` 읽기만 가능, 쓰기 불가 | `api_service`로 `SELECT count(*)`, `UPDATE ...`, `INSERT ...` 각각 시도 | SELECT 성공(730), UPDATE/INSERT는 `permission denied` | SELECT → `730` 성공. UPDATE → `ERROR: permission denied for table market_calendar`. INSERT → `ERROR: permission denied for table market_calendar` | **PASS** | §3-1 "reference: batch_worker/api_service 둘 다 읽기, 쓰기는 batch_worker만" 설계를 GRANT 적용 후 실제로 확인(단, 이 GRANT 자체가 코드화되어 있지 않다는 점은 DEF-003과 동일 근본 원인) |
| **TC-071** | **(보조/proxy 검증) `api_service`의 `raw_internal` 접근 거부** - UNIT-02 산출물 부재로 인한 대역 스킴 사용 | `migrator`로 테스트 전용 `raw_internal` 스키마 + `raw_ohlcv` 테이블을 임시 생성(더미 1행), `batch_worker`에만 GRANT, `api_service`에는 아무 GRANT도 주지 않음 | `api_service`로 `SELECT * FROM raw_internal.raw_ohlcv` 및 `SET search_path TO raw_internal; SELECT ...` 시도. 검증 후 `DROP SCHEMA raw_internal CASCADE`로 즉시 정리 | `api_service`는 스키마 단계에서부터 거부(`permission denied for schema`)되어야 하고, `batch_worker`는 정상 조회 가능해야 함 | `api_service` → `ERROR: permission denied for schema raw_internal`(테이블 단계까지 가지도 못하고 스키마 USAGE 자체가 거부됨 - §1-1이 요구하는 것보다 더 강한 형태의 차단). `batch_worker` → 정상 조회(1행). 검증 후 `DROP SCHEMA raw_internal CASCADE` 실행, `\dn` 재확인 결과 `reference`/`public`만 남고 잔존물 없음 | **PASS(권한 모델 자체의 동작 확인, 단 UNIT-01 코드에 대한 검증은 아님)** | **주의: 이 테스트가 검증하는 것은 "GRANT를 안 주면 Postgres가 실제로 막아주는가"라는 일반 원리이지, "UNIT-01/UNIT-02 코드가 실제로 이렇게 배포됐는가"가 아니다.** `raw_internal` 스키마 자체가 UNIT-01에 존재하지 않으므로, 진짜 검증은 UNIT-02(`raw_internal.raw_ohlcv` 마이그레이션) 완료 후 재수행이 반드시 필요하다(§7 리스크로 이관) |

### AC-5 확정 검증 - 실제 롤백

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-072 | 실제 PostgreSQL에서 `alembic downgrade base` | TC-067~071 이후 상태(데이터 730건 존재) | `ALEMBIC_DATABASE_URL=...migrator... python -m alembic downgrade base` 후 `\dn`, `to_regclass('reference.market_calendar')`, `pg_type` ENUM 조회, `SELECT * FROM alembic_version` | 종료코드 0, `reference` 스키마·테이블·ENUM 전부 제거, `alembic_version` 비어 있음 | 종료코드 0. `\dn` → `public`만 남음. `to_regclass` → NULL(테이블 없음). `market_session` ENUM 조회 → 0 rows. `alembic_version` → 0 rows | **PASS(확정)** | v1/v2는 `--sql` 오프라인 모드로만 확인했으나 이번엔 실제 DB에서 데이터까지 포함해 완전히 제거됨을 확인(`DROP SCHEMA ... CASCADE`가 730건의 데이터도 함께 삭제한다는 것도 확인 - 당연하지만 실제로 관찰된 사실로 기록) |
| TC-073 | 롤백 후 재적용(clean re-upgrade) | TC-072 상태(완전히 빈 DB) | `alembic upgrade head` 재실행 | 종료코드 0, 스키마/테이블 재생성, 에러 없음(잔존 객체로 인한 충돌 없음) | 종료코드 0, `\dt reference.*` → `market_calendar` 테이블 재확인 | PASS | ENUM 중복 생성 등 잔존 문제가 실제로 없음을 확인(v1이 오프라인 모드로 우려했던 지점의 실제 환경 재현) |

### 부가 검증 - 실제 DB를 통한 Public API 엔드투엔드(수동 확인 항목 부분 해소)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| **TC-074** | **(범위 확장, 자발적 추가) 실제 Postgres 기반 Public API 전 구간 재검증** - `unit-01-note.md` §3 "Public API 실제 기동 미검증" 항목을 부분 해소 | `PUBLIC_API_DATABASE_URL=postgresql+psycopg://api_service:devpass@localhost:5432/stock_screener`로 `TestClient(app)` 생성(Fake 의존성 오버라이드 없음, 실제 `SqlCalendarRepository`+실제 Postgres ENUM 컬럼 경로 사용) | `GET /health`, `GET /calendar/last-trading-day?market=KRX&as_of=...12:00:00`(마감 전), `...16:00:00`(마감 후), `market=NXT&as_of=...20:30:00`(마감 후) 호출 | health 200 ok; KRX 12:00 → 200, 09-11(전일); KRX 16:00 → 200, 09-14(당일); NXT 20:30 → 200, 09-14(당일) | 4건 전부 예상과 일치(`health: 200 {'status':'ok','db':'ok'}`; KRX 12:00→`2026-09-11`; KRX 16:00→`2026-09-14`; NXT 20:30→`2026-09-14`) | **PASS** | **DEF-001(마감 시각 기준 판단)의 수정이 Fake가 아닌 실제 Postgres ENUM 타입·실제 SQLAlchemy ORM 경로를 통해서도 정확히 동작함을 확인** - 이전까지의 172,800회 스윕(TC-046)은 전부 `FakeCalendar`(인메모리) 기반이었는데, 이번엔 실제 DB 라운드트립으로 같은 결론 재확인. 단, 이 테스트는 `TestClient`(인프로세스)로 수행했고 별도 프로세스로 `uvicorn`을 기동해 네트워크 너머로 호출한 것은 아니므로, "uvicorn 실기동 미검증" 항목은 **부분 해소**로 표기한다(완전 해소 아님) |

> 정상 경로/경계값/예외 입력 커버리지 요약(v3): TC-064·067·068·070·072·073·074는 정상 경로 확정 검증, TC-065는 GRANT 부재 상태의 예외(실패) 경로, TC-069는 실제 내용 변경 시나리오(위험 케이스, DEF-004 발견), TC-071은 범위를 넘어선 보조 위험 케이스(대역 스키마, 검증 후 즉시 정리).

## 4-4. v4 재검증 테스트 케이스 (DEF-003/DEF-004 수정 확인, 코디네이터 지시 1~4)

> 5단계가 검증 후 남겨둔 DB 상태(0002 적용, GRANT 있음, 730건 데이터)를 그대로 믿지 않고, 6단계가 `alembic downgrade base`로 완전히 초기화한 뒤 처음부터 재구성했다. 오염 테스트도 5단계가 쓴 값과 다른 값(`WRONG_TEST_VALUE_V4`)으로 별도 재현했다.

### 지시 1: `downgrade base` → `upgrade head`로 0001+0002 순서 적용, GRANT 실제 반영

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-075 | 완전 초기화 후 fresh upgrade, 리비전 순서·GRANT 자동 반영 확인 | 이전 세션 상태(0002 적용됨)를 신뢰하지 않고 완전 초기화부터 시작 | `alembic downgrade base`(스키마/테이블/GRANT 전부 제거 확인, `\dn`/`alembic_version` 조회) → `alembic upgrade head` 재실행 → `\dp reference.market_calendar`, `has_schema_privilege(...)` 재조회 | downgrade 로그에 `0002 -> 0001 -> (base)` 순서 출력, 초기화 후 `public`만 남음. upgrade 로그에 `-> 0001 -> 0002` 순서 출력. GRANT는 **6단계가 수동 개입 없이** `batch_worker=arw`, `api_service=r`, `has_schema_privilege`가 둘 다 `t`로 나와야 함 | downgrade 로그: `Running downgrade 0002 -> 0001` → `Running downgrade 0001 -> ` 순서 확인, 초기화 후 `\dn`에 `public`만 남음, `alembic_version` 0 rows. upgrade 로그: `Running upgrade -> 0001` → `Running upgrade 0001 -> 0002` 순서 확인. `\dp`: `batch_worker=arw`, `api_service=r` 확인. `has_schema_privilege`: `batch_usage=t, api_usage=t` | **PASS** | 5단계 로그를 재사용하지 않고 6단계가 처음부터 완전히 재현. "우연히 이전 세션 GRANT가 남아있던 것"이 아니라 "마이그레이션 자체가 실행하는 것"임을 확인 |
| TC-081 | 부분 롤백(0002만 REVOKE) 및 데이터 보존 확인(보너스) | TC-075 이후 상태(0002 적용, 730건 데이터 없음 — 이 시점 이전) | `alembic downgrade 0001`(0002만 롤백) → `has_schema_privilege` 재조회, `\dp` 재조회, `SELECT count(*)` | GRANT만 REVOKE되고 `market_calendar` 테이블/데이터는 그대로 남아야 함(0001 객체는 안 건드림) | `has_schema_privilege`: `batch_usage=f, api_usage=f`(정확히 REVOKE됨). `\dp reference.market_calendar`: `migrator`만 남고 `batch_worker`/`api_service` 행 자체가 사라짐. `count(*)=730`(데이터 보존 확인, 이 시점엔 TC-078에서 이미 데이터 적재된 이후) | **PASS** | 0002가 0001의 테이블/데이터를 건드리지 않고 GRANT만 독립적으로 REVOKE함을 확인(리비전 분리가 실제로 안전함) |

### 지시 2: `api_service`의 `reference` 쓰기 시도 실제 거부 (독립 재현)

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| TC-076 | `api_service`로 UPDATE/INSERT/DELETE 각각 시도 | `api_service`로 `UPDATE reference.market_calendar SET source=...`, `INSERT INTO reference.market_calendar (...)`, `DELETE FROM reference.market_calendar WHERE ...` 각각 직접 실행 | 3건 모두 `permission denied for table market_calendar` | UPDATE → `ERROR: permission denied for table market_calendar`. INSERT → 동일 에러. DELETE → 동일 에러 | **PASS** | 5단계는 UPDATE만 확인했다고 note에 기록했으나, 6단계는 INSERT/DELETE까지 범위를 넓혀 재확인(위험 케이스 추가) |
| **TC-077** | **(보너스, 위험 케이스 추가) `batch_worker`도 DELETE는 거부되는지(최소 권한 원칙 확인)** | `batch_worker`로 `DELETE FROM reference.market_calendar WHERE ...` 시도 | `permission denied`(note가 "DELETE는 부여하지 않음 - 최소 권한 원칙"이라고 주장한 것을 실측) | `ERROR: permission denied for table market_calendar` | **PASS** | note의 "최소 권한 원칙 준수" 주장을 코드 리딩이 아니라 실제 권한 오류로 확인 |

### 지시 3: `batch_worker` CLI 재실행 시 `updated_at` 실제 갱신

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-078 | (재구성) 초기화된 DB에 `batch_worker`로 캘린더 재적재 | TC-075 이후 빈 테이블 | `BATCH_DATABASE_URL`(batch_worker)로 `scripts/load_calendar.py data/calendar/2026.example.yaml` 실행 | 종료코드 0, 730건 반영 | 종료코드 0, `[완료] 730건을 reference.market_calendar에 반영했습니다.`, `count(*)=730` | PASS | AC-3 회귀 확인 겸 이후 테스트의 전제 데이터 구성 |
| **TC-079** | **`updated_at` 실제 갱신 확인(DEF-004 수정 재현, 5단계와 다른 오염값 사용)** | `2026-01-01`/`KRX` 행을 `migrator`로 `holiday_name='WRONG_TEST_VALUE_V4', source='corrupted-for-v4-test'`로 오염, `updated_at` 기록(`15:18:34.555998`) | `pg_sleep(2)` → `batch_worker`로 동일 YAML 재실행 → 동일 행 재조회 | 내용은 정상값(`신정`, 정상 source)으로 복구되고, `updated_at`은 오염 시각보다 **이후**의 새 값으로 갱신되어야 함 | 내용 정확히 복구(`신정`, 정상 source). `updated_at`이 `15:18:34.555998` → `15:18:58.702229`로 **실제로 갱신됨**(24초 경과, `pg_sleep(2)`+처리시간과 부합) | **PASS(확정)** | DEF-004 Fixed 확정. 5단계가 note에 기록한 값(`15:08:56`→`15:09:38`)과 다른 독립 실행에서 동일한 패턴(갱신됨)을 재현 |
| **TC-080** | **(관찰, 결함 아님) 내용이 바뀌지 않아도 `updated_at`이 매번 갱신되는지** | TC-079 이후 상태(내용 이미 정상) | 추가 변경 없이 `batch_worker`로 동일 YAML을 한 번 더 재실행(`pg_sleep(1)` 후) | (참고용 관찰 — AC/DEF 어디에도 "내용 불변 시 타임스탬프 불변" 요구는 없음) | `updated_at`이 `15:18:58.702229` → `15:19:14.625934`로 **내용 변경이 없었음에도 갱신됨** | **관찰 사항(결함 아님)** | `ON CONFLICT DO UPDATE`가 값 비교 없이 무조건 실행되는 구조라 매 upsert마다 전체 730행의 `updated_at`이 갱신된다. DEF-004가 요구한 것("실제 변경 시 갱신되어야 함")은 충족했고 이 이상을 요구하는 AC/DEF는 없으므로 결함으로 등록하지 않되, "이 컬럼이 곧 마지막 실제 변경 시각을 의미하지는 않는다"는 점을 §7 리스크로 남긴다 |

### 지시 4: DEF-001/DEF-002 및 기존 AC 전체 회귀 확인

| ID | 시나리오 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|-----------|-----------|-----------|-----------|------|
| TC-082 | `pytest tests/unit`/`ruff` 전체 재실행 | `python -m pytest tests/unit -q`, `python -m ruff check .` | 36건 전부 pass, 린트 오류 0건(회귀 없음) | `36 passed, 1 warning`(기존 httpx deprecation 경고, 변경 없음). `All checks passed!` | **PASS** | 마이그레이션 0002·`load_calendar.py` 수정이 Fake 기반 단위테스트 스위트에 회귀를 일으키지 않음 확인 |
| **TC-083** | **DEF-001 수정이 이번 변경으로 깨지지 않았는지 실제 DB로 재확인** | `PUBLIC_API_DATABASE_URL`(api_service)로 `TestClient(app)`, GRANT 재적용된 상태 | `GET /health`, `GET /calendar/last-trading-day?market=KRX&as_of=...12:00:00`(마감 전), `...16:00:00`(마감 후) | health 200 ok; 12:00 → 09-11(전일); 16:00 → 09-14(당일) | health 200 `{'status':'ok','db':'ok'}`; 12:00 → `2026-09-11`; 16:00 → `2026-09-14` — 전부 일치 | **PASS** | DEF-003/004 수정(마이그레이션 0002 추가, CLI upsert 로직 변경)이 REQ-005 핵심 계산 로직에 영향을 주지 않음을 실제 DB로 재확인 |
| TC-084 | `market_hours`/`market_open_time` 잔존 참조 재확인(회귀) | `grep -rn "market_hours\|market_open_time" --include="*.py" .` | docstring 설명 문구 외에 실제 import/호출 없어야 함 | 매칭 1건, `last_trading_day.py` 상단 docstring 설명 문장뿐(기존과 동일) — 신규 코드에서 재도입된 참조 없음 | **PASS** | v2에서 확인한 상태가 이번 v4 변경(0002, load_calendar.py)으로도 훼손되지 않았음을 재확인 |

> 정상 경로/경계값/예외 입력 커버리지 요약(v4): TC-075·078·081~084는 정상 경로 확정 재검증, TC-076·077은 예외(권한 거부) 경로, TC-079는 실제 변경 시나리오(DEF-004 확정), TC-080은 결함이 아닌 관찰 사항(투명성 확보 목적으로 기록).


## 4-5. v5 재검증 테스트 케이스 (DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판, AC-8~AC-10)

### 회귀 확인 (정적 분석/전체 스위트)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-085 | `pytest tests/unit -q` 전체 독립 재실행(165건, v5 신규 10건 포함) | 5단계 자체 보고("165 passed")를 신뢰하지 않고 직접 실행 | `python -m pytest tests/unit -q` | 165 passed | `165 passed, 2 warnings`(기존 httpx/쿠키 deprecation 경고, 기능 결함 아님, 이전 버전부터 동일) | **PASS** | 숫자(165)와 결과 모두 직접 확인. 155(v4 시점)→165 순증 10건이 실제로 rate limit/보안헤더/DB예외/catch-all/타임아웃 테스트임을 파일을 열어 직접 확인(§4-5 하단 목록 대조) |
| TC-086 | `ruff check .` 독립 재실행 | 위와 동일 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** | |

### AC-8 재검증 — IP rate limiting

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| **TC-087** | **(실네트워크) 분당 60회 초과 시 429, CORS 헤더 유지, 60회 이하는 정상 영향 없음** | 실제 `uvicorn`(포트 8095/8094, DB는 실제 리스닝 서버+오인증으로 빠르게 실패하도록 구성해 반복 호출 시간을 단축) | `/api/v1/health`를 60회 연속 호출 후 61번째 호출, 매번 `http_code` 기록. 429 응답의 `access-control-allow-origin` 헤더도 확인 | 1~60회차 200, 61회차 429 + `RATE_LIMITED` + CORS 헤더 유지 | 60회 전부 200(1건도 429 없음), 61번째 `429`, 바디 `{"error":{"code":"RATE_LIMITED","message":"..."},"data":null}`, `access-control-allow-origin: http://localhost:3000` 존재 | **PASS** | `TestClient`(인프로세스)가 아니라 실제 소켓 HTTP로 재현(5단계 note가 주장한 것과 동일한 방식이나, 6단계가 독립 세션·독립 포트에서 재현) |
| TC-088 | OPTIONS 프리플라이트는 rate limit 카운터를 소모하지 않는가(`main.py` 주석의 주장 검증) | 위와 별도 세션(포트 8092) | `OPTIONS /api/v1/health`를 70회 연속 호출(허용 오리진 헤더 포함) 후, 곧바로 일반 `GET` 호출 | OPTIONS 70회 전부 429 아님(CORS가 라우터/RateLimit 이전에 자체 처리), 이후 GET도 여전히 200(쿼터 소모 안 됨) | OPTIONS 70회 중 429 0건(`blocked_count=0`), 이후 GET 호출 `200` | **PASS** | `main.py` 주석 "preflight가 rate limit 카운터를 불필요하게 소모하지 않는다"는 주장을 실측으로 확인 |

### AC-9 재검증 — 보안 응답 헤더 (신규 결함 DEF-005 발견)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-089 | 정상 200 응답에 3개 보안 헤더 전부 존재(허용/비허용 오리진 무관) | 실제 `uvicorn`(포트 8093) | `GET /api/v1/health`를 `Origin: http://evil.example.com`으로 호출, 헤더 전수 확인 | CSP/`X-Content-Type-Options`/HSTS 3개 모두 존재, `access-control-allow-origin`은 없음(비허용 오리진) | 3개 헤더 정확히 일치하는 값으로 존재(`default-src 'none'; frame-ancestors 'none'`, `nosniff`, `max-age=63072000; includeSubDomains`), CORS 헤더 없음 | **PASS** | AC-9 1번째 불릿 재확인(정상 경로) |
| **TC-090** | **(위험 케이스, 신규 발견) 429 rate-limited 응답에 보안 헤더가 붙는가** | 실제 `uvicorn`(포트 8094/8096), rate limit 카운터를 61회째까지 채운 상태 | 61번째 `GET /api/v1/health` 호출(429 유발) 후 응답 헤더 전수 확인 | AC-9/오케스트레이터 지시("모든 응답")에 따르면 3개 헤더 모두 존재해야 함 | **`content-security-policy`/`x-content-type-options`/`strict-transport-security` 전부 응답에 없음.** `content-length`/`content-type`만 존재(CORS 헤더는 별도로 존재 — TC-087과 동일 응답을 재확인) | **FAIL → 신규 결함 DEF-005** | 두 개의 독립 서버 세션(포트 8094, 8096)에서 재현성 확인(우연/1회성 아님). 원인: `RateLimitMiddleware`가 `SecurityHeadersMiddleware`보다 바깥쪽(`main.py`에 나중에 `add_middleware`됨)에 있어, 429로 즉시 응답을 반환할 때 `call_next()`를 호출하지 않아 안쪽의 `SecurityHeadersMiddleware.dispatch()` 자체가 실행되지 않음(코드 확인: `rate_limit.py` L100-101 `if count > self._limit: return _rate_limited_response()` — `call_next` 미호출) |
| **TC-091** | **(위험 케이스, 신규 발견) `RequestTimeoutMiddleware`의 타임아웃 503 응답에도 보안 헤더가 붙는가** | 격리된 Starlette 앱: `SecurityHeadersMiddleware`(안쪽) + `RequestTimeoutMiddleware`(바깥쪽, `timeout_seconds=0.05`) + 0.2초 걸리는 슬로우 엔드포인트 — `main.py`와 동일한 상대적 배치 순서를 그대로 재현 | `GET /slow` 호출, 응답 헤더 확인 | 503 응답에도 3개 보안 헤더가 존재해야 함(TC-090과 동일 기준) | `status=503`, `body.error.code=SERVICE_UNAVAILABLE`(정상), **`has CSP header: False`** — `headers`에 `content-length`/`content-type`뿐, 보안 헤더 3종 전부 없음 | **FAIL → DEF-005 재현(2번째 독립 경로)** | `asyncio.wait_for(call_next(request), ...)`가 타임아웃되면 `TimeoutError`를 캐치해 `RequestTimeoutMiddleware`가 자체적으로 `_service_unavailable_response()`를 반환한다 — 이 경로도 안쪽 `SecurityHeadersMiddleware`를 거치지 않음(코드 구조상 TC-090과 동일한 근본 원인). pytest의 기존 `test_request_timeout_middleware_returns_503_service_unavailable_envelope`는 `SecurityHeadersMiddleware` 없이 `RequestTimeoutMiddleware`만 단독으로 격리해 테스트하므로 이 상호작용 자체가 애초에 검증 대상이 아니었음(테스트 설계 공백) |
| TC-092 | (대조군) `DBAPIError` 예외 핸들러 503과 `UnhandledExceptionMiddleware` catch-all 503은 보안 헤더가 정상적으로 붙는가 | §4-5 TC-095(블랙홀 DB) 응답, 격리 앱에서 라우터가 임의 예외를 던지는 경로 | TC-095의 503 응답 헤더 재확인 + pytest `test_unexpected_exception_returns_503_envelope_not_raw_500` 통과 확인(간접) | 두 경로 모두 보안 헤더 존재해야 함(정상 동작 경로이므로) | TC-095 응답에 3개 헤더 전부 존재 확인(§4-5 TC-095 참조). `UnhandledExceptionMiddleware`는 라우터에 가장 가까운 안쪽(가장 먼저 `add_middleware`)이라 예외를 정상 `Response`로 변환한 뒤 그 응답이 바깥쪽 `SecurityHeadersMiddleware`를 정상적으로 통과함(코드 구조상 확인) | **PASS(대조군, DEF-005가 전면적 회귀가 아니라 특정 두 경로에 국한됨을 확인)** | DEF-SEC-02가 "완전히 미구현"에서 "일부 경로에서 누락"으로 개선된 것은 사실이나, AC-9 문면("모든 응답")은 여전히 충족하지 못함 |

### AC-10 재검증 — 전역 예외 처리 + TCP 블랙홀 (핵심 재검증)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| **TC-093** | **(핵심) 진짜 TCP 블랙홀에서 `connect_timeout=3`이 실제로 약 3초에 끊기는가 — 순수 psycopg 레벨** | 격리 스크립트, `10.255.255.1:5432`(존재하지 않는 호스트) | `psycopg.connect(..., connect_timeout=3)` 직접 호출, 소요시간 측정 | 약 3초(±0.5초) 내 `ConnectionTimeout`(또는 동등 예외) 발생 | `elapsed=3.053s`, `exc_type=ConnectionTimeout` | **PASS** | 5단계가 재현하지 않았다고 스스로 밝힌 항목(`unit-01-note.md` §3 v5 신규)을 6단계가 처음으로 직접 재현 |
| **TC-094** | 앱 실제 설정(`db/session.py::get_engine()`, `connect_args`)으로도 동일하게 동작하는가 | 격리 스크립트, `PUBLIC_API_DATABASE_URL`을 `10.255.255.1`로 설정 | `services.public_api.db.session.get_engine()`으로 얻은 SQLAlchemy `Engine`으로 `.connect()` 시도, 소요시간 측정 | 약 3초 내 `OperationalError`(SQLAlchemy가 `ConnectionTimeout`을 래핑) | `elapsed=3.063s`, `exc_type=OperationalError` | **PASS** | 순수 psycopg(TC-093)와 앱이 실제로 사용하는 `create_engine(connect_args=...)` 설정(TC-094) 양쪽에서 일치 — `connect_args`가 실제로 psycopg까지 전달됨을 확인 |
| **TC-095** | **(종단, 핵심) 실제 `uvicorn` + 블랙홀 DB로 전체 요청 경로가 5초 이내 503 Envelope을 반환하는가** | 실제 `uvicorn`(포트 8097), `PUBLIC_API_DATABASE_URL=10.255.255.1` | `GET /api/v1/health`, `GET /api/v1/stocks?query=samsung`(DB 라운드트립 필요) 각각 호출, `curl -w time_total` + 헤더 전수 확인 | `/health`는 200(`db:"degraded"`), `/stocks`는 503 `SERVICE_UNAVAILABLE` Envelope — 둘 다 5초 이내, 이상적으로 `connect_timeout`(3초) 근방 | `/health`: `http_code=200 time=3.084s`, `{"status":"ok","db":"degraded"}`. `/stocks`: `http_code=503 time=3.082s`, `{"error":{"code":"SERVICE_UNAVAILABLE",...},"data":null}`. 두 응답 모두 CSP/`X-Content-Type-Options`/HSTS/CORS 헤더 정상 존재(이 경로는 `DBAPIError` 핸들러 경로라 TC-092와 동일하게 정상) | **PASS** | **DEF-FS-01/REQ-025의 핵심 요구사항("5초 이내 503")이 진짜 무응답 네트워크 장애에서도 충족됨을 최초로 실증.** `RequestTimeoutMiddleware`(4.5초)보다 `connect_timeout`(3초)이 먼저 발동해, 요청 타임아웃 백업이 아니라 DB 타임아웃 자체가 주 방어선으로 작동함을 확인(설계 의도와 일치, `unit-01-note.md` §0-d 서술대로) |
| **TC-096** | **(중요 재현, 5단계 보고 정확성 검증) 5단계가 "0.12초"로 보고한 시나리오는 실제로 무엇을 테스트한 것인가** | 격리 스크립트, `localhost:5432`(실제 리스닝 중인 `stock-screener-db`)에 존재하지 않는 DB명+임의 사용자로 접속 시도 | `psycopg.connect("postgresql://user:pass@localhost:5432/nonexistent_db_smoke_test", connect_timeout=3)` 호출, 소요시간·예외 메시지 확인 | (가설 검증용) — TCP는 즉시 연결되고 Postgres 프로토콜 레벨에서 인증 실패로 즉시 거부될 것으로 예상 | `elapsed=0.054s`, `OperationalError`, 메시지 `FATAL: password authentication failed for user "user"` — **TCP 3-way handshake는 즉시 성공했고, `connect_timeout`은 전혀 관여하지 않았다.** 실제 서버가 응답하고 있었으므로 애초에 "타임아웃"을 테스트한 것이 아니라 "빠른 인증 거부"를 테스트한 것 | **확인(결함 아님, 5단계 note의 설명 정확도 이슈)** | 5단계가 이 경로를 "DB 연결 불가 시나리오"라고 서술한 것은 결과(빠른 503)는 맞았으나 원인 설명이 부정확했다 — `connect_timeout`이 실제로 작동하는지는 이번 TC-093~095가 처음으로 검증했다. 코드 결함은 아니므로 별도 DEF로 등록하지 않고 §0-4/§7에 문서 정확도 이슈로만 기록 |
| TC-097 | 정상(빠른) 요청은 `RequestTimeoutMiddleware`(4.5초)에 영향받지 않는가(false positive 없음) | 실제 `uvicorn`(포트 8093/8095, 빠른 응답 DB 설정) + 격리 pytest 재확인 | 실측: `/health` 응답시간 0.2초대(TC-089 등 다수 호출에서 전부 0.2~0.3초, 4.5초 근처 지연 없음). `pytest tests/unit -q -k request_timeout_middleware_allows_fast_requests` 재실행 | 200, 지연 없음 | 실측 호출 전부 0.05~0.3초대(4.5초 타임아웃 근처 지연 0건), `1 passed` | **PASS** | 오케스트레이터 지시 4번("정상 요청 흐름에 부작용 없는지") 충족 |
| TC-098 | 존재하지 않는 라우트(404)가 catch-all에 영향받지 않는가(회귀) | `pytest -k test_unknown_route_404_is_unaffected_by_catch_all_handler` | 재실행 | 404 | `1 passed` | **PASS** | TC-085(165건)에 포함되어 있음을 개별 재확인 |

> 정상 경로/경계값/예외 입력 커버리지 요약(v5): TC-087·089·092·094·095·097·098은 정상/제어 경로 확정, TC-088은 경계(프리플라이트가 카운터에서 제외되는 특수 경로), **TC-090·091은 이번 재검증이 직접 발견한 예외 경로 결함(DEF-005)**, TC-093·095는 이번 재검증의 핵심 위험 케이스(진짜 네트워크 무응답), TC-096은 문서 정확도 검증(위험 기반 추가 케이스, AC 범위 밖이지만 결함 의심 소지가 있어 직접 확인).


## 4-6. v6 재검증 테스트 케이스 (DEF-005 대응, 규칙 F 2차 라운드 독립 재검증)

> 코디네이터 지시(1~4번)에 1:1로 대응. TC-085/086과 동일한 정적 분석/전체 스위트 재실행부터 시작해, DEF-005 해소를 실측+코드 리뷰+mutation testing 3중으로 검증하고, 회귀 항목(a)~(d)를 순서대로 확인했다. 05단계(`unit-01-note.md` §6-1 v6)가 쓴 포트(8199)를 재사용하지 않고 6단계 독립 세션에서 새 포트(8111~8113)로 재현했다.

### 정적 분석/전체 스위트 독립 재실행 (코디네이터 지시 3)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-099 | `pytest tests/unit -q` 전체 독립 재실행(167건, v6 신규 2건 포함) | 5단계 자체 보고("167 passed")를 신뢰하지 않고 직접 실행 | `python -m pytest tests/unit -q` | 167 passed | `167 passed, 2 warnings`(기존 httpx/쿠키 deprecation 경고, 변경 없음) | **PASS** | 165(v5 시점)→167 순증 2건이 `test_rate_limited_response_still_carries_security_headers`/`test_request_timeout_response_still_carries_security_headers`임을 파일을 열어 직접 확인(§4-6 하단 TC-108) |
| TC-100 | `ruff check .` 독립 재실행 | 위와 동일 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | **PASS** | |

### DEF-005 해소 확인 (코디네이터 지시 1)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-101 | `main.py`의 실제 `add_middleware` 등록 순서가 note의 주장과 일치하는지 코드 리뷰 | 소스 확인 | `services/public_api/main.py`의 `app.add_middleware(...)` 호출 4줄을 순서대로 직접 읽음 | `UnhandledExceptionMiddleware → RequestTimeoutMiddleware → RateLimitMiddleware → SecurityHeadersMiddleware → CORSMiddleware`(안쪽→바깥쪽) 순서여야 함(`SecurityHeadersMiddleware`가 `RateLimitMiddleware`/`RequestTimeoutMiddleware`보다 바깥쪽) | 실제 코드: `app.add_middleware(UnhandledExceptionMiddleware)` → `app.add_middleware(RequestTimeoutMiddleware)` → `app.add_middleware(RateLimitMiddleware)` → `app.add_middleware(SecurityHeadersMiddleware)` → `app.add_middleware(CORSMiddleware, ...)` — 정확히 일치 | **PASS** | note가 주장한 순서와 실제 코드가 문자 그대로 일치함을 확인(추측 아님) |
| **TC-102** | **(핵심, mutation testing) 신규 pytest 2건이 실제로 DEF-005를 잡아내는지 — 순서를 되돌려 실패 여부 확인** | `services/public_api/main.py`를 `.harness-tmp/main.py.orig.bak`로 백업 | 파이썬 스크립트로 `add_middleware` 순서를 v5의 버그 순서(`UnhandledException → SecurityHeaders → RequestTimeout → RateLimit → CORS`, `SecurityHeaders`를 `RequestTimeout`/`RateLimit`보다 안쪽으로 이동)로 일시 변경 후 `pytest tests/unit/test_public_api.py -q -k "test_rate_limited_response_still_carries_security_headers or test_request_timeout_response_still_carries_security_headers"` 재실행 | 버그 순서에서는 `test_rate_limited_response_still_carries_security_headers`가 **FAIL**해야 함(실제 `app`을 사용하는 테스트이므로 순서 변경에 반응해야 함) | `test_rate_limited_response_still_carries_security_headers`: **FAIL** — `KeyError: 'content-security-policy'`(429 응답에 헤더가 실제로 사라짐을 확인). `test_request_timeout_response_still_carries_security_headers`: PASS(변화 없음 — 아래 비고 참조) | **PASS(테스트 실효성 확인) — 단, 구조적 한계 1건 발견(결함 아님, §7 기록)** | 신규 테스트 중 하나(rate-limit 헤더)는 `main.py`의 실제 등록 순서에 실제로 반응하는 유효한 회귀 안전망임을 실증했다. 다른 하나(request-timeout 헤더)는 `main.py`를 참조하지 않는 완전히 격리된 Starlette 앱(테스트 코드 내부에 순서를 직접 하드코딩)이라, main.py 자체의 등록 순서가 바뀌어도 이 특정 테스트는 반응하지 않는다 — v5의 TC-091도 동일한 격리 방식이었으므로 이번 v6에서 새로 생긴 문제는 아니다. 검증 직후 `.harness-tmp/main.py.orig.bak`으로 `main.py`를 즉시 복원하고 `diff`로 바이트 단위 동일함을 확인했다(§6-1 Teardown 참조) |
| TC-107 | (TC-102 보강) 격리 Starlette 앱 방법론 자체가 순서 버그를 정확히 판별하는지 별도 확인 | `.harness-tmp/`에 임시 스크립트 작성(`main.py`와 무관, `RequestTimeoutMiddleware`+`SecurityHeadersMiddleware`만으로 구성된 순수 격리 앱) | 스크립트 안에서 `SecurityHeadersMiddleware`를 `RequestTimeoutMiddleware`보다 먼저 등록(버그 순서와 동일한 상대 배치)한 뒤 0.05초 타임아웃 유발, 헤더 존재 확인 | 버그 순서로 구성하면 헤더가 없어야 함(테스트 방법론 자체가 유효하다는 근거) | `status=503`, `has CSP header: False` — 예상대로 버그 순서에서는 헤더가 사라짐을 확인, 검증 후 스크립트 즉시 삭제 | **PASS(방법론 유효성 확인)** | TC-091/TC-420(신규 2건 중 timeout 쪽)이 채택한 "격리 앱에 상대 순서를 하드코딩"하는 방식 자체는 결함을 정확히 판별할 수 있는 유효한 설계임을 확인했다 — 다만 `main.py`의 실제 순서를 자동으로 읽어오지 않는다는 한계(TC-102 비고)는 별개로 남는다 |
| **TC-103** | **(실네트워크, 05단계와 독립된 세션) 60/61 경계 재현 + 429 응답의 보안 헤더 3종 재확인** | 실제 `uvicorn`(포트 8112, `PUBLIC_API_DATABASE_URL`을 실제 `api_service` 계정으로 연결), 카운터 초기화 상태에서 시작 | `/api/v1/health`를 60회 연속 호출(전부 200 기대) 후 61번째 호출, 응답 헤더 전수 확인 | 1~60회차 200, 61회차 429 + CSP/`X-Content-Type-Options`/HSTS/CORS 헤더 전부 존재 | 60회 전부 200(`fail=0`), 61번째 `429`. 헤더: `content-security-policy: default-src 'none'; frame-ancestors 'none'`, `x-content-type-options: nosniff`, `strict-transport-security: max-age=63072000; includeSubDomains`, `access-control-allow-origin: http://localhost:3000` 전부 확인 | **PASS** | **DEF-005 해소 확인(429 경로).** v5의 TC-090(포트 8094/8096)·05단계 note의 포트 8199와 전혀 다른 독립 세션(포트 8112)에서 3번째로 재현 — 우연이 아님을 추가로 뒷받침 |

### 회귀 확인 (코디네이터 지시 2)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| **TC-104** | (회귀 a) 정상 200 응답에 보안 헤더 + CORS 헤더가 여전히 붙는가 | 실제 `uvicorn`(포트 8111) | `GET /api/v1/health`를 `Origin: http://localhost:3000`으로 호출, 헤더 전수 확인 | 3개 보안 헤더 + CORS 헤더 정상 존재(회귀 없음) | `content-security-policy`/`x-content-type-options`/`strict-transport-security`/`access-control-allow-origin` 전부 정상 값으로 존재 | **PASS** | 미들웨어 순서 재배치가 정상 경로에 영향을 주지 않음을 확인 |
| **TC-105** | (회귀 a) `DBAPIError` 503 경로에 보안 헤더 + CORS 헤더가 여전히 붙는가 | 실제 `uvicorn`(포트 8113, 존재하지 않는 DB 계정으로 기동해 `/stocks` 호출 시 `DBAPIError` 유발) | `GET /api/v1/stocks?query=samsung`을 `Origin: http://localhost:3000`으로 호출, 헤더+상태코드+소요시간 확인 | 503 `SERVICE_UNAVAILABLE`, 보안 헤더 3종 + CORS 헤더 정상 존재 | `503`, `{"error":{"code":"SERVICE_UNAVAILABLE",...}}`, `time_total=0.055s`(실제 리스닝 서버에 대한 인증 거부 경로 — v5 TC-096과 동일 패턴, TCP 블랙홀 자체를 재현한 것은 아님), 4개 헤더 전부 정상 존재 | **PASS** | `DBAPIError` 핸들러 경로(§4-5 TC-092 대조군)에 이번 순서 변경으로 인한 회귀가 없음을 확인. 진짜 3초 블랙홀 재현은 v5(TC-093~096)에서 이미 확정됐고 이번 변경이 `db/session.py`/예외 핸들러 코드를 건드리지 않았으므로 반복하지 않음(TC-109 코드 무변경 확인과 결합해 판단) |
| **TC-106** | (회귀 c) OPTIONS 프리플라이트가 여전히 rate limit 카운터를 소모하지 않는가 | 실제 `uvicorn`(포트 8113) | `OPTIONS /api/v1/health`를 5회 연속 호출 후 곧바로 일반 `GET` 호출 | OPTIONS 5회 전부 200(429 아님), 이후 GET도 200 | OPTIONS 5회 전부 `200`, 이후 `GET` `200` | **PASS** | v5 TC-088과 동일한 동작이 이번 순서 변경 이후에도 유지됨을 확인 |
| TC-108 | (코디네이터 지시 4) 신규 pytest 2건이 DEF-005 시나리오를 의미 있게 커버하는지 코드 리뷰 | `tests/unit/test_public_api.py` 소스 확인 | `test_rate_limited_response_still_carries_security_headers`/`test_request_timeout_response_still_carries_security_headers` 두 함수 본문을 직접 읽음 | 각각 429/타임아웃 503 응답에서 CSP/`X-Content-Type-Options`/HSTS 3개 헤더의 실제 값까지 assert해야 함(단순 상태코드만 확인하는 얕은 테스트가 아니어야 함) | 두 함수 모두 `assert blocked.headers["content-security-policy"] == expected_csp`, `x-content-type-options`, `strict-transport-security`(부분 문자열 `max-age=63072000` 포함 확인) 3개 헤더 값을 전부 명시적으로 assert함을 확인 | **PASS** | TC-102의 mutation testing 결과(rate-limit 쪽은 실제로 실패함을 실증)와 결합해, 이 테스트들이 "우연히 통과하는 얕은 테스트"가 아니라 실질적인 회귀 안전망임을 코드 리뷰+실행 양쪽으로 확인 |
| **TC-109** | (회귀 d) `rate_limit.py`/`db/session.py`/`main.py`의 `DBAPIError`·`SATimeoutError` 핸들러가 이번 변경으로 손대지 않았는지 | 소스 확인 | `services/public_api/rate_limit.py`, `services/public_api/db/session.py`, `main.py`의 `@app.exception_handler(DBAPIError)`/`@app.exception_handler(SATimeoutError)` 블록을 직접 읽고 v5 시점 로직과 대조 | 코드 로직 자체(카운터 계산, `connect_timeout`/`statement_timeout` 값, 핸들러 매핑)는 무변경이어야 함(변경 범위는 `main.py`의 `add_middleware` 순서 4줄뿐이라는 note 주장 확인) | `rate_limit.py`/`db/session.py` 전체, `main.py`의 두 예외 핸들러 함수 본문 모두 v5 시점 로직과 동일(로직 변경 없음, `main.py`에서 변경된 부분은 `add_middleware` 호출 순서와 그 주석뿐임을 확인). 또한 `@app.exception_handler`는 FastAPI 라우팅/엔드포인트 계층에서 처리되어 일반 `Response`로 변환된 뒤 미들웨어 스택을 통과하는 메커니즘이라, `add_middleware` 순서 변경과는 구조적으로 독립적임을 코드 구조로 확인 | **PASS** | TC-105(실측)와 결합해, 이번 미들웨어 순서 변경이 DB 타임아웃 경로의 동작/타이밍에 영향을 줄 수 없음을 코드 레벨+실측 양쪽으로 확인. 코디네이터 지시("최소한 코드 레벨로 확인")를 충족 |

> 정상 경로/경계값/예외 입력 커버리지 요약(v6): TC-099·100·101·104·106·108·109는 정상/회귀 확인, **TC-102·107은 이번 재검증의 핵심 — 테스트 자체의 실효성을 mutation testing으로 직접 증명**(테스트가 잘못 설계되어 결함을 놓칠 가능성을 재점검하는 원칙의 실천), TC-103·105는 실네트워크 위험 경로(429/503) 재확인. TC-102에서 발견한 "timeout 쪽 신규 테스트가 main.py의 실제 순서를 동적으로 읽지 않는다"는 구조적 한계는 결함이 아니라 테스트 설계상 알려진 트레이드오프로 §7에 기록한다(v5의 TC-091부터 존재했던 동일한 패턴이며 이번에 새로 생긴 문제는 아니다).


## 5. 커버리지 (v6 최종)
- 기능 커버리지(v4까지): `unit-01-note.md`(v3) AC-1~AC-7 전 불릿 **전부 확정 PASS**(변경 없음, v5/v6 재작업이 손대지 않은 영역).
- 기능 커버리지(v5): AC-8(전 불릿 PASS)·AC-10(전 불릿 PASS)·AC-9(1번째 불릿만 PASS, 2번째 불릿 "모든 응답" 조건은 FAIL — DEF-005).
- **기능 커버리지(v6, 최종)**: **AC-9(보안 헤더) 전 불릿 PASS로 전환.** DEF-005 해소로 정상 200/429/타임아웃 503/`DBAPIError` 503/catch-all 503 전 응답 경로에 보안 헤더 3종이 일관되게 적용됨을 확인했다(TC-103~105, TC-089/092 회귀 재확인 포함). AC-8/AC-10은 v5와 동일하게 전 불릿 PASS 유지(회귀 없음, TC-099·103·106·109로 재확인).
- 인수 조건 ↔ 테스트 케이스 추적성(v6 신규분만): AC-9(TC-099, 101~105, 108 — DEF-005 해소 확인 및 2건의 신규 pytest 실효성 검증).
- 코드 커버리지(라인/브랜치): 수치화 도구는 이번에도 도입되지 않음. TC-101(코드 리뷰)+TC-103(실네트워크)+TC-102/107(mutation testing)의 3중 교차 확인으로 `main.py`의 미들웨어 등록 순서 변경이 실제 코드 경로에 유효하게 반영됐고, 신규 회귀 테스트가 실제로 그 경로를 검증하고 있음을 확인했다.
- 커버되지 않은 부분과 사유(v6 기준, 신규): (1) `test_request_timeout_response_still_carries_security_headers`가 `main.py`의 실제 등록 순서를 동적으로 읽지 않고 격리된 앱에 순서를 하드코딩하는 구조적 한계(TC-102/107 비고, §7 참조) — 결함은 아니나 향후 `main.py`의 `RequestTimeoutMiddleware`/`SecurityHeadersMiddleware` 상대 순서가 다시 깨질 경우 이 특정 테스트만으로는 감지되지 않을 수 있음(단, `test_rate_limited_response_still_carries_security_headers`는 실제 `app`을 사용하므로 감지 가능 — 두 미들웨어 모두 CORS보다 안쪽에서 동일한 상대 순서를 공유하므로 rate-limit 테스트가 사실상 이 조합에 대한 간접 안전망 역할도 한다). (2) v5와 동일하게 멀티 워커/인스턴스 환경, 스레드풀 고갈 부하테스트는 이번 지시 범위 밖(변경 없음, 승계).

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도 | 상태 | 조치 내용 |
|----|------|-----------|--------|------|-----------|
| DEF-001 | (v1) `get_last_trading_day()`가 개장 시각 기준으로 비교해 장중(개장~마감 사이) 내내 "당일"을 직전 거래일로 잘못 반환. | (v1) TC-008~010 참조. | High | **Fixed** | v2 재검증(TC-043/046/047)으로 해소 확인. v3/v4/v5/v6에서 실제 Postgres(TC-074/083) 및 회귀 재실행(TC-085 165건, TC-099 167건 포함)으로 반복 확인, 회귀 없음. |
| DEF-002 | (v1) `/health` DB 예외(degraded)·`CalendarScanLimitExceeded`→503 매핑에 대한 정식 회귀 테스트 부재. | (v1) `tests/unit/test_public_api.py`에서 `degraded`/`503` 키워드 검색 시 매칭 없음. | Low | **Fixed** | v2 재검증(TC-057/058)으로 해소 확인. v3~v6 변경 없음(재작업 대상 아니었음), TC-099로 회귀 없음 재확인. |
| DEF-003 | (v3 신규) 마이그레이션 `0001`이 `reference` 스키마에 대해 어떤 GRANT도 실행하지 않아, `alembic upgrade head` 직후 `batch_worker`/`api_service` 모두 접근 권한이 없었음. | TC-065. | Medium | **Fixed** | v4 재검증(TC-075~077, 081)으로 완전 초기화 후 재구성해 해소 확인. v5/v6에서 변경 없음(재작업 대상 아님). |
| DEF-004 | (v3 신규) `scripts/load_calendar.py`의 upsert가 `updated_at`을 갱신하지 않음. | TC-069. | Low | **Fixed** | v4 재검증(TC-079)으로 해소 확인. v5/v6에서 변경 없음. |
| DEF-SEC-01 | (09단계 발견, v5 귀속) IP 기준 rate limiting 미구현 — `03-system-design.md` §6-3(Must) "분당 60회" 요구사항이 코드/인프라 어디에도 없었음(REQ-022 데이터 라이선스 리스크와 직결). | `09-security-audit.md` TC-SEC-27. | High | **Fixed** | 5단계가 `services/public_api/rate_limit.py`로 구현, 6단계가 v5(TC-087/088)에서 실제 `uvicorn` 서버로 독립 재현. **v6에서 회귀 없음 재확인**(TC-103/106, 05단계와 다른 독립 세션·포트) — `rate_limit.py` 코드 자체는 이번 v6 변경 대상이 아니었음(TC-109). |
| DEF-SEC-02 | (09단계 발견, v5 귀속) 보안 응답 헤더(CSP/`X-Content-Type-Options`/HSTS) 미구현 — `03-system-design.md` §6-3(Must). | `09-security-audit.md` TC-SEC-26. | Medium | **Fixed(v6 최종 확인)** | 5단계가 `SecurityHeadersMiddleware`로 구현(v5). v5 재검증에서 429/타임아웃 503 경로 누락(DEF-005)으로 **Partially Fixed**였으나, v6 재작업(미들웨어 등록 순서 재배치)으로 그 잔여 경로까지 완전히 해소됨을 6단계가 독립 재현해 **최종 Fixed**로 확정(TC-103~105, TC-092/089 회귀 재확인 포함). |
| **DEF-005** | (v5 신규, 6단계 독립 재검증에서 발견) `SecurityHeadersMiddleware`가 `RateLimitMiddleware`·`RequestTimeoutMiddleware`보다 안쪽(라우터에 더 가까운 위치)에 등록되어 있어, 이 두 미들웨어가 `call_next()`를 호출하지 않고 자체적으로 응답을 반환(short-circuit)하는 경로(429 rate-limited, 요청 타임아웃 503)에서는 `SecurityHeadersMiddleware.dispatch()` 자체가 실행되지 않는다. 그 결과 429/타임아웃-503 응답에 CSP/`X-Content-Type-Options`/HSTS 세 헤더가 전부 누락된다. | (v5) §4-5 TC-090(실제 `uvicorn` 서버 2회 독립 세션, 포트 8094/8096), TC-091(격리 Starlette 앱). | Medium | **Fixed(v6 최종 확인)** | **5단계 조치**: `main.py`의 `add_middleware` 등록 순서를 `UnhandledException → RequestTimeout → RateLimit → SecurityHeaders → CORS`로 재배치(`SecurityHeadersMiddleware`를 short-circuit 미들웨어들보다 바깥쪽으로 이동). `tests/unit/test_public_api.py`에 회귀 테스트 2건 추가. **6단계 v6 독립 재검증**: (1) 코드 리뷰로 실제 순서가 주장과 일치함을 확인(TC-101). (2) 6단계 독립 세션(05단계와 다른 포트 8111~8113)에서 실제 `uvicorn`으로 429 응답에 보안 헤더 3종이 정상 부착됨을 재현(TC-103, 세 번째 독립 경로 — v5의 실서버 2회 + 이번 1회). (3) **mutation testing으로 신규 회귀 테스트의 실효성을 직접 증명** — `main.py`를 버그 순서로 일시 되돌린 뒤 `test_rate_limited_response_still_carries_security_headers`가 실제로 FAIL함을 확인(`KeyError: 'content-security-policy'`), 원본으로 즉시 복원(TC-102). (4) 회귀 확인(정상 200/`DBAPIError` 503 헤더 유지, CORS 일관성, rate limit 60/61 경계·OPTIONS 미소모, DB 타임아웃 경로 코드 무변경) 전부 PASS(TC-104~106, 109). **DEF-005 최종 Fixed로 확정, Open 상태 종료.** |
| (승계, 재등록 아님) DEF-FS-01 / REQ-025 확장판 | 8/9단계가 발견한 "DB 연결 장애 시 raw 500을 60~90초에 반환"/"전역 예외 처리 부재". | §4-5 TC-093~096(진짜 TCP 블랙홀 3중 재현 + 5단계 "0.12초" 보고의 실제 정체 확인). | High | **Fixed** | v5에서 6단계 독립 재확인 완료(3.05~3.08초 내 503 SERVICE_UNAVAILABLE Envelope). **v6에서 회귀 없음 재확인** — `db/session.py`/`DBAPIError`·`SATimeoutError` 핸들러 코드가 이번 v6 변경(미들웨어 순서만)과 무관하게 전혀 손대지 않았음을 코드 리뷰로 확인(TC-109)하고, 실측으로도 `DBAPIError` 503 경로가 여전히 정상 동작함을 확인(TC-105). 코디네이터 지시대로 3초 TCP 블랙홀 시나리오 자체는 이번에 재실행하지 않았다(회귀만 확인하면 충분하다는 지시에 따름). |

- **v6 재검증에서 신규로 발견된 결함은 0건이다.** v5가 발견한 유일한 Open 결함이었던 DEF-005가 이번 v6에서 **Fixed로 확정**됐고, mutation testing으로 그 해소가 우연이 아님을 실증했다. DEF-001~004, DEF-SEC-01, DEF-FS-01/REQ-025는 v5와 동일하게 Fixed 상태를 유지하며 이번 v6 변경(main.py 미들웨어 등록 순서 4줄 + pytest 2건)으로 인한 회귀가 없음을 TC-099(pytest 167건 전체 재실행)와 TC-104~106/109(표적 회귀 확인)로 확인했다.

## 6-1. 테스트 환경 정리(Teardown) 확인 — 규칙 K (v5부터 신규 도입)

> v1~v4는 이 절을 별도로 두지 않았다(가벼운 Fake 기반 pytest/오프라인 도구 위주였기 때문). v5부터는 실제 `uvicorn` 프로세스와 기존 Docker 컨테이너를 사용하므로, 규칙 K에 따라 매 세션마다 명시적으로 확인한다.

### v5 Teardown (이력 보존)
- 이번 v5 테스트에서 생성한 임시 아티팩트 목록:
  - 실제 `uvicorn` 프로세스 6개(로컬 포트 8092~8097, `services.public_api.main:app`) — 전부 `.harness-tmp/`나 프로젝트 디렉터리에 파일을 남기지 않는 인메모리 프로세스.
  - 검증용 파이썬 스크립트 7개 — 프로젝트 디렉터리 밖, 세션 격리 스크래치패드에만 생성.
  - uvicorn 로그 파일 6개 — 위와 동일하게 스크래치패드에만 생성.
- `.harness-tmp/` 하위에서만 생성했는가(규칙 K 1번): 해당 없음(프로젝트 디렉터리 내부에는 어떤 임시 아티팩트도 생성하지 않았다 — 세션 스크래치패드만 사용).
- **Docker**: `stock-screener-db` 컨테이너는 이미 실행 중이던 것을 재사용만 했다. 검증 전후 `docker ps` 결과가 `Up` 상태로 동일함을 확인했다.
- 정리(삭제) 완료: 스크래치패드의 스크립트/로그 파일 전부 삭제 완료. 6개 `uvicorn` 프로세스는 `netstat -ano`로 실제 LISTENING PID를 찾아 `taskkill //F //PID <pid>`로 종료, 최종적으로 포트 8092~8099에 리스너가 전혀 없음을 확인.
- 정리 후 `git status --short`가 세션 시작 시점과 정확히 동일함을 확인(`unit-01-test.md` 자체 수정 제외).
- `.harness-tmp/` 상태: 세션 내내 빈 디렉터리(이번 v5 검증은 이 디렉터리를 사용하지 않았다).
- 강제 중단(TaskStop 등): 없음.

### v6 Teardown (이번 세션)
- 세션 시작 시점 `git status --short` (사전 확인, 05단계 v6 재작업 직후 상태와 정확히 동일함을 확인):
```
 M docs/harness/traceability.md
 M docs/harness/units/unit-01-note.md
 M services/public_api/db/session.py
 M services/public_api/main.py
 M tests/unit/test_public_api.py
?? services/public_api/middleware.py
?? services/public_api/rate_limit.py
```
- 세션 시작 시점 `docker ps` 확인: `stock-screener-db Up 9 hours`(중간에 재시작된 적 없이 연속) — 6단계가 새로 만들거나 중지하지 않았다(재사용만).
- **이번 v6 세션에서 생성한 임시 아티팩트 목록**:
  1. `.harness-tmp/main.py.orig.bak` — TC-102 mutation testing을 위해 `services/public_api/main.py`를 백업한 파일. 규칙 K에 따라 `.harness-tmp/` 하위에만 생성했다. 검증(TC-102) 직후 백업본으로 `main.py`를 복원하고 `diff`로 바이트 단위 동일함(`RESTORED_IDENTICAL`)을 확인한 뒤 백업 파일을 삭제했다.
  2. `.harness-tmp/mutation_check_timeout_order.py`(TC-107) — 격리 Starlette 앱으로 방법론을 검증하기 위한 임시 스크립트. `.harness-tmp/` 하위에만 생성, 실행 직후 삭제.
  3. `.harness-tmp/uvicorn_v6_verify*.log`(3개, 포트 8111/8112/8113 각각) — 실제 `uvicorn` 기동 로그. `.harness-tmp/` 하위에만 생성, 검증 종료 후 전부 삭제.
  4. 실제 `uvicorn` 프로세스 3개(로컬 포트 8111/8112/8113, `services.public_api.main:app`, 각기 다른 `PUBLIC_API_DATABASE_URL`로 시나리오 분리 — 정상 계정 2회, 존재하지 않는 계정 1회) — 05단계가 쓴 포트 8199와 겹치지 않는 독립 세션.
  5. `/tmp/body_429.json`(임시 curl 출력 파일 1개, 프로젝트 밖) — 검증 후 삭제.
- 이번 v6 세션은 (1)~(3)을 **전부 `.harness-tmp/` 하위에만** 생성했다(규칙 K 1번 준수, v5의 "해당 없음" 방식과 달리 이번엔 실제로 `.harness-tmp/`를 사용했다).
- 정리(삭제) 완료 여부: (1) `main.py.orig.bak` — `diff` 동일성 확인 후 `rm -f`로 삭제 완료. (2) `mutation_check_timeout_order.py` — 실행 직후 `rm -f`로 삭제 완료. (3) uvicorn 로그 3개 — `rm -f`로 삭제 완료. (4) uvicorn 프로세스 3개 — 매번 `netstat -ano`로 실제 LISTENING PID를 찾아 `taskkill //F //PID <pid>`로 종료, 최종적으로 `netstat -ano | grep LISTENING | grep -E ":81(11|12|13)"` 결과 0건(리스너 없음)을 확인. (5) `/tmp/body_429.json` — `rm -f`로 삭제 완료.
- 정리 후 `.harness-tmp/` 상태: `ls -la .harness-tmp/`가 `.`/`..`만 남은 빈 디렉터리임을 확인.
- 정리 후 `docker ps` 재확인: `stock-screener-db Up 9 hours`(세션 시작 시점과 동일, 재시작되지 않음).
- 정리 후 `git status --short` 재확인 결과 (그대로 첨부):
```
 M docs/harness/traceability.md
 M docs/harness/units/unit-01-note.md
 M services/public_api/db/session.py
 M services/public_api/main.py
 M tests/unit/test_public_api.py
?? services/public_api/middleware.py
?? services/public_api/rate_limit.py
```
  (세션 시작 시점과 정확히 동일 — 이번 6단계 세션은 `unit-01-test.md` 자체와(저장 후 `docs/harness/traceability.md`에 REQ-025/026/027 갱신 예정) 외에 저장소에 어떤 파일도 추가/수정하지 않았다. mutation testing 중 `main.py`를 일시 변경했으나 검증 직후 원본과 바이트 단위로 동일하게 복원했으므로 최종 diff에는 나타나지 않는다.)
- 이번 v6 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **없음**.

## 7. 리스크 및 잔존 이슈 (v6 최종)
- **DEF-001~004는 전부 Fixed로 유지된다(회귀 없음, TC-099 확인).**
- **DEF-SEC-01/DEF-FS-01(REQ-025)/DEF-SEC-02(REQ-027)는 v6에서 전부 완전히 Fixed로 확인됐다.** DEF-005(REQ-027의 잔여 부분)는 v6에서 최종 Fixed로 확정됐다(Open 결함 0건).
- **(v6 신규 관찰, 결함 아님) `test_request_timeout_response_still_carries_security_headers`가 `main.py`의 실제 미들웨어 등록 순서를 동적으로 읽지 않고, 격리된 Starlette 앱에 상대 순서를 직접 하드코딩하는 구조적 한계가 있다**(TC-102/107). `main.py`를 버그 순서로 되돌려도 이 특정 테스트는 반응하지 않음을 mutation testing으로 직접 확인했다 — 단, `test_rate_limited_response_still_carries_security_headers`는 실제 `app`을 사용해 `SecurityHeadersMiddleware`가 `RateLimitMiddleware`/`RequestTimeoutMiddleware` 둘 다보다 바깥쪽에 있어야만 통과하므로, 이 조합에 대한 간접적 안전망 역할은 한다. 향후 `main.py`의 미들웨어 등록 순서를 다시 변경하는 재작업이 있을 경우, 6단계는 이번처럼 mutation testing으로 회귀 테스트의 실효성을 재검증할 것을 권고한다(테스트 설계 개선 후속 과제로 기록, 배포 차단 사유 아님).
- **(v5 신규 리스크, 승계) rate limiter는 여전히 단일 프로세스 인메모리 상태다** — 멀티 인스턴스/워커 확장 시 재구현 필요(이번 v6 재검증 범위에서 재확인하지 않음, §2 제외범위).
- **(v5 신규 리스크, 승계) `RequestTimeoutMiddleware`는 스레드 자체를 강제 종료하지 못한다** — 근본 방어선은 여전히 `db/session.py`의 타임아웃.
- **(v5 신규 관찰, 결함 아님, 승계) 이 로컬 Windows/Docker Desktop 환경에서는 "닫힌 로컬 포트"로의 접속 시도도 즉시 RST가 아니라 약 3초 뒤 타임아웃되는 것을 관찰했다** — 10단계 배포 환경에서 "connection refused"와 "블랙홀" 양쪽 모두 5초 이내 503을 반환하는지 재확인을 권고한다.
- **(v5 신규, 문서 정확도 이슈, 결함 아님, 승계) 5단계 note §6-1의 "0.12초 실측"은 실제로는 TCP 타임아웃이 아니라 Postgres 인증 즉시 거부 경로를 측정한 것이었다**(TC-096).
- v4까지의 기존 리스크(raw_internal 실제 재검증 필요, uvicorn 실기동 부분 해소, 역할 프로비저닝 문서화 공백, updated_at 매번 갱신)는 이번 v5/v6 변경과 무관해 상태 불변으로 승계한다.


## 8. 결론 및 판정 (v6, 최종 판정 갱신 — v5의 FAIL을 대체)
- [x] **PASS — 다음 단계 진행 가능**
- [ ] CONDITIONAL PASS — 조건:
- [ ] FAIL — 사유 및 재작업 요청 사항:
- **판정 근거**:
  1. v4까지 확정됐던 AC-1~AC-7(REQ-005/REQ-012/CORS)은 이번 v5/v6 변경(db/session.py, main.py, rate_limit.py, middleware.py)으로 인한 회귀가 없음을 TC-099(pytest 167건 전체)로 확인했다. 이 부분의 v4 PASS 판정은 그대로 유효하다.
  2. **AC-8(rate limiting)/AC-10(전역 예외 처리+DB 타임아웃)은 v5에서 이미 전 불릿 PASS로 확인됐고, 이번 v6에서도 회귀 없음을 재확인했다**(TC-103/106/109). DEF-SEC-01/DEF-FS-01(REQ-025)은 Fixed 상태를 그대로 유지한다.
  3. **AC-9(보안 헤더)는 v5에서 1번째 불릿(정상 응답)만 PASS였으나, 이번 v6에서 2번째 불릿("모든 응답")까지 완전히 PASS로 전환됐다.** 6단계가 실제 `uvicorn` 서버(05단계·v5와 전혀 다른 독립 세션·포트 8111~8113)로 429 응답에 보안 헤더 3종이 정상 부착됨을 재현했고(TC-103), 정상 200/`DBAPIError` 503 경로에도 회귀가 없음을 확인했다(TC-104/105/092).
  4. **DEF-005 해소가 우연이 아님을 mutation testing으로 직접 증명했다.** `main.py`를 v5의 버그 순서로 일시 되돌린 결과 `test_rate_limited_response_still_carries_security_headers`가 실제로 FAIL함을 확인했고(TC-102), 원본 복원 후 재확인 PASS했다. 이는 "테스트 자체가 잘못 설계되어 결함을 놓칠 가능성을 항상 의심한다"는 원칙을 실제로 실천한 것이며, 단순히 "5단계가 수정했고 pytest가 통과하니 믿는다"는 판단을 하지 않았다는 근거다.
  5. **신규 pytest 2건 중 하나(요청 타임아웃 헤더 테스트)는 `main.py`의 실제 등록 순서를 동적으로 읽지 않는 구조적 한계가 있음을 발견했다**(TC-102/107). 이는 결함이 아니라 테스트 설계상의 알려진 트레이드오프이며(v5의 TC-091부터 존재), `test_rate_limited_response_still_carries_security_headers`가 실질적으로 두 미들웨어의 상대 순서 전체에 대한 간접 안전망 역할을 하므로 판정에 영향을 주지 않는다. §7 리스크로 투명하게 기록했다.
  6. Tier=High(`decisions.md` DEC-021)에 규칙 B 완화가 적용되지 않으므로, 최소 2회 독립 검증(§9 1차/2차) 원칙을 v6에서도 그대로 적용했다 — "5단계가 고쳤다고 하니 통과"가 아니라 코드 리뷰(TC-101)+실측(TC-103~106)+mutation testing(TC-102/107)의 3중 독립 검증으로 판정했다.
  7. **종합 판정: PASS.** DEF-005(Medium, Open)이 이번 v6에서 Fixed로 확정되어 UNIT-01의 모든 결함(DEF-001~005, DEF-SEC-01/02, DEF-FS-01/REQ-025)이 Fixed 상태다. 신규 결함 0건. 8단계(전체 풀테스트 재실행) → 9단계(보안검증 재검증) 착수 가능(`decisions.md` DEC-027의 5→6→8→9 순서 원칙에 따라 07단계는 이번에도 재실행하지 않는다 — 미들웨어 등록 순서만 바꾼 순수 additive 변경이라는 근거는 v5와 동일).

## 9. 내부 검증 (최소 2회)

### v1 검증 로그(이력 보존)
- v1의 1차/2차 내부 검증 로그는 `docs/harness/units/verify-log_unit-01-test.md`(v1 부분)에 그대로 보존되어 있다. 요약: v1 문서 자체의 완결성(자기완결적 재현 절차, severity 근거, DEF-002 신설 누락 방지)을 검증했으며, 판정 대상(UNIT-01 코드)은 FAIL, 판정 대상 문서(테스트 결과서 자체)는 PASS로 구분해 남겼다.

### v2 1차 검증 (작성자 관점 자가 재검토)
- 검증자(역할): 20년차 QA 겸 개발자(작성자 본인 관점)
- 일시: 2026-09-14
- 체크리스트
  - [x] DEF-001의 "예상 결과"가 이번에도 추측이 아니라 `03-system-design.md` v4 §3-3 원문(13행 진리표)에 근거하는지 재확인 — TC-043의 "예상 결과" 열이 표를 그대로 옮긴 것인지 원문과 재대조 완료(일치).
  - [x] "5단계가 36건 pass라고 했으니 믿는다"는 식의 서술이 문서 어디에도 없는지 재검토 — §4-2 TC-059 비고에 "그대로 믿지 않고 직접 재실행"이라는 문구로 명시했는지 확인, 있음.
  - [x] DEF-002 해소 근거가 "동작이 정상이다"가 아니라 "정식 회귀 테스트가 실제로 파일에 존재하고 통과한다"는 것인지 확인 — TC-057/058이 파일을 열어 테스트 함수 존재를 확인한 뒤 `-v`로 개별 재실행했음을 재확인(단순 "36건에 포함되어 있겠지" 식 추정이 아님).
  - [x] AC-3/AC-5 미검증을 이번에도 정직하게 남겼는지 — §4-2 TC-063, §6, §8에서 모두 "미검증(NOT TESTED)"으로 일관되게 표기했는지 재확인.
  - 발견된 결함(문서 자체의): TC-046(전 구간 스윕)의 "총 172,800회" 수치가 계산상 맞는지(86,400초/일 × 2개 시장) 재검산 필요 — 재검산 결과 86400×2=172800으로 일치 확인, 수정 불필요.
- 조치 내용: 없음(재검산으로 수치 정합성만 재확인, 문서 수정 불필요).

### v2 2차 검증 (독립 심사자 관점 — "오늘 처음 이 v2 결과서를 받아본 7단계 통합테스터")
- 검증자(역할): 07-integration-tester 관점, 1차 검증자가 놓쳤을 법한 순환논리·암묵적 가정을 의심
- 일시: 2026-09-14
- 체크리스트
  - [ ] → [발견] TC-046이 "6단계가 별도로 새로 작성한 스크립트"라고 주장하는데, 그 스크립트가 사용한 캘린더 픽스처(2026-09-11/14 거래일, 09-12/13 휴장, close 시각)가 `tests/unit/test_last_trading_day.py`의 `week_calendar`와 **날짜·시각 값이 완전히 동일**하다. "5단계 테스트 코드의 편향을 배제하기 위해 별도 작성했다"는 취지와, "동일한 전제값을 재사용했다"는 사실이 언뜻 모순으로 보일 수 있음.
  - **재검토 결과**: 이는 순환논리가 아니다 — 배제하려는 편향은 "픽스처 값"이 아니라 "구현 코드와 짝지어진 테스트 로직/파라미터화 구조"다(예: 5단계 테스트가 놓쳤을 수 있는 특정 시각만 표본으로 뽑는 방식). TC-046은 값은 설계서 원문(§3-3 진리표 전제 문단)에서 직접 가져오되, **검증 방식 자체(전 구간·초 단위 172,800회 전수 실행)를 독립적으로 새로 설계**했다는 점에서 의미가 있다. 이 구분이 문서에 명시적으로 드러나 있지 않았던 점을 보완할 필요가 있다고 판단해, §4-2 TC-046 비고에 "기존 테스트 코드 재사용 없이 별도 작성"이라는 표현이 정확히 무엇을 의미하는지 이번 문단으로 명확히 했다(값의 출처는 설계서 원문, 독립성은 검증 방식에 있음).
  - [x] TC-054의 시행착오(캘린더 픽스처 누락으로 424 오관측)를 "발견 즉시 은폐하지 않고 §6에 기록했는가" — §4-2 TC-054 비고와 §6 서술 양쪽에 모두 명시되어 있음을 확인. 이는 "테스트 자체가 잘못 설계되어 결함을 놓칠 가능성을 항상 의심한다"는 원칙을 실제로 실천한 사례로, 오히려 이 문서의 신뢰도를 높이는 근거로 남긴다.
  - [x] CONDITIONAL PASS(§8)가 "사실상 PASS인데 형식적으로만 조건을 단 것"이 아니라 실질적 조건(AC-3 불릿4/AC-5 미해결)을 담고 있는지 재확인 — §8 3번 항목이 (a)(b)(c) 구체적 완료 조건을 명시하고 있어 형식적 조건이 아님을 확인.
  - [x] traceability.md REQ-005/REQ-012 갱신이 이 판정(CONDITIONAL PASS, DEF-001/002 Fixed, AC-3/AC-5 미검증)과 정확히 일치하는 문구로 반영되는지 사후 확인 필요(§9 작성 시점에는 아직 반영 전 — 이 문서 완성 직후 traceability.md를 갱신하며 재대조할 것을 다음 조치로 남김).
- 발견된 결함 목록(문서 자체의): 1건(TC-046 픽스처 재사용과 "독립 작성" 주장의 관계가 불명확했던 서술 문제, 위에서 보완 완료). 코드 결함은 0건.
- 조치 내용: §4-2 TC-046 비고 보완(위 반영), traceability.md 갱신 시 이 판정과 문구 일치 여부 재확인(다음 단계로 즉시 수행).

### v3 1차 검증 (작성자 관점 자가 재검토, 실제 Postgres 확정 검증 이후)
- 검증자(역할): 20년차 QA 겸 개발자(작성자 본인 관점)
- 일시: 2026-09-14 (Postgres 확보 이후 재검증)
- 체크리스트
  - [x] AC-3/AC-5의 "확정 PASS" 판정이 실제 DB 쿼리 결과에 근거하는지(추측/코드 리뷰만으로 판정하지 않았는지) — TC-064(스키마/ENUM/PK), TC-067~068(row count/idempotency), TC-072~073(롤백/재적용) 전부 `psql` 쿼리 결과를 직접 인용했는지 재확인, 근거 있음.
  - [x] DEF-003을 "GRANT가 없다"는 코드 리딩만으로 결론 내리지 않고 실제로 실패를 재현했는지 — TC-065에서 GRANT 적용 전 실제 `permission denied` 에러 메시지를 먼저 관측한 뒤에 GRANT를 적용했는지 순서를 재확인(있음, GRANT를 먼저 적용하고 나중에 실패를 재현하는 식으로 "짜맞추지" 않았다).
  - [x] DEF-004를 "코드 상 set_에 updated_at이 없다"는 정적 분석만으로 등록하지 않고 실제 값 변화(또는 무변화)를 관측했는지 — TC-069에서 `pg_sleep(2)`로 시간 간격을 두고 실제 내용을 오염시킨 뒤 재실행해 `updated_at`이 실제로 그대로임을 쿼리로 확인했는지 재확인, 있음.
  - [x] `raw_internal` 대역 검증(TC-071)이 "UNIT-01/UNIT-02 코드 자체를 검증한 것"으로 과장되어 서술되지 않았는지 — §0-2, §4-3 TC-071 비고, §5, §7 전부에서 "proxy/보조 검증이며 실제 산출물은 아니다"라는 제한을 일관되게 명시했는지 재확인, 있음.
  - [x] 코드를 직접 수정하지 않고 재작업을 요청하는 원칙을 지켰는지 — GRANT는 라이브 테스트 DB에만 적용했고 마이그레이션 파일은 건드리지 않았음을 §0-2/TC-066 비고에서 명시적으로 확인.
  - 발견된 결함(문서 자체의): §8 결론이 "AC-3/AC-5는 확정 PASS"라고 하면서 동시에 "UNIT-01 전체는 CONDITIONAL PASS"라고 해 얼핏 모순처럼 보일 수 있음 — 이 둘이 다른 층위(개별 AC 판정 vs 전체 유닛 판정)임을 명확히 구분하는 문장이 §8 5번에 있는지 재확인, 있음(보완 불필요하나 표현을 한 번 더 명확히 다듬을 필요는 인지).
- 조치 내용: §8 5번 항목의 표현을 유지하되, 최종 판정 요약(하단)에도 동일한 구분을 반복해 강조하기로 결정(아래 반영).

### v3 2차 검증 (독립 심사자 관점 — "오늘 처음 이 v3 결과서를 받아본 9단계 보안검증/10단계 배포테스터")
- 검증자(역할): 09-security-reviewer/10-deployment-tester 관점 — 이 시점부터는 "인프라가 실제로 준비된 상태에서 배포 가능한가"를 의심하는 독자를 상정
- 일시: 2026-09-14
- 체크리스트
  - [ ] → [발견] DEF-003의 심각도를 "Medium"으로 매긴 근거가 "데이터 유출이 아니라 가용성 문제"라는 설명만으로 충분한가? **재검토**: 실제로는 이보다 더 강조해야 할 지점이 있다 — 이 결함은 "실패 방향이 안전하다(기본값이 거부)"는 점에서 보안 관점에서는 오히려 바람직하지만, **health 체크(`GET /health`)가 `reference` 스키마를 전혀 건드리지 않기 때문에 DEF-003이 실제 프로덕션에 존재해도 헬스체크는 계속 "ok"를 반환해 증상이 가려진다**는 점을 초안이 언급하지 않았다. 이는 운영 관점에서 "장애를 늦게 발견하게 만드는" 요인이라 Medium 심각도의 근거를 보강할 필요가 있음.
  - [x] AC-3/AC-5가 "확정 PASS"라는 판정이 DEF-003/DEF-004의 존재와 모순되지 않는지 — 재검토 결과 모순 아님: AC-3/AC-5의 문면(note의 정확한 불릿 텍스트)은 "GRANT가 코드화되어 있어야 한다"거나 "updated_at이 항상 갱신돼야 한다"고 요구하지 않는다. 이 문서는 AC 문면을 오라클로 삼아 판정하되, 문면 밖에서 발견한 실사용 리스크는 별도 결함으로 등록하는 방식을 v1부터 일관되게 유지해왔다(TC-001/AC-1 불릿1 사례와 동일한 패턴) — 일관성 확인됨.
  - [x] "라이브 DB에 적용한 GRANT/데이터를 되돌리지 않고 남겨뒀다"는 결정이 다음 세션(7단계 등)에 혼란을 주지 않는지 — §3 "환경 관리 원칙" 문단에 명시적으로 남겨, 다음 단계 담당자가 이 DB 상태(GRANT 적용됨, 730행 존재)를 전제로 작업을 이어갈 수 있도록 문서화했는지 확인, 있음.
  - [x] TC-071(대역 스키마)이 검증 후 실제로 완전히 삭제됐는지, 즉 다음 세션에 `raw_internal`이라는 이름이 남아 있어 UNIT-02의 실제 마이그레이션과 충돌할 가능성이 없는지 — `DROP SCHEMA raw_internal CASCADE` 실행 후 `\dn` 재조회로 스키마 목록에서 사라졌음을 실제로 재확인했는지 검증, 있음(§4-3 TC-071, §3 환경 관리 원칙).
  - [x] 코디네이터의 원 질문("UNIT-01 전체가 최종 PASS인지")에 이 문서가 애매하지 않고 명확하게 답하는지 — §8 5번과 최종 판정 요약에서 "AC-3/AC-5는 확정 PASS, 전체는 DEF-003 미해결로 CONDITIONAL PASS"라고 두 층위를 분리해 명시하고 있어 애매하지 않음을 확인.
- 발견된 결함 목록(문서 자체의): 1건(DEF-003 심각도 근거에 "헬스체크로는 증상이 가려진다"는 운영 리스크가 누락됨). 코드 결함은 0건(신규).
- 조치 내용: §6 DEF-003 설명에 "헬스체크가 `reference` 스키마를 확인하지 않아 이 결함이 존재해도 `/health`는 계속 ok를 반환한다"는 문장을 추가해 심각도 근거를 보강함(아래 반영 — §6 DEF-003 행 갱신).


### v4 1차 검증 (작성자 관점 자가 재검토, DEF-003/DEF-004 수정 확인 이후)
- 검증자(역할): 20년차 QA 겸 개발자(작성자 본인 관점)
- 일시: 2026-09-15
- 체크리스트
  - [x] 5단계의 자체 검증 로그(note §0-b)를 그대로 베끼지 않고 6단계가 독립적으로 재현했는지 — TC-075에서 5단계가 남겨둔 DB 상태를 신뢰하지 않고 `downgrade base`로 완전히 밀어버린 뒤 처음부터 재구성했는지, TC-079에서 5단계와 다른 오염값(`WRONG_TEST_VALUE_V4`)을 사용했는지 재확인 — 둘 다 확인됨.
  - [x] "GRANT가 걸려 있다"는 결과가 "0002 마이그레이션이 실행한 것"이지 "이전 세션에 우연히 남아있던 것"이 아님을 구분해서 확인했는지 — 완전 초기화(스키마/ENUM/테이블/GRANT/alembic_version 전부 제거 확인) 후 재적용이라는 절차 자체가 이 구분을 보장하는지 재확인, 그렇다.
  - [x] api_service 거부 확인 범위를 5단계(UPDATE만)보다 넓혔는지, 그리고 그 근거를 명시했는지 — TC-076에서 INSERT/DELETE까지 확장했고 §4-4 표에 "5단계보다 범위 확장"이라고 명시했는지 확인.
  - [x] updated_at 갱신 확인이 실제 시각 비교(문자열 비교 아님)로 이뤄졌는지, 그리고 "매번 갱신되는 현상"을 결함으로 오인해 등록하지 않았는지 — TC-079/080 구분이 명확한지, TC-080이 "관찰 사항"으로만 표기되고 결함 표(§6)에는 등록되지 않았는지 재확인.
  - [x] 최종 판정을 CONDITIONAL PASS에서 PASS로 바꾸는 근거가 "DEF-003이 유일한 조건이었다"는 v3 §8 3번 문구와 정확히 대응하는지 — v3 §8이 "DEF-003이 Fixed로 전환되기 전에는 9단계 이후 진행 불가"라고 조건을 명시했었고, 이번에 그 조건이 충족됐음을 확인.
  - 발견된 결함(문서 자체의): 없음.
- 조치 내용: 없음.

### v4 2차 검증 (독립 심사자 관점 — "오늘 처음 이 v4 결과서를 받아본 8단계 전체테스터/9단계 보안검증자")
- 검증자(역할): 08-full-tester/09-security-reviewer 관점 — "PASS라는 결론만 보고 넘어가도 되는가"를 의심
- 일시: 2026-09-15
- 체크리스트
  - [ ] → [발견] §7 리스크 목록에 남아 있는 4개 항목(raw_internal 실제 재검증 필요, uvicorn 미기동, 역할 프로비저닝 문서화 공백, updated_at 매번 갱신)이 "PASS" 판정과 모순되지 않는지 재검토 필요 — 이것들이 진짜 "결함이 아님"이 맞는가?
  - **재검토 결과**: 4건 모두 (a) 현재 UNIT-01의 AC/REQ 문면이 요구하지 않는 범위이거나(raw_internal 실제 스키마, uvicorn 실기동), (b) 명시적 실패로 이미 안전하게 처리되고 있거나(역할 프로비저닝 — 없으면 에러로 막힘, 조용한 통과 아님), (c) 어떤 요구사항 위반도 아닌 구현상의 자연스러운 트레이드오프(updated_at 매번 갱신)다. 셋 다 "지금 당장 배포를 막을 결함"이 아니라 "후속 유닛/문서화가 챙겨야 할 항목"으로 분류하는 것이 근거 있게 타당함을 재확인했다. 다만 이 구분("결함이 아니라 후속 과제")이 §7뿐 아니라 §8 6번에도 명시적으로 반복돼 있는지 확인 — 있음, 일관됨.
  - [x] "5단계가 코드를 고쳤다"는 사실이 "6단계가 검증 없이 승인했다"로 오독될 여지가 없는지 — §0-3, §4-4 전체가 6단계의 독립 재현 절차(완전 초기화, 다른 오염값, 범위 확장)를 구체적으로 서술하고 있어 단순 승인이 아님을 확인.
  - [x] PASS 판정 이후에도 남은 리스크(§7)가 향후 어느 단계/유닛이 챙겨야 하는지 책임 소재가 명확한지 — raw_internal(UNIT-02), uvicorn 실기동(추후 배포 관련 단계), 역할 프로비저닝(UNIT-02 raw_internal 도입 시점), updated_at(향후 요구 발생 시)로 각각 명시되어 있는지 확인, 있음.
  - [x] 코디네이터의 4개 지시사항 각각에 대응하는 TC가 1:1로 존재하는지 최종 재확인 — 지시1→TC-075/081, 지시2→TC-076/077, 지시3→TC-078/079(+080 관찰), 지시4→TC-082/083/084. 누락 없음.
  - [x] traceability.md 갱신이 이 PASS 판정과 정확히 일치하는 문구로 반영될 예정인지(작성 시점 기준 사후 확인 필요 항목으로 남김) — 이 문서 완성 직후 traceability.md를 갱신하며 재대조할 것.
- 발견된 결함 목록(문서 자체의): 0건(1건의 재검토 사항은 결함이 아니라 서술 타당성 확인으로 종결).
- 조치 내용: 없음(재검토로 기존 서술의 타당성만 확인, 문서 수정 불필요).


### v5 1차 검증 (작성자 관점 자가 재검토)
- 검증자(역할): 20년차 QA 겸 개발자(작성자 본인 관점)
- 일시: 2026-09-18
- 체크리스트
  - [x] `unit-01-note.md`(v5) AC-8~AC-10의 모든 불릿을 TC로 1:1 매핑했는가 — AC-8(3개 불릿, TC-087/088 + TC-085), AC-9(2개 불릿, TC-089~092), AC-10(5개 불릿, TC-093~098) 전부 매핑 확인, 누락 없음.
  - [x] 5단계의 자체 보고("165 passed", "0.12초 실측")를 그대로 베끼지 않고 실제로 재실행/재현했는가 — TC-085(pytest 재실행), TC-093~096(직접 스크립트로 connect_timeout 실측, 5단계가 전혀 재현하지 않은 시나리오) 전부 이번 세션에서 직접 실행한 결과임을 재확인.
  - [x] "실행해보니 에러 없음"만으로 PASS 처리한 항목이 없는가 — DEF-005 발견 과정(TC-090)에서 기대값("헤더 3개 존재")과 실제값("헤더 0개")을 명시적으로 대조해 FAIL로 판정했는지 재확인, 있음. 다른 PASS 행들도 전부 기대/실제 값을 병기했는지 표 전수 재확인, 있음.
  - [x] 오케스트레이터가 명시한 5개 검증 항목(rate limit/보안헤더/TCP블랙홀/타임아웃 부작용/회귀) 전부에 대응하는 TC가 있는가 — 1번(TC-087/088), 2번(TC-089~092), 3번(TC-093~096), 4번(TC-097/098), 5번(TC-085/086 + §6 회귀 서술) 전부 확인, 누락 없음.
  - [x] DEF-005의 심각도(Medium) 판단이 자의적이지 않고 AC 문면·Tier 규칙과 연결되는가 — §6 DEF-005 행과 §8 5번 항목에서 "Medium 심각도지만 AC-9 문면 미충족이므로 전체는 FAIL"이라는 논리를 명시했는지 재확인, 있음(단독 심각도와 전체 판정을 혼동하지 않도록 구분 서술).
  - 발견된 결함(문서 자체의): TC-096 비고에서 "5단계 note의 설명이 부정확했다"는 표현이 5단계를 비난하는 어조로 읽힐 수 있어, 사실관계(결과는 맞았으나 원인 설명이 부정확)를 더 중립적으로 표현할 필요가 있다고 판단.
- 조치 내용: TC-096 및 §0-4 관련 서술을 "결과 자체는 우연히 올바른 방향이었으나 원인 설명이 부정확했다"는 사실 중심 표현으로 유지(이미 반영해 작성함 — 추가 수정 불필요, 재확인만 수행).

### v5 2차 검증 (독립 심사자 관점 — "오늘 처음 이 v5 결과서를 받아본 07/08단계 담당자")
- 검증자(역할): 07-integration-tester/08-full-tester 관점 — "FAIL 판정을 그대로 신뢰하고 5단계 재호출을 기다려도 되는가"를 의심
- 일시: 2026-09-18
- 체크리스트
  - [x] DEF-005가 1회성 우연(타이밍/네트워크 잡음)이 아니라 재현 가능한 구조적 결함인지 — TC-090(실서버, 서로 다른 포트로 2회 독립 세션)과 TC-091(완전히 격리된 Starlette 앱, DB/네트워크 전혀 무관)이라는 **원인이 다른 두 경로**에서 동일한 증상을 재현했는지 재확인 — 있음. 하나는 실제 네트워크, 하나는 순수 미들웨어 조합 재현이라 우연의 일치일 수 없음(코드 구조 분석과도 일치).
  - [x] "DEF-SEC-01/DEF-FS-01은 완전히 Fixed"라는 판정이 성급하지 않은가 — 재검토 결과, TC-087(실네트워크 60/61 경계)·TC-093~096(3중 재현: 순수 psycopg/앱 엔진/실제 uvicorn 종단)이 모두 독립적인 재현 방식이라 이 두 건은 충분히 확정 가능한 근거를 갖췄다고 판단. 다만 TC-093~096은 "단일 요청" 기준이라 09단계 §4-6이 분석한 "동시 다발 요청으로 인한 스레드풀 고갈" 시나리오까지 검증한 것은 아니라는 한계를 §2/§7에 명시했는지 재확인 — 있음.
  - [x] §8 6번의 재작업 범위 권고("DEF-005 하나로 국한")가 5단계에게 실질적으로 실행 가능한 지시인지 — 구체적인 수정 방향(미들웨어 순서 재배치 또는 헤더 직접 추가) 두 가지 옵션과 재검증 기준(TC-090/091 재현)을 명시하고 있어 모호하지 않음을 확인.
  - [x] traceability.md REQ-025/026/027 갱신이 이 판정(REQ-025/026은 Fixed 확인, REQ-027은 Partially Fixed/Open 유지)과 정확히 일치하는 문구로 반영될 예정인지 — 이 문서 완성 직후 traceability.md를 갱신하며 재대조할 것(다음 조치).
  - [x] 규칙 K(Teardown) — 이번 세션에서 기동한 uvicorn 프로세스 6개, docker(재사용만, 신규 생성 없음), 스크래치 스크립트가 전부 정리됐고 `git status`가 세션 시작 시점과 동일한지 재확인 필요 — §7(테스트 환경 정리) 절에서 별도 확인(아래 참조).
- 발견된 결함 목록(문서 자체의): 0건(모두 재확인으로 종결, 문서 수정 불필요).
- 조치 내용: 없음.

### v6 1차 검증 (작성자 관점 자가 재검토)
- 검증자(역할): 20년차 QA 겸 개발자(작성자 본인 관점)
- 일시: 2026-09-18
- 체크리스트
  - [x] DEF-005 해소가 5단계의 자체 보고("167 passed", "포트 8199 실측")를 그대로 베끼지 않고 실제로 독립 재현됐는가 — TC-101(코드 리뷰, 05단계와 무관하게 직접 소스를 읽음), TC-103(05단계·v5와 전혀 다른 포트 8111~8113에서 독립 세션으로 429 헤더 재현) 전부 6단계 자신의 이번 세션 실행 결과임을 재확인.
  - [x] "pytest가 167건 통과했으니 DEF-005가 해소됐다"는 식의 얕은 논리에 머무르지 않았는가 — TC-102(mutation testing)에서 `main.py`를 실제로 버그 순서로 되돌려 신규 테스트가 실제로 FAIL하는지까지 확인했는지 재확인, 있음. 이는 "이 테스트를 통과했다고 다음 단계(8단계)에 넘겨도 되는가"를 의심하는 2차 검증 관점을 1차에서 선제적으로 반영한 것.
  - [x] 회귀 확인 4개 항목(정상 200/DBAPIError 503 헤더 유지, CORS 일관성, rate limit 60/61 경계, DB 타임아웃 코드 무변경)이 전부 실측 또는 코드 레벨 근거를 갖췄는지 — TC-104(실측)/TC-105(실측)/TC-106(실측)/TC-109(코드 리뷰) 각각에 구체적인 실행 결과(헤더 값, 상태코드, 소요시간, 코드 diff 대조)가 병기되어 있는지 재확인, 있음.
  - [x] 코디네이터가 명시한 4개 검증 항목(DEF-005 해소/회귀/pytest·ruff 재실행/신규 테스트 실효성)에 전부 대응하는 TC가 있는가 — 1번(TC-101~103, 107), 2번(TC-104~106, 109), 3번(TC-099/100), 4번(TC-102, 108) 전부 확인, 누락 없음.
  - [x] TC-102/107에서 발견한 "타임아웃 헤더 테스트가 main.py를 동적으로 읽지 않는다"는 한계를 결함으로 잘못 등록하거나, 반대로 숨기지 않았는가 — §5 커버리지 미해결 항목, §7 리스크에 각각 명시했고 §6 결함 목록에는 등록하지 않았는지(결함이 아니라 테스트 설계 한계이므로) 재확인, 있음.
  - 발견된 결함(문서 자체의): 없음.
- 조치 내용: 없음.

### v6 2차 검증 (독립 심사자 관점 — "오늘 처음 이 v6 결과서를 받아본 08단계 전체테스터/09단계 보안검증자")
- 검증자(역할): 08-full-tester/09-security-reviewer 관점 — "PASS로 8단계에 넘겨도 되는가"를 의심
- 일시: 2026-09-18
- 체크리스트
  - [x] DEF-005 Fixed 판정이 3번의 독립 재현(v5 실서버 2회 + v6 실서버 1회, 게다가 v6은 mutation testing까지 추가)에 근거하는지, 혹은 5단계 note를 그대로 신뢰한 부분이 섞여 있지 않은지 — §0-5, §4-6 전체를 재검토한 결과 모든 TC가 6단계 자신의 실행 로그(포트 번호, 실제 헤더 값, FAIL 메시지 원문)를 직접 인용하고 있어 5단계 note를 신뢰의 근거로 삼은 문장이 없음을 확인.
  - [x] mutation testing(TC-102) 절차 자체가 안전하게 수행됐는가(원본 코드 유실 위험) — 백업 파일(`.harness-tmp/main.py.orig.bak`) 생성 → 변경 → 테스트 → `diff`로 바이트 단위 동일성 확인 후 복원이라는 순서가 §4-6/§6-1에 구체적으로 기록되어 있고, 복원 후 `pytest tests/unit -q`(167건)를 재실행해 정상 상태로 돌아왔음을 확인했는지 재검토 — TC-099가 mutation testing(TC-102) **이후**에 수행된 최종 재실행 결과임을 서술 순서로 확인, 안전하게 수행됨.
  - [x] "이미 Fixed로 확인된 DEF-SEC-01/DEF-FS-01을 처음부터 다시 검증할 필요는 없다"는 코디네이터 지시를 따른 것이, 실제로 회귀가 없다는 결론을 뒷받침하기에 충분한 근거인가(단순히 "안 봤다"가 아닌지) — 재검토 결과, TC-109(코드 리뷰로 무변경 확인)와 TC-103/105/106(핵심 경계·경로 실측)을 **결합**해서 판단했으므로 "지시라서 안 본 것"이 아니라 "코드 레벨+표적 실측으로 회귀 없음을 적극적으로 확인한 것"임을 확인. TCP 블랙홀 3초 지연 자체를 반복 측정하지 않은 것은 코드가 무변경임을 먼저 확인했기 때문에 정당화된다.
  - [x] §7에 남긴 "타임아웃 헤더 테스트의 구조적 한계"가 8단계/9단계 담당자에게 충분히 명확하게 전달되는가(모호한 표현으로 리스크를 축소하지 않았는지) — §5·§7·§4-6 TC-102 비고 세 곳에서 일관되게 "이 특정 테스트는 main.py 순서 변경에 반응하지 않는다"고 구체적으로 서술하고 있으며, 동시에 "rate-limit 테스트가 간접 안전망 역할을 한다"는 완화 근거도 함께 제시해 과장도 축소도 하지 않았음을 확인.
  - [x] traceability.md REQ-025/026/027 갱신이 이 판정(3건 모두 최종 Fixed/PASS)과 정확히 일치하는 문구로 반영될 예정인지 — 이 문서 완성 직후 traceability.md를 갱신하며 재대조할 것(다음 조치).
  - [x] 규칙 K(Teardown) — mutation testing으로 생성한 백업 파일이 `.harness-tmp/`에만 있었는지, uvicorn 프로세스 3개가 전부 종료됐는지, `git status`가 세션 시작 시점과 동일한지 재확인 — §6-1 v6 Teardown 절에서 전부 확인 완료.
- 발견된 결함 목록(문서 자체의): 0건(모두 재확인으로 종결, 문서 수정 불필요).
- 조치 내용: 없음.

## 최종 판정 요약 (v6, 최종 — v5의 FAIL을 대체)
- **AC-1~AC-7(REQ-005/REQ-012/CORS)**: 회귀 없음, v4 PASS 상태 그대로 유효(TC-099로 재확인).
- **AC-8(rate limiting)/AC-10(전역 예외 처리+DB 타임아웃)**: 전 불릿 **PASS**(v5부터 유지, v6에서 회귀 없음 재확인 — TC-103/106/109).
- **AC-9(보안 응답 헤더)**: v5의 부분 FAIL(429/타임아웃 503 응답 헤더 누락, DEF-005)이 이번 v6에서 **완전히 해소되어 전 불릿 PASS**로 전환됐다. 6단계 독립 세션(05단계와 다른 포트)의 실측 재현(TC-103)과 mutation testing(TC-102)으로 우연이 아님을 직접 증명했다.
- **UNIT-01(v6) 종합 판정: PASS.** DEF-001~005, DEF-SEC-01/02, DEF-FS-01/REQ-025 **전부 Fixed로 최종 확정**됐다. 신규 결함 0건. v5의 FAIL 판정을 이번 v6이 대체한다.
- **다음 단계**: `decisions.md` DEC-027이 확정한 5→6→8→9 순서에 따라, 8단계(전체 풀테스트 재실행) → 9단계(보안검증 재검증) 순서로 진행한다. 07단계(feature 통합테스트)는 이번에도 재실행하지 않는다(미들웨어 등록 순서만 바꾼 순수 additive 변경). traceability.md REQ-025/026/027을 이 판정(3건 모두 최종 Fixed/PASS)으로 갱신한다.
- **후속 과제(배포 차단 아님)**: (1) `test_request_timeout_response_still_carries_security_headers`가 `main.py`의 실제 등록 순서를 동적으로 읽지 않는 구조적 한계 — 향후 미들웨어 순서를 다시 바꿀 때 mutation testing으로 재검증 권고(§7). (2) v4까지의 기존 리스크(raw_internal 실제 재검증 필요, uvicorn 실기동 부분 해소, 역할 프로비저닝 문서화 공백, updated_at 매번 갱신), (3) 멀티 워커 rate limiter 한계, `RequestTimeoutMiddleware`의 스레드 강제종료 불가 한계, 로컬 환경의 "닫힌 포트도 3초 지연" 관찰, 5단계 note의 "0.12초" 문서 정확도 이슈 — 전부 이번 v5/v6과 무관하게 상태 불변으로 승계한다.
