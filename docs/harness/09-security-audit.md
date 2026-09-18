# 테스트 결과서 (Test Result Report) — 09단계 보안검증 (Security Audit)

> `templates/test-report-template.md` 사용. 대상: **개발된 시스템 전체 코드베이스**(services/public_api, services/derivation_batch, services/ingestion_batch, shared, frontend, db/alembic) + `docs/harness/03-system-design.md`(v4) 보안 설계 원칙. 입력: 8단계 `docs/harness/08-full-system-test.md`(**CONDITIONAL PASS**, Critical 0건/High 1건 — DEF-FS-01/REQ-025, 10단계 전 게이트로 이미 등록됨).
>
> **Tier=High**(`decisions.md` DEC-021) — 규칙 I(자본시장법 인접 규제 도메인) 대상. 완화 조항 전혀 적용하지 않고 규칙 B(최소 2회 독립 검증) 원문 그대로 적용한다.

## 1. 개요
- 테스트 대상: 전체 코드베이스(Public API 4개 데이터 엔드포인트, Ingestion/Derivation 배치, 프론트엔드 4개 화면, DB 마이그레이션/GRANT, 의존성 매니페스트) + `03-system-design.md` §6 보안 설계 원칙
- 테스트 유형: 보안(09단계, Security Audit)
- 적용 Tier: **High**(`decisions.md` DEC-021) — 완화 없음
- 테스트 목적:
  1. 인증/인가 우회·권한 경계(수평/수직 권한 상승) 가능성 점검
  2. 인젝션(SQL/커맨드/XSS)·입력 검증 누락 점검, 특히 DEF-006(LIKE 와일드카드)의 보안 관점 재평가
  3. 시크릿/자격증명 하드코딩·로그 노출 점검(코드 전체 + `git log` 이력)
  4. 의존성 취약점(CVE) 스캔(Python/프론트엔드) 및 **의존성 환각(hallucinated dependency)** 점검
  5. 민감정보 저장/전송 암호화 여부, 에러 메시지를 통한 정보 노출 점검(특히 DEF-FS-01 500 에러 재현)
  6. 설계서(§6 보안 설계 원칙)와 실제 구현의 불일치 점검
  7. 개인정보 처리 컴플라이언스, 오픈소스 라이선스 검토, 외부 데이터/API 이용약관 준수(원본 시세 재게시 금지) 최종 종합 확인
  8. 규제 민감 도메인 대응(규칙 I, REQ-005~010) 반영 여부 최종 확인, 규칙 J(AI/LLM) 비해당 재확인
  9. **DEF-FS-01(REQ-025)을 자원고갈/DoS 인접 관점에서 추가 점검**(오케스트레이터 위임 사항 — 재발견/재등록이 아니라 "이 응답 지연이 실제 DoS로 악용 가능한가"라는 신규 질문에 답한다)
