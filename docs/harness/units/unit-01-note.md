# UNIT-01 구현 노트 — 휴장일/영업일 캘린더 서비스

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-14 (최초), 2026-09-14 재작업(v2 — DEF-001 대응), 2026-09-15 재작업(v3 — DEF-003/DEF-004 대응)
- 포함 REQ: REQ-005(직전 거래일 산정), REQ-012(휴장일/특수개장일 캘린더 관리, 하드코딩 금지)
- 입력(최초): `docs/harness/03-system-design.md`(v3, PASS) §3-3/§3-4/§1-3, `docs/harness/04-ux-design.md`(v3, PASS), `docs/harness/02-planning.md`(v3) §9 UNIT-01
- 입력(v2 재작업): `docs/harness/03-system-design.md`(**v4**, PASS, §3-3 재작성) — 6단계(`unit-01-test.md`)가 발견한 DEF-001(High) 대응, `decisions.md` DEC-018
- 입력(v3 재작업): `docs/harness/units/unit-01-test.md`(**v3**) — 6단계가 실제 PostgreSQL(Docker `stock-screener-db`)로 검증하며 발견한 **DEF-003(Medium)**/**DEF-004(Low)** 대응. 설계 결함이 아니라 구현 누락(코드화 누락)이므로 3단계 재작업 없이 5단계가 직접 수정.
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
- `services/public_api/main.py`: FastAPI 앱, 공통 에러 핸들러(`ApiError`, `RequestValidationError` → envelope 형태로 통일).
- `GET /api/v1/health`: §4-2 명세대로 `{status, db}` 반환(DB 연결 실패 시 예외를 삼키지 않고 로깅 후 `db: "degraded"`로 응답).
- `GET /api/v1/calendar/last-trading-day?market=&as_of=`: §4-2 명세 구현.
  - `market`이 `KRX`/`NXT`가 아니면 400 `INVALID_PARAMETER`.
  - `get_last_trading_day()`가 `None`이면 424 `CALENDAR_NOT_CONFIRMED`.
  - `CalendarIntegrityError`(`CalendarScanLimitExceeded`/`CalendarDataError`) 발생 시 503 `SERVICE_UNAVAILABLE`.
  - 성공 시 공통 envelope(§4-1) + `meta.data_freshness`(§3-4 구조) + `data.trade_date` 반환.
- `services/public_api/db/`: `SqlCalendarRepository`(`CalendarLookup` 구현체), SQLAlchemy 세션/엔진 팩토리(`PUBLIC_API_DATABASE_URL` 환경변수, `raw_internal` 자격증명 미주입 — §1-1 3차 방어 원칙 준수).
- `services/public_api/schemas/envelope.py`: 공통 응답 envelope(`meta`/`data`/`error`), `DISCLAIMER_TEXT`(REQ-007 문구)를 백엔드 상수 1곳에서 관리(§6-4).

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

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터 및 향후 운영자용)

- **[v3에서 해소됨] PostgreSQL 실제 연동 미검증**: 최초 작성 시 로컬에 PostgreSQL이 없어 `--sql` 오프라인 모드로만 검증했었다. **v3 재작업에서 6단계가 준비해 둔 로컬 Docker `stock-screener-db` 컨테이너로 실제 `alembic downgrade base` → `alembic upgrade head`(0001+0002) → 재검증까지 직접 수행해 확인 완료**(§0-b 참조). 다만 이번에 사용한 것은 6단계가 이미 세팅해 둔 로컬 1회성 컨테이너이므로, **CI/스테이징 등 다른 환경에서의 최초 프로비저닝(역할 생성 등)은 별도로 검증이 필요하다**(아래 신규 항목 참조).
- **[v3에서 해소됨] `scripts/load_calendar.py`의 실제 DB upsert 경로**: v3 재작업에서 실제 `BATCH_DATABASE_URL`(batch_worker)로 신규 삽입(730건) + 오염 후 재실행 갱신(TC-069 재현, `updated_at` 포함) 양쪽 다 실제 DB로 확인 완료(§0-b 참조).
- **[v3 신규] `batch_worker`/`api_service` 역할(role) 자체의 프로비저닝은 여전히 코드화되어 있지 않음**: 이번 DEF-003 수정은 "역할이 이미 존재한다"는 전제 하의 GRANT만 코드화했다(§0-b "범위 결정" 참조). 이번에 검증에 사용한 로컬 Docker 컨테이너는 6단계가 이미 두 역할과 비밀번호(`devpass`)를 만들어 둔 상태였다 — **이 역할 생성 자체를 누가/어떻게 프로비저닝하는지(수동 psql, 별도 스크립트, IaC 등)는 아직 어떤 산출물에도 문서화되어 있지 않다.** CI/스테이징/운영 환경을 새로 구축할 때 이 절차가 없으면 `alembic upgrade head` 자체가 "role does not exist"로 실패한다(설계상 의도된 명시적 실패이긴 하지만, 사전에 "무엇을 준비해야 하는지" 안내가 없다는 점은 운영 문서화 공백). UNIT-02 이후 `raw_internal`에 대한 역할 분리까지 다룰 때 이 프로비저닝 절차를 정식으로 문서화/스크립트화할 것을 권고한다.
- **[v3 신규] 실 DB 통합 테스트 자동화 부재**: DEF-003/DEF-004는 로컬 Docker 컨테이너에 대해 수동으로(bash 명령을 직접 실행해) 검증했다. `pytest tests/unit` 스위트는 Fake 기반이라 이런 실제 GRANT/upsert 회귀를 자동으로 잡아내지 못한다(이번에도 6단계의 실제 인프라 검증이 아니었다면 발견되지 못했을 결함이다). 향후 유닛(예: UNIT-02 데이터 파이프라인)에서 `testcontainers` 등으로 실제 Postgres를 띄우는 통합 테스트 계층 도입을 검토 권고 — 이번 유닛 범위에서 즉시 도입하지는 않았다(과설계 방지, 범위 외 변경 최소화 원칙).
- **Public API 실제 기동(uvicorn) 미검증**: `services/public_api/main:app`을 FastAPI `TestClient`로 인프로세스 호출해서만 검증했다(§4 테스트 결과 참조). 실제 `uvicorn services.public_api.main:app` 구동 + `PUBLIC_API_DATABASE_URL`을 통한 실 DB 조회는 여전히 미검증(이번 DEF-003/004 수정 범위 밖).
- **`data/calendar/2026.example.yaml`의 휴장일 목록**: 예시/플레이스홀더이며 KRX 공식 발표와 대조 검증되지 않았다.
- **[v2에서 해소됨] `market_open_time` 상수 정확성 / 개장·마감 경계 조건 해석**: v4 재작업으로 `market_open_time` 개념 자체가 제거되고 마감 시각(`session_close_at`, §3-2에 이미 존재하는 데이터) 기준으로 통일되어, 더 이상 "확인 필요" 대상이 아니다. 남은 것은 `session_close_at` 값 자체(KRX 15:30/NXT 20:00)가 실제 KRX 공식 자료와 일치하는지이며, 이는 `scripts/load_calendar.py`로 적재하는 YAML 데이터(`default_close_time`)의 정확성 문제로 위 `2026.example.yaml` 항목과 동일한 성격이다(운영자가 실제 캘린더 데이터를 적재할 때 KRX 공식 발표 기준 마감 시각을 정확히 채워야 함 — §3-3 v4 "캘린더 갱신 절차" 문단 참조).
- **[v2 신규] `CalendarDataError` 경로는 정상 운영에서 발생하지 않아야 함**: `scripts/load_calendar.py`로 적재된 캘린더가 "거래일인데 마감 시각 없음" 상태가 되지 않도록, 운영자가 YAML의 `default_close_time`/`special_trading_days[].close_time`을 빠짐없이 채우는 것이 전제다. 이 경로가 실제로 트리거되면 503 응답과 함께 로그를 남기므로 운영 모니터링(§7-2) 관점에서 5xx 알림에 포함되는지 배포 전 확인 필요.

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
  - `python -m pytest tests/unit -q` **36건**(v2 재작업으로 21건 → 36건 확장) 전부 pass

---

## 5. 게이트 1 — 정적 분석/린트 결과

- 이 프로젝트는 그린필드라 착수 시점에는 lint/type-check/formatter 설정이 **전혀 없었다**. 이번 유닛에서 `pyproject.toml`에 `ruff` 설정을 최초로 도입했다(있는데 건너뛴 것이 아니라, 없었던 것을 이번에 만들고 바로 적용함).
- `python -m ruff check .` 최초 실행 시 10건 발견(B008 FastAPI 관용구 오탐, UP035/UP007/UP046 문법 스타일, E501 라인 길이 1건) → 전부 수정 또는 (FastAPI 관용구인 B008, pydantic 제네릭 안정성 문제인 UP046) 근거를 명시하고 `pyproject.toml`에서 명시적으로 ignore 처리. 최종 `All checks passed!` 확인.
- v2 재작업(DEF-001 대응) 후 재실행 시 `last_trading_day.py`의 라인 길이 초과 1건(E501) 신규 발견 → 즉시 수정, 최종 `All checks passed!` 재확인.
- v3 재작업(DEF-003/DEF-004 대응, `db/alembic/versions/0002_grant_reference_privileges.py` 신규·`scripts/load_calendar.py` 수정) 후 재실행 → `All checks passed!`(신규 결함 없음).
- mypy 등 타입체커, black 등 포매터는 아직 도입하지 않았다(범위 외 — 필요 시 후속 유닛에서 검토).

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — §3-3(v4) 알고리즘(마감 시각 기준, `_already_closed`, 단락 평가 순서, 13행 진리표), §3-2 데이터 모델, §4-2 API 명세, §4-1 공통 envelope/에러 코드 체계, §1-1/§3-1(v3 재작업으로 GRANT 코드화)을 그대로 구현. 남은 편차 5건은 위 §2 "설계서 대비 편차"에 사유와 함께 전부 명시(2건은 v2에서 해소됨으로 종결, 1건은 v2 신규 추가). DEF-003/004는 설계 위반이 아니라 구현 누락이었으므로 §2 편차 목록에 추가하지 않고 §0-b에 결함 수정 이력으로 기록.
- [x] **에러 처리가 누락된 경로가 없는가(예외를 삼키고 무시하는 코드 없음)** — CLI(YAML/DB 예외를 종료 코드+메시지로 전파), API(`ApiError`/`RequestValidationError`를 공통 핸들러로 처리), `health`(DB 예외를 캐치하되 `logger.exception`으로 남기고 `degraded` 응답 — 무시하지 않음), `get_last_trading_day`(스캔 상한 초과·데이터 무결성 위반을 `CalendarIntegrityError` 계열 예외로 노출, `None`과 시각을 비교하는 암묵적 크래시 없음). **(v3 추가)** 마이그레이션 0002는 역할이 없으면 `role does not exist`로 명시적으로 실패(조용한 스킵 없음).
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — API: `market` 화이트리스트 검증(400), `as_of` 파싱 실패는 FastAPI/Pydantic이 1차 검증 후 커스텀 핸들러가 공통 에러 포맷으로 변환. CLI: YAML 필수 필드/날짜 형식/시장 값/연도 일치/날짜 중복·충돌을 `calendar_file.py`에서 전부 검증. `get_last_trading_day`: 알 수 없는 `market`은 `ValueError`, 거래일인데 마감 시각이 없는 비정상 데이터는 `CalendarDataError`로 검증. (v3 변경 없음 — DEF-003/004는 시스템 경계 검증과 무관한 권한/타임스탬프 이슈)
- [x] **하드코딩된 시크릿/자격증명이 없는가** — DB 접속 정보는 전부 환경변수(`PUBLIC_API_DATABASE_URL`/`ALEMBIC_DATABASE_URL`/`BATCH_DATABASE_URL`)로만 주입. `.env.example`에는 `CHANGE_ME` 플레이스홀더만 존재. **(v3 확인)** 신규 마이그레이션 0002의 GRANT 대상 역할명(`batch_worker`/`api_service`)은 이미 §3-1에 문서화된 역할명을 그대로 참조할 뿐, 비밀번호 등 자격증명을 코드에 넣지 않았다. 로컬 검증 시 사용한 비밀번호(`devpass`)는 6단계가 미리 세팅해 둔 로컬 1회성 Docker 컨테이너의 값이며 코드/설정 파일 어디에도 커밋하지 않았다.
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — v2 재작업은 DEF-001이 지목한 `last_trading_day.py`/`market_hours.py`와 그 직접 연관 코드만 수정했다. **v3 재작업은 DEF-003(신규 마이그레이션 0002 추가)·DEF-004(`scripts/load_calendar.py`의 `set_` 딕셔너리 한 줄 추가)로 한정**했다. 기존 0001 마이그레이션 파일, `last_trading_day.py`, Public API, 테스트 스위트는 손대지 않았다(6단계가 AC-1~AC-2, AC-4, AC-6은 이미 PASS로 확인했으므로 재작업 대상에서 제외).

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

---

## 7. 다음 단계

이 노트 작성 및 traceability.md 갱신 완료 후, 6단계(단위테스트, `06-unit-tester`)를 UNIT-01 대상으로 **재호출**해야 한다. v2(DEF-001)에 이어 이번 v3(DEF-003/DEF-004)도 6단계가 실제 PostgreSQL로 독립 재검증해야 하며, 특히: (1) 신선한(fresh) DB에서 `alembic upgrade head` 한 번만으로 GRANT가 자동 반영되는지, (2) 역할이 존재하지 않는 상태에서 0002 실행 시 명시적 에러로 실패하는지(조용한 스킵이 아닌지), (3) `updated_at`이 실제 내용 변경 시 매번 갱신되는지를 6단계 스스로 재현해 확인할 것을 권고한다. §3에 새로 추가한 "역할 프로비저닝 문서화 공백"과 "실 DB 통합 테스트 자동화 부재" 항목도 6단계/후속 유닛이 참고해야 한다.
