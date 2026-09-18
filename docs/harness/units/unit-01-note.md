# UNIT-01 구현 노트 — 휴장일/영업일 캘린더 서비스

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-14 (최초), 2026-09-14 재작업(v2 — DEF-001 대응), 2026-09-15 재작업(v3 — DEF-003/DEF-004 대응), 2026-09-18 재작업(v4 — DEF-U09-01 대응, CORS 미들웨어 부재), 2026-09-18 재작업(v5 — DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판 대응, 규칙 F), 2026-09-18 재작업(v6 — DEF-005 대응, 규칙 F 2차 라운드), 2026-09-18 재작업(**v7 — DEF-SEC-03 대응, 규칙 F 3차 라운드**)
- **속도 트랙(ORCHESTRATOR.md 1장 "구현 속도 트랙" L1~L5): L3(기본값, 트랙 명시 없이 진행됨).** UNIT-01은 이 프로젝트가 트랙 시스템(DEC-028) 도입 이전에 05단계를 마친 기존 유닛이라 트랙이 소급 지정되지 않았다 — v5·v6·v7(이번) 재작업도 모두 동일 유닛의 결함 수정이므로 L3 그대로 적용한다. 6단계는 L3 표준 절차(완화 없음)로 검증할 것.
- 포함 REQ: REQ-005(직전 거래일 산정), REQ-012(휴장일/특수개장일 캘린더 관리, 하드코딩 금지), **(v4 추가) 03-system-design.md §6-3(CORS 제한) — 공용 Public API 기반(`main.py`) 소관**, **(v5 추가) REQ-025(확장판)·REQ-026(신규)·REQ-027(신규, 백엔드 범위) — 03-system-design.md §5-4/§6-3 Must 요구사항, 공용 Public API 기반(`main.py`/`db/session.py`) 소관**, **(v6) REQ-027 잔여분(보안 헤더가 "모든 응답"에 적용) — `main.py` 미들웨어 등록 순서 소관**, **(v7) REQ-026 잔여분(rate limiting의 IP 판별 신뢰 경계) — `rate_limit.py`/신규 `scripts/run_public_api.py` 소관**
- 입력(최초): `docs/harness/03-system-design.md`(v3, PASS) §3-3/§3-4/§1-3, `docs/harness/04-ux-design.md`(v3, PASS), `docs/harness/02-planning.md`(v3) §9 UNIT-01
- 입력(v2 재작업): `docs/harness/03-system-design.md`(**v4**, PASS, §3-3 재작성) — 6단계(`unit-01-test.md`)가 발견한 DEF-001(High) 대응, `decisions.md` DEC-018
- 입력(v3 재작업): `docs/harness/units/unit-01-test.md`(**v3**) — 6단계가 실제 PostgreSQL(Docker `stock-screener-db`)로 검증하며 발견한 **DEF-003(Medium)**/**DEF-004(Low)** 대응. 설계 결함이 아니라 구현 누락(코드화 누락)이므로 3단계 재작업 없이 5단계가 직접 수정.
- 입력(v4 재작업): `docs/harness/units/unit-09-test.md`(TC-031, DEF-U09-01) — 6단계가 UNIT-09 검증 중 발견한 **CORS 미들웨어 부재(Critical)**. `03-system-design.md` §6-3 "CORS는 자사 프론트엔드 오리진으로만 제한"을 UNIT-01~08 어느 유닛도 구현하지 않아, 프론트엔드/백엔드가 다른 오리진일 때 브라우저 fetch가 100% 차단됨. 근본 원인이 설계 결함이 아니라 UNIT-01이 만든 공용 기반의 구현 누락이므로(설계서는 이미 요구사항을 명시했음), 3단계 재작업 없이 5단계가 직접 수정. `decisions.md` DEC-022 참조.
- 입력(v5 재작업): `docs/harness/09-security-audit.md` §4-5, §4-6, §6, §9(FAIL 판정) — **DEF-SEC-01(High)**(IP rate limiting 미구현), **DEF-SEC-02(Medium)**(보안 응답 헤더 미구현), **DEF-FS-01/REQ-025 확장판(High)**(전역 예외 처리 부재로 근본 원인 확장). `docs/harness/decisions.md` **DEC-027**(오케스트레이터가 재작업 범위·순서를 5→6→8→9단계로 확정, 07단계 4건은 재실행 안 함). 셋 다 근본 원인이 `services/public_api/main.py`/`db/session.py`(UNIT-01 공용 기반)로 귀속되어 한 사이클로 함께 해소.
- 입력(v7 재작업): `docs/harness/09-security-audit.md`(**v2**) §11-3~§11-8(FAIL, 근거 전면 교체) — 9단계 재감사가 DEF-SEC-01/02/FS-01(REQ-025/026/027)은 전부 Fixed로 재확인했으나, 이번 재작업으로 신규 도입된 `rate_limit.py`의 첫 정밀 감사에서 **DEF-SEC-03(High, 신규)**을 발견: `request.client.host`가 uvicorn `ProxyHeadersMiddleware`(기본 `proxy_headers=True`, loopback 암묵 신뢰)를 거친 값인데 이 신뢰 경계를 고정하는 배포 설정이 저장소에 없어 `X-Forwarded-For` 스푸핑만으로 rate limit이 100% 우회 가능함을 실제 uvicorn 프로세스로 재현·확정(§11-3 TC-SEC-45). `decisions.md` DEC-027 재검증 사이클의 3차 라운드(좁은 범위 — DEF-SEC-01/02/FS-01 로직은 이번에 건드리지 않는다, 9단계가 이미 정상 동작 재확인 완료).
- 의존성: 없음(선행 유닛) — 그린필드 프로젝트라 이번 유닛에서 최소 스캐폴딩도 함께 구성

---

## 0. 재작업 이력 (v2 — DEF-001 대응, 규칙 F 피드백 루프)

6단계(단위테스트)가 UNIT-01을 검증하는 과정에서 **DEF-001(High)**을 발견했다: `get_last_trading_day()`가 장중(개장~마감 사이) 내내 "당일"을 직전 거래일로 잘못 반환하는 결함. 근본 원인은 5단계 코드가 아니라 **`03-system-design.md`(v3) §3-3 의사코드 자체의 내적 모순**(주석은 "마감 전 오늘 제외"라 서술하나 조건식은 개장 시각과 비교)이었으므로, 6단계는 UNIT-01을 **FAIL** 판정하고 3단계 재작업을 요청했다(`unit-01-test.md` §8). 이에 따라 `03-system-design.md`가 **v4**로 개정되어(§3-3 전면 재작성 — 마감 시각 기준, `_already_closed` 헬퍼, 13행 진리표), 이번 재작업은 그 v4 설계를 그대로 반영한다.

**변경 요약**:
1. `shared/calendar_service/last_trading_day.py`: 판단 기준을 개장 시각에서 **마감 시각**(`row.session_close_at`)으로 전면 재작성. `_already_closed(candidate, row, as_of)` 헬퍼 분리(과거 날짜는 무조건 마감 취급, 오늘 날짜만 실제 시각 비교). `row.is_trading_day and _already_closed(...)` **단락 평가 순서를 명시적으로 지킴**(휴장일 행의 `session_close_at=None`과 비교하다 크래시 나는 것 방지).
2. `shared/calendar_service/market_hours.py` **삭제** — `market_open_time()`과 그 상수(KRX 09:00/NXT 08:00, 근거 없는 가정값이었음)를 로직에서 완전히 제거(v4 설계 지시, §3-3 "구현 시 필수 주의사항" 1번).
3. 알 수 없는 `market` 값에 대한 `ValueError`는 (기존에 `market_open_time()`이 담당했으나) `get_last_trading_day()` 진입부에서 `VALID_MARKETS` 검사로 직접 수행하도록 이동.
4. `CalendarDataError` 신규 추가(`CalendarIntegrityError` 공통 베이스로 `CalendarScanLimitExceeded`와 통합) — 거래일(`is_trading_day=True`) 행인데 `session_close_at`이 비어 있는 데이터 무결성 위반을 명시적 예외로 처리(설계서에 없는 추가 방어, "None과 시각 비교로 크래시" 대신 원인이 분명한 예외).
5. `services/public_api/api/calendar.py`: `CalendarScanLimitExceeded` 대신 공통 베이스 `CalendarIntegrityError`를 캐치하도록 변경(503 매핑 범위를 `CalendarDataError`까지 확장).
6. `tests/unit/test_last_trading_day.py`: v4 §3-3의 **13행 경계 시각 진리표를 `pytest.mark.parametrize`로 그대로 재현**(행 #1~#11), 휴장일 스킵(#12)·캘린더 공백(#13) 별도 테스트, 과거 날짜는 시각 무관 항상 마감 취급 테스트, 단락 평가 순서 보호 테스트, `CalendarDataError` 발생 테스트 추가.
7. `tests/unit/test_public_api.py`: 기존 `test_last_trading_day_success`가 v4 로직에서는 `session_close_at=None`인 거래일 행 때문에 503으로 바뀌는 것을 발견해 테스트 픽스처를 수정(§4 참조). 6단계가 지적한 DEF-002(경미, 회귀 테스트 공백) 겸사겸사 해소 — `/health` DB 예외→degraded, `CalendarScanLimitExceeded`(현재는 `CalendarIntegrityError` 계열)→503 매핑 회귀 테스트 2건 추가.
8. 결과: `pytest tests/unit` **21건 → 36건**으로 확장, 전부 pass. `ruff check .` 전체 통과 유지.

아래 §1~§6은 v2(재작업) 기준으로 갱신된 내용이다. 최초 작성 시점의 서술 중 v4로 대체된 부분(§2 편차 항목 1·2)은 "해소됨"으로 표시하고 근거를 남겼다(이력 추적을 위해 삭제하지 않음).

---

## 0-b. 재작업 이력 (v3 — DEF-003/DEF-004 대응, 실제 PostgreSQL 검증 결과)

6단계가 로컬 Docker의 실제 PostgreSQL(`stock-screener-db` 컨테이너)로 UNIT-01을 검증하는 과정에서, Fake 기반 단위테스트로는 드러나지 않는 신규 결함 2건을 발견했다(`unit-01-test.md` v3). 둘 다 **설계 결함이 아니라 구현 누락**이므로(코디네이터 판단과 일치), 3단계 재작업 없이 5단계가 직접 코드로 수정했다.

**DEF-003(Medium) — `reference` 스키마 GRANT 누락**: `db/alembic/versions/0001_create_reference_market_calendar.py`가 스키마/테이블만 만들고 GRANT를 전혀 실행하지 않아, `alembic upgrade head` 직후 `batch_worker`/`api_service` 둘 다 `reference`에 접근 권한이 전혀 없는 상태였다(6단계가 TC-065에서 `permission denied for schema reference`로 100% 재현). §1-1(2차 방어, DB 권한 분리)/§3-1(역할별 접근 매트릭스: `reference`는 batch_worker/api_service 둘 다 읽기, 쓰기는 batch_worker만) 설계를 실제로 동작시키려면 GRANT가 코드로 존재해야 하는데 빠져 있었다.

- **조치**: 새 Alembic 리비전 `db/alembic/versions/0002_grant_reference_privileges.py`를 추가했다(기존 0001을 수정하지 않음 — 이미 실제 테스트 DB에 적용된 리비전을 사후 수정하면 alembic이 "이미 적용됨"으로 판단해 재실행되지 않으므로, 신규 forward 리비전으로 처리하는 것이 표준적이고 안전하다).
  - `GRANT USAGE ON SCHEMA reference TO batch_worker, api_service`
  - `GRANT SELECT, INSERT, UPDATE ON reference.market_calendar TO batch_worker` (DELETE는 부여하지 않음 — `load_calendar.py`가 upsert만 하고 삭제하지 않으므로 최소 권한 원칙)
  - `GRANT SELECT ON reference.market_calendar TO api_service`
  - `downgrade()`는 위 GRANT를 역순 REVOKE.
  - **범위 결정**: `batch_worker`/`api_service` **역할(role) 자체의 생성**은 이 마이그레이션에 포함하지 않았다. 역할 생성·비밀번호 관리는 인프라 프로비저닝 영역이라 스키마 마이그레이션이 자격증명을 다루는 것은 부적절하다고 판단했다(코디네이터 지시도 "GRANT를 추가"로 한정). 역할이 아직 없는 환경에서 이 리비전을 실행하면 PostgreSQL이 `role "batch_worker" does not exist`로 명시적으로 실패한다 — 조용한 스킵이 아니라 "역할을 먼저 프로비저닝하라"는 신호로 작동하므로 REQ-005/012의 "명시적 실패" 원칙과 일관된다.
- **실제 검증(로컬 Docker `stock-screener-db`, migrator/batch_worker/api_service 계정 모두 확인)**:
  1. `alembic downgrade base`로 완전히 초기화(스키마/테이블/GRANT 전부 제거) 후 `alembic upgrade head`(0001+0002) 재실행.
  2. `\dp reference.market_calendar` 조회 → **수동 개입 없이** `batch_worker=arw`, `api_service=r` 확인(수정 전에는 이 시점에 아무 권한도 없었음 — DEF-003 재현 조건과 동일).
  3. `BATCH_DATABASE_URL`(batch_worker)로 `scripts/load_calendar.py data/calendar/2026.example.yaml` 실행 → **정상 성공**(수정 전에는 TC-065처럼 `permission denied for schema reference`로 실패했을 상황).
  4. `api_service` 계정으로 직접 접속해 `SELECT count(*)`(730건 성공) / `UPDATE`(`permission denied for table market_calendar`로 거부) 확인 — §3-1 읽기전용 원칙 재확인.
  5. `alembic downgrade 0001`로 0002만 롤백 → GRANT가 정확히 REVOKE되는지(`has_schema_privilege`가 `f`로 바뀜) 확인 후 다시 `alembic upgrade head`로 복원.

**DEF-004(Low) — `scripts/load_calendar.py`의 `updated_at` 미갱신**: `upsert_rows()`의 `on_conflict_do_update(set_={...})`에 `updated_at`이 빠져 있어, 내용이 실제로 갱신돼도 타임스탬프가 최초 삽입 시각에 고정됐다(6단계가 TC-069에서 행을 오염시킨 뒤 재실행해 내용은 복구되지만 `updated_at`은 그대로임을 실측).

- **조치**: `scripts/load_calendar.py`의 `set_` 딕셔너리에 `"updated_at": func.now()`를 추가했다. (모델 컬럼의 `onupdate=func.now()`가 아니라 `set_`에 직접 넣는 방식을 택한 이유: 이 upsert는 SQLAlchemy ORM의 단위작업(UPDATE)이 아니라 Core `INSERT ... ON CONFLICT DO UPDATE` 문이라, 컬럼 레벨 `onupdate`는 애초에 이 경로에서 트리거되지 않는다 — DEF-004 리포트가 권고한 두 방법 중 실제로 동작하는 쪽을 선택.)
- **실제 검증(TC-069와 동일 절차 재현)**: `2026-01-01`/`KRX` 행을 `migrator`로 직접 `UPDATE ... SET holiday_name='WRONG_TEST_VALUE', source='corrupted-for-test'`로 오염 → `pg_sleep(2)` → `batch_worker`로 동일 YAML 재실행 → `holiday_name`/`source`는 원래 값(`신정`, 정상 source)으로 복구되고, **`updated_at`도 오염 이전 값(`15:08:56`)에서 재실행 시각(`15:09:38`)으로 실제로 갱신됨을 쿼리로 확인**.

**결과**: 두 결함 모두 로컬 Docker의 실제 PostgreSQL(`stock-screener-db`, migrator/batch_worker/api_service 3계정)로 수정 전 재현 → 수정 → 수정 후 해소를 동일 절차로 직접 확인했다(코드 리딩만으로 결론 내리지 않음). `pytest tests/unit`(36건)·`ruff check .` 모두 기존과 동일하게 통과(이번 수정은 마이그레이션 GRANT/CLI upsert의 실제 DB 상호작용 영역이라, DB 없이 도는 기존 Fake 기반 pytest 스위트로는 애초에 검증 대상이 아니다 — 아래 §3 "실 DB 통합 테스트 자동화 부재" 항목 참조). 검증 후 DB는 `alembic upgrade head` + 캘린더 데이터 적재 완료 상태로 남겨뒀다(다음 세션 편의를 위해 6단계와 동일한 관례를 따름).

---

## 0-c. 재작업 이력 (v4 — DEF-U09-01 대응, 규칙 F 피드백 루프)

6단계가 UNIT-09(종목 검색 화면)를 검증하는 과정에서, UNIT-09 자신의 코드가 아니라 UNIT-01이 최초 작성한 공용 Public API 기반(`services/public_api/main.py`)에서 **DEF-U09-01(Critical)**을 발견했다(`docs/harness/units/unit-09-test.md` TC-031, §8). 요지: `03-system-design.md` §6-3이 "CORS는 자사 프론트엔드 오리진으로만 제한"을 명시적으로 요구하는데, `main.py`에 CORS 미들웨어가 전혀 구성되어 있지 않아, 프론트엔드와 백엔드가 다른 오리진(로컬 개발 기본값도 포트가 다름 — `frontend/.env.example`은 백엔드 기본 포트 8000, Next.js 프런트 기본 개발 포트는 3000)일 때 브라우저의 모든 크로스오리진 `fetch`가 `Access-Control-Allow-Origin` 헤더 부재로 100% 차단된다. 이는 설계서 자체의 결함이 아니라(§6-3이 이미 요구사항을 명시했음) UNIT-01~08 어느 유닛도 이를 구현하지 않은 **구현 누락**이므로, 3단계 재작업 없이 5단계(UNIT-01 담당)가 직접 수정한다(`decisions.md` DEC-022).

**변경 요약**:
1. `services/public_api/core/config.py`: `get_cors_allowed_origins()` 신설. 환경변수 `PUBLIC_API_CORS_ALLOWED_ORIGINS`(쉼표 구분 오리진 목록)를 읽되, 미설정/공백이면 로컬 개발 기본값 `["http://localhost:3000"]`(Next.js 기본 개발 포트)로 폴백한다. 기존 `get_settings()`(DB URL)와 달리 미설정 시 예외를 던지지 않는다 — CORS 허용 오리진은 DB 자격증명과 달리 시크릿이 아니고, 로컬 개발이 별도 설정 없이 바로 동작해야 한다는 요구사항(오케스트레이터 지시, `decisions.md` DEC-022)에 따른 의도적 설계 판단이다.
2. `services/public_api/main.py`: `app.add_middleware(CORSMiddleware, allow_origins=get_cors_allowed_origins(), allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])` 추가. `allow_credentials=False`는 §6-1(인증/쿠키 없음, REQ-016 Out-of-Scope)과 일관되고, `allow_methods=["GET"]`은 이 API가 §1-2에서 "무상태, 읽기전용"으로 설계되어 모든 엔드포인트가 GET만 제공하는 것과 일관된다(코드 리뷰로 실제 라우터 전수 확인 — POST/PUT/DELETE 라우트 없음).
3. `.env.example`: `PUBLIC_API_CORS_ALLOWED_ORIGINS` 사용법 주석 추가(기존 `GOV_DATA_PORTAL_BASE_URL`의 "기본값 존재 + 필요 시 재정의" 관례를 그대로 따름 — 값 자체는 주석 처리해 코드 기본값이 적용되게 둠).
4. `tests/unit/test_public_api.py`: CORS 회귀 테스트 4건 신규 — (a) 허용 오리진(`http://localhost:3000`)에서 `Access-Control-Allow-Origin` 헤더가 실제로 반환됨, (b) 허용되지 않은 오리진에서는 그 헤더가 응답에 없음, (c) `get_cors_allowed_origins()`가 쉼표로 구분된 환경변수를 올바르게 파싱(공백 트림 포함)함, (d) 환경변수 미설정 시 기본값으로 폴백함.
5. 결과: `pytest tests/unit` **151건 → 155건**으로 확장, 전부 pass. `ruff check .` 전체 통과 유지.

**회귀 재검증 범위 확인(코드 리딩 + 실제 서버 기동으로 최소 확인, §6-1 참조)**:
- `frontend/src/lib/screenApi.ts`(UNIT-07)·`frontend/src/lib/stockSearchApi.ts`(UNIT-09) 둘 다 이 fetch 함수를 호출하는 페이지 컴포넌트(`frontend/src/app/screener/page.tsx`, `frontend/src/app/stocks/page.tsx`)에 `"use client"` 지시어가 있어 **브라우저에서 직접 fetch**한다 — 이 결함에 실제로 노출되어 있었고, 이번 수정 이후 두 유닛 모두 6단계 회귀 재검증이 필요하다(오케스트레이터가 트리거).
- `frontend/src/lib/stockMetrics.ts`(UNIT-06, `/stocks/[code]`)·`frontend/src/lib/marketSummary.ts`(UNIT-08, `/` 홈)는 호출부(`frontend/src/app/stocks/[code]/page.tsx`, `frontend/src/app/page.tsx`)에 `"use client"`가 없는 **서버 컴포넌트**다 — Next.js 서버가 서버 사이드에서 Public API를 호출하는 서버-서버 요청이라 브라우저 CORS 정책의 적용 대상이 아니다. 이 판단은 코드 리뷰(파일 전체에서 `"use client"` grep)로 확인했다 — 이번 수정으로 인한 회귀 재검증 불필요(§6-1 근거 로그 참조).

아래 §1~§6은 v4까지 누적 반영된 최신 내용이다. v4로 신규 추가/변경된 부분은 위 목록과 아래 각 항목에 "(v4)"로 표시했다(이력 추적을 위해 기존 서술은 삭제하지 않음).

---

## 0-d. 재작업 이력 (v5 — DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판 대응, 규칙 F 피드백 루프)

09단계(보안검증)가 **FAIL**을 판정하며 3건의 결함을 발견했다(`09-security-audit.md` §4-5, §4-6, §6, §9). 셋 다 근본 원인이 UNIT-01 공용 기반(`services/public_api/main.py`, `db/session.py`)으로 귀속되어, 오케스트레이터가 `decisions.md` DEC-027로 재작업 범위·순서(5단계 재작업 → 6단계 재검증 → 8단계 전체 재실행 → 9단계 보안 재검증, 07단계 4건은 재실행하지 않음)를 확정했다. 이번 v5는 그 5단계 재작업이다.

**DEF-SEC-01(High) — IP 기준 rate limiting 미구현**: `03-system-design.md` §6-3(Must)이 "IP 기준 rate limiting(예: 분당 60회), 스크레이핑/대량 재배포 방지 목적"을 요구하지만 코드/인프라 어디에도 구현돼 있지 않았다(REQ-022 데이터 라이선스 방어 논리를 자동화 스크래핑으로 무력화 가능).

**DEF-SEC-02(Medium) — 보안 응답 헤더 미구현**: `03-system-design.md` §6-3(Must)이 요구하는 `Content-Security-Policy`/`X-Content-Type-Options`/`Strict-Transport-Security` 세 헤더가 백엔드/프론트엔드 어디에도 없었다.

**DEF-FS-01/REQ-025 확장판(High) — 전역 예외 처리 부재**: 8단계가 발견한 "DB 연결 장애 시 raw 500을 60~90초에 반환"(기존 DEF-FS-01)의 근본 원인을, 09단계가 코드 레벨로 재확인한 결과 "DB 연결 실패 특정"이 아니라 **"ApiError/RequestValidationError 외 어떤 예외 핸들러도 없는 구조적 공백"**임을 확정했다(TC-SEC-24/25). 수정 범위를 `connect_timeout` 하나에서 "DB 예외 핸들러 + catch-all 핸들러 + 요청 단위 타임아웃"으로 확장할 것을 권고받았다(§4-6).

### 변경 요약

1. **`services/public_api/db/session.py`**: `create_engine()`에 `connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"}` 추가. `connect_timeout`(연결 자체, 3초)과 `statement_timeout`(연결 이후 쿼리 실행, 3초)을 모두 짧게 고정해, DB가 무응답이어도 스레드가 60~90초가 아니라 수 초 내에 명시적 예외(`OperationalError` 등)로 실패하도록 한다. `03-system-design.md` §5-4가 명시한 "쿼리 타임아웃 5초"도 이 변경으로 함께 충족한다(§2 편차 항목1 참조 — 원 지시는 `connect_timeout`만 언급했으나 같은 결함 근본 위치에서 §5-4 요구사항을 함께 충족하는 것이 합리적이라 판단해 확장).
2. **`services/public_api/rate_limit.py`(신규)**: `RateLimitMiddleware` — IP(요청의 `request.client.host`) 기준 고정 윈도(fixed window) 카운터를 프로세스 메모리에 유지하는 인메모리 rate limiter. 기본값 분당 60회(§6-3 예시 수치 그대로 채택). 초과 시 429 + `Envelope`(`error.code="RATE_LIMITED"`)를 반환한다. 테스트가 카운터를 초기화할 수 있도록 `reset_rate_limit_state()`를 함께 노출한다.
3. **`services/public_api/middleware.py`(신규)**:
   - `SecurityHeadersMiddleware` — 모든 응답에 `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Strict-Transport-Security: max-age=63072000; includeSubDomains` 세 헤더를 추가.
   - `RequestTimeoutMiddleware` — `asyncio.wait_for`로 `call_next()`를 감싸 4.5초 초과 시 503 `SERVICE_UNAVAILABLE` Envelope을 반환하는 요청 단위 타임아웃(09단계 §4-6 권고). **알려진 구조적 한계**를 클래스 docstring에 명시했다: 동기 라우터 함수가 스레드풀(anyio worker thread)에서 실행되므로, 이 타임아웃은 클라이언트 응답은 빠르게 보장하지만 이미 블로킹 중인 스레드 자체를 강제 종료하지는 못한다(파이썬 스레드는 외부에서 강제 종료 불가) — 스레드 점유 시간을 근본적으로 줄이는 주된 방어선은 여전히 `db/session.py`의 타임아웃이다.
   - `UnhandledExceptionMiddleware` — `call_next()`를 감싸 그 안에서 발생하는 모든 미처리 예외를 로깅 후 503 `SERVICE_UNAVAILABLE` Envelope으로 변환하는 catch-all 안전망.
4. **`services/public_api/main.py`**:
   - 미들웨어를 `UnhandledExceptionMiddleware → SecurityHeadersMiddleware → RequestTimeoutMiddleware → RateLimitMiddleware → CORSMiddleware`(안쪽→바깥쪽) 순서로 등록(주석으로 근거 명시). CORS를 가장 바깥에 둔 이유는 rate limit(429)·타임아웃(503) 등 내부 계층이 만든 에러 응답에도 CORS 헤더가 일관되게 붙어야 브라우저가 이를 읽을 수 있기 때문이다.
   - `@app.exception_handler(DBAPIError)`, `@app.exception_handler(SATimeoutError)`(SQLAlchemy) 신규 등록 — 둘 다 503 `SERVICE_UNAVAILABLE` Envelope으로 매핑. `OperationalError`는 `DBAPIError`의 하위클래스라 별도 등록 없이 함께 커버된다.
5. 결과: `pytest tests/unit` **155건 → 165건**(rate limit/보안헤더/DB예외/catch-all/타임아웃/CORS+rate-limit 상호작용 신규 테스트 10건 추가). `ruff check .` 전체 통과.

### 게이트 1 적용 방법에 대한 판단 근거 (규칙 A 해당 없음)

- **단일 인스턴스 전제**: 오케스트레이터 지시가 이 전제를 "설계서/decisions.md 어디에도 없으면 질문하라"고 명시했으나, `03-system-design.md` §5-2가 "초기 규모(§8-A3, 동시 사용자 수백 명 이하)에서는 단일 인스턴스로 충분하며, 트래픽 실측 후 확장 여부 결정(과설계 방지)"이라고 **이미 명시적으로 확정**하고 있어(DEC-005/007과 동일한 YAGNI 원칙 기조), 질문 목록에 올리지 않고 그대로 인메모리 rate limiter를 채택했다. 멀티 인스턴스로 확장되는 시점(트래픽 실측 후)에는 공유 스토어(Redis 등) 기반으로 재구현이 필요하다는 한계를 `rate_limit.py` 모듈 docstring에 명시해 후속 담당자가 인지하도록 했다.
- **rate limiting 구현 방식(slowapi vs 직접 구현)**: `slowapi`는 실제 PyPI 패키지이나(육안 확인 — 별도 설치/조회는 아래 게이트2에서 수행), 이 서비스는 이미 자체 `Envelope`/`ErrorDetail` 응답 계약을 갖고 있어 `slowapi`의 기본 예외/응답 포맷을 그대로 쓰면 계약을 깨고, 커스텀 핸들러로 감싸면 결국 이번에 만든 것과 비슷한 양의 코드가 필요해진다. 반면 요구사항(IP+분당 60회, 단일 인스턴스, Envelope 준수)은 고정 윈도 카운터 20줄 남짓으로 충분히 구현 가능해, 새 외부 의존성을 추가하는 것보다 직접 구현이 더 단순하고 통제 가능하다고 판단했다(YAGNI, `decisions.md` DEC-005/007과 동일한 판단 기조). 이 판단은 설계서가 구현 방식(라이브러리 vs 직접 구현)을 명시하지 않아 규칙 A상 "두 갈래로 갈리는 모호함"에 해당할 수 있었으나, 신규 의존성 도입 여부는 규칙 A-3(비가역적 결정이 아니면 에이전트가 근거를 갖고 자체 판단)의 대상으로 보아 여기 근거를 남기고 진행했다 — 필요 시 `decisions.md`에 정식 등록할지는 오케스트레이터 판단에 맡긴다.
- **catch-all 예외 처리의 매핑 코드**: `03-system-design.md` §4-1 에러 코드 표에는 "그 외 모든 미처리 예외" 전용 코드가 정의돼 있지 않다. 오케스트레이터 지시가 명시적으로 "503 SERVICE_UNAVAILABLE로 매핑"을 요구했으므로 그대로 따랐다(§2 편차 항목2 참조 — 프로그래밍 버그까지 "일시적 서비스 장애"로 표현하는 것이 완전히 정확한 의미는 아니라는 한계를 편차로 기록).
- **`@app.exception_handler(Exception)` 대신 미들웨어로 구현**: 이는 규칙 A 대상 모호함이 아니라, 실제로 FastAPI/Starlette(설치 버전: fastapi 0.139.0/starlette 1.6.0) 프레임워크 동작을 직접 실행해 검증한 결과 발견한 기술적 사실이다 — `@app.exception_handler(Exception)`(또는 500)으로 등록하면 Starlette가 이를 일반 `exception_handlers` 딕셔너리가 아니라 가장 바깥쪽 `ServerErrorMiddleware`의 `handler`로 특별 취급해(`starlette/applications.py` `build_middleware_stack()` 확인), 우리가 만든 `SecurityHeadersMiddleware`/`RateLimitMiddleware`/`CORSMiddleware`를 모두 우회하고, 응답을 보낸 뒤에도 예외를 항상 재-raise해(`starlette/middleware/errors.py`, "We always continue to raise the exception") `TestClient`의 기본 동작(`raise_server_exceptions=True`)을 깨뜨린다는 것을 직접 재현해 확인했다. 그래서 이 접근을 버리고 `UnhandledExceptionMiddleware`(라우터에 가장 가까운 안쪽 위치)로 전환했다 — 자세한 근거는 `middleware.py`의 `UnhandledExceptionMiddleware` docstring 참조.

---

## 0-e. 재작업 이력 (v6 — DEF-005 대응, 규칙 F 2차 라운드)

6단계가 v5 재작업을 독립 재검증하며 **FAIL** 판정했다(`unit-01-test.md` v5, §4-5 TC-090/091, §6, §9). DEF-SEC-01(rate limiting)과 DEF-FS-01/REQ-025(전역 예외 처리 + DB 타임아웃)는 완전히 Fixed로 확인됐으나, DEF-SEC-02(보안 응답 헤더)는 **신규 결함 DEF-005(Medium)**로 인해 부분적으로만 해소됐다는 것이 유일한 FAIL 사유였다.

**DEF-005 근본 원인**: `SecurityHeadersMiddleware`가 `RateLimitMiddleware`/`RequestTimeoutMiddleware`보다 안쪽(라우터에 더 가까운 위치, `main.py`에서 더 먼저 `add_middleware`)에 등록돼 있었다. Starlette는 **나중에 `add_middleware`된 미들웨어가 더 바깥쪽**(먼저 요청을 받고 나중에 응답을 처리)이 된다 — 이 방향을 직접 최소 재현 스크립트(3개 미들웨어를 등록 순서대로 로그를 찍는 격리된 Starlette 앱)로 실행해 실측 확인했다(v5 note의 기존 주석은 이 방향 자체는 맞게 서술했으나, 실제 `add_middleware` 호출 순서가 그 의도와 어긋나 있었다 — `SecurityHeadersMiddleware`가 `RequestTimeoutMiddleware`/`RateLimitMiddleware`보다 먼저 등록되어 있어 이 둘보다 안쪽에 위치했다). `RateLimitMiddleware`(429)와 `RequestTimeoutMiddleware`(타임아웃 503)는 `call_next()`를 호출하지 않고 자체 응답을 즉시 반환(short-circuit)하므로, 그보다 안쪽에 있는 `SecurityHeadersMiddleware.dispatch()` 자체가 아예 실행되지 않아 세 헤더가 전부 누락됐다.

### 변경 요약

1. **`services/public_api/main.py`**: `add_middleware()` 호출 순서를 `UnhandledExceptionMiddleware → RequestTimeoutMiddleware → RateLimitMiddleware → SecurityHeadersMiddleware → CORSMiddleware`(안쪽→바깥쪽, 등록 순서 그대로)로 재배치했다. 이전 순서는 `UnhandledExceptionMiddleware → SecurityHeadersMiddleware → RequestTimeoutMiddleware → RateLimitMiddleware → CORSMiddleware`였다 — `SecurityHeadersMiddleware`의 등록 위치만 뒤로(RateLimit 다음, CORS 이전) 옮겼다. `RateLimitMiddleware`와 `RequestTimeoutMiddleware`의 상대 순서, `UnhandledExceptionMiddleware`가 가장 안쪽인 것, `CORSMiddleware`가 가장 바깥쪽인 것은 그대로 유지했다(6단계가 이미 정상 동작을 확인한 부분은 건드리지 않는다는 오케스트레이터 지시 준수). 주석도 실제 동작 방향과 DEF-005 근거를 명시하도록 갱신했다.
2. **`tests/unit/test_public_api.py`**: DEF-005 회귀 테스트 2건 신규 추가.
   - `test_rate_limited_response_still_carries_security_headers`: 실제 `app`에서 60회 호출 후 61번째(429) 응답에 보안 헤더 3종이 모두 존재함을 확인.
   - `test_request_timeout_response_still_carries_security_headers`: 격리된 Starlette 앱(`RequestTimeoutMiddleware` + `SecurityHeadersMiddleware`, `main.py`와 동일한 상대적 배치)에서 타임아웃 503 응답에도 보안 헤더 3종이 모두 존재함을 확인.
3. `services/public_api/rate_limit.py`, `services/public_api/db/session.py`, `main.py`의 DBAPIError/SATimeoutError 핸들러 로직 자체는 **손대지 않았다**(6단계가 이미 Fixed로 확인한 DEF-SEC-01/DEF-FS-01 영역, 오케스트레이터 지시대로 범위 유지).

### 방식 선택 근거 (미들웨어 순서 재배치 vs 각 short-circuit 지점에서 직접 헤더 추가)

6단계 권고안(순서 재배치, `UnhandledException → RequestTimeout → RateLimit → SecurityHeaders → CORS`)과, 대안으로 `rate_limit.py`의 `_rate_limited_response()`·`middleware.py`의 `_service_unavailable_response()` 각 지점에서 직접 세 헤더를 추가하는 방식을 비교해 **순서 재배치를 채택**했다.

- **순서 재배치를 선택한 이유**: (1) 헤더 값(CSP/`X-Content-Type-Options`/HSTS)이 `SecurityHeadersMiddleware` 한 곳에만 존재하는 단일 진실 공급원(SSOT) 구조를 유지할 수 있다 — 각 short-circuit 지점에 직접 추가하면 동일한 헤더 값 문자열이 최소 2곳(`rate_limit.py`, `middleware.py`의 `_service_unavailable_response`) 이상으로 중복되고, 향후 CSP 정책이 바뀔 때 한 곳을 빠뜨릴 위험이 생긴다(DRY 위반). (2) `RequestTimeoutMiddleware`뿐 아니라 `UnhandledExceptionMiddleware`도 같은 `_service_unavailable_response()` 헬퍼를 공유하는데, 이 경로는 이미 정상 동작(§4-5 TC-092 대조군)하므로 헬퍼 함수 자체를 건드리면 이미 정상인 경로에 불필요한 변경이 섞인다 — 순서 재배치는 헬퍼 함수를 전혀 건드리지 않아 이 위험이 없다. (3) 코드 변경 범위가 `main.py`의 `add_middleware` 호출 순서 4줄로 최소화되어, "이미 정상 동작하는 rate limiting/DB 타임아웃 로직은 건드리지 않는다"는 오케스트레이터 지시를 가장 안전하게 지킬 수 있다.
- **부작용 검토(CORS와의 상호작용)**: `CORSMiddleware`는 이번 변경 전후로 항상 가장 바깥쪽(마지막 `add_middleware`) 위치를 유지한다 — `SecurityHeadersMiddleware`를 `RateLimitMiddleware`/`RequestTimeoutMiddleware`보다 바깥쪽으로 옮겨도 `CORSMiddleware`보다는 여전히 안쪽이므로, "CORS가 모든 에러 응답에 일관되게 붙어야 한다"는 기존 요구사항(§0-d, `test_rate_limited_response_still_carries_cors_header`)은 깨지지 않는다 — 실제로 아래 로컬 검증에서 429/타임아웃 503 응답 모두 CORS 헤더와 보안 헤더 3종이 함께 존재함을 확인했다. `RateLimitMiddleware`와 `RequestTimeoutMiddleware`의 상대 순서(RateLimit이 RequestTimeout보다 바깥쪽)는 이번 변경으로 바뀌지 않았으므로, "rate limit 초과 시 타임아웃 로직 자체가 실행되지 않고 즉시 429"라는 기존 동작도 그대로 유지된다.

---

## 0-f. 재작업 이력 (v7 — DEF-SEC-03 대응, 규칙 F 3차 라운드)

9단계(보안검증)가 v2 재감사(`09-security-audit.md`)에서 DEF-SEC-01/DEF-SEC-02/DEF-FS-01(REQ-025/026/027)은 전부 Fixed로 재확인했으나, 이번 재작업 사이클로 신규 도입된 `services/public_api/rate_limit.py`에 대한 **첫 정밀 감사**에서 신규 결함을 발견해 **FAIL**(근거 전면 교체)을 판정했다(§11-3~§11-8).

**DEF-SEC-03(High) — `X-Forwarded-For` 스푸핑으로 rate limit 완전 우회**: `rate_limit.py`의 `RateLimitMiddleware`는 코드만 보면 `request.client.host`만 참조해 안전해 보인다. 그러나 이 값 자체가 이미 신뢰할 수 없다 — uvicorn을 `uvicorn services.public_api.main:app`으로(이 저장소가 v6까지 문서화해 온 유일한 실행 방법) 기동하면 uvicorn의 기본 설정(`proxy_headers=True`, `forwarded_allow_ips` 미지정 시 `127.0.0.1`(loopback) 암묵 신뢰)이 적용되는데, 이 신뢰 경계를 명시적으로 재정의하는 배포 설정(Dockerfile/시작 스크립트 등)이 이 저장소 어디에도 없었다. 그 결과 uvicorn 자신의 `ProxyHeadersMiddleware`가 우리 애플리케이션 코드에 요청이 도달하기 **전에** ASGI scope의 `client`를 클라이언트가 보낸 `X-Forwarded-For` 헤더값으로 그대로 덮어써 버린다. 09단계가 실제 uvicorn 프로세스로 재현한 결과, 60회 소진 → 61번째 429 확인 후 `X-Forwarded-For` 헤더를 요청마다 다른 값으로 바꿔 보내는 것만으로 rate limit을 100% 결정론적으로 우회할 수 있었다(§11-3 TC-SEC-45~47).

**이번 라운드의 범위(좁게 한정)**: 오케스트레이터 지시에 따라 DEF-SEC-01(rate limiting 로직/60회 한도)·DEF-SEC-02(보안헤더)·DEF-FS-01/REQ-025(DB 타임아웃+전역 예외처리)·`middleware.py`는 9단계가 이미 정상 동작을 재확인했으므로 **건드리지 않았다**. 이번 수정은 `rate_limit.py`의 IP 판별 신뢰 경계 문제 하나로 한정한다.

### 변경 요약

1. **`scripts/run_public_api.py`(신규)** — 이 서비스의 **공식 기동 스크립트**. `uvicorn.run("services.public_api.main:app", ...)`을 프로그래밍 방식으로 호출하며, 기본값으로 `proxy_headers=False`(프록시 헤더 신뢰 자체를 끔, fail closed)를 강제한다. 실제 리버스 프록시가 생기는 시점(10단계 배포 아티팩트 확정 시)에는 그 프록시의 실제 IP를 `PUBLIC_API_TRUSTED_PROXY_IPS`(쉼표 구분) 환경변수에 명시적으로 설정해야만 프록시 헤더 신뢰가 켜진다(그 경우 uvicorn에 `proxy_headers=True`+`forwarded_allow_ips=<지정값>`이 전달된다) — 신뢰 범위를 운영자가 명시적으로 결정하게 강제하며, 설정하지 않으면(기본값) 암묵적으로 아무것도 신뢰하지 않는다. `uvicorn services.public_api.main:app`을 직접 실행하면 더 이상 이 서비스의 공식 기동 방법이 아니다(이 스크립트로 대체).
2. **`services/public_api/rate_limit.py`**: IP 판별 로직 자체(= `request.client.host` 사용)는 **변경하지 않았다** — 이 로직은 uvicorn이 올바른 옵션으로 기동됐다는 전제 하에서는 이미 정확하다(09단계 §11-3 TC-SEC-44도 코드 자체는 문제없다고 확인). 대신 모듈 docstring에 이 모듈의 안전성이 uvicorn 기동 옵션에 전적으로 의존한다는 신뢰 경계를 명시하고, `scripts/run_public_api.py`로만 기동해야 한다는 사실을 남겼다. 추가로, `DEFAULT_LIMIT`을 환경변수 `PUBLIC_API_RATE_LIMIT_PER_MINUTE`로 재정의 가능하게 했다(미설정 시 기존과 동일하게 60) — 이는 rate limiting의 보안 로직과 무관한 **테스트 전용 편의 기능**이다(§2 편차 항목 참조).
3. **`tests/integration/test_rate_limit_proxy_trust.py`(신규)** — 9단계가 지적한 "`TestClient`는 ASGI를 인프로세스로 직접 호출하기 때문에 uvicorn의 `ProxyHeadersMiddleware`를 아예 거치지 않아 이 벡터를 구조적으로 검증할 수 없다"는 문제에 대응한다. `scripts/run_public_api.py`로 실제 uvicorn 서브프로세스를 띄우고, 실제 소켓을 통해 09단계와 동일한 재현 절차(한도 소진 → 429 → `X-Forwarded-For` 스푸핑)를 자동화했다. `pytest tests/unit -q`에는 포함되지 않고 별도로 `pytest tests/integration -q`로 실행한다(§3/§4/§6-1 참조).
4. **`tests/unit/*`, `db/session.py`, `main.py`, `middleware.py`**: 이번 라운드에서 **전혀 손대지 않았다**(오케스트레이터 지시 및 게이트2 "범위 외 변경 없음" 체크리스트 참조) — `git status --short`로 확인.

### 방식 선택 근거 (규칙 A 해당 없음 — 판단 과정 기록)

09단계 §11-5가 제시한 두 방향 중 하나를 선택해야 했다:
- **(a) 배포 설정 레벨**: `--forwarded-allow-ips`를 실제 리버스 프록시 IP로 고정하거나 `--proxy-headers`를 끄는 것. 문제는 이 저장소에 아직 Dockerfile/배포 스크립트 등 배포 아티팩트 자체가 없다(v1 §2, 09단계 §11-3 "주의" 문단이 이미 확인한 사실) — "설정"만으로는 코드 저장소 안에 재현 가능한 방어 경로가 없다.
- **(b) 애플리케이션 코드 레벨**: 신뢰할 수 없는 `X-Forwarded-For`를 무시하고 `request.client.host`만 쓰도록 `rate_limit.py`를 고치는 것. 그러나 **이 방식은 이미 적용되어 있었다** — `rate_limit.py`는 애초에 `X-Forwarded-For`를 전혀 읽지 않는다(09단계 §11-3 TC-SEC-44). 문제는 `request.client.host` **자체가** uvicorn의 `ProxyHeadersMiddleware`에 의해 이미 스푸핑된 값으로 치환된 뒤 우리 코드에 도달한다는 것이다 — 즉 (b)를 문자 그대로 재적용해도 이 결함은 전혀 해소되지 않는다(이미 그 상태였다).

오케스트레이터 지시가 명시한 대로 "단일 인스턴스, 리버스 프록시/배포 아티팩트가 아직 확정되지 않은 현재 프로젝트 상태"를 감안해, **(a)를 인프라 설정 파일이 아니라 이 저장소에 커밋되는 코드(`scripts/run_public_api.py`)로 구현**하는 절충안을 택했다 — 이 스크립트가 uvicorn을 프로그래밍 방식으로(즉 코드로) 기동하면서 `proxy_headers=False`를 기본값으로 강제하므로, "아직 배포 아티팩트가 없다"는 상태에서도 코드 저장소 안에서 즉시 재현 가능한 방어가 성립한다. 10단계에서 실제 리버스 프록시가 확정되면, `PUBLIC_API_TRUSTED_PROXY_IPS` 환경변수 하나만 설정하면 되고 코드 변경은 필요 없다 — 이 저장소가 예정한 배포 토폴로지(리버스 프록시 뒤 uvicorn, HSTS 헤더 설계가 이를 전제, 09단계 §11-3도 지적)와도 자연스럽게 연결된다. 이는 09단계가 "권장"한 (a)+(b) 조합의 취지를 코드 레벨에서 구현한 것이며, 최종 판단 근거는 이 문단에 남긴다.

**`PUBLIC_API_RATE_LIMIT_PER_MINUTE` 환경변수 추가에 대한 판단**: 설계서/오케스트레이터 지시 어디에도 명시되지 않은 추가다. 실제 uvicorn 서브프로세스로 기본 한도(60/분)를 소진하려면 실제 TCP 연결을 60회 이상 빠르게 맺어야 하는데, 로컬 개발 환경(Windows 루프백 소켓)에서 연속 요청 50회 안팎부터 개별 요청이 간헐적으로 지연되는 현상이 관찰되어(코드/로직과 무관한 로컬 네트워크 스택 특성으로 판단, §3 참조) 회귀 테스트가 비현실적으로 느려지거나 불안정해졌다. 프로덕션 기본값(60)은 전혀 바꾸지 않고, 테스트가 필요할 때만 더 낮은 한도로 재정의할 수 있게 한 것이라 rate limiting의 보안 성격 자체에는 영향이 없다고 판단해 범위 외 변경으로 보지 않고 함께 반영했다.

아래 §1~§6은 v7까지 누적 반영된 최신 내용이다.

---

## 1. 구현 범위

### 1-1. 핵심 로직 (`shared/calendar_service/`)
- `types.py`: `Market`(`KRX`\|`NXT`, 거래소 세션 구분 — §3-1-1), `CalendarRow` 값 객체, `CalendarLookup` Protocol(DB 비의존 추상화).
- `last_trading_day.py`: **03-system-design.md §3-3(v4) 실행 가능한 pseudocode를 그대로 구현**한 `get_last_trading_day(market, as_of, calendar)`.
  - 캘린더 행이 없으면(`row is None`) `None` 반환 — "달력상 전날"로 조용히 대체하지 않음(REQ-005 핵심 요구사항, silent fallback 금지).
  - 오늘 제외 판단은 **마감 시각**(`row.session_close_at`) 기준(v4). `_already_closed(candidate, row, as_of)` 헬퍼: 과거 날짜는 무조건 마감 취급, 오늘 날짜만 `as_of.time() >= row.session_close_at`(`>=`로 마감 정각 포함) 비교. 개장 시각 개념은 없음(v3의 `market_open_time` 제거).
  - `row.is_trading_day and _already_closed(...)` **단락 평가 순서 유지** — 휴장일 행은 `session_close_at=None`일 수 있어 순서를 바꾸면 크래시.
  - 휴장일이면 하루씩 역순 탐색(연휴 자동 처리, 하드코딩 없음).
  - **의사코드에 없는 추가 방어 1**: `MAX_LOOKBACK_DAYS=400`을 넘겨 역순 탐색해야 하면 `CalendarScanLimitExceeded` 예외(정상 캘린더에서는 발생하지 않음). "캘린더 데이터가 아예 없음"(None, 424)과 "캘린더 데이터는 있으나 비정상"(예외, 503)을 구분.
  - **의사코드에 없는 추가 방어 2(v2 재작업 신규)**: 거래일 행인데 `session_close_at`이 `None`이면(데이터 무결성 위반) `CalendarDataError`를 던진다. 둘 다 공통 베이스 `CalendarIntegrityError`로 묶어 API 레이어가 한 번에 503으로 매핑할 수 있게 했다.
  - `market_hours.py`는 **삭제**됐다(v4 설계 지시 — §0 재작업 이력 참조).
- `calendar_file.py`: 연간 캘린더 YAML을 파싱해 (연도 × 시장) 전체 날짜의 `CalendarRowInput` 목록을 생성하는 순수 함수(`build_calendar_rows`). DB 접근 없음 — CLI 스크립트와 단위테스트 양쪽에서 재사용. (v4 개정과 무관, 변경 없음)

### 1-2. 데이터 모델 / 마이그레이션
- `shared/db_models/reference.py`: `reference.market_calendar` SQLAlchemy 2.x 모델(§3-2 컬럼 정의 그대로: `trade_date`, `market`, `is_trading_day`, `session_close_at`, `holiday_name`, `source`, `updated_at`, PK는 `(trade_date, market)` 복합키).
- `db/alembic/versions/0001_create_reference_market_calendar.py`: `reference` 스키마 생성 + `market_session` ENUM(`KRX`/`NXT`) 생성 + `market_calendar` 테이블 생성. `downgrade()`도 작성(§7-3 "각 마이그레이션마다 downgrade 경로 작성 의무화" 준수).
  - 로컬 검증(최초 작성 시): PostgreSQL이 설치되어 있지 않아 실제 `alembic upgrade head` 실행은 못 했다. 대신 `alembic upgrade head --sql`(오프라인 SQL 생성 모드)로 문법을 검증했고, 이 과정에서 **ENUM 타입이 두 번 생성되는 버그**(명시적 `.create()` 호출과 `create_table()`의 암묵적 타입 생성이 중복)를 발견해 `postgresql.ENUM(..., create_type=False)`로 컬럼을 선언하도록 수정했다. `alembic downgrade 0001:base --sql`로 롤백 SQL도 확인했다.
- **`db/alembic/versions/0002_grant_reference_privileges.py`(v3 신규 — DEF-003 수정)**: `reference` 스키마 USAGE, `market_calendar` 테이블 권한(`batch_worker`=SELECT/INSERT/UPDATE, `api_service`=SELECT)을 GRANT하는 forward-only 신규 리비전. 기존 0001을 직접 수정하지 않고 새 리비전으로 추가했다(§0-b "범위 결정" 참조 — 이미 적용된 리비전을 사후 수정하면 alembic이 재실행하지 않으므로). `downgrade()`는 역순 REVOKE. 실제 로컬 Docker PostgreSQL로 upgrade/downgrade 양방향 모두 검증 완료(§0-b, §6-1 참조).

### 1-3. CLI 캘린더 갱신 (REQ-012)
- `scripts/load_calendar.py <yaml 경로> [--dry-run]`: 03-system-design.md §3-3 "연 1회 이상 운영자가 CLI로 캘린더 데이터 파일을 DB에 upsert" 요구사항 구현.
  - YAML 파싱(`calendar_file.build_calendar_rows`) → `reference.market_calendar`에 `INSERT ... ON CONFLICT (trade_date, market) DO UPDATE` upsert. **(v3 수정 — DEF-004)** `DO UPDATE`의 `set_`에 `"updated_at": func.now()`를 추가해, 내용이 실제로 바뀔 때 갱신 시각도 함께 최신화되도록 했다(수정 전에는 내용만 갱신되고 `updated_at`은 최초 삽입 시각에 고정됐음 — §0-b 참조).
  - DB 접속은 환경변수 `BATCH_DATABASE_URL`(batch_worker 역할 — reference 스키마 쓰기 권한, §3-1)로만 받는다.
  - **명시적 실패 원칙 적용**: 파일 없음, YAML 형식 오류, 필수 필드 누락, 알 수 없는 market, 대상 연도 밖 날짜, 휴장일/특수개장일 날짜 충돌, DB URL 미설정, DB 반영 실패 — 전부 0이 아닌 종료 코드 + stderr 메시지로 명시적으로 실패한다(조용히 넘어가는 경로 없음).
  - `--dry-run` 플래그로 DB에 쓰지 않고 파싱 요약(시장별 거래일/휴장일 수)만 미리 확인 가능(설계서에 없는 추가 안전장치 — §2 편차 항목 참조).
- `data/calendar/2026.example.yaml`: YAML 형식 예시. **휴장일 목록 자체는 플레이스홀더이며 KRX 공식 발표로 검증되지 않았다**(02-planning.md §8-A6 승계, 실사용 전 재확인 필요).

### 1-4. Public API (REQ-005 관련 엔드포인트)
- `services/public_api/main.py`: FastAPI 앱, 공통 에러 핸들러(`ApiError`, `RequestValidationError` → envelope 형태로 통일). **(v4 신규 — DEF-U09-01 대응)** `CORSMiddleware` 등록(§0-c 참조) — `03-system-design.md` §6-3 "CORS는 자사 프론트엔드 오리진으로만 제한"을 구현. 이 미들웨어는 이 파일에 등록된 전 라우터(`health`/`calendar`/`stocks`/`metrics`/`screen`/`market_summary`)에 공통 적용되므로, REQ-001~005 전체에 걸치는 cross-cutting 수정이다.
- `services/public_api/core/config.py`: **(v4 신규)** `get_cors_allowed_origins()` — CORS 허용 오리진 목록을 환경변수(`PUBLIC_API_CORS_ALLOWED_ORIGINS`)에서 읽고, 미설정 시 로컬 기본값(`http://localhost:3000`)으로 폴백(§0-c 참조).
- `GET /api/v1/health`: §4-2 명세대로 `{status, db}` 반환(DB 연결 실패 시 예외를 삼키지 않고 로깅 후 `db: "degraded"`로 응답).
- `GET /api/v1/calendar/last-trading-day?market=&as_of=`: §4-2 명세 구현.
  - `market`이 `KRX`/`NXT`가 아니면 400 `INVALID_PARAMETER`.
  - `get_last_trading_day()`가 `None`이면 424 `CALENDAR_NOT_CONFIRMED`.
  - `CalendarIntegrityError`(`CalendarScanLimitExceeded`/`CalendarDataError`) 발생 시 503 `SERVICE_UNAVAILABLE`.
  - 성공 시 공통 envelope(§4-1) + `meta.data_freshness`(§3-4 구조) + `data.trade_date` 반환.
- `services/public_api/db/`: `SqlCalendarRepository`(`CalendarLookup` 구현체), SQLAlchemy 세션/엔진 팩토리(`PUBLIC_API_DATABASE_URL` 환경변수, `raw_internal` 자격증명 미주입 — §1-1 3차 방어 원칙 준수). **(v5 신규)** `db/session.py`의 `create_engine()`에 `connect_timeout=3`/`statement_timeout=3000ms` 추가(§0-d, §5-4).
- `services/public_api/schemas/envelope.py`: 공통 응답 envelope(`meta`/`data`/`error`), `DISCLAIMER_TEXT`(REQ-007 문구)를 백엔드 상수 1곳에서 관리(§6-4).
- **(v5 신규)** `services/public_api/rate_limit.py`: `RateLimitMiddleware`(§6-3 IP rate limiting, §0-d 참조).
- **(v5 신규)** `services/public_api/middleware.py`: `SecurityHeadersMiddleware`(§6-3 보안 헤더), `RequestTimeoutMiddleware`(요청 단위 타임아웃), `UnhandledExceptionMiddleware`(catch-all → 503, §0-d 참조).
- **(v5 신규)** `services/public_api/main.py`: `DBAPIError`/`SATimeoutError`(SQLAlchemy) 전용 예외 핸들러 등록 → 503 `SERVICE_UNAVAILABLE` Envelope(§0-d 참조).
- **(v7 신규)** `scripts/run_public_api.py`: 이 서비스의 공식 기동 스크립트(§0-f 참조) — 기본값으로 uvicorn `proxy_headers=False` 강제(DEF-SEC-03 대응).
- **(v7 신규)** `services/public_api/rate_limit.py`: IP 판별 로직 무변경, 신뢰 경계 docstring 보강 + 테스트 전용 `PUBLIC_API_RATE_LIMIT_PER_MINUTE` 환경변수 추가(§0-f 참조).

### 1-5. 프로젝트 스캐폴딩 (그린필드 최소 구성)
- `requirements.txt` / `requirements-dev.txt`: FastAPI, SQLAlchemy, Alembic, Pydantic, psycopg, PyYAML(런타임) / pytest, httpx, ruff(개발).
- `pyproject.toml`: ruff 린트 설정, pytest 설정. **이 프로젝트에 기존 lint/format 설정이 없었으므로 이번 유닛에서 최초로 도입했다.**
- `alembic.ini`, `db/alembic/env.py`, `db/alembic/script.py.mako`: Alembic 골격(§3-5 "3개 스키마를 각각 별도 리비전 네임스페이스로 관리" — 이번 리비전은 `branch_labels=("reference",)`로 표시).
- `.env.example`: `PUBLIC_API_DATABASE_URL`/`ALEMBIC_DATABASE_URL`/`BATCH_DATABASE_URL` 3개 계정을 역할별로 분리해 예시 제공(§1-1 3차 방어 — 서비스마다 다른 DB 자격증명).
- `.gitignore`: `__pycache__`, `.env` 등 기본 항목.
- `tests/unit/`: pytest 36건(최초 21건 → v2 재작업으로 진리표/회귀 테스트 추가, 아래 §4 참조).

---

## 2. 설계서 대비 편차 (사유 포함)

1. **[v2에서 해소됨] `market_open_time(market)` 상수값(KRX 09:00, NXT 08:00)**: (최초 작성 시 서술) v3 §3-3 의사코드의 함수 시그니처를 근거로 개장 시각 상수 모듈을 신설했으나, 그 수치 자체는 설계서에 명시된 근거가 없는 가정값이었다. **v4 재작업으로 이 상수/함수 자체가 로직에서 완전히 제거**되어(§0 재작업 이력), 이 편차 항목은 "확인 필요"에서 "해소됨"으로 종결한다. `market_hours.py` 파일도 삭제했다.
2. **[v2에서 해소됨 — DEF-001] 의사코드 주석과 조건식의 불일치**: (최초 작성 시 서술) v3 §3-3 의사코드 주석은 "오늘 마감 전 데이터는 존재할 수 없으므로 오늘을 제외"라고 설명하면서도 조건식은 개장 시각과 비교하도록 되어 있어, 문자 그대로 구현하면 장중 내내 "당일"을 잘못 반환했다. 6단계가 이를 **DEF-001(High)**로 판정해 FAIL 처리했고, 근본 원인이 설계서 자체에 있어 규칙 F에 따라 `03-system-design.md`가 v4로 재작성됐다(§3-3, 마감 시각 기준 + `_already_closed` 헬퍼 + 13행 진리표, `decisions.md` DEC-018). **이번 재작업(v2)에서 v4 pseudocode를 그대로 구현해 해소했다** — §0 재작업 이력, 아래 §4 AC-1(개정판) 참조. 이 사례는 "리터럴 구현 자체는 잘못이 아니었고, 설계서의 내적 모순이 근본 원인이었다"는 규칙 F의 취지를 그대로 보여준 케이스로 기록해 둔다.
3. **`MAX_LOOKBACK_DAYS=400` 방어적 상한 추가**: v4 의사코드도 "무한 루프 방지 상한 도입은 구현체 재량 사항"이라고 명시적으로 위임하고 있다(§3-3). 정상 캘린더 데이터에서는 도달할 수 없는 상한(최장 연휴도 10일 내외)이라 정상 동작에 영향 없이, 캘린더 데이터 이상(예: 장기간 휴장으로 잘못 적재) 상황에서 무한에 가까운 DB 조회가 발생하는 것만 방지한다. 초과 시 `CalendarScanLimitExceeded` 예외를 던지고, API 레이어는 이를 424(캘린더 미확인)와 구분되는 503(서비스 이상)으로 매핑한다.
4. **[v2 재작업 신규 추가] `CalendarDataError`**: v4 설계서는 "거래일인데 마감 시각이 비어 있는" 데이터 무결성 위반 케이스를 명시적으로 다루지 않는다(정상 데이터라면 발생할 수 없다는 암묵적 전제). 다만 `None`과 시각을 비교하다 알아보기 힘든 `TypeError`로 죽는 것을 막기 위해, 이 케이스를 명시적 예외(`CalendarDataError`, `CalendarIntegrityError` 계열)로 잡아 503으로 응답하도록 방어적으로 추가했다. REQ-005/012가 반복적으로 요구하는 "명시적 실패, silent fallback 금지" 원칙의 연장선이며 설계서와 상충하지 않는다.
5. **`GET /calendar/last-trading-day`의 `meta.data_freshness` 자체 완결적 구성**: §3-4의 `data_freshness` 구조는 원래 `current_published_batch.trade_date`(실제 서빙 데이터 기준일)와 `get_last_trading_day()` 계산 결과를 비교해 `is_latest_trading_day`/`staleness_note`를 채우도록 설계되어 있다. 그러나 `current_published_batch`는 UNIT-02(Derivation Batch) 이후에 생기는 테이블이라 UNIT-01 시점에는 존재하지 않는다. 이 엔드포인트는 "캘린더 계산 자체"가 목적인 디버깅 겸용 공개 API(§4-2)이므로, `data_freshness`를 계산 결과만으로 자체 완결적으로 채웠다(`is_latest_trading_day=true` 고정, `expected_last_trading_day=trade_date`와 동일, `staleness_note=null`). 실제 데이터 서빙 엔드포인트(REQ-002/003/004, UNIT-06~08)는 이 방식이 아니라 `current_published_batch`를 참조하는 정식 로직이 필요하며, 이는 이번 유닛 범위 밖이다. **(참고: 6단계 `unit-01-test.md`는 이 하드코딩 덕분에 DEF-001이 실제 사용자 응답에는 아직 노출되지 않았다고 확인했다 — 그렇다고 DEF-001 자체를 방치해도 된다는 뜻은 아니었고, 이번 v2 재작업으로 원인 자체를 해소했다.)**
6. **CLI YAML 형식은 "휴장일/특수개장일 목록 + 시장별 기본 마감시각"만 기술하고, 전체 365일×시장 데이터는 스크립트가 생성**: 설계서는 YAML 파일의 구체적 스키마를 규정하지 않는다("scripts/load_calendar.py <year>.yaml" 형태로만 서술). 운영자가 매년 730행(365일×2시장)을 전부 나열하는 것은 비현실적이라 판단해, 평일/주말이라는 보편적 규칙은 스크립트 로직에 두고 **연도마다 바뀌는 실제 도메인 데이터(공휴일 목록, 특수개장일)만 YAML에 기술**하도록 설계했다. REQ-012 "하드코딩 금지"의 취지(휴장일 목록을 코드가 아니라 데이터로 관리)는 그대로 유지된다.
7. **DB 역할(batch_worker/api_service) 생성 및 GRANT/REVOKE 스크립트는 이번 유닛에 포함하지 않음**: §1-1 2차 방어(DB 권한 분리)의 핵심은 "`api_service`에 `raw_internal` GRANT 없음"인데, `raw_internal` 스키마 자체가 아직 없다(UNIT-02 이후). `reference` 스키마는 애초에 `batch_worker`/`api_service` 둘 다 읽기 가능하도록 설계되어 있어(§3-1), 이번 유닛만으로는 권한 분리 이슈가 발생하지 않는다. 대신 `.env.example`에 3개 역할의 접속 문자열을 이미 분리해 두어, 이후 실제 역할 생성/권한 부여가 이뤄지면 코드 변경 없이 연결 문자열만 채우면 되도록 준비했다. 실제 `CREATE ROLE`/`GRANT` SQL은 UNIT-02(raw_internal 도입 시점)에서 통합적으로 다루는 것을 권고한다.
8. **[v4 신규] CORS 허용 오리진 설정 방식 — 환경변수 폴백 vs `get_settings()`식 강제 예외 중 폴백을 선택**: `03-system-design.md` §6-3은 "CORS는 자사 프론트엔드 오리진으로만 제한"이라고만 서술하고, 허용 오리진을 하드코딩할지 환경변수로 뺄지, 미설정 시 예외를 던질지 기본값을 둘지는 명시하지 않는다. 기존 `get_settings()`(DB URL)는 미설정 시 `ConfigError`를 던지는 엄격한 패턴이지만, 이번에는 (a) CORS 허용 오리진은 DB 자격증명과 달리 시크릿이 아니고, (b) 오케스트레이터 지시가 "로컬 개발 기본값이 안전하게 동작해야 한다"를 명시적으로 요구했으므로, `get_cors_allowed_origins()`는 미설정 시 예외 대신 로컬 기본값(`http://localhost:3000`)으로 폴백하도록 만들었다(`decisions.md` DEC-022). 이는 기존 `.env.example`의 `GOV_DATA_PORTAL_BASE_URL` 항목("기본값은 코드에 이미 있으며, 필요 시에만 재정의한다")과 동일한 관례를 따른 것이라 설계서와 상충하지 않는다고 판단했다. 프로덕션 배포 시에는 반드시 `PUBLIC_API_CORS_ALLOWED_ORIGINS`를 실제 도메인으로 재정의해야 하며, 이 확인은 12단계 배포 전 체크리스트에 포함되어야 한다(§3 신규 항목 참조).
9. **[v5 신규] `db/session.py`에 `statement_timeout`까지 함께 추가(오케스트레이터 원 지시는 `connect_timeout`만 언급)**: `03-system-design.md` §5-4가 "쿼리 타임아웃 5초"도 Must로 명시하고 있고, 09단계 §4-6이 지목한 근본 문제("스레드가 60~90초씩 점유")는 연결 단계뿐 아니라 연결 이후 쿼리 실행 단계에서도 발생할 수 있다. 같은 파일(`db/session.py`)의 같은 `create_engine()` 호출 안에서 같은 근본 원인을 다루는 추가라 범위를 벗어난 별도 변경으로 보지 않고 함께 반영했다.
10. **[v5 신규] catch-all 예외를 `INTERNAL_ERROR` 같은 새 코드가 아니라 기존 `SERVICE_UNAVAILABLE`로 매핑**: `03-system-design.md` §4-1 에러 코드 표에 "임의의 미처리 예외" 전용 코드가 없다. 오케스트레이터 지시가 "503 SERVICE_UNAVAILABLE로 매핑"을 명시적으로 요구했으므로 그대로 따랐으나, 엄밀히는 DB 인프라 장애가 아닌 프로그래밍 버그까지 "일시적 서비스 장애"라는 문구로 뭉뚱그리는 것이 사용자/운영자에게 완전히 정확한 정보는 아니다. 새 에러 코드(예: `INTERNAL_ERROR`) 신설은 `03-system-design.md` §4-1을 수정하는 설계 변경이라 이번 5단계 재작업 범위를 벗어난다고 판단해 신설하지 않았다 — 후속 설계 개선 과제로 남긴다.
11. **[v5 신규] rate limiting을 `slowapi` 같은 외부 라이브러리가 아니라 직접 구현**: §0-d "게이트 1 적용 방법에 대한 판단 근거"에 상세 근거 기록(요약: 기존 `Envelope` 계약 유지 필요성 + 요구사항 규모(IP+분당 60회, 단일 인스턴스) 대비 직접 구현이 더 단순 + `decisions.md` DEC-005/007의 YAGNI 기조와 일관).
12. **[v7 신규] DEF-SEC-03 대응 방식(배포 설정 vs 코드): 인프라 설정 파일이 아니라 저장소에 커밋되는 기동 스크립트(`scripts/run_public_api.py`)로 구현**: §0-f "방식 선택 근거"에 상세 기록(요약: 아직 배포 아티팩트가 없는 현재 상태에서 코드 레벨로 즉시 재현 가능한 방어가 필요했고, 09단계 §11-5가 권고한 (a)+(b) 조합을 코드로 구현한 것 — 10단계에서 실제 리버스 프록시가 확정되면 환경변수 하나만 설정하면 되도록 설계).
13. **[v7 신규] `PUBLIC_API_RATE_LIMIT_PER_MINUTE` 테스트 전용 환경변수 추가**: 설계서/오케스트레이터 지시에 명시되지 않은 추가. §0-f 마지막 문단에 근거 기록(요약: 실제 uvicorn 서브프로세스로 기본 한도 60회를 빠르게 소진하는 회귀 테스트가 로컬 루프백 소켓 환경 특성상 불안정해져, 테스트 전용으로만 한도를 낮출 수 있게 했다 — 프로덕션 기본값은 60으로 불변).

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터 및 향후 운영자용)

- **[v3에서 해소됨] PostgreSQL 실제 연동 미검증**: 최초 작성 시 로컬에 PostgreSQL이 없어 `--sql` 오프라인 모드로만 검증했었다. **v3 재작업에서 6단계가 준비해 둔 로컬 Docker `stock-screener-db` 컨테이너로 실제 `alembic downgrade base` → `alembic upgrade head`(0001+0002) → 재검증까지 직접 수행해 확인 완료**(§0-b 참조). 다만 이번에 사용한 것은 6단계가 이미 세팅해 둔 로컬 1회성 컨테이너이므로, **CI/스테이징 등 다른 환경에서의 최초 프로비저닝(역할 생성 등)은 별도로 검증이 필요하다**(아래 신규 항목 참조).
- **[v3에서 해소됨] `scripts/load_calendar.py`의 실제 DB upsert 경로**: v3 재작업에서 실제 `BATCH_DATABASE_URL`(batch_worker)로 신규 삽입(730건) + 오염 후 재실행 갱신(TC-069 재현, `updated_at` 포함) 양쪽 다 실제 DB로 확인 완료(§0-b 참조).
- **[v3 신규] `batch_worker`/`api_service` 역할(role) 자체의 프로비저닝은 여전히 코드화되어 있지 않음**: 이번 DEF-003 수정은 "역할이 이미 존재한다"는 전제 하의 GRANT만 코드화했다(§0-b "범위 결정" 참조). 이번에 검증에 사용한 로컬 Docker 컨테이너는 6단계가 이미 두 역할과 비밀번호(`devpass`)를 만들어 둔 상태였다 — **이 역할 생성 자체를 누가/어떻게 프로비저닝하는지(수동 psql, 별도 스크립트, IaC 등)는 아직 어떤 산출물에도 문서화되어 있지 않다.** CI/스테이징/운영 환경을 새로 구축할 때 이 절차가 없으면 `alembic upgrade head` 자체가 "role does not exist"로 실패한다(설계상 의도된 명시적 실패이긴 하지만, 사전에 "무엇을 준비해야 하는지" 안내가 없다는 점은 운영 문서화 공백). UNIT-02 이후 `raw_internal`에 대한 역할 분리까지 다룰 때 이 프로비저닝 절차를 정식으로 문서화/스크립트화할 것을 권고한다.
- **[v3 신규] 실 DB 통합 테스트 자동화 부재**: DEF-003/DEF-004는 로컬 Docker 컨테이너에 대해 수동으로(bash 명령을 직접 실행해) 검증했다. `pytest tests/unit` 스위트는 Fake 기반이라 이런 실제 GRANT/upsert 회귀를 자동으로 잡아내지 못한다(이번에도 6단계의 실제 인프라 검증이 아니었다면 발견되지 못했을 결함이다). 향후 유닛(예: UNIT-02 데이터 파이프라인)에서 `testcontainers` 등으로 실제 Postgres를 띄우는 통합 테스트 계층 도입을 검토 권고 — 이번 유닛 범위에서 즉시 도입하지는 않았다(과설계 방지, 범위 외 변경 최소화 원칙).
- **Public API 실제 기동(uvicorn) 미검증**: `services/public_api/main:app`을 FastAPI `TestClient`로 인프로세스 호출해서만 검증했다(§4 테스트 결과 참조). 실제 `uvicorn services.public_api.main:app` 구동 + `PUBLIC_API_DATABASE_URL`을 통한 실 DB 조회는 여전히 미검증(이번 DEF-003/004 수정 범위 밖). **(v4 부분 해소)** CORS 동작만은 이번에 실제 `uvicorn`으로 서버를 기동해 `curl`로 OPTIONS 프리플라이트 요청(허용 오리진/비허용 오리진 각각)을 보내 실제 HTTP 응답 헤더를 확인했다(§6-1 참조) — 단, 이는 CORS 헤더 자체의 검증이며 DB 조회 경로까지 실 uvicorn으로 검증한 것은 아니다.
- **`data/calendar/2026.example.yaml`의 휴장일 목록**: 예시/플레이스홀더이며 KRX 공식 발표와 대조 검증되지 않았다.
- **[v4 신규] 실제 브라우저(Chrome 등)로 두 오리진 간 fetch를 재현한 것은 아님**: 이번 수정은 (1) `TestClient`(ASGI 인프로세스) 기반 pytest 4건, (2) 실제 `uvicorn` 서버에 대한 `curl` OPTIONS 프리플라이트 수동 확인으로 검증했다. 6단계(`unit-09-test.md`)가 사용했던 것과 같은 헤드리스 Chrome/Puppeteer 기반의 실제 브라우저 크로스오리진 `fetch` 재현은 이번 5단계 범위에서 수행하지 않았다 — 이는 6단계가 UNIT-07/UNIT-09 재검증 시 다시 수행해야 할 항목이다(오케스트레이터가 재호출 예정).
- **[v4 신규] 프로덕션 배포 도메인 확정 전까지 `PUBLIC_API_CORS_ALLOWED_ORIGINS` 미설정 상태로 유지됨**: 호스팅 벤더가 아직 미확정(`03-system-design.md` §2-1)이므로, 실제 배포 시에는 반드시 이 환경변수에 실제 프론트엔드 도메인을 설정해야 한다. 로컬 기본값(`http://localhost:3000`)을 프로덕션에 그대로 방치하면 프로덕션 프론트엔드가 차단된다 — 12단계 배포 체크리스트에 반영 필요.
- **[v2에서 해소됨] `market_open_time` 상수 정확성 / 개장·마감 경계 조건 해석**: v4 재작업으로 `market_open_time` 개념 자체가 제거되고 마감 시각(`session_close_at`, §3-2에 이미 존재하는 데이터) 기준으로 통일되어, 더 이상 "확인 필요" 대상이 아니다. 남은 것은 `session_close_at` 값 자체(KRX 15:30/NXT 20:00)가 실제 KRX 공식 자료와 일치하는지이며, 이는 `scripts/load_calendar.py`로 적재하는 YAML 데이터(`default_close_time`)의 정확성 문제로 위 `2026.example.yaml` 항목과 동일한 성격이다(운영자가 실제 캘린더 데이터를 적재할 때 KRX 공식 발표 기준 마감 시각을 정확히 채워야 함 — §3-3 v4 "캘린더 갱신 절차" 문단 참조).
- **[v2 신규] `CalendarDataError` 경로는 정상 운영에서 발생하지 않아야 함**: `scripts/load_calendar.py`로 적재된 캘린더가 "거래일인데 마감 시각 없음" 상태가 되지 않도록, 운영자가 YAML의 `default_close_time`/`special_trading_days[].close_time`을 빠짐없이 채우는 것이 전제다. 이 경로가 실제로 트리거되면 503 응답과 함께 로그를 남기므로 운영 모니터링(§7-2) 관점에서 5xx 알림에 포함되는지 배포 전 확인 필요.
- **[v5 신규] rate limiter는 단일 프로세스 인메모리 상태 — 멀티 인스턴스/워커로 확장하면 재구현 필요**: `RateLimitMiddleware`의 카운터는 애플리케이션 프로세스 메모리에만 존재한다. `uvicorn --workers N`(N>1)이나 여러 컨테이너 인스턴스로 수평 확장하면 워커/인스턴스마다 카운터가 독립적이라 실질 허용치가 N배로 늘어난다(§5-2 "초기 규모에서는 단일 인스턴스" 전제가 깨지는 시점에 Redis 등 공유 스토어 기반으로 재구현 필요 — `rate_limit.py` 모듈 docstring에도 명시).
- **[v5 신규] rate limiter는 프로세스 재시작 시 카운터가 초기화됨**: 배포/재시작이 잦으면(예: 컨테이너 재기동) 실질적으로 제한이 느슨해질 수 있다 — 단일 인스턴스 MVP 규모에서는 무해하나, 운영 중 재시작 빈도가 늘어나면 재검토 대상.
- **[v5 신규] `RequestTimeoutMiddleware`는 스레드 자체를 강제 종료하지 못함**: §0-d/`middleware.py` docstring에 상세 기록. 클라이언트 체감 응답시간은 보장하지만, 근본적인 스레드풀 슬롯 점유 시간 단축은 여전히 `db/session.py`의 `connect_timeout`/`statement_timeout`에 의존한다 — 이 사실을 오인해 "타임아웃 미들웨어가 있으니 스레드풀 고갈 문제가 완전히 해결됐다"고 판단하지 말 것.
- **[v5 신규] 실제 DB 장애(네트워크 블랙홀 등 TCP RST가 아니라 패킷이 그냥 사라지는 상황)에서 `connect_timeout=3`이 실제로 3초에 끊기는지는 로컬 uvicorn+"connection refused"(즉시 실패) 시나리오로만 확인했고, 진짜 블랙홀 네트워크(예: 방화벽이 SYN을 드롭)로는 재현하지 않음**: §6-1 로컬 검증은 `PUBLIC_API_DATABASE_URL`을 존재하지 않는 로컬 포트로 설정해 즉시 "connection refused"가 나는 경로만 확인했다(0.12초). libpq의 `connect_timeout`이 SYN 자체가 응답 없이 드롭되는 상황(8단계가 원래 60~90초를 실측했던 시나리오와 더 가까움)에서도 정확히 3초에 끊기는지는 이번 재작업에서 실제로 네트워크를 블랙홀 처리해 재현하지 않았다 — `connect_timeout`은 libpq 표준 옵션으로 이런 시나리오를 위해 설계된 것이 맞지만(문서상 보장), 8단계/9단계가 원래 결함을 실측했던 것과 동일한 방식(예: `docker stop` 후 호출)으로의 재검증은 6단계 몫으로 남긴다.
- **[v7 신규] 실제 리버스 프록시를 둔 환경에서의 `PUBLIC_API_TRUSTED_PROXY_IPS` 동작은 이번에 검증하지 않았다**: 이번 재작업은 "리버스 프록시가 아직 없는 현재 상태"(기본값 `proxy_headers=False`)만 실제 uvicorn 프로세스로 검증했다(§6-1 v7 참조). `PUBLIC_API_TRUSTED_PROXY_IPS`를 실제로 설정해 `proxy_headers=True`+`forwarded_allow_ips=<값>`으로 기동했을 때, (a) 지정한 IP에서 온 연결의 `X-Forwarded-For`가 정확히 신뢰되는지, (b) 지정하지 않은 IP에서 온 연결은 여전히 거부/무시되는지는 코드 리뷰(uvicorn 소스 확인, §0-f)로만 근거를 확보했고 실측 재현은 하지 않았다 — **10단계에서 실제 리버스 프록시가 도입되는 시점에 이 환경변수를 설정한 뒤, 09단계가 이번에 쓴 것과 동일한 방식(실제 uvicorn 프로세스 + XFF 스푸핑 시도)으로 반드시 재검증해야 한다.**
- **[v7 신규] `uvicorn services.public_api.main:app`을 실수로 직접 실행하면 이번 수정이 무력화된다**: `scripts/run_public_api.py`가 새로운 공식 기동 방법이지만, 이를 강제하는 장치(예: `main.py` 자체에서 직접 실행을 막는 가드)는 두지 않았다 — 운영자/CI가 실수로 옛 방식(`uvicorn services.public_api.main:app`)으로 기동하면 uvicorn 기본값(`proxy_headers=True`)이 다시 적용되어 DEF-SEC-03이 재발한다. 10단계 배포 아티팩트(Dockerfile/Procfile 등)의 `CMD`/`ENTRYPOINT`가 반드시 `scripts/run_public_api.py`를 가리키도록 확인이 필요하다(배포 전 체크리스트 반영 권고).

---

## 4. 인수 조건 (Acceptance Criteria) — 6단계 테스터용

**AC-1 (핵심 알고리즘, v2 개정 — DEF-001 대응)** `pytest tests/unit/test_last_trading_day.py`가 아래를 포함해 전부 pass:
  - **03-system-design.md §3-3(v4) 13행 경계 시각 진리표를 그대로 재현**(`test_boundary_truth_table` 파라미터화, 행 #1~#11): KRX 마감(15:30) 전(08:59:59~15:29:59)에는 전일, 마감 정각(15:30:00) 이후(마감 정각 포함, `>=`)로는 당일 반환. KRX 시간외단일가 시각(18:00)도 이미 마감 처리된 당일 반환(시간외단일가는 판단 기준 아님). NXT는 동일 패턴을 마감 20:00 기준으로 반복.
  - 휴장일(#12, 주말 등)은 시각과 무관하게 항상 스킵되어 역순 탐색(연휴 자동 처리, 하드코딩 없음)
  - 과거 날짜는 마감 시각과 무관하게 항상 "마감됨"으로 취급(`_already_closed`의 날짜 비교 분기)
  - 휴장일 행(`session_close_at=None` 가능)에서 단락 평가로 인해 크래시가 나지 않음(`row.is_trading_day and _already_closed(...)` 순서 보존)
  - 캘린더 행이 없는 날짜(데이터 공백, #13) → `None` 반환 (조용한 대체 없음)
  - `MAX_LOOKBACK_DAYS` 초과 시 `CalendarScanLimitExceeded` 예외
  - 거래일인데 `session_close_at`이 비어 있으면(데이터 무결성 위반) `CalendarDataError` 예외
  - 알 수 없는 `market` 값 → `ValueError`

**AC-2 (CLI YAML 파싱)** `pytest tests/unit/test_calendar_file.py`가 아래를 포함해 전부 pass:
  - 정상 YAML → 대상 연도 전체 일수만큼 행 생성, 평일=거래일/주말=휴장 기본 규칙 적용
  - 공휴일 지정 시 평일이어도 휴장으로 override
  - 특수개장일 지정 시 주말이어도 거래일로 override
  - 필수 필드 누락, 잘못된 market, 대상 연도 밖 날짜, 휴장일/특수개장일 날짜 충돌 → 전부 `CalendarFileError`로 명시적 실패

**AC-3 (CLI 실행, v3 개정 — DEF-003/DEF-004 대응)**
  - `python scripts/load_calendar.py data/calendar/2026.example.yaml --dry-run` → 종료 코드 0, 시장별 거래일/휴장일 집계 출력, DB 미변경
  - 존재하지 않는 파일 경로 → 종료 코드 1, `[실패]` 메시지
  - `BATCH_DATABASE_URL` 미설정 상태로 `--dry-run` 없이 실행 → 종료 코드 1, 환경변수 안내 메시지
  - **(Postgres 환경, v3에서 실제 검증 완료)** `alembic upgrade head`(0001+0002) 직후 `BATCH_DATABASE_URL`(batch_worker)로 `--dry-run` 없이 실행 → **GRANT가 마이그레이션에 코드화되어 있으므로 별도 수동 조치 없이 정상 성공**(DEF-003 수정 확인, §0-b 참조)
  - **(Postgres 환경, v3에서 실제 검증 완료)** 정상 실행 → `reference.market_calendar`에 upsert 반영 확인, 재실행 시 동일 데이터로 갱신(중복 삽입 오류 없음), **내용이 실제로 바뀐 행을 재실행하면 `updated_at`도 함께 갱신됨**(DEF-004 수정 확인, §0-b 참조 — 수정 전에는 내용만 복구되고 `updated_at`은 고정된 채였음)

**AC-4 (Public API)** `pytest tests/unit/test_public_api.py`가 아래를 포함해 전부 pass:
  - `GET /api/v1/calendar/last-trading-day?market=KRX&as_of=...` 정상 케이스(이미 마감된 시각) → 200, `data.trade_date` 존재, `meta.disclaimer`에 면책 문구 포함, `error`는 `null`
  - 캘린더 데이터 공백 → 424, `error.code == "CALENDAR_NOT_CONFIRMED"`, `data == null`
  - `market`이 `KRX`/`NXT`가 아님 → 400, `error.code == "INVALID_PARAMETER"`
  - `GET /api/v1/health` → 200, `data.status == "ok"`(DB 연결 성공 시 `data.db == "ok"`, 실패 시에도 예외 없이 `"degraded"` — **회귀 테스트 추가(DEF-002)**)
  - `CalendarIntegrityError` 계열(`CalendarScanLimitExceeded`) 발생 시 → 503, `error.code == "SERVICE_UNAVAILABLE"` (**회귀 테스트 추가(DEF-002)**)

**AC-5 (마이그레이션, v3에서 실제 Postgres로 검증 완료)**
  - `ALEMBIC_DATABASE_URL=<DDL 권한 계정> alembic upgrade head` 성공 → `reference` 스키마, `reference.market_session` ENUM(`KRX`/`NXT`), `reference.market_calendar` 테이블(PK `(trade_date, market)`) 생성 확인
  - **(v3 신규)** `alembic upgrade head` 성공 직후, **추가 조치 없이** `\dp reference.market_calendar` 조회 시 `batch_worker=arw`, `api_service=r` 권한이 이미 부여되어 있음(DEF-003 수정 확인)
  - `alembic downgrade base` 성공 → 위 객체 전부 제거 확인(에러 없이 완전 롤백, GRANT도 스키마와 함께 제거됨)
  - **(v3 신규)** `alembic downgrade 0001`(0002만 롤백) → GRANT가 정확히 REVOKE되어 `has_schema_privilege(...)`가 `false`로 바뀜을 확인

**AC-6 (정적 분석)**
  - `python -m ruff check .` 오류 0건
  - `python -m pytest tests/unit -q` **36건**(v2 재작업으로 21건 → 36건 확장) 전부 pass (**참고**: 이후 UNIT-03/06/07/08/09가 각자 테스트를 누적 추가해 v4 시점 기준 총계는 151건이었다 — 아래 AC-7/§6-1 참조. 이 36건은 v2 재작업 시점 스냅샷으로 이력 보존 목적으로 남겨둔다.)

**AC-7 (v4 신규 — DEF-U09-01/CORS 대응)** `pytest tests/unit/test_public_api.py`가 아래를 포함해 전부 pass:
  - 허용 오리진(`http://localhost:3000`)에서 요청 시 응답에 `Access-Control-Allow-Origin: http://localhost:3000` 헤더가 존재
  - 허용되지 않은 오리진(예: `http://evil.example.com`)에서 요청 시 응답에 `Access-Control-Allow-Origin` 헤더가 존재하지 않음
  - `get_cors_allowed_origins()`가 `PUBLIC_API_CORS_ALLOWED_ORIGINS`(쉼표 구분, 공백 트림)를 올바르게 파싱
  - `PUBLIC_API_CORS_ALLOWED_ORIGINS` 미설정 시 기본값 `["http://localhost:3000"]`으로 폴백
  - (수동 확인, §6-1 참조) 실제 `uvicorn` 기동 후 `curl -X OPTIONS`로 허용/비허용 오리진 각각의 실제 HTTP 프리플라이트 응답 헤더 확인

**AC-8 (v5 신규 — DEF-SEC-01/rate limiting 대응)** `pytest tests/unit/test_public_api.py`가 아래를 포함해 전부 pass:
  - 격리된 앱에서 `limit=3`으로 4번째 요청 시 429, `error.code == "RATE_LIMITED"`, `data == null`
  - 실제 `app`(기본값 분당 60회)에서 60번째까지는 200, 61번째는 429
  - 429 응답에도 CORS 헤더(`access-control-allow-origin`)가 정상적으로 포함됨(미들웨어 순서 검증)
  - (수동 확인, §6-1 참조) 실제 `uvicorn` 기동 후 curl로 60회 호출 후 61번째가 429임을 확인

**AC-9 (v5 신규 — DEF-SEC-02/보안 헤더 대응, v6에서 "모든 응답" 조건까지 확정 — DEF-005 수정)** `pytest tests/unit/test_public_api.py`가 아래를 포함해 전부 pass:
  - 정상 200 응답에 `content-security-policy`(`default-src 'none'; frame-ancestors 'none'`), `x-content-type-options`(`nosniff`), `strict-transport-security`(`max-age=63072000; includeSubDomains`) 세 헤더가 모두 존재
  - **(v6 신규 — DEF-005 회귀 테스트)** 429(rate-limited) 응답에도 세 헤더가 모두 존재(`test_rate_limited_response_still_carries_security_headers`)
  - **(v6 신규 — DEF-005 회귀 테스트)** `RequestTimeoutMiddleware`가 만든 타임아웃 503 응답에도 세 헤더가 모두 존재(`test_request_timeout_response_still_carries_security_headers`, 격리된 앱)
  - (수동 확인, §6-1 참조) 실제 `uvicorn` 기동 후 curl로 정상 200 응답과 429 응답 양쪽 모두에서 세 헤더 확인

**AC-10 (v5 신규 — DEF-FS-01/REQ-025 확장판 대응)** `pytest tests/unit/test_public_api.py`가 아래를 포함해 전부 pass:
  - 리포지토리가 `sqlalchemy.exc.OperationalError`를 던지면 → 503, `error.code == "SERVICE_UNAVAILABLE"`, `data == null`(raw 500 아님)
  - 리포지토리가 DB와 무관한 임의의 예외(예: `ValueError`)를 던져도 → 503 Envelope(raw "Internal Server Error" 아님)
  - 존재하지 않는 라우트(`GET /api/v1/does-not-exist`) → 여전히 404(catch-all 핸들러가 FastAPI 기본 404를 가로채지 않음)
  - `RequestTimeoutMiddleware`를 격리된 앱에서 0.05초로 설정하고 0.2초 걸리는 핸들러 호출 시 → 503 `SERVICE_UNAVAILABLE` Envelope
  - `RequestTimeoutMiddleware`가 타임아웃 미만으로 끝나는 정상 요청은 그대로 통과시킴(200)
  - (수동 확인, §6-1 참조) 실제 `uvicorn` + 존재하지 않는 DB URL로 `/api/v1/stocks?query=...` 호출 시 503 Envelope이 0.5초 이내(실측 0.12초)에 반환됨을 확인

**AC-11 (v7 신규 — DEF-SEC-03/rate limiting IP 신뢰 경계 대응)** `pytest tests/integration/test_rate_limit_proxy_trust.py`(실제 uvicorn 서브프로세스 기반, `tests/unit`과 별도 실행)가 아래를 포함해 전부 pass:
  - `scripts/run_public_api.py`(기본값, `PUBLIC_API_TRUSTED_PROXY_IPS` 미설정)로 기동한 실제 uvicorn 프로세스에서, 존재하지 않는 경로로 rate limit 한도를 소진하면 429가 반환됨
  - 한도 소진 후 `X-Forwarded-For` 헤더를 매 요청 다른 값(`9.9.9.9`/`10.0.0.1`/`203.0.113.5`)으로 바꿔 보내도 **여전히 429**(더 이상 200/404로 우회되지 않음)
  - 별도의 새 서버 인스턴스(카운터 초기화 상태)에서는 스푸핑 없는 정상 요청이 한도 내에서 정상 처리됨(429 아님) — 정상 트래픽에 대한 회귀가 없음을 함께 확인
  - (수동 확인, §6-1 참조) 09단계가 실측한 재현 절차(60회 소진 → 61번째 429 확인 → `X-Forwarded-For` 스푸핑)를 `scripts/run_public_api.py`로 기동한 실제 uvicorn(기본 한도 60/분)에서 동일하게 재현해, 스푸핑 시도가 전부 429로 막힘을 확인
  - (부정 대조군, §6-1 참조) `scripts/run_public_api.py`를 의도적으로 DEF-SEC-03 이전 상태(uvicorn `proxy_headers=True`/loopback 신뢰)로 되돌리면 위 회귀 테스트가 실제로 FAIL함을 직접 확인해, 테스트 자체가 이 결함을 실제로 탐지할 수 있음을 검증

---

## 5. 게이트 1 — 정적 분석/린트 결과

- 이 프로젝트는 그린필드라 착수 시점에는 lint/type-check/formatter 설정이 **전혀 없었다**. 이번 유닛에서 `pyproject.toml`에 `ruff` 설정을 최초로 도입했다(있는데 건너뛴 것이 아니라, 없었던 것을 이번에 만들고 바로 적용함).
- `python -m ruff check .` 최초 실행 시 10건 발견(B008 FastAPI 관용구 오탐, UP035/UP007/UP046 문법 스타일, E501 라인 길이 1건) → 전부 수정 또는 (FastAPI 관용구인 B008, pydantic 제네릭 안정성 문제인 UP046) 근거를 명시하고 `pyproject.toml`에서 명시적으로 ignore 처리. 최종 `All checks passed!` 확인.
- v2 재작업(DEF-001 대응) 후 재실행 시 `last_trading_day.py`의 라인 길이 초과 1건(E501) 신규 발견 → 즉시 수정, 최종 `All checks passed!` 재확인.
- v3 재작업(DEF-003/DEF-004 대응, `db/alembic/versions/0002_grant_reference_privileges.py` 신규·`scripts/load_calendar.py` 수정) 후 재실행 → `All checks passed!`(신규 결함 없음).
- **v4 재작업(DEF-U09-01 대응, `services/public_api/main.py`/`core/config.py` 수정, `tests/unit/test_public_api.py` 확장) 후 재실행 → `python -m ruff check .` `All checks passed!`(신규 결함 없음), `python -m pytest tests/unit -q` **155 passed**(v4 재작업 직전 151건 + CORS 회귀 테스트 4건 신규 = 155건).**
- **v5 재작업(DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판 대응, `services/public_api/db/session.py`/`main.py` 수정, `services/public_api/rate_limit.py`·`services/public_api/middleware.py` 신규, `tests/unit/test_public_api.py` 확장) 후 재실행 → `python -m ruff check .` **All checks passed!**(신규 결함 0건, import 정렬 오류 1건은 `--fix`로 즉시 해결), `python -m pytest tests/unit -q` **165 passed**(v5 착수 전 155건 + rate limit/보안헤더/DB예외/catch-all/타임아웃 관련 신규 10건).**
- **v6 재작업(DEF-005 대응, `services/public_api/main.py` 미들웨어 등록 순서만 수정, `tests/unit/test_public_api.py` 확장) 후 재실행 → `python -m ruff check .` **All checks passed!**(신규 결함 0건 — 최초 실행 시 신규 테스트 2건 중 1건에서 E501 라인 길이 초과 1건 발견, 즉시 변수 분리로 수정 후 재확인), `python -m pytest tests/unit -q` **167 passed**(v6 착수 전 165건 + DEF-005 회귀 테스트 2건).**
- **v7 재작업(DEF-SEC-03 대응, `scripts/run_public_api.py` 신규·`services/public_api/rate_limit.py` docstring+환경변수 추가·`tests/integration/test_rate_limit_proxy_trust.py` 신규) 후 재실행 → `python -m ruff check .` **All checks passed!**(신규 결함 0건), `python -m pytest tests/unit -q` **167 passed**(v6과 동일 — 이번 재작업은 `tests/unit`을 확장하지 않음, 회귀 없음), `python -m pytest tests/integration -q` **2 passed**(신규 스위트, `tests/unit`과 별도 실행).**
- 이 저장소에는 프론트엔드(Next.js/TypeScript, `npm run lint`/`tsc`/`next build`)에도 별도 lint/type-check 설정이 있으나, 이번 v5/v6/v7 수정은 프론트엔드 파일을 전혀 변경하지 않았으므로(v7 범위: `scripts/run_public_api.py`/`services/public_api/rate_limit.py`/`tests/integration/*`만) 프론트엔드 게이트는 재실행 대상이 아니다.
- mypy 등 타입체커, black 등 포매터는 아직 도입하지 않았다(범위 외 — 필요 시 후속 유닛에서 검토).

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — §3-3(v4) 알고리즘(마감 시각 기준, `_already_closed`, 단락 평가 순서, 13행 진리표), §3-2 데이터 모델, §4-2 API 명세, §4-1 공통 envelope/에러 코드 체계, §1-1/§3-1(v3 재작업으로 GRANT 코드화)을 그대로 구현. 남은 편차 6건은 위 §2 "설계서 대비 편차"에 사유와 함께 전부 명시(2건은 v2에서 해소됨으로 종결, 1건은 v2 신규 추가, 1건은 v4 신규 추가). DEF-003/004는 설계 위반이 아니라 구현 누락이었으므로 §2 편차 목록에 추가하지 않고 §0-b에 결함 수정 이력으로 기록. **(v4 추가)** §6-3 "CORS는 자사 프론트엔드 오리진으로만 제한"을 `CORSMiddleware`로 그대로 구현. 오리진을 하드코딩할지 환경변수로 뺄지는 설계서가 명시하지 않아 §2 편차 항목8에 판단 근거 기록.
- [x] **에러 처리가 누락된 경로가 없는가(예외를 삼키고 무시하는 코드 없음)** — CLI(YAML/DB 예외를 종료 코드+메시지로 전파), API(`ApiError`/`RequestValidationError`를 공통 핸들러로 처리), `health`(DB 예외를 캐치하되 `logger.exception`으로 남기고 `degraded` 응답 — 무시하지 않음), `get_last_trading_day`(스캔 상한 초과·데이터 무결성 위반을 `CalendarIntegrityError` 계열 예외로 노출, `None`과 시각을 비교하는 암묵적 크래시 없음). **(v3 추가)** 마이그레이션 0002는 역할이 없으면 `role does not exist`로 명시적으로 실패(조용한 스킵 없음). **(v4 추가)** `get_cors_allowed_origins()`는 예외를 삼키는 코드가 아니다 — 애초에 예외를 던질 필요가 없는 값(시크릿이 아닌 CORS 설정)이라 안전한 기본값으로 폴백하는 것이 의도된 동작이며(§2 편차8), DB URL처럼 "없으면 반드시 실패해야 하는" 값과는 성격이 다름.
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — API: `market` 화이트리스트 검증(400), `as_of` 파싱 실패는 FastAPI/Pydantic이 1차 검증 후 커스텀 핸들러가 공통 에러 포맷으로 변환. CLI: YAML 필수 필드/날짜 형식/시장 값/연도 일치/날짜 중복·충돌을 `calendar_file.py`에서 전부 검증. `get_last_trading_day`: 알 수 없는 `market`은 `ValueError`, 거래일인데 마감 시각이 없는 비정상 데이터는 `CalendarDataError`로 검증. (v3 변경 없음 — DEF-003/004는 시스템 경계 검증과 무관한 권한/타임스탬프 이슈) **(v4 추가)** CORS는 브라우저가 강제하는 클라이언트측 정책이라 서버가 "검증"할 사용자 입력값이 아니다 — `CORSMiddleware`가 요청의 `Origin` 헤더를 허용 목록과 대조하는 것 자체가 이 경계의 방어 로직이며, 허용 목록 자체(`PUBLIC_API_CORS_ALLOWED_ORIGINS`)는 운영자가 설정하는 배포 구성값이라 사용자 입력 검증 대상이 아니다.
- [x] **하드코딩된 시크릿/자격증명이 없는가** — DB 접속 정보는 전부 환경변수(`PUBLIC_API_DATABASE_URL`/`ALEMBIC_DATABASE_URL`/`BATCH_DATABASE_URL`)로만 주입. `.env.example`에는 `CHANGE_ME` 플레이스홀더만 존재. **(v3 확인)** 신규 마이그레이션 0002의 GRANT 대상 역할명(`batch_worker`/`api_service`)은 이미 §3-1에 문서화된 역할명을 그대로 참조할 뿐, 비밀번호 등 자격증명을 코드에 넣지 않았다. 로컬 검증 시 사용한 비밀번호(`devpass`)는 6단계가 미리 세팅해 둔 로컬 1회성 Docker 컨테이너의 값이며 코드/설정 파일 어디에도 커밋하지 않았다. **(v4 확인)** `PUBLIC_API_CORS_ALLOWED_ORIGINS` 기본값(`http://localhost:3000`)은 시크릿이 아니라 공개적으로 알려져도 무방한 로컬 개발용 URL이며, `.env.example`에도 값 자체는 주석 처리해 실제 값을 커밋하지 않았다.
- [x] **신규 외부 의존성이 실제로 존재하는 패키지인가** — **(v4)** 이번 수정은 신규 패키지를 추가하지 않았다. `fastapi.middleware.cors.CORSMiddleware`는 이미 설치된 FastAPI(Starlette 내장)에 포함된 기존 모듈이며, `python -c "from fastapi.middleware.cors import CORSMiddleware"`로 임포트 가능함을 직접 확인했다(§6-1 로그 참조). `requirements.txt` 변경 없음.
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — v2 재작업은 DEF-001이 지목한 `last_trading_day.py`/`market_hours.py`와 그 직접 연관 코드만 수정했다. **v3 재작업은 DEF-003(신규 마이그레이션 0002 추가)·DEF-004(`scripts/load_calendar.py`의 `set_` 딕셔너리 한 줄 추가)로 한정**했다. 기존 0001 마이그레이션 파일, `last_trading_day.py`, Public API, 테스트 스위트는 손대지 않았다(6단계가 AC-1~AC-2, AC-4, AC-6은 이미 PASS로 확인했으므로 재작업 대상에서 제외). **v4 재작업은 `services/public_api/main.py`(CORS 미들웨어 추가)·`services/public_api/core/config.py`(`get_cors_allowed_origins()` 추가)·`.env.example`(주석 추가)·`tests/unit/test_public_api.py`(CORS 테스트 4건 추가)로 한정**했다. `raw_models.py`/`compute.py`/`repository.py`/`run_derivation.py`/`public_serving.py` 등 git status에 나타나는 다른 수정분은 이번 v4 작업 이전(UNIT-08 등 선행 작업)에 이미 존재하던 변경이며, 이번 v4 작업에서 손대지 않았음을 `git diff`로 확인했다. **v5 재작업은 `services/public_api/db/session.py`(connect_timeout/statement_timeout 추가)·`services/public_api/main.py`(예외 핸들러 3개 + 미들웨어 등록 4줄 추가)·`services/public_api/rate_limit.py`(신규)·`services/public_api/middleware.py`(신규)·`tests/unit/test_public_api.py`(autouse 리셋 픽스처 + 신규 테스트 10건)로 한정**했다. 라우터 파일(`api/*.py`)·응답 스키마·DB 리포지토리 등 비즈니스 로직 파일은 전혀 건드리지 않았다 — `git status --short` 결과가 위 5개 파일(2개 신규 포함)만 나열됨을 확인했다.

**v5 게이트 2 체크리스트(신규 항목)**:
- [x] **설계서 명세와 구현 일치** — §6-3(rate limiting 예시 60/분, CSP/`X-Content-Type-Options`/HSTS), §5-4(쿼리 타임아웃 5초, 5초 이내 503 반환)를 그대로 구현. 로컬 uvicorn 실측으로 DB 장애 시 0.12초, rate limit 초과 시 즉시 429임을 확인(§6-1 v5 추가 참조).
- [x] **에러 처리 누락 경로 없음** — `UnhandledExceptionMiddleware`가 `logger.exception()`으로 로깅 후 응답을 반환한다(예외를 조용히 삼키지 않음). `RequestTimeoutMiddleware`의 타임아웃도 `logger.warning()`으로 남긴다. `DBAPIError`/`SATimeoutError` 핸들러도 `logger.exception()` 사용.
- [x] **입력값 검증** — rate limit의 "입력"은 요청 빈도 자체이며 IP별 카운터 초과 여부가 검증 로직이다. 보안 헤더/타임아웃은 사용자 입력 검증과 무관한 응답측 조치.
- [x] **하드코딩된 시크릿 없음** — 이번 변경에 시크릿/자격증명이 전혀 포함되지 않는다(rate limit 수치, 헤더 값, 타임아웃 초 수는 전부 공개 가능한 설정값).
- [x] **신규 외부 의존성 검증** — 이번 재작업은 **신규 패키지를 추가하지 않았다**(`requirements.txt` 변경 없음). rate limiting을 직접 구현하기로 결정하기 전 비교 검토했던 `slowapi`는 실제로 `pip index versions slowapi` 조회로 PyPI 실존을 확인했다(0.1.10, 육안+실제 조회 이중 확인 — §0-d 참조)하지만 최종적으로 채택하지 않았으므로 `requirements.txt`에는 반영되지 않는다.
- [x] **범위 외 변경 없음** — 위 항목 참조.

**v6 게이트 2 체크리스트(신규 항목)**:
- [x] **설계서 명세와 구현 일치** — §6-3 "CSP/X-Content-Type-Options/HSTS" Must 요구사항이 이제 정상 응답뿐 아니라 429/타임아웃 503 short-circuit 응답에도 적용됨을 실측 확인(아래 §6-1 v6 추가). `unit-01-test.md` v5 §4-5 TC-090/091가 지목한 두 경로 모두 재현해 해소를 확인했다.
- [x] **에러 처리 누락 경로 없음** — 이번 변경은 `add_middleware` 호출 순서만 바꾼 것이라 에러 처리 로직 자체에 변경이 없다. 기존 `logger.exception`/`logger.warning` 호출은 그대로 유지된다.
- [x] **입력값 검증** — 해당 없음(미들웨어 등록 순서 변경으로 사용자 입력 검증 로직에 변화 없음).
- [x] **하드코딩된 시크릿 없음** — 이번 변경에 시크릿/자격증명이 전혀 포함되지 않는다.
- [x] **신규 외부 의존성 검증** — 이번 재작업은 신규 패키지를 추가하지 않았다(`requirements.txt` 변경 없음, `main.py`의 `add_middleware` 호출 순서와 `tests/unit/test_public_api.py`의 기존 import만 재사용).
- [x] **범위 외 변경 없음** — 변경 파일은 `services/public_api/main.py`(미들웨어 등록 순서 4줄 재배치 + 주석 갱신)와 `tests/unit/test_public_api.py`(신규 테스트 2건 추가)뿐이다. 오케스트레이터가 명시적으로 "건드리지 말라"고 지시한 `rate_limit.py`, `db/session.py`, `main.py`의 `DBAPIError`/`SATimeoutError` 핸들러 로직은 `git diff`로 무변경임을 확인했다.

**v7 게이트 2 체크리스트(신규 항목)**:
- [x] **설계서 명세와 구현 일치** — §6-3 "IP 기준 rate limiting" Must 요구사항이 실제로 IP 스푸핑에 방어되는지까지 확인(설계서는 "IP 기준"이라고만 명시하고 신뢰 경계를 구체화하지 않았으나, "IP 기준"이라는 표현 자체가 스푸핑 불가능한 실제 클라이언트 IP를 전제하므로 이번 수정이 설계 의도와 상충하지 않는다고 판단). 09단계가 실측한 재현 절차를 동일하게 재현해 더 이상 우회되지 않음을 확인(§6-1 v7 참조).
- [x] **에러 처리 누락 경로 없음** — 이번 변경은 기동 옵션/문서화/테스트 전용 환경변수 추가라 런타임 에러 처리 로직 자체에 변경이 없다. `scripts/run_public_api.py`는 `uvicorn.run()`이 던지는 예외를 별도로 삼키지 않는다(발생 시 프로세스가 그대로 비정상 종료 — 명시적 실패, 조용한 무시 아님).
- [x] **입력값 검증** — `PUBLIC_API_TRUSTED_PROXY_IPS`/`PUBLIC_API_RATE_LIMIT_PER_MINUTE`는 운영자가 설정하는 배포 구성값이지 사용자 입력이 아니다(기존 `PUBLIC_API_CORS_ALLOWED_ORIGINS`와 동일한 성격, §2 편차8 참조). `PUBLIC_API_RATE_LIMIT_PER_MINUTE`가 정수로 파싱되지 않는 값이면 `int()`가 즉시 `ValueError`로 실패한다(운영자 설정 오류를 조용히 무시하지 않음 — 배포 구성값이므로 DB URL과 동일하게 "명시적 실패" 원칙 적용).
- [x] **하드코딩된 시크릿 없음** — 이번 변경에 시크릿/자격증명이 전혀 포함되지 않는다(신뢰 IP 목록/포트/rate limit 수치는 전부 공개 가능한 설정값).
- [x] **신규 외부 의존성 검증** — 신규 패키지를 추가하지 않았다(`requirements.txt` 변경 없음). `scripts/run_public_api.py`가 쓰는 `uvicorn`은 이미 `requirements.txt`(`uvicorn[standard]>=0.30`)에 존재하는 기존 의존성이며, `python -c "import uvicorn; print(uvicorn.__version__)"`(0.50.0) + `uvicorn.config.Config.load()` 소스 직접 확인으로 `proxy_headers`/`forwarded_allow_ips` 동작을 실증했다(§6-1 v7 참조). `tests/integration/*`가 쓰는 `httpx`도 이미 `requirements.txt`에 존재.
- [x] **범위 외 변경 없음** — 변경/신규 파일은 `scripts/run_public_api.py`(신규)·`services/public_api/rate_limit.py`(docstring + `DEFAULT_LIMIT` 환경변수 읽기 1줄, IP 판별 로직 자체는 무변경)·`tests/integration/test_rate_limit_proxy_trust.py`(신규)뿐이다. 오케스트레이터가 명시적으로 "건드리지 말라"고 지시한 DEF-SEC-01(rate limiting 로직/60회 한도)·DEF-SEC-02(보안헤더)·DEF-FS-01/REQ-025(DB 타임아웃/전역 예외처리)·`middleware.py`는 `git diff`로 무변경임을 확인했다. `tests/unit/*`도 이번에 손대지 않았다(§6-1 v7 `pytest tests/unit -q` 결과가 v6과 동일한 167건인 것으로 재확인).

---

## 6-1. 로컬 동작 확인 요약 (실행 로그 근거)

- `python -m pytest tests/unit -q` → **36 passed** (v2 재작업, 최초 21건에서 15건 순증 — `test_last_trading_day.py`: 진리표 파라미터화 11건 + 신규 5건(휴장일/캘린더공백/과거일자/단락평가/데이터무결성) 추가, 개장 시각 기준의 구(舊) 테스트 3건 제거 = 순증 13건; `test_public_api.py`: DEF-002 회귀 테스트 2건 추가 = 순증 2건; 합계 +15건)
- `python -m ruff check .` → **All checks passed!**
- `python scripts/load_calendar.py data/calendar/2026.example.yaml --dry-run` → 정상 출력(`총 730건`, KRX/NXT 각 거래일 257일·휴장일 108일), 종료 코드 0
- `python scripts/load_calendar.py data/calendar/nope.yaml --dry-run` → `[실패] 파일을 찾을 수 없습니다`, 종료 코드 1
- `python scripts/load_calendar.py data/calendar/2026.example.yaml`(BATCH_DATABASE_URL 미설정) → `[실패] 환경변수 BATCH_DATABASE_URL이 설정되지 않았습니다`, 종료 코드 1
- `ALEMBIC_DATABASE_URL=postgresql+psycopg://user:pass@localhost/db python -m alembic upgrade head --sql` → 정상 DDL 생성 확인(초기 버전의 ENUM 중복 생성 버그를 이 과정에서 발견·수정)
- `ALEMBIC_DATABASE_URL=... python -m alembic downgrade 0001:base --sql` → 정상 롤백 DDL 생성 확인
- `Session.get(Model, {"col1": ..., "col2": ...})` 복합 PK 조회 패턴을 SQLite 기반 임시 스크립트로 별도 검증(실제 `SqlCalendarRepository.get()` 구현이 사용하는 API가 설치된 SQLAlchemy 2.0.51에서 정상 동작함을 확인)

**v3 추가 — 실제 PostgreSQL(로컬 Docker `stock-screener-db` 컨테이너, 6단계가 세팅해 둔 환경 재사용) 검증**:
- `alembic downgrade base` → `alembic upgrade head`(0001+0002) 재실행 → `\dp reference.market_calendar` 조회 결과 **수동 개입 없이** `batch_worker=arw`, `api_service=r` 확인(DEF-003 해소)
- `BATCH_DATABASE_URL`(batch_worker)로 `python scripts/load_calendar.py data/calendar/2026.example.yaml` → 정상 성공(730건), 종료 코드 0(수정 전이었다면 `permission denied for schema reference`로 실패했을 상황)
- `api_service` 계정으로 직접 `SELECT count(*)` → `730` 성공, `UPDATE` 시도 → `permission denied for table market_calendar`로 거부(§3-1 읽기전용 원칙 확인)
- `2026-01-01`/`KRX` 행을 `migrator`로 오염(`holiday_name='WRONG_TEST_VALUE'`) → `pg_sleep(2)` → `batch_worker`로 재실행 → 내용 복구(`신정`) **및 `updated_at`이 `15:08:56`→`15:09:38`로 실제 갱신**됨을 쿼리로 확인(DEF-004 해소)
- `alembic downgrade 0001`(0002만 롤백) → `has_schema_privilege` 재조회로 GRANT가 정확히 REVOKE됨을 확인 → `alembic upgrade head` + 데이터 재적재로 원복(다음 세션을 위해 정상 상태로 유지)
- `python -m pytest tests/unit -q`(36건)·`python -m ruff check .` 재실행 → 기존과 동일하게 전부 통과(회귀 없음)

**v4 추가 — DEF-U09-01(CORS) 대응 검증(이번 재작업)**:
- `python -m pytest tests/unit -q` → **155 passed**(v4 착수 전 151건 + CORS 회귀 테스트 4건 신규: `test_cors_allows_default_localhost_frontend_origin`, `test_cors_blocks_unlisted_origin`, `test_get_cors_allowed_origins_reads_comma_separated_env_var`, `test_get_cors_allowed_origins_falls_back_to_default_when_unset`)
- `python -m ruff check .` → **All checks passed!**
- `python -c "from fastapi.middleware.cors import CORSMiddleware; print(CORSMiddleware)"` → `<class 'starlette.middleware.cors.CORSMiddleware'>` (신규 패키지 불필요, 기존 설치된 FastAPI/Starlette 내장 모듈임을 확인)
- **실제 `uvicorn` 서버 기동 + `curl` OPTIONS 프리플라이트 수동 확인**(TestClient 인프로세스 호출이 아니라 실제 소켓 기반 HTTP): `PUBLIC_API_DATABASE_URL`에 더미 값(CORS 프리플라이트는 미들웨어 레벨에서 라우트 핸들러 진입 전에 처리되어 DB 접근 없음)을 주고 `uvicorn services.public_api.main:app --port 8099`로 기동한 뒤:
  - `curl -X OPTIONS "http://127.0.0.1:8099/api/v1/stocks?query=samsung&market=ALL" -H "Origin: http://localhost:3000" -H "Access-Control-Request-Method: GET"` → `200 OK`, `access-control-allow-origin: http://localhost:3000` 확인(UNIT-09 `stockSearchApi.ts`가 호출하는 실제 엔드포인트로 확인)
  - `curl -X OPTIONS "http://127.0.0.1:8099/api/v1/screen?market=ALL" -H "Origin: http://evil.example.com" -H "Access-Control-Request-Method: GET"` → `400 Bad Request`, `Disallowed CORS origin`, `access-control-allow-origin` 헤더 없음(UNIT-07 `screenApi.ts`가 호출하는 실제 엔드포인트로 확인)
  - 검증 후 서버 프로세스 종료, 임시로 생성된 더미 DB 파일·로그 삭제, `git status`로 잔여물 없음 재확인(규칙 K 준수)
- 프론트엔드 파일은 이번 v4에서 변경하지 않았으므로 `npm run lint`/`tsc`/`next build` 재실행은 게이트1 대상이 아니다(§5 참조). 다만 UNIT-06/UNIT-08의 서버 컴포넌트 여부는 `git grep '"use client"' frontend/src/app`으로 확인해, `frontend/src/app/stocks/[code]/page.tsx`(UNIT-06)·`frontend/src/app/page.tsx`(UNIT-08)에는 `"use client"`가 없고(서버 컴포넌트, 영향 없음), `frontend/src/app/stocks/page.tsx`(UNIT-09)·`frontend/src/app/screener/page.tsx`(UNIT-07)에는 있음(클라이언트 컴포넌트, 이번 결함에 실제로 노출)을 코드로 직접 확인했다(§0-c 참조).

**v5 추가 — DEF-SEC-01/DEF-SEC-02/DEF-FS-01 확장판 대응 검증(이번 재작업)**:
- `python -m pytest tests/unit -q` → **165 passed**(v5 착수 전 155건 + 신규 10건: rate limit 격리/앱수준/CORS상호작용 3건, 보안헤더 앱수준/격리 2건, DBAPIError/unexpected exception/404 무영향 3건, 요청 타임아웃 2건)
- `python -m ruff check .` → **All checks passed!**(import 순서 오류 1건은 `--fix`로 즉시 정정)
- **실제 `uvicorn` 서버 기동(`--port 8098`) 검증**(존재하지 않는 DB(`PUBLIC_API_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/nonexistent_db_smoke_test`)로 기동):
  - `GET /api/v1/health` → `200`, `{"status":"ok","db":"degraded"}`(DB 연결 실패를 삼키지 않고 명시적으로 반영, 기존 동작 그대로)
  - 정상 오리진(`http://localhost:3000`) 요청 헤더에 `content-security-policy: default-src 'none'; frame-ancestors 'none'`, `x-content-type-options: nosniff`, `strict-transport-security: max-age=63072000; includeSubDomains`, `access-control-allow-origin: http://localhost:3000` 모두 확인
  - 비허용 오리진(`http://evil.example.com`) 요청에도 보안 헤더 3종은 그대로 존재하되 `access-control-allow-origin`은 없음(CORS가 SecurityHeaders보다 바깥이라 항상 적용됨을 실측 확인)
  - `GET /api/v1/stocks?query=samsung`(실제 DB 연결 시도, 존재하지 않는 DB) → `503`, `error.code == "SERVICE_UNAVAILABLE"`, **응답 시간 0.122초**(설계 목표 "5초 이내"를 실측으로 여유 있게 충족 — 단, 이 재현은 "connection refused"(즉시 실패) 시나리오이고, 8/9단계가 원래 실측했던 "TCP 자체가 응답 없음"(블랙홀) 시나리오는 이번에 재현하지 않았다 — §3 신규 항목 참조)
  - 동일 IP로 `/api/v1/health` 60회 호출 후 61번째 호출 → `429`, `error.code == "RATE_LIMITED"`(기본값 분당 60회가 실제 앱에 연결되어 있음을 종단으로 확인)
  - 검증 후 서버 프로세스(`kill`) 종료, 로그 파일(`/tmp/uvicorn_smoke.log`, 프로젝트 디렉터리 밖의 세션 스크래치 영역) 삭제, `git status`로 프로젝트 내부에 잔여물 없음 재확인(규칙 K 준수 — 이번에도 프로젝트 디렉터리 내부에는 어떤 임시 아티팩트도 생성하지 않았다)

**v6 추가 — DEF-005 대응 검증(이번 재작업)**:
- `python -m pytest tests/unit -q` → **167 passed**(v6 착수 전 165건 + DEF-005 회귀 테스트 2건: `test_rate_limited_response_still_carries_security_headers`, `test_request_timeout_response_still_carries_security_headers`)
- `python -m ruff check .` → **All checks passed!**(최초 실행 시 신규 테스트 1건에서 E501 1건 발견, 즉시 수정 후 재확인)
- **실제 `uvicorn` 서버 기동(로컬 포트 8199) + 로컬 Docker `stock-screener-db`(이미 실행 중이던 컨테이너 그대로 재사용, 새로 시작/중지하지 않음) 검증**(`PUBLIC_API_DATABASE_URL=postgresql+psycopg://api_service:devpass@localhost:5432/stock_screener`):
  - `GET /api/v1/health`를 60회 호출 후 61번째 호출 → `429`, 응답 헤더에 `content-security-policy: default-src 'none'; frame-ancestors 'none'`, `x-content-type-options: nosniff`, `strict-transport-security: max-age=63072000; includeSubDomains` **세 헤더 모두 확인**(DEF-005 실제 서버 재현 해소)
  - 카운터 리셋을 위해 서버 프로세스를 재시작한 뒤 `GET /api/v1/health`(정상 200) 재확인 → 세 헤더 그대로 존재(회귀 없음, 정상 경로 계속 정상)
  - 검증 후 `netstat -ano`로 실제 LISTENING PID를 찾아 `taskkill //F //PID <pid>`로 서버 프로세스 종료, `netstat`으로 포트 8199에 잔여 LISTENING 없음 재확인(규칙 K 준수). `docker ps`로 `stock-screener-db`가 검증 전후 동일하게 `Up`(재시작되지 않음) 상태임을 확인
- 타임아웃 503 경로(`RequestTimeoutMiddleware` short-circuit)는 실제 uvicorn으로 4.5초를 기다리는 대신, 위 pytest 신규 테스트(`test_request_timeout_response_still_carries_security_headers`, 격리된 Starlette 앱에서 `timeout_seconds=0.05`로 단축 재현)로 확인했다 — `unit-01-test.md` v5 TC-091과 동일한 재현 방식(완전히 격리된 Starlette 앱, DB/네트워크 무관)이라 별도로 실제 uvicorn 4.5초 대기를 반복할 필요가 없다고 판단했다.
- `DBAPIError` 503 경로(대조군, TC-092)는 이번 변경으로 미들웨어 상대 순서가 바뀌지 않았으므로(여전히 `UnhandledExceptionMiddleware`가 가장 안쪽, `SecurityHeadersMiddleware`가 그보다 바깥) 별도 재현 없이 pytest 스위트(`test_db_operational_error_returns_503_service_unavailable_envelope`, 기존 §4-5 TC-092 근거)의 통과로 회귀 없음을 확인했다.

**v7 추가 — DEF-SEC-03 대응 검증(이번 재작업)**:
- `python -m pytest tests/unit -q` → **167 passed**(v6과 동일, 이번 재작업은 `tests/unit`을 확장하지 않음 — 회귀 없음)
- `python -m pytest tests/integration -q` → **2 passed**(신규 스위트: `test_x_forwarded_for_spoofing_no_longer_bypasses_rate_limit`, `test_normal_client_without_spoofing_is_not_penalized_by_rate_limit_reset`) — 4회 연속 재실행해 매번 안정적으로 통과함을 확인(로컬 루프백 소켓 환경 특성상 간헐적 지연 가능성을 감안해 재현성 확인)
- `python -m ruff check .` → **All checks passed!**
- **uvicorn 소스 직접 확인**(`python -c "..."`로 `uvicorn.config.Config.load()` 조회): `if self.proxy_headers: self.loaded_app = ProxyHeadersMiddleware(...)` — `proxy_headers=False`면 이 래핑 자체가 전혀 적용되지 않아 `request.client`가 항상 실제 TCP peer를 반영함을 소스 레벨로 확정(09단계가 §11-3 TC-SEC-46에서 실측한 것과 동일한 결론을 05단계도 독립적으로 재확인).
- **09단계 재현 절차 동일 재현(실제 uvicorn, 기본 한도 60/분, 로컬 포트 8199)**: `scripts/run_public_api.py`로 기동(옵션 없이 기본값) → 존재하지 않는 경로로 60회 호출(전부 404) → 61번째 `429` 확인 → `X-Forwarded-For: 9.9.9.9`/`10.0.0.1`/`203.0.113.5` 각각으로 62~64번째 호출 → **셋 다 429**(수정 전이었다면 09단계가 실측한 대로 200이었을 상황). 검증 후 `netstat -ano`로 LISTENING PID 확인해 `taskkill //F //PID <pid>`로 종료, 포트 잔여 리스너 없음 재확인(규칙 K).
- **부정 대조군(회귀 테스트의 실효성 검증)**: `scripts/run_public_api.py`를 임시로 `proxy_headers=True`/`forwarded_allow_ips="127.0.0.1"`로 되돌린 뒤 `pytest tests/integration -q`를 재실행 → `test_x_forwarded_for_spoofing_no_longer_bypasses_rate_limit`가 **실제로 FAIL**함을 확인(`AssertionError: ... assert 404 == 429`, 스푸핑이 다시 통함을 테스트가 정확히 탐지) → 즉시 원래 코드로 복구 후 재실행해 다시 2건 pass로 돌아옴을 재확인. 이 절차로 신규 회귀 테스트가 "항상 통과하는 무의미한 테스트"가 아니라 실제로 이 결함을 탐지할 수 있음을 직접 증명했다.
- 검증 과정에서 생성된 모든 서버 프로세스(로컬 실험용 포트 8765~8796, 8199 등)는 각각 `taskkill //F //PID <pid>`로 종료했고, 최종적으로 `netstat -ano`와 `tasklist`로 잔여 LISTENING/python.exe 프로세스가 없음을 재확인했다(규칙 K, 중간에 디버깅 과정에서 일부 프로세스가 즉시 정리되지 않은 적이 있었으나 최종적으로 전부 정리 완료). `git status --short`로 프로젝트 파일 잔여물도 의도한 변경분(신규 2개 파일 + `rate_limit.py` 수정)만 남아 있음을 확인했다(`.harness-tmp/`는 빈 상태 유지).

---

## 7. 다음 단계

이 노트 작성 및 traceability.md 갱신 완료 후, 6단계(단위테스트, `06-unit-tester`)를 UNIT-01 대상으로 **재호출**해야 한다. v2(DEF-001)에 이어 이번 v3(DEF-003/DEF-004)도 6단계가 실제 PostgreSQL로 독립 재검증해야 하며, 특히: (1) 신선한(fresh) DB에서 `alembic upgrade head` 한 번만으로 GRANT가 자동 반영되는지, (2) 역할이 존재하지 않는 상태에서 0002 실행 시 명시적 에러로 실패하는지(조용한 스킵이 아닌지), (3) `updated_at`이 실제 내용 변경 시 매번 갱신되는지를 6단계 스스로 재현해 확인할 것을 권고한다. §3에 새로 추가한 "역할 프로비저닝 문서화 공백"과 "실 DB 통합 테스트 자동화 부재" 항목도 6단계/후속 유닛이 참고해야 한다.

**v4 추가 — 다음 단계**: 이번 v4 재작업은 UNIT-01(`main.py`/`core/config.py`) 자체에 대한 6단계 재검증뿐 아니라, 근본 원인이 여기 있었기 때문에 영향을 받은 **UNIT-07**(`frontend/src/lib/screenApi.ts`, REQ-003)과 **UNIT-09**(`frontend/src/lib/stockSearchApi.ts`, REQ-001)에 대한 6단계의 **실제 두 오리진 브라우저 fetch 회귀 재검증**이 오케스트레이터에 의해 트리거되어야 한다(`unit-09-test.md` §11이 명시적으로 요청한 사항). UNIT-06/UNIT-08은 서버 컴포넌트 렌더링이라 이번 결함의 영향을 받지 않았음을 위 검증으로 확인했으므로 재검증 불필요. 프로덕션 배포 도메인이 확정되면 `PUBLIC_API_CORS_ALLOWED_ORIGINS` 환경변수 설정이 12단계 배포 체크리스트에 반영되어야 한다.

**v5 추가 — 다음 단계 (`decisions.md` DEC-027이 확정한 순서)**: 이 노트와 `traceability.md`(REQ-025 갱신, REQ-026/027 신규 등록) 갱신 완료 후, **6단계(단위테스트, `06-unit-tester`)를 UNIT-01 대상으로 재호출**해야 한다. DEC-027은 "07단계(feature 통합테스트) 4건은 재실행하지 않는다"고 명시적으로 판단했으므로(순수 additive 미들웨어 변경이라 근거), 6단계 통과 후에는 바로 **8단계(전체 풀테스트) 전체 재실행 → 9단계(보안검증) 재검증** 순서로 진행해야 한다(07단계는 건너뛴다). 6단계가 특히 확인해야 할 것:
1. AC-8~AC-10(§4)이 요구하는 신규 테스트 10건을 독립적으로 재현(5단계 자체 보고를 신뢰하지 않고 직접 실행).
2. §3에 남긴 "실제 TCP 블랙홀(패킷 드롭) 시나리오에서 `connect_timeout=3`이 정확히 3초에 끊기는지"는 이번 5단계가 검증하지 못했다 — 6단계가 08단계와 동일한 방식(예: 로컬 Docker DB `docker stop` 후 호출)으로 재현할 것을 권고한다(로컬 "connection refused" 재현은 이미 5단계가 0.12초로 확인했으나, 8/9단계가 원래 실측했던 "60~90초" 문제는 TCP 응답 없음 시나리오였다).
3. rate limiter가 멀티 워커/인스턴스 환경(예: `uvicorn --workers 2`)에서는 카운터가 워커별로 독립적이라는 §3 신규 항목의 한계를 재확인(이번 재작업은 단일 워커로만 검증).
4. `RequestTimeoutMiddleware`의 "스레드 자체는 강제 종료되지 않는다"는 구조적 한계(§3 신규 항목)가 실제 운영에 미치는 영향을 오인하지 않도록, 6단계 테스트 결과서에도 이 한계를 그대로 승계해 기록할 것을 권고한다.

**v6 추가 — 다음 단계 (DEF-005 대응, `decisions.md` DEC-027 순서 준용)**: 이 노트와 `traceability.md` 갱신 완료 후, **6단계(단위테스트, `06-unit-tester`)를 UNIT-01 대상으로 재호출**해야 한다(오케스트레이터 트리거). v5와 동일하게 DEC-027의 5→6→8→9 순서를 유지하며, 07단계(feature 통합테스트)는 이번에도 재실행하지 않는다(미들웨어 등록 순서만 바꾼 additive 변경이라 근거는 v5와 동일). 6단계가 특히 확인해야 할 것:
1. `unit-01-test.md` v5 §4-5 TC-090(429 응답 보안 헤더)·TC-091(타임아웃 503 응답 보안 헤더)과 동일한 시나리오를 독립적으로 재현해 DEF-005가 실제로 해소됐는지 확인(5단계 자체 보고를 신뢰의 근거로 삼지 않는다).
2. DEF-SEC-01(rate limiting)/DEF-FS-01(REQ-025, DB 타임아웃/전역 예외 처리)에 회귀가 없는지 — 이번 v6은 미들웨어 "순서"만 바꿨을 뿐 `rate_limit.py`/`db/session.py`/DBAPIError·SATimeoutError 핸들러 코드는 전혀 손대지 않았으므로, TC-087/088(rate limiting)·TC-093~096(TCP 블랙홀)이 v5와 동일하게 통과하는지 재확인 권고.
3. CORS 헤더가 이번 변경 이후에도 429/타임아웃 503을 포함한 모든 에러 응답에 여전히 일관되게 붙는지(`test_rate_limited_response_still_carries_cors_header` 등 기존 회귀 테스트가 167건 스위트에 여전히 포함돼 있음을 확인).
4. `pytest tests/unit -q`가 **167 passed**로 나오는지(v6 착수 전 165건에서 DEF-005 회귀 테스트 2건 순증).

**v7 추가 — 다음 단계 (DEF-SEC-03 대응, `decisions.md` DEC-027 재검증 사이클 3차 라운드)**: 이 노트와 `traceability.md` 갱신 완료 후, **6단계(단위테스트, `06-unit-tester`)를 UNIT-01 대상으로 재호출**해야 한다(오케스트레이터 트리거). 이번에도 DEC-027의 5→6→8→9 순서를 유지한다. 6단계가 특히 확인해야 할 것:
1. `09-security-audit.md` §11-3 TC-SEC-45~47과 동일한 시나리오(실제 uvicorn 프로세스, 60회 소진 → 61번째 429 → `X-Forwarded-For` 스푸핑)를 독립적으로 재현해 DEF-SEC-03이 실제로 해소됐는지 확인(5단계 자체 보고를 신뢰의 근거로 삼지 않는다) — `scripts/run_public_api.py`를 6단계 자신의 독립 포트로 직접 기동해 재현할 것.
2. `tests/integration/test_rate_limit_proxy_trust.py`를 6단계 자신의 세션에서 재실행하고, §0-f "부정 대조군" 절차(임시로 옛 방식으로 되돌려 테스트가 실제로 FAIL하는지)도 6단계가 독립적으로 재현해 이 회귀 테스트의 실효성을 스스로 확인할 것을 권고한다.
3. DEF-SEC-01(rate limiting 로직/60회 한도)·DEF-SEC-02(보안헤더)·DEF-FS-01(REQ-025, DB 타임아웃/전역 예외 처리)에 회귀가 없는지 — 이번 v7은 `rate_limit.py`의 IP 판별 로직·`db/session.py`·`main.py`의 예외 핸들러·`middleware.py`를 전혀 손대지 않았으므로, 기존 회귀 테스트(TC-087/088/090/091/093~096 계열)가 v6과 동일하게 통과하는지 재확인 권고.
4. `PUBLIC_API_TRUSTED_PROXY_IPS`를 설정했을 때(향후 리버스 프록시 도입 시나리오 시뮬레이션) 프록시 헤더 신뢰가 opt-in으로 정확히 동작하는지는 이번 5단계 범위에서 검증하지 않았다(§3 "v7 신규" 항목 참조) — 6단계가 여력이 되면 추가로 확인하거나, 10단계 실제 배포 시점으로 이관할 수 있다(오케스트레이터 판단).
5. `pytest tests/unit -q`가 **167 passed**(v6과 동일, 회귀 없음)로, `pytest tests/integration -q`가 신규로 **2 passed**로 나오는지.
6. 9단계 §11-5가 "REQ-028(신규) 등록을 오케스트레이터에 권고"했으나, 이번 v7 재작업은 기존 REQ-026(IP rate limiting)의 잔여 신뢰 경계 결함으로 판단해 REQ-026 행만 갱신했다(REQ-ID 신규 등록은 2단계/오케스트레이터 소관이라 05단계가 임의로 추가하지 않음, §2 원칙 참조) — REQ-028 신규 등록 여부는 오케스트레이터가 최종 판단할 사항으로 남긴다.