- 관련 산출물: `docs/harness/03-system-design.md`(v4) §6·§7-4, `docs/harness/02-planning.md`(v5) §6·§7, `docs/harness/decisions.md`(DEC-004/006/021/022/024/026), `docs/harness/traceability.md`(REQ-005~010, REQ-022, REQ-024, REQ-025), `docs/harness/08-full-system-test.md`(CONDITIONAL PASS), 각 unit/feature 테스트 문서(DEF-006/008/009/010 등)
- 테스트 수행자(에이전트): 09-security-auditor
- 테스트 일시: 2026-09-18

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - `services/public_api/*`(main.py, core/config.py, db/session.py, api/*, db/*repository*.py, schemas/*, errors.py) 전체 코드 리뷰
  - `services/ingestion_batch/*`, `services/derivation_batch/*`의 시크릿 처리·로그 노출·외부 API 호출 패턴
  - `shared/db_models/public_serving.py`, `db/alembic/versions/*` — 3중 방어(스키마/DB권한/프로세스 분리) 최종 확인
  - `frontend/src/*`(layout.tsx, DisclaimerBanner, copy.ko.json, lint-forbidden-copy.mjs, DataFreshnessBadge 사용처, next.config.mjs) — 규제 대응·출력 이스케이프 확인
  - `requirements.txt`/`requirements-dev.txt`/`pyproject.toml`, `frontend/package.json` 의존성 전수 + 실제 `pip-audit`/`npm audit` 실행(네트워크 가능 확인 후 실시)
  - `.env.example`, 코드 전체, `git log`(전체 이력) 시크릿 하드코딩/노출 스캔
  - DEF-FS-01(REQ-025)의 자원고갈/DoS 인접 관점 재분석(코드 레벨 재현 포함, 실제 DB/서비스 대상 공격 미실행 — TestClient 기반 격리 재현)
  - 6~8단계가 남긴 Low/Open 결함(DEF-006 등)의 보안 관점 재평가
- 제외 범위 및 사유:
  - 각 feature 내부 비즈니스 로직 정확성(필터/정렬/페이지네이션 SQL 정확성 자체, percentile 계산식 등) — 06/07단계가 이미 실 PostgreSQL로 광범위 검증. 이 문서는 그 로직이 아니라 **보안 경계**(권한/인젝션/노출)만 재확인한다.
  - 실제 프로덕션 호스팅 환경(벤더 미확정, §2-1)에서의 TLS/방화벽/WAF 설정 — 코드 저장소에 해당 아티팩트(Dockerfile/nginx/docker-compose)가 아직 존재하지 않음(확인함, 아래 §4-6 참조). 10단계 배포테스트 영역으로 이관.
  - 실제 침투테스트(라이브 서비스/제3자 대상 실공격) — 규칙(정적분석/코드리뷰/로컬 재현 범위 내 검증)에 따라 실행하지 않음. 모든 재현은 로컬 `TestClient`/격리된 프로세스로만 수행.
  - REQ-022(KRX 공식 확인/법률 자문), REQ-024(실 서비스키 파이프라인 실행) — 코드 보안 결함이 아닌 배포 전 별도 게이트. 상태 불변만 재확인.
  - DEF-IT-M01(Medium/Deferred) — 이미 10단계 전 게이트로 확정, 09단계가 재조사하지 않음.

## 3. 테스트 환경
- 실행 환경: Windows 10(Git Bash), Python 3.13(anaconda), Node.js 24 / npm 11(frontend `node_modules` 기존 설치 재사용, 신규 설치 없음), 실제 DB 미기동(이번 09단계는 라이브 PostgreSQL/uvicorn 프로세스를 기동하지 않고, 정적 코드 리뷰 + `pip-audit`/`npm audit`(레지스트리 조회) + 격리된 `fastapi.testclient.TestClient` 기반 재현만 사용 — 실제 서비스/DB에 부하나 변경을 가하지 않기 위함).
- 테스트 데이터: 없음(DB 미접속). 재현이 필요한 케이스는 `Fake`/`Exploding` 리포지토리로 의존성 오버라이드해 애플리케이션 계층만 격리 검증.
- 전제 조건: `docs/harness/08-full-system-test.md` CONDITIONAL PASS 확인 완료. 세션 시작 시 `.harness-tmp/` 빈 상태 확인(강제 중단 이력 없음). 재현 스크립트는 규칙 K 취지에 따라 프로젝트에 흔적을 남기지 않도록 세션 격리 스크래치패드(`C:\Users\mega\AppData\Local\Temp\claude\...\scratchpad\`)에서만 생성·실행했다(§7 Teardown 참조 — 이번 09단계는 실 DB/venv 등 `.harness-tmp/` 대상 아티팩트를 전혀 만들지 않았다).

## 4. 테스트 케이스 및 결과

### 4-1. 인증/인가 우회, 권한 경계(수평/수직 권한 상승)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-SEC-01 | 인증/세션/쿠키 관련 코드가 어디에도 남아있지 않은가(REQ-009/016 설계 의도와 실제 코드 일치 확인) | 없음 | `services/`, `frontend/src/`, `shared/` 전체를 `jwt\|session_id\|set-cookie\|authorization\|login\|password_hash\|bcrypt\|passlib\|oauth` 정규식(대소문자 무시)으로 재스캔 | 매치 0건 | 매치 0건 (node_modules 제외 전체 재스캔) | **PASS** | UNIT-04가 블랙박스(TestClient 헤더/쿠키 동일성)로 이미 검증한 것을 09단계는 화이트박스(소스 전체 재스캔)로 교차 확인 |
| TC-SEC-02 | 4개 데이터 API 전부가 `GET`만 노출하는가(설계 §4-1 "모든 엔드포인트는 GET" 강제 확인) | 없음 | `services/public_api/` 전체에서 `@router.post\|put\|delete\|patch` 검색 | 매치 0건 | 매치 0건 | **PASS** | 쓰기 경로 자체가 존재하지 않아 수직 권한 상승(쓰기 권한 탈취) 표면이 원천 부재 |
| TC-SEC-03 | 사용자 식별 파라미터(`user_id`/`holding_price`/`quantity` 등)가 API 계약에 실수로 추가되지 않았는가 | 없음 | `services/public_api/api/*.py`, `schemas/*.py`의 모든 `Query(...)` 파라미터와 응답 필드 전수 열거 | 개인 식별/개인화 파라미터 0건 | `stocks`: `query`,`market` / `metrics`: `date` / `screen`: `market`,`market_cap_*`,`volume_min`,`return_pct_*`,`per_max`,`pbr_max`,`sort_by`,`sort_dir`,`page`,`page_size` / `market-summary`: `date`,`market` — 전부 종목/시장/지표 파라미터, 사용자 식별 파라미터 없음 | **PASS** | REQ-009 아키텍처적 구현(§6-1) 실제 코드 일치 |
| TC-SEC-04 | DB 계정 권한 분리(3중 방어 1·2차)가 실제 마이그레이션 코드에 존재하는가 | 없음 | `db/alembic/versions/0002_grant_reference_privileges.py` 등 GRANT 관련 마이그레이션 확인, `shared/db_models/public_serving.py` 전체 모델에 `open/high/low/close/volume` 원문 컬럼이 없는지 확인 | `public_serving` 모델에 원본 시세 컬럼 없음, GRANT가 코드화되어 있음 | `StockMaster`/`DerivedMetricsDaily`/`MarketSummaryDaily`/`BatchRun`/`CurrentPublishedBatch` 전 모델에 OHLCV 원문 컬럼 없음(코드 확인). GRANT는 0002/0005/0006/0009 등 마이그레이션에 이미 코드화(UNIT-01~08이 실 Postgres로 반복 재검증 완료 — 승계, 09단계 재실행은 안 했으나 코드 존재 자체는 재확인) | **PASS** | 3중 방어 중 1차(스키마 분리)를 09단계가 최종 코드 레벨로 재확인. 2차(DB 권한)는 코드 존재만 재확인(실 DB 재실행은 06~08단계가 이미 반복 검증해 반복하지 않음, §2 제외범위) |
| TC-SEC-05 | 권한 상승으로 이어질 수 있는 관리자/운영 전용 엔드포인트가 공개 API에 실수로 노출되지 않았는가 | 없음 | `services/public_api/api/*.py` 라우터 6개(health/calendar/stocks/metrics/screen/market_summary) 전수 목록화, 캘린더 갱신(`scripts/load_calendar.py`)이 API로 노출되는지 확인 | 캘린더 갱신 등 운영 기능은 API에 없고 CLI 전용 | 확인됨 — `scripts/load_calendar.py`는 CLI 스크립트이며 `services/public_api`에 대응 라우터 없음 | **PASS** | 설계 §7-3/§8-1 "관리자 UI 없음" 원칙과 일치 |

**종합**: 인증 없음(REQ-009/016)이라는 설계 의도가 코드 전체에 예외 없이 일관되게 구현되어 있고, 특정 엔드포인트에만 인증/세션 코드가 남아있는 경우는 발견되지 않았다. 수직 권한 상승(쓰기 경로) 표면 자체가 없다.

### 4-2. 인젝션(SQL/커맨드/XSS), 입력 검증 누락

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-SEC-06 | 4개 데이터 API 전체가 문자열 결합/포맷 SQL을 쓰지 않고 ORM 파라미터 바인딩만 쓰는가 | 없음 | `services/public_api/db/*repository*.py` 4개 파일 전체 리뷰 + `services/`, `shared/` 전체에서 `execute(`/`text(`/f-string/`%`/`.format(` 패턴 교차 검색 | SQL 문자열 결합 0건, `text()` 사용은 `SELECT 1`(리터럴, 헬스체크) 1건뿐 | `stock_repository.py`/`screen_repository.py`/`metrics_repository.py`/`market_summary_repository.py` 전부 SQLAlchemy `select()`/`Session.get()` ORM 바인딩만 사용. `text("SELECT 1")`(`health.py`)은 사용자 입력이 전혀 개입하지 않는 리터럴 헬스체크 쿼리. f-string은 전부 에러 메시지 구성용(사용자 입력이 값으로만 삽입되고 SQL/쉘 컨텍스트로 실행되지 않음) | **PASS** | SQL 인젝션 표면 없음(ORM 바인딩 강제, 설계 §6-3과 일치) |
| TC-SEC-07 | 커맨드 인젝션(사용자 입력이 셸 명령으로 전달되는 경로)이 있는가 | 없음 | `services/`, `frontend/`(scripts 포함) 전체에서 `subprocess`/`os.system`/`exec(`/`eval(`/`child_process` 검색 | 매치 0건(또는 사용자 입력 미개입) | 매치 0건 | **PASS** | 커맨드 인젝션 표면 없음 |
| TC-SEC-08 | 프론트엔드에 출력 기반 XSS 표면(비이스케이프 렌더링)이 있는가 | 없음 | `frontend/src/` 전체에서 `dangerouslySetInnerHTML`/`innerHTML`/`document.write`/`eval(` 검색 | 매치 0건 | 매치 0건 | **PASS** | React JSX 기본 이스케이프에 의존, 사용자 검색어(`SearchInput`)·조건값(`ConditionFilterPanel`) 등 사용자 입력이 그대로 HTML로 삽입되는 경로 없음 |
| TC-SEC-09 | **DEF-006(LIKE 와일드카드 미이스케이프) 보안 관점 재평가** — `GET /stocks?query=`에 `%`/`_` 입력 시 정보노출/DoS 여부 | 없음 | `stock_repository.py` L48 `pattern = f"%{query}%"` 코드 리뷰 + 영향 분석: (a) 반환 데이터 성격, (b) 결과 상한, (c) 쿼리 비용 | 정보노출 없음(공개 비민감 데이터), DoS 유발 안 됨(상한 있음) | (a) 반환 필드는 `stock_code`/`name`/`market`뿐 — 이미 `query=""`나 `query="a"`로도 얻을 수 있는 완전 공개·비민감 정보(상장 종목명/코드)이므로 `%`/`_` 입력이 새로운 정보를 노출시키지 않음. (b) `MAX_SEARCH_RESULTS=100`(코드 내부 상수)로 응답 크기가 항상 상한선 이하. (c) 대상 테이블(`stock_master`)이 실 서비스 규모에서도 ~2,500행 수준(설계 §5-1)이라 인덱스 없는 ILIKE 전체 스캔도 비용이 낮음(20~30ms 수준, 07/08단계 실측 P95 응답시간과 일치) | **PASS(결함 아님, DEF-006 Low 유지 — 근거 갱신)** | DEF-006은 SQL 인젝션이 아니며(파라미터 바인딩 유지), 정보노출·DoS 어느 관점으로도 실질적 위험이 확인되지 않아 기존 Low/Open 판정을 그대로 유지한다. 다만 방어적 코딩 관점에서 `%`/`_`를 이스케이프하는 것을 권고(§8 참조, 배포 차단 아님) |
| TC-SEC-10 | 범위/타입 검증 우회 시 어떤 응답이 나오는가(입력 검증 경계) | 없음 | `screen.py`의 `market_cap_min/max`, `page`, `page_size` 등 Query 파라미터 제약 리뷰: `page`에 상한이 없음(`ge=1`만 존재)을 확인 | 상한 없어도 실서비스 규모(~2,500행)에서 과도한 비용 유발 안 함 | `page`에 `le=` 상한이 없어 임의로 큰 `page` 값을 보낼 수 있으나, PostgreSQL의 `OFFSET`은 실제 테이블 크기(수천 행)를 넘어서면 스캔이 곧바로 종료되므로 이 데이터 규모에서 유의미한 자원 소모로 이어지지 않음(설계 §5-1 인덱스 근거와 일치) | **PASS(경미한 개선 권고)** | Critical/High 아님 — 방어적 코딩 관점에서 `page`에도 합리적 상한(`le=100000` 등)을 추가할 것을 권고(§8, Low) |
| TC-SEC-11 | 예외적 수치 입력(예: PostgreSQL bigint 범위를 초과하는 `market_cap_max`)이 인젝션이 아닌 안정성 문제로 이어지는가 | 없음 | `market_cap_max`에 `int` 타입 파라미터를 `9` 반복 30자리 등 bigint 범위 초과값으로 바인딩 시도(코드 리뷰 + `_apply_filters`가 값을 그대로 바인딩함을 확인) | ORM이 파라미터 바인딩 시 타입 오류를 던지고, 이는 §4-3에서 재현하는 "핸들러 없는 예외 → raw 500" 패턴과 동일 경로로 귀결됨 | 코드 확인 결과 사전 범위 검증이 없어 DB 드라이버 레벨에서 `DataError`/`OverflowError`가 발생할 수 있고, `main.py`에 이를 잡는 범용 핸들러가 없어 §4-3 TC-SEC-13과 동일하게 raw 500으로 귀결됨(인젝션 아님, 가용성 이슈로 §4-3에서 통합 다룸) | **PASS(별도 인젝션 아님, §4-3과 통합 처리)** | 신규 결함으로 별도 등록하지 않고 §4-3(에러 처리) 결함의 근거 확장으로 다룬다 |

**종합**: SQL/커맨드/XSS 인젝션 표면이 코드 전체에서 발견되지 않았다. DEF-006은 보안 관점(정보노출/DoS)에서 재평가한 결과 Low 유지가 타당하다.

### 4-3. 시크릿/자격증명 하드코딩 또는 로그 노출

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-SEC-12 | `.env.example`에 실제 자격증명이 남아있지 않은가 | 없음 | `.env.example` 전문 확인 | 전부 `CHANGE_ME` 플레이스홀더 | `PUBLIC_API_DATABASE_URL`/`ALEMBIC_DATABASE_URL`/`BATCH_DATABASE_URL`/`GOV_DATA_PORTAL_SERVICE_KEY` 전부 `CHANGE_ME`, CORS 오리진은 주석 처리된 예시값(비밀 아님) | **PASS** | |
| TC-SEC-13 | 코드 전체에 하드코딩된 패스워드/API 키/토큰 패턴이 있는가 | 없음 | `(password\|secret\|api_key\|service_key\|token)\s*[:=]\s*['"][A-Za-z0-9+/_-]{12,}['"]` 정규식으로 전체 소스(`.py`/`.ts`/`.tsx`/`.json`/`.md`) 스캔, `CHANGE_ME`/example/placeholder 제외 | 매치 0건 | 매치 0건 | **PASS** | |
| TC-SEC-14 | `git log` 이력에 실제 `.env`나 시크릿 파일이 커밋된 적이 있는가 | 없음 | `git log --all --name-only`으로 전체 커밋에서 `.env`(`.example` 제외)/credential/`.pem`/`.key` 파일명 검색 | 매치 0건(`.env.example`만 존재) | `.env.example`만 이력에 존재, 실 `.env`/비밀키 파일 커밋 이력 없음. `.gitignore`에 `.env`/`frontend/.env.local` 등록 확인 | **PASS** | |
| TC-SEC-15 | 배치 서비스가 DB 접속 실패/예외 시 로그에 자격증명(비밀번호 포함 URL)을 그대로 출력하는가 | 없음 | `run_ingestion.py`/`run_derivation.py`의 진단 출력(`print`) 확인 | 자격증명 마스킹 | `print("  BATCH_DATABASE_URL: 설정됨")`처럼 값 대신 "설정됨" 문자열만 출력, `GOV_DATA_PORTAL_SERVICE_KEY`도 동일 패턴("설정됨"/"미설정") | **PASS** | 로그 통한 자격증명 노출 없음 |
| TC-SEC-16 | Public API가 SQLAlchemy 엔진 생성 시 `echo=True` 등으로 쿼리(바인딩 파라미터 포함)를 로그에 남기지 않는가 | 없음 | `services/public_api/db/session.py`의 `create_engine()` 호출 인자 확인 | `echo` 미설정(기본 False) | `create_engine(settings.database_url, pool_pre_ping=True)` — `echo` 인자 없음(기본값 False) | **PASS** | |

**종합**: 시크릿 하드코딩·로그 노출 결함 0건. `.env` 관리 체계(placeholder만 커밋, 실제 값은 gitignore)가 일관되게 지켜지고 있다.

### 4-4. 의존성 취약점(CVE) 스캔 및 의존성 환각(hallucinated dependency) 점검

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-SEC-17 | Python 의존성(`requirements.txt`) CVE 스캔 | `pip-audit` 설치됨, 네트워크 가능 | `python -m pip_audit -r requirements.txt` 실행 | 알려진 취약점 0건 또는 발견 시 목록화 | `No known vulnerabilities found` | **PASS** | 실제 PyPI 취약점 DB 조회(네트워크 접속 확인 후 실시, 오프라인 대체 없음) |
| TC-SEC-18 | 프론트엔드 의존성(`package.json`) CVE 스캔 | `node_modules` 기존 설치 존재 | `npm audit`(devDependencies 포함) + `npm audit --omit=dev`(프로덕션만) 각각 실행 | 취약점 0건 또는 목록화 | 둘 다 `found 0 vulnerabilities` | **PASS** | |
| TC-SEC-19 | **의존성 환각 점검**: `requirements.txt`/`requirements-dev.txt`/`pyproject.toml`/`package.json`의 모든 패키지명이 실제 공식 레지스트리(PyPI/npm)에 존재하는 정상 패키지인지, 흔한 오타/유사 패키지(타이포스쿼팅)는 아닌지 확인 | 없음 | 전체 패키지 목록화 후 (a) `pip-audit`/`npm audit`이 각 패키지를 레지스트리에서 실제로 조회·해석했는지(= 존재하지 않는 패키지면 두 도구 모두 오류를 낸다) 확인, (b) 패키지명 육안 검토(일반적으로 잘 알려진 이름과 일치하는지, 미묘한 철자 변형이 있는지) | 전 패키지가 정상 레지스트리 조회 성공, 타이포스쿼팅 의심 이름 없음 | **Python**: `fastapi`,`uvicorn[standard]`,`sqlalchemy`,`alembic`,`pydantic`,`psycopg[binary]`,`pyyaml`,`httpx`,`pytest`,`ruff` — 전부 `pip-audit`이 정상 조회(오류 없음), 전부 널리 알려진 정식 패키지명과 정확히 일치(예: `psycopg`를 `pyscopg`/`psycopg2-binary` 등으로 오기하지 않음). **프론트엔드**: `next`,`react`,`react-dom`,`@types/node`,`@types/react`,`@types/react-dom`,`eslint`,`eslint-config-next`,`typescript` — 전부 `npm audit`이 정상 조회, 전부 실제 설치되어 08단계에서 `npm run build`/`next start`로 실제 구동이 검증된 패키지(즉 레지스트리에 실존하며 실제로 동작함이 이미 실측됨). 타이포스쿼팅 의심 이름·비정상적으로 빈약한 최근 등록 패키지 0건 | **PASS** | |
| TC-SEC-20 | **검증 전용 도구(puppeteer-core/playwright/lighthouse 등)가 프로덕션 의존성에 잔존하지 않는가** | 없음 | `requirements.txt`/`requirements-dev.txt`/`frontend/package.json`(dependencies+devDependencies) 전체를 `puppeteer\|playwright\|lighthouse` 정규식으로 검색 | 매치 0건 | 매치 0건 — 8단계 결과서(§7 Teardown)가 명시한 대로 `puppeteer-core@23`/`lighthouse@11`은 `.harness-tmp/08-full-system-test/`에만 설치됐고 테스트 종료 후 삭제되어 프로덕션 매니페스트에 흔적이 없음. `.harness-tmp/`도 현재 빈 상태로 재확인 | **PASS** | |
| TC-SEC-21 | 오픈소스 라이선스 검토(상용/배포 목적과 충돌하는 강한 카피레프트 여부) | 없음 | 설치된 패키지 메타데이터(`importlib.metadata`)로 라이선스 확인 + 공지된 라이선스 지식과 대조 | 강한 카피레프트(GPL/AGPL) 없음 | FastAPI/SQLAlchemy/Alembic/Pydantic/httpx/PyYAML/pytest/ruff = MIT/BSD 계열(permissive), Next.js/React/TypeScript/ESLint = MIT, PostgreSQL = PostgreSQL License(permissive). **`psycopg`(psycopg3)는 LGPL-3.0** — 약한 카피레프트이나, 이 서비스는 SaaS로 호스팅되고(라이브러리 자체를 수정해 재배포하지 않음) psycopg 코드 자체를 수정하지 않으므로 LGPL의 소스공개 의무가 트리거되지 않음. 강한 카피레프트(GPL/AGPL) 의존성 없음 | **PASS(정보성 권고 포함)** | psycopg의 LGPL 성격은 차단 사유가 아니나, 향후 이 소프트웨어를 온프레미스로 "배포"(SaaS가 아닌 설치형 판매 등)하는 방향으로 사업 모델이 바뀔 경우 재검토가 필요함을 §8에 기록 |

**종합**: CVE 스캔 결과 Python/프론트엔드 양쪽 모두 알려진 취약점 0건(실제 레지스트리 조회 기반). 의존성 환각(존재하지 않는 패키지명을 지어내는 slopsquatting 공급망 리스크) 징후 없음 — 모든 패키지가 실제 레지스트리에 존재하고, 실제로 설치·구동되어 이전 단계에서 실측 검증됨. 검증 전용 도구가 프로덕션 매니페스트에 잔존하지 않음. 라이선스 충돌 없음(psycopg LGPL은 SaaS 운영 방식에서 비차단).

### 4-5. 민감정보 저장/전송 암호화, 에러 메시지를 통한 정보 노출 (DEF-FS-01 재현 포함)

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-SEC-22 | 개인정보/인증정보를 다루지 않는다는 설계 전제(REQ-016 Out-of-Scope)가 실제로 지켜지는가 | 없음 | 전 스키마(`shared/db_models/public_serving.py`, `raw_internal`/`reference` 모델 포함)에서 이름/전화번호/이메일/주민번호/계좌/보유종목/매수단가 등 PII 컬럼 검색 | PII 컬럼 0건 | 전 스키마에 종목/시세/캘린더/배치이력 관련 컬럼만 존재, 사용자 개인정보 컬럼 0건 | **PASS** | |
| TC-SEC-23 | DB 연결 문자열/자격증명이 API 응답 본문에 노출되는가(에러 메시지 정보 노출) | 없음(TestClient 격리 재현) | `get_settings()`가 `ConfigError`를 던지는 경로(환경변수 미설정)와, `OperationalError` 발생 경로 각각의 응답 본문에 연결 문자열/비밀번호가 포함되는지 코드 추적 | 미포함 | `ConfigError` 메시지는 `PUBLIC_API_DATABASE_URL이 설정되지 않았습니다` 등 정적 안내 문구뿐(실제 값 미포함) — 단, 이 예외 자체는 앱 부팅 시점(엔진 lazy 생성이지만 `lru_cache`로 최초 요청 시 1회 시도)에만 발생하며 요청 처리 중 발생 시 처리되지 않은 예외로 §4-3 TC-SEC-24와 동일 경로(raw 500, 본문에 스택트레이스/연결정보 미노출)로 귀결됨을 확인 | **PASS** | |
| TC-SEC-24 | **DEF-FS-01 재현(로컬, 실 DB 대상 아님)**: DB 연결 실패 시 실제 HTTP 응답이 무엇을 노출하는가 | `TestClient(app, raise_server_exceptions=False)`, `get_stock_search_repository`를 `OperationalError`를 던지는 `ExplodingRepository`로 오버라이드(실 DB/실 서비스 미사용, 순수 애플리케이션 계층 재현) | `GET /api/v1/stocks?query=삼성` 호출 | 500, 스택트레이스/DB 연결정보 미노출, 그러나 Envelope 형식이 아님(설계 위반은 08이 이미 발견) | `status_code=500`, `content-type: text/plain`, `body: "Internal Server Error"` — **스택트레이스나 DB 접속 문자열 등 민감정보는 노출되지 않는다**(FastAPI가 `debug=False` 기본값으로 동작, 앱 어디에도 `debug=True` 설정 없음을 코드로 확인). 다만 여전히 `error.code`/`meta` 없는 raw 텍스트 응답으로, 설계(§4-1) Envelope 계약을 위반한다(08단계 DEF-FS-01과 동일 패턴 — 09단계 신규 재현) | **PASS(정보노출 없음) / 기존 결함 DEF-FS-01(REQ-025) 유지 확인(재등록 아님)** | 정보노출 관점은 안전하나, API 계약 위반(Envelope 미준수)은 여전히 Open. 상세는 §6 결함 목록, §4-6 DoS 분석 참조 |
| TC-SEC-25 | main.py의 예외 핸들러가 DB 연결 실패에 국한되지 않고 **모든 미처리 예외에 범용적으로 적용되지 않는 구조**인지 일반화 확인 | 위와 동일 재현 스크립트 | `ExplodingRepository`가 `OperationalError`(연결 실패를 모사) 대신 임의의 `ValueError`를 던지도록 변형해도 동일 결과가 나오는지 코드 경로 추적(실행은 1건만 수행, 나머지는 `main.py`의 핸들러 등록 목록으로 정적 확인) | `ApiError`/`RequestValidationError` 외 모든 예외가 동일하게 raw 500으로 귀결 | `main.py`에는 `@app.exception_handler(ApiError)`와 `@app.exception_handler(RequestValidationError)` 단 2개만 등록되어 있어(코드 확인), `OperationalError`뿐 아니라 리포지토리/스키마 계층에서 발생 가능한 **어떤 미처리 예외든** 동일하게 Envelope 없는 raw 500으로 응답한다는 사실을 확인 | **PASS(구조 확인) — REQ-025 범위가 "DB 연결 장애"보다 넓은 "전역 예외 처리 부재"임을 09단계가 추가로 확정** | 이는 새 결함이 아니라 DEF-FS-01/REQ-025의 근본 원인 설명을 보강하는 것 — 수정 시 `OperationalError`/`DBAPIError`뿐 아니라 catch-all(`Exception`) 핸들러까지 함께 고려할 것을 §6/§8에 권고 |
| TC-SEC-26 | 응답 헤더에 설계(§6-3)가 요구하는 보안 헤더(CSP/`X-Content-Type-Options`/HSTS)가 실제로 적용되는가 | 없음 | `services/public_api/main.py` 전체(미들웨어 목록)와 `frontend/next.config.mjs` 전체 확인 | 세 헤더 모두 설정되어 있어야 함(Must, §6-3) | **미구현 확인** — `main.py`에는 `CORSMiddleware`만 등록되어 있고 CSP/`X-Content-Type-Options`/HSTS를 추가하는 미들웨어나 커스텀 헤더 로직이 없음. `frontend/next.config.mjs`에도 `headers()` 설정이나 보안 헤더 관련 코드가 전혀 없음(현재 `reactStrictMode: true`만 존재). 인프라 레벨(nginx/Docker) 설정도 저장소에 아직 존재하지 않음(`Dockerfile`/`docker-compose.yml`/`nginx.conf` 검색 결과 0건 — 호스팅 벤더 미확정 §2-1과 일치) | **FAIL → 신규 결함 등록(§6 DEF-SEC-02)** | `unit-09-test.md`가 이미 "9단계에서 종합 재확인 필요"로 명시적으로 인계한 항목(§4-6 CORS 절 참고) — 09단계가 실제로 확인해 미구현임을 확정 |
| TC-SEC-27 | 설계(§6-3)가 요구하는 IP 기준 rate limiting(스크레이핑/대량 재배포 방지 목적, 429 `RATE_LIMITED`)이 실제로 구현되어 있는가 | 없음 | `services/`, 저장소 전체에서 `rate.?limit`/`slowapi`/`Limiter`/`429`/`RATE_LIMITED` 검색, 인프라 설정 파일 존재 여부 확인 | 구현되어 있어야 함(Must, §6-3, §4-1 에러표에 429 코드가 이미 예약됨) | **미구현 확인** — 코드베이스 전체에 rate limiting 관련 미들웨어/라이브러리(`slowapi` 등) 부재, `RATE_LIMITED`/429를 실제로 반환하는 코드 경로 없음. 인프라 레벨(리버스 프록시 등)도 저장소에 없음 | **FAIL → 신규 결함 등록(§6 DEF-SEC-01)** | §4-1 에러 코드 표에 429가 "설계"되어 있으나 "구현"되지 않은 전형적인 설계-구현 불일치. 아래 §4-6/§6에서 비즈니스 영향(REQ-022 데이터 라이선스 리스크)과 연결해 심각도 판단 |

**종합**: 민감정보 미수집(REQ-016) 원칙은 코드에 정확히 반영되어 있고, DEF-FS-01 재현 결과 **스택트레이스/DB 자격증명 등 민감정보의 직접적 노출은 없음**을 확인했다(정보노출 관점은 PASS). 그러나 이 재현 과정에서 REQ-025의 근본 원인이 "DB 연결 실패 특정"이 아니라 "전역 예외 처리 부재" 전반임을 추가로 확정했다. 별도로, 설계 §6-3이 Must로 규정한 **보안 응답 헤더**와 **IP rate limiting**이 코드/인프라 어디에도 구현되어 있지 않음을 신규로 확인했다(DEF-SEC-01/02, §6 참조).

### 4-6. DEF-FS-01(REQ-025)의 자원고갈/DoS 인접 관점 추가 분석 (오케스트레이터 위임 사항)

> 이 절은 DEF-FS-01을 재발견/재등록하는 것이 아니라, "이 응답 지연이 실제 DoS 취약점으로 악용 가능한가"라는 8단계가 남긴 신규 질문에 답하기 위한 것이다.

**분석 절차**:
1. `services/public_api/api/*.py`의 모든 라우터 함수가 `async def`가 아니라 동기 `def`로 선언되어 있음을 확인(예: `def screen_stocks(...)`, `def health(...)`). FastAPI/Starlette는 동기 `def` 경로 함수를 스레드풀(anyio worker thread, 기본 동시 실행 상한 40)에서 실행한다.
2. `services/public_api/db/session.py`의 `create_engine()`에 `connect_timeout`이 없어(§6 DEF-FS-01/REQ-025 원인) DB가 응답하지 않을 때 연결 시도가 OS/드라이버 기본 타임아웃(08단계 실측 60~90초)까지 스레드를 점유한다.
3. 이 두 사실을 결합하면: DB 장애 중 동시 요청이 스레드풀 상한(기본 40)을 넘으면, 이후 요청은 스레드가 반환될 때까지 **대기열에서 60~90초 단위로 순차 대기**하게 되어, 정상 트래픽조차 사실상 전면 마비 상태에 빠진다. `/health`도 동일한 스레드풀을 공유하므로(§7-2 업타임 모니터가 5분 간격으로 호출) 장애 감지 자체도 지연될 수 있다.
4. **공격자 관점 재질문**: "그렇다면 외부 공격자가 이 상태를 악의적으로 유발할 수 있는가?" — 코드 전체를 재검토한 결과, 공개 API 어디에도 DB 연결 자체를 끊거나 DB 서버에 과도한 부하를 강제할 수 있는 경로(예: 매우 비싼 쿼리를 트리거하는 파라미터, 재귀적 조인, 무제한 `IN` 절 등)가 없다(§4-2 TC-SEC-10/11 참조 — page 상한 부재는 있으나 실 데이터 규모에서 비용이 낮음). 따라서 **외부 공격자가 이 취약점을 "단독으로" 트리거해 DoS를 일으키는 직접적인 공격 경로는 확인되지 않았다.**
5. 그러나 이는 "취약점이 아니다"를 의미하지 않는다. 이 결함은 **자연 발생적(네트워크 일시 단절, DB 유지보수, 클라우드 사업자 장애 등) 인프라 이슈를 전체 서비스 마비로 증폭시키는 가용성 증폭기**로 작용한다 — 정상적이라면 "일부 요청 실패 + 자동 복구"로 끝날 상황이, 스레드풀 고갈로 인해 "전체 서비스가 수 분간 완전히 응답 불능"이 되는 더 심각한 결과로 이어진다. 이는 08단계가 이미 High로 판정한 근거(REQ-022/REQ-024와 동일한 패턴으로 10단계 전 게이트)를 그대로 유지해야 하는 이유이며, **"사용자가 적어서 괜찮다"는 식으로 축소 판단할 근거가 되지 않는다** — 오히려 초기 규모(§8-A3, 동시 사용자 수백 명 이하)에서는 스레드풀(기본 40)이 상대적으로 더 쉽게 소진될 수 있어(퍼센트 기준으로는 작아도 절대 동시 요청 수 40건은 소규모 실사용 트래픽에서도 순간적으로 발생 가능), 오히려 소규모 서비스일수록 이 증폭 효과가 두드러질 수 있다.
6. **결론**: DEF-FS-01/REQ-025는 외부 공격자가 원격으로 직접 트리거하는 고전적 DoS 취약점은 아니지만, 실제 인프라 장애를 전면 서비스 마비로 증폭시키는 **가용성(자원고갈) 리스크가 실재하며 심각도 High 판정은 정확하다(하향 조정 근거 없음)**. 09단계는 이 결함을 재등록하지 않고, 기존 REQ-025 게이트(10단계 착수 전 필수 해소)의 심각도·시급성을 강화하는 근거로만 기록한다. 수정 시 `connect_timeout` 추가와 `OperationalError`/`DBAPIError` 핸들러뿐 아니라(§4-5 TC-SEC-25), 요청 단위 타임아웃(예: `asyncio.wait_for`나 API Gateway 레벨 타임아웃)을 함께 고려해 "스레드가 60~90초씩 점유되는 근본 원인" 자체도 줄일 것을 권고한다.

### 4-7. 개인정보 처리 컴플라이언스

| ID | 시나리오 | 실행 절차 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|
| TC-SEC-28 | 수집 최소화 원칙 준수 | §6-2 설계(요청 시각/경로/응답코드/해시 IP만 수집)와 실제 구현 대조 | `services/public_api/api/health.py` 1곳 외 어떤 구조화 요청 로깅 미들웨어도 구현되어 있지 않음(코드 전체 재확인, `logging.`/`logger.` 사용처가 `health.py`뿐임을 확인) — **즉 현재는 설계가 허용하는 최소 항목조차 "전혀 수집하지 않는" 상태**이므로 수집 최소화 원칙 위반 자체가 발생할 수 없음(수집물이 없음) | **PASS(위반 대상 없음)** |
| TC-SEC-29 | 명시된 보관기간(30일)·파기 절차 구현 여부 | 위와 동일 소스 재확인 | 접속 로그 자체가 구현되어 있지 않아 보관/파기 절차도 아직 구현 대상이 없음. 이는 보안/개인정보 결함이 아니라 **관측성(observability) 기능 자체의 미착수**이며, `decisions.md` DEC-025(8단계, "계측 인프라는 배포 후 별도 착수"로 사용자 승인)와 정확히 일치하는 기존에 승인된 상태 | **PASS(기존 DEC-025 승인 범위, 신규 리스크 아님)** |
| TC-SEC-30 | 제3자 제공/위탁 시 고지·동의 흐름 | 코드/설정 전체에서 외부 애널리틱스 SaaS, 광고 SDK, 제3자 데이터 전송 코드 검색 | 매치 0건(§6-2 "외부 애널리틱스 SaaS 미확정" 그대로 유지, 광고/결제 SDK도 REQ-010 검증에서 이미 0건 확인 승계) | **PASS** |
| TC-SEC-31 | 3단계 설계서(§6-2)에 적은 원칙과 실제 구현의 일치 | 설계 문구("계정·보유종목·매수단가 등 투자 관련 개인정보를 수집하지 않는다")와 전 스키마·API 파라미터 대조 | 개인정보 컬럼/파라미터 0건(§4-1 TC-SEC-03, §4-5 TC-SEC-22와 동일 근거) | **PASS** |

**종합**: 이 서비스는 개인정보를 전혀 수집하지 않는다는 전제가 실제로 지켜지고 있다. 접속 로그 미구현은 "설계 원칙 위반"이 아니라 "설계가 허용하는 범위 내에서 최소한도 아직 시작하지 않은 상태"이며, 이는 8단계에서 사용자가 이미 승인한 결정(DEC-025)과 일치해 새로운 리스크로 취급하지 않는다.

### 4-8. 규제 민감 도메인 대응(규칙 I) 반영 여부 최종 확인

| ID | REQ | 화면/문구 | 실행 절차 | 실제 결과 | Pass/Fail |
|----|-----|-----------|-----------|-----------|-----------|
| TC-SEC-32 | REQ-007(면책 문구 상시 노출) | `/`, `/screener`, `/stocks`, `/stocks/{code}` 전체 | `frontend/src/app/layout.tsx`(RootLayout)가 `DisclaimerBanner`를 무조건 렌더링하는 구조 확인(코드), 4개 라우트 모두 이 레이아웃의 자식임을 라우트 파일 목록으로 확인(`about/`,`page.tsx`,`screener/page.tsx`,`stocks/page.tsx`,`stocks/[code]/page.tsx`) | 모든 라우트가 Next.js App Router 공통 `RootLayout`을 상속하는 구조적 강제이므로, 개별 화면이 배너를 빼먹거나 우회할 방법이 코드 구조상 없음. 문구도 `copy.ko.json`에서 설계서 §4-1 문구와 정확히 일치함을 확인("이 서비스는 투자자문업 등록 사업자가 아니며...") | **PASS** |
| TC-SEC-33 | REQ-006(데이터 기준시각 표기) | `/`, `/screener`, `/stocks/{code}` | `DataFreshnessBadge` import 여부를 4개 화면 소스에서 검색 | `page.tsx`(홈), `ScreenerClient.tsx`(스크리너), `stocks/[code]/page.tsx`(상세) 3곳에서 사용 확인 — `/stocks`(검색 목록, 날짜 종속 데이터 아님)는 설계상 적용 대상이 아니며(KPI 항목5의 "시세/스크리닝/리포트 전 화면" 정의와 일치) 실제로도 미사용, 이는 누락이 아니라 설계 범위와 정확히 일치 | **PASS** |
| TC-SEC-34 | REQ-008(금지표현 가이드라인) | CI 게이트 | `frontend/scripts/lint-forbidden-copy.mjs` 전문 리뷰, `package.json`의 `prebuild` 훅 연결 확인 | 11개 금지어 + 1개 정규식 패턴을 정규화(공백 제거) 문자열에서 검사, `npm run build`의 `prebuild`로 강제 연결됨을 확인. 알려진 잔여 한계(DEF-009, JS 이스케이프 시퀀스 우회 — Low, Open, 6단계가 이미 인지)는 09단계도 동일하게 재확인, 배포 차단 사유 아님 | **PASS(DEF-009 Low 유지)** |
| TC-SEC-35 | REQ-009(불특정 다수/1:1 배제) | API 전체 | §4-1 TC-SEC-03과 동일 근거 | 사용자 식별 파라미터 0건 | **PASS** |
| TC-SEC-36 | REQ-010(무료 운영 정책) | 코드/의존성 전체 | `stripe`/`iamport`/`toss`/`kakaopay`/`adsense`/`admob`/`paypal`/`coupang` 등 결제/광고 SDK 키워드로 `package.json`/`requirements*.txt` 재검색 | 매치 0건(6단계와 동일 결과, 09단계 독립 재확인) | **PASS** |
| TC-SEC-37 | §4-3 데이터 가공 원칙(원본 시세 재게시 금지) — **4개 API + 프론트엔드 전체를 09단계가 최종 관통 확인** | 없음 | 4개 응답 Pydantic 스키마(`schemas/stocks.py`,`metrics.py`,`screen.py`,`market_summary.py`) 전체 필드 목록화 + `_build_matched_metrics()`(screen.py) 화이트리스트 로직 리뷰 + `shared/db_models/public_serving.py` 전 모델의 원본 컬럼 부재 재확인 | 4개 응답 스키마 어디에도 `open`/`high`/`low`/`close`/원문 `volume`/`per_raw`/`pbr_raw`/`market_cap_raw_krw`/`volume_raw` 필드가 존재하지 않음(코드 레벨 화이트리스트 확인). `screen.py`의 `_build_matched_metrics()`는 `per_percentile`/`pbr_percentile`/`market_cap_percentile`/`return_pct`/`volume_anomaly_score`만 반환 가능한 폐쇄형 딕셔너리(`value_by_key`)로 구현되어 있어, 원시값이 우발적으로 섞여 들어갈 코드 경로 자체가 없음 | **PASS** |

**종합**: 규칙 I이 요구하는 REQ-005~010 전 항목이 4개 화면 전체에 예외 없이 반영되어 있음을 09단계가 코드 레벨로 최종 확인했다. **미반영 항목 0건** — 미반영이 있었다면 Critical로 취급했을 것이나 해당 사항 없음.

### 4-9. 규칙 J(AI/LLM) 비해당 재확인

| ID | 시나리오 | 실행 절차 | 실제 결과 | Pass/Fail |
|----|----------|-----------|-----------|-----------|
| TC-SEC-38 | 서비스 코드에 LLM/생성형 AI 관련 경로가 전혀 없는가 | `services/`, `frontend/src/` 전체에서 `openai`/`anthropic`/`gpt-`/`langchain`/`llm`/`chatbot`/`claude` 키워드 검색(대소문자 무시), `requirements.txt`/`package.json`에 관련 패키지 존재 여부 확인 | 매치 0건(코드/의존성 양쪽) | **PASS** |

**종합**: REQ-023("규칙 J 비해당")의 판정이 실제 코드와 정확히 일치함을 재확인했다. 이 서비스에는 LLM 관련 경로가 전혀 없다.

## 5. 커버리지
- **1차 내부검증 관점 커버리지**: 에이전트 정의 필수 점검 항목 11개(인증/인가, 인젝션, 시크릿, 의존성 CVE, 의존성 환각, 민감정보 암호화, 에러 정보노출, 설계-구현 불일치, 개인정보 컴플라이언스, 오픈소스 라이선스, 외부 API 이용약관, 규제도메인 REQ-ID, 규칙 J 비해당, DEF-FS-01 DoS 분석) 전부 §4-1~§4-9에서 최소 1개 이상의 TC로 커버됨 — 누락 없음(아래 §10 1차 검증 체크리스트 참조).
- 커버리지 지표: TC-SEC-01~38(38건) + DEF-FS-01 DoS 정성 분석 1건 = 총 39개 관측 포인트. `pip-audit`/`npm audit` 실제 레지스트리 조회 2건, TestClient 격리 재현 2건(exploding repository 시나리오).
- 커버되지 않은 부분과 사유:
  - 실제 프로덕션 호스팅 환경에서의 TLS/HTTPS 강제, WAF/CDN 레벨 rate limiting — 저장소에 아직 `Dockerfile`/`nginx.conf`/`docker-compose.yml` 등 배포 아티팩트가 존재하지 않아(호스팅 벤더 미확정, §2-1) 코드 리뷰 대상 자체가 없음. 10단계(배포테스트)에서 실제 배포 아티팩트가 나온 뒤 재확인 필요.
  - DB 권한 분리(2차 방어)의 실 PostgreSQL 재실행 — 06~08단계가 이미 반복적으로(완전 초기화 후 재구성 포함) 실측 검증했고, 코드(마이그레이션 파일) 자체의 존재는 09단계가 재확인했으므로 반복 실행하지 않음(§2 제외범위).
  - 실제 침투테스트/실 공격 실행 — 규칙상 실행하지 않음(정적분석/코드리뷰/로컬 재현 범위로 한정).
  - REQ-022(KRX 라이선스 확인)/REQ-024(실 파이프라인 실행) 게이트 자체의 실제 이행 여부 — 09단계 소관 아님(상태 불변 확인만 수행).

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도 | 상태 | 조치 내용 |
|----|------|-----------|--------|------|-----------|
| DEF-SEC-01 | **(신규)** 설계서(§6-3, Must) "IP 기준 rate limiting(스크레이핑/대량 재배포 방지 목적, 429 `RATE_LIMITED`)"이 코드/인프라 어디에도 구현되어 있지 않다. 4개 데이터 API 전부가 요청 빈도 제한 없이 무제한 자동화 호출을 허용한다. | §4-5 TC-SEC-27: 저장소 전체에서 rate limiting 관련 코드/설정(`slowapi`,`Limiter`,`429`,`RATE_LIMITED`) 검색 결과 매치 0건, `Dockerfile`/`nginx.conf`/`docker-compose.yml` 부재로 인프라 레벨 구현도 없음을 확인(재현 가능, 결정론적) | **High** | Open | **비즈니스 영향과 연결한 심각도 판단**: 이 프로젝트는 데이터 소스 이용약관(§4-3, DEC-004)의 "제3자 재배포 엄격 금지"를 회피하기 위해 서비스 전체를 "가공 지표만 제공"으로 재정의했고, 이 재정의의 법적 방어력 자체가 REQ-022 게이트로 아직 미확정 상태다(자본시장법 인접 Tier=High). rate limiting 부재는 자동화 스크립트가 `/stocks`(전 종목)+`/stocks/{code}/metrics`(종목별 전 지표)+`/screen`(전 조건 조합)을 짧은 시간에 반복 호출해 **파생 지표 데이터셋 전체를 사실상 재구성·대량 수집(스크레이핑)할 수 있게** 만든다. 이는 설계 §6-3이 명시적으로 "가공 데이터라도 대량으로 긁어가면 사실상 원본 재배포와 유사한 결과를 낳을 수 있음"이라고 경고한 바로 그 시나리오이며, REQ-022의 법적 리스크(서비스 존립 근거)를 직접 훼손할 수 있다. "사용자 수가 적어서 스크레이핑 위험이 낮다"는 축소 판단은 하지 않는다 — 오히려 자동화 스크립트는 사용자 수와 무관하게 동작한다. 근본 원인은 UNIT-01(공통 Public API 기반)이 이 Must 요구사항을 구현하지 않고 넘어간 설계→구현 공백(규칙 F 대상)이다. **권고 조치**: `services/public_api/main.py`에 IP 기준 요청 빈도 제한 미들웨어(예: `slowapi` 또는 동등 기능)를 추가하고 429 `RATE_LIMITED` Envelope 응답을 §4-1 명세대로 반환하도록 구현. 10단계(배포테스트) 착수 전 필수 해소 조건으로 게이트 등록을 오케스트레이터에 권고(REQ-022/024/025와 동일 패턴, 신규 REQ-ID 등록 필요 — 09단계는 traceability.md/decisions.md를 직접 수정하지 않고 이 문서로 오케스트레이터에 인계한다). |
| DEF-SEC-02 | **(신규)** 설계서(§6-3, Must) "응답 헤더에 기본 보안 헤더 적용: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`(HTTPS 강제)"가 백엔드(`main.py`)와 프론트엔드(`next.config.mjs`) 어디에도 구현되어 있지 않다. | §4-5 TC-SEC-26: `main.py`의 미들웨어가 `CORSMiddleware`뿐임을 확인, `next.config.mjs`에 `headers()` 설정 없음을 확인(재현 가능, 결정론적) | **Medium** | Open | 이 서비스는 인증/쿠키가 없고(REQ-016 Out-of-Scope) 사용자 입력을 그대로 HTML로 렌더링하는 경로가 없어(§4-2 TC-SEC-08) 헤더 부재가 즉각적인 계정 탈취/세션 하이재킹으로 이어지지는 않으나, MIME 스니핑 기반 공격 방어(`X-Content-Type-Options`), 향후 기능 추가 시 XSS 심층방어(CSP), 프로덕션에서 HTTP 다운그레이드/MITM 방지(HSTS)라는 표준 방어선이 전무한 상태다. Critical/High로 격상할 직접적 익스플로잇 경로는 확인되지 않아 Medium으로 판단하나, 설계 Must 요구사항 미이행이므로 방치하지 않는다. **권고 조치**: 백엔드에 보안 헤더 미들웨어 추가(또는 10단계에서 확정될 리버스 프록시/CDN 레벨에서 일괄 적용), 프론트엔드는 `next.config.mjs`의 `headers()`로 CSP/`X-Content-Type-Options` 적용. 호스팅 벤더 확정 시(§2-1) 10단계 배포테스트 체크리스트 항목으로 반드시 포함할 것을 권고. |
| (승계, 신규 등록 아님) DEF-FS-01 / REQ-025 | 8단계가 발견한 "DB 연결 장애 시 5초 이내 503 대신 raw 500을 60~90초에 반환"하는 결함. 09단계는 이를 재발견/재등록하지 않고, (a) 정보노출 관점은 안전함(스택트레이스/자격증명 미노출)을 재확인했고, (b) 근본 원인이 "DB 연결 실패 특정"이 아니라 "전역 예외 처리 부재"임을 코드로 확정했으며, (c) 자원고갈/DoS 인접 관점을 분석해 "외부 공격자가 직접 트리거하는 공격 경로는 없으나, 실제 인프라 장애를 전면 서비스 마비로 증폭시키는 가용성 리스크가 실재함"을 결론지었다. | §4-5 TC-SEC-24/25, §4-6 전체 참조(TestClient 격리 재현, `ExplodingRepository`로 `OperationalError` 모사) | **High(기존 판정 유지, 하향 없음)** | Open(10단계 착수 전 게이트, `traceability.md` REQ-025 기존 등록 상태 그대로 유효) | 09단계는 직접 재작업하지 않는다(규칙 F, 근본 원인은 5단계/UNIT-01 `services/public_api/db/session.py`+`main.py`). 기존 REQ-025 게이트(10단계 전 필수 해소)를 그대로 유지하되, 수정 범위를 "DB `connect_timeout` + `OperationalError`/`DBAPIError` 핸들러"에서 **"범용(catch-all) 예외 핸들러 + 요청 단위 타임아웃"까지 확장**할 것을 권고사항으로 추가한다. |

- **그 외 결함 없음.** 근거: §4-1(인증/인가 5건)·§4-2(인젝션/입력검증 6건)·§4-3(시크릿 5건)·§4-4(의존성 5건)·§4-5(민감정보/에러노출 6건)·§4-7(개인정보 4건)·§4-8(규제도메인 6건)·§4-9(규칙J 1건) 전부를 코드 전체 재스캔·`pip-audit`/`npm audit` 실제 레지스트리 조회·격리된 `TestClient` 재현으로 실행했다. DEF-006(LIKE 와일드카드)은 보안 관점(정보노출/DoS)에서 재평가한 결과 기존 Low/Open 판정을 유지하는 것이 타당함을 근거와 함께 확정했다(재작업 불필요, 방어적 코딩 권고만 §8에 기록).

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- 세션 시작 시 `.harness-tmp/` 확인 결과: 비어 있음(강제 중단 이력 없음).
- 이번 테스트에서 생성한 임시 아티팩트 목록: **`.harness-tmp/` 하위에는 아무것도 생성하지 않았다.** 재현이 필요했던 유일한 스크립트(`repro_unhandled_exception.py`, §4-5 TC-SEC-24/25)는 실 DB/venv를 구성하지 않는 순수 진단 스크립트였으므로, 환경 도구가 제공하는 세션 격리 스크래치패드(`C:\Users\mega\AppData\Local\Temp\claude\...\scratchpad\`, 프로젝트 디렉터리 밖)에 생성·실행했다 — 이는 규칙 K가 의도하는 "프로젝트 루트에 흔적을 남기지 않는다"는 목적을 `.harness-tmp/`보다 더 엄격하게 충족한다(프로젝트 저장소 내부에는 어떤 파일도 생성되지 않았고, `.harness-tmp/` 삭제·정리 절차 자체가 필요 없다).
- 위 아티팩트를 전부 `.harness-tmp/` 하위에서만 생성했는가(규칙 K 1번): **해당 없음(사유: 프로젝트 디렉터리 내부에는 어떤 임시 아티팩트도 생성하지 않았다 — 세션 스크래치패드만 사용, §3 참조).**
- 정리(삭제) 완료 여부: 프로젝트 내부에 생성한 것이 없으므로 삭제할 것이 없다. 세션 스크래치패드의 재현 스크립트는 이 세션 종료 시 자동으로 격리·소멸되는 영역이라 별도 삭제 조치가 불필요하다.
- DB 정리: 이번 09단계는 실제 DB에 전혀 접속하지 않았다(정적 코드 리뷰 + `TestClient` 격리 재현만 수행). DB 상태 변경 없음.
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
	docs/harness/08-full-system-test.md
	docs/harness/feature-market-summary-integration-test.md
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
  (이 목록은 08단계 종료 시점의 `git status`와 정확히 동일하다 — 09단계는 `docs/harness/09-security-audit.md` 신규 생성 외 저장소에 어떤 파일도 추가/수정하지 않았다. 위 diff에 `09-security-audit.md`가 아직 나타나지 않는 것은 이 명령을 파일 저장 직전에 실행했기 때문이며, 저장 후에는 Untracked에 이 문서 1건만 추가된다.)
- 이번 테스트 도중 강제 중단(TaskStop 등)이 있었는가: **[x] 없음**.

## 8. 리스크 및 잔존 이슈
- **DEF-SEC-01(High, Open, 신규)**: rate limiting 미구현 — REQ-022 데이터 라이선스 리스크와 직결. 10단계 착수 전 필수 해소 게이트로 오케스트레이터에 등록 권고(신규 REQ-ID, 예: REQ-026).
- **DEF-SEC-02(Medium, Open, 신규)**: 보안 응답 헤더(CSP/`X-Content-Type-Options`/HSTS) 미구현. 10단계(배포 아티팩트 확정 시점)에 반드시 포함할 체크리스트 항목으로 인계.
- **DEF-FS-01/REQ-025(High, Open, 승계)**: 기존 게이트 유지. 09단계 분석으로 (a) 정보노출 없음 확인, (b) 근본 원인이 "전역 예외 처리 부재"로 더 넓음을 확정, (c) 자원고갈 증폭 리스크가 실재하나 외부 공격자의 직접 트리거 경로는 없음을 결론지었다 — 심각도는 하향하지 않는다.
- **DEF-006(Low, Open, 승계)**: LIKE 와일드카드 미이스케이프. 보안 관점(정보노출/DoS) 재평가 결과 실질적 위험 없음, Low 유지. 방어적 코딩 권고(이스케이프 처리)는 배포 차단 사유 아님.
- **DEF-009(Low, Open, 승계)**: 금지어 스캐너의 JS 이스케이프 시퀀스 우회 한계. AST 기반 파싱으로 근본 해결 가능(후속 개선 과제, 배포 차단 아님).
- **`page` 파라미터 상한 부재(정보성, 결함 미등록)**: 현재/목표 데이터 규모(~2,500행)에서 실질적 위험 없음. 방어적 코딩 관점의 상한 추가만 권고.
- **psycopg(LGPL-3.0) 라이선스 성격(정보성)**: SaaS 운영 방식에서는 비차단이나, 온프레미스 배포로 사업 모델이 바뀌면 재검토 필요.
- **실제 프로덕션 호스팅 환경의 TLS/보안 헤더/rate limiting 인프라 레벨 검증 미실시**: 배포 아티팩트(Dockerfile/nginx/docker-compose)가 아직 존재하지 않아 10단계로 이관.
- 8단계가 이미 인계한 승계 리스크(실 서비스 규모 성능 미실측, 단일 워커 미검증, UAT KPI 측정 인프라 부재 DEC-025 등)는 09단계가 재검증하지 않았으며 상태 변경 없음 — 여기서 재서술하지 않는다.

## 9. 결론 및 판정
- [ ] PASS
- [ ] CONDITIONAL PASS — (이 단계는 오케스트레이터 지시에 따라 CONDITIONAL PASS 개념을 적용하지 않는다. Critical/High 결함이 있으면 FAIL로 처리한다.)
- [x] **FAIL** — 사유 및 재작업 요청 사항: 아래 참조

**판정 근거**: 인증/인가, 인젝션, 시크릿 하드코딩, 의존성 CVE, 의존성 환각, 민감정보 암호화, 개인정보 컴플라이언스, 오픈소스 라이선스, 외부 API 이용약관 준수(원본 재게시 금지), 규제 민감 도메인(규칙 I) 반영, 규칙 J 비해당 — 이 11개 항목은 전부 결함 0건으로 확인됐다(§4-1~§4-4, §4-7~§4-9). 그러나 다음 **High 결함 2건**이 미해소 상태로 남아있어 PASS로 판정할 수 없다:
1. **DEF-SEC-01(High, 신규)** — IP rate limiting 미구현, REQ-022 데이터 라이선스 리스크와 직결.
2. **DEF-FS-01/REQ-025(High, 승계)** — 전역 예외 처리 부재로 인한 API 계약 위반 및 자원고갈 증폭 리스크. 09단계가 자원고갈 관점을 추가 분석했으나 심각도를 하향할 근거를 찾지 못했다(오히려 원인 범위가 넓어짐을 확인).

**규칙 F에 따른 근본 원인 추적(재작업은 하지 않음)**:
- DEF-SEC-01/DEF-SEC-02: 근본 원인은 **3단계 설계서(§6-3)가 이미 명시한 Must 요구사항이 5단계(UNIT-01, `services/public_api` 공통 기반) 구현 단계에서 누락**된 것이다. 설계 자체는 정확했으므로 3단계 재작업은 불필요하며, 5단계(`services/public_api/main.py`)로 되돌아가 구현하고 06(단위)·07(해당 feature 통합)·08(전체)·09(본 문서 재검증)을 다시 거쳐야 한다.
- DEF-FS-01/REQ-025: 8단계가 이미 근본 원인을 5단계(UNIT-01, `services/public_api/db/session.py`+`main.py`)로 정확히 귀속했다. 09단계는 이 귀속을 그대로 승계하며, 수정 범위를 "DB 타임아웃 + 특정 예외 핸들러"에서 "범용 예외 핸들러 + 요청 단위 타임아웃"으로 넓힐 것을 추가 권고한다.
- 두 결함 모두 동일한 5단계 산출물(`services/public_api/main.py`, 공통 기반)에 귀속되므로, 재작업 시 한 번의 5단계 재작업 사이클로 함께 해소하는 것을 권고한다(효율성 — 새로운 판단 기준이 아니라 근본 원인 위치가 우연히 같다는 사실 기반 권고).

## 10. 내부 검증 (최소 2회, `verification-log-template.md` 사용)

### 1차 검증 (작성자 관점 자가 재검토 — "필수 점검 항목 체크리스트를 빠짐없이 수행했는가")
- 검증자(역할): 09-security-auditor(작성자 본인)
- 일시: 2026-09-18
- 체크리스트
  - [x] 인증/인가 우회·권한 경계(수평/수직) → §4-1(TC-SEC-01~05) 코드 전체 재스캔으로 확인, 결함 0건
  - [x] 인젝션(SQL/커맨드/XSS)·입력 검증 누락 → §4-2(TC-SEC-06~11), SQL은 전부 ORM 바인딩 확인, DEF-006 재평가 완료
  - [x] 시크릿/자격증명 하드코딩·로그 노출 → §4-3(TC-SEC-12~16), `.env.example`/코드/`git log` 이력 전부 확인
  - [x] 의존성 취약점(CVE) 스캔 → §4-4(TC-SEC-17~18), `pip-audit`/`npm audit` 실제 실행(네트워크 조회 기반)
  - [x] **의존성 환각(hallucinated dependency) 점검** → §4-4(TC-SEC-19~20), 전 패키지 레지스트리 실존 확인 + 타이포스쿼팅 없음 + 검증전용 도구(puppeteer 등) 프로덕션 잔존 없음
  - [x] 민감정보 저장/전송 암호화 여부 → §4-5(TC-SEC-22), PII 컬럼 0건
  - [x] 에러 메시지를 통한 정보 노출 → §4-5(TC-SEC-23~25), DEF-FS-01을 로컬 격리 재현해 정보노출 없음을 직접 확인
  - [x] 설계서의 보안 원칙과 실제 구현의 불일치 → §4-5(TC-SEC-26~27), rate limiting/보안헤더 미구현을 신규로 확정(DEF-SEC-01/02)
  - [x] 개인정보 처리 컴플라이언스(수집 최소화/보관기간/파기/제3자 제공/설계 일치) → §4-7(TC-SEC-28~31)
  - [x] 오픈소스 의존성 라이선스 검토(강한 카피레프트 여부) → §4-4(TC-SEC-21)
  - [x] 외부 데이터/API 이용약관 준수(호출 빈도·크롤링 여부, 3단계 확인 내용과 실제 구현 일치) → §4-4(TC-SEC-21 라이선스와 별개), 배치 호출 빈도(1~2회/일) 설계 일치 확인, 크롤링 코드 0건 확인
  - [x] **규제 민감 도메인 대응(규칙 I) 반영 여부** → §4-8(TC-SEC-32~37), REQ-005~010 전 항목 4개 화면 전수 확인, 미반영 0건(있었다면 Critical)
  - [x] **AI/LLM 기능 내장 대응(규칙 J) 반영 여부** → §4-9(TC-SEC-38), REQ-023 비해당 판정과 실제 코드 일치 재확인
  - [x] DEF-FS-01 자원고갈/DoS 인접 관점 추가 점검(오케스트레이터 위임) → §4-6, 정성 분석 + 코드 근거로 결론 도출
  - 발견된 결함: DEF-SEC-01(High), DEF-SEC-02(Medium) 신규. DEF-FS-01/REQ-025(High)는 승계 확인. 조치: §6 결함 목록에 전부 등록, §9에서 FAIL 판정.

### 2차 검증 (역할전환 — "공격자라면 이 시스템에서 어디를 노릴까")
- 검증자(역할): 09-security-auditor(공격자 관점 재검토)
- 일시: 2026-09-18
- 체크리스트(1차에서 놓친 공격 표면이 있는지 역할전환으로 재검토)
  - [x] **"인증이 없다는 것 자체를 악용할 수 있는가?"** — 이 서비스는 애초에 인증을 요구사항에서 배제했으므로(REQ-009), "인증 우회"라는 개념 자체가 성립하지 않는다. 대신 "인증이 없으니 모든 트래픽이 익명 대량 요청일 수 있다"는 관점에서 rate limiting 부재를 재검토했고, 이것이 1차 검증에서 이미 DEF-SEC-01로 포착됐음을 재확인 — 놓친 것 없음.
  - [x] **"공격자가 스크리닝 API(`/screen`)의 다중 조건 조합을 악용해 비싼 쿼리를 유발할 수 있는가?"** — `screen_repository.py`를 재검토한 결과, 모든 필터는 인덱스가 걸린 컬럼(§5-1)에 대한 단순 범위 비교이고 서브쿼리/조인은 `stock_master` 1개뿐(카디널리티 낮음), `page_size` 상한(200)이 강제되어 있어 "쿼리 자체를 무겁게 만드는" 방법을 찾지 못했다. `page` 상한 부재(TC-SEC-10)만 재확인했고, 현재 데이터 규모에서는 실익이 없음을 재확인 — 신규 발견 없음.
  - [x] **"공격자가 CORS 설정을 악용해 제3자 사이트에서 이 API를 자동으로 긁어갈 수 있는가?"** — CORS는 브라우저의 same-origin 정책을 프론트엔드 보호 목적으로만 강제하는 것이며, 서버 API 자체는 CORS와 무관하게 `curl`/스크립트로 직접 호출 가능하다(이 API에 인증이 없으므로 애초에 "권한 있는 자만 호출 가능"한 설계가 아니다). 이는 CORS 설정의 결함이 아니라 **바로 rate limiting 부재(DEF-SEC-01)가 방어해야 할 시나리오 그 자체**임을 재확인 — 별도 신규 결함이 아니라 DEF-SEC-01의 비즈니스 영향 서술(§6)에 이미 반영되어 있음을 확인.
  - [x] **"공격자가 의존성 공급망을 노릴 수 있는가(슬롭스쿼팅)?"** — 1차 검증에서 이미 전 패키지의 레지스트리 실존을 확인했으나, 공격자 관점에서 재검토하면 "실제 배포 시 `npm install`/`pip install`이 lockfile 없이 실행되면 latest 버전이 설치되어 그 사이 패키지가 탈취/오염될 수 있는가"도 확인 대상이다 → `frontend/package-lock.json` 존재 여부를 재확인(존재함, `npm ci`로 고정 설치 가능한 상태), Python 쪽은 `requirements.txt`가 버전 범위(`>=`)만 고정하고 정확한 lockfile(`requirements.lock`/`pip freeze` 산출물)이 없어 배포 시점마다 정확히 동일한 버전이 설치된다는 보장이 없음을 새로 확인했다. 이는 즉각적 취약점은 아니지만(CVE 스캔은 현재 설치본 기준으로 클린) 향후 상위 버전에서 발생할 신규 CVE에 무방비로 노출될 수 있는 재현성 리스크다.
  - 발견된 결함: 위 재검토에서 **신규 코드 결함은 발견되지 않았으나**, 1건의 **권고 사항**(Python 의존성 버전 고정 lockfile 부재)을 추가로 §8에 기록한다. 이는 Critical/High가 아니며(현재 스캔 결과가 깨끗하고, 이미 pip-audit이 CI에 포함될 예정임을 설계 §6-3이 명시) 판정을 바꾸지 않는다.
  - 조치 내용: §8에 "Python 의존성 lockfile 부재(정보성)" 항목 추가. 결함 목록(§6)과 최종 판정(§9)은 변경 없음 — **FAIL 유지**(DEF-SEC-01, DEF-FS-01/REQ-025 두 건의 High가 해소되지 않았으므로).

- 검증 로그 파일 경로: 이 문서 §10에 통합 기록(06~08단계 산출물이 따른 관례와 동일하게 별도 파일 분리하지 않음).

## 절차 흐름 (참고용 다이어그램)
```mermaid
flowchart TD
    A["8단계 CONDITIONAL PASS + 전체 코드베이스"] --> B["인증/인가·인젝션·시크릿·의존성 점검(§4-1~4-4)"]
    B --> C["민감정보/에러노출/설계-구현 불일치 점검(§4-5) → DEF-SEC-01/02 발견"]
    C --> D["DEF-FS-01 자원고갈/DoS 관점 추가분석(§4-6, 위임사항)"]
    D --> E["개인정보 컴플라이언스 + 규제도메인 REQ-ID + 규칙J 비해당 점검(§4-7~4-9)"]
    E --> F{Critical/High 결함?}
    F -->|Yes: DEF-SEC-01(High), DEF-FS-01/REQ-025(High)| G["FAIL 판정 → 근본원인 5단계(UNIT-01) 귀속 보고"]
    F -->|No| H["내부검증 1차/2차: 공격자 관점 재검토"]
    G --> I["오케스트레이터에 FAIL 보고, 직접 재작업 안 함(규칙 F)"]
    H -->|결함 있음| B
    H -->|결함 없음| J["09-security-audit.md 확정 PASS"]
```
