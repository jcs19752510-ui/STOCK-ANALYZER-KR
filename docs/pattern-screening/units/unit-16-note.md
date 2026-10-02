# UNIT-16 구현 노트 및 내부 테스트 결과서 — 패턴 스크리닝 API (REQ-032, 034~036)

- 작성: 2026-10-02 14:5x KST · 대상: `GET /api/v1/screen/pattern` · 관련: 02 설계서 §5·§6, 05 테스트계획 §7(TC-A01~A35)·§8(TC-S01~S12)·§9(TC-P01~P03)
- **결론: 구현·테스트 완료(신규 120건 통과, 전체 회귀 0). 기존 `/screen` 계약 불변을 골든 비교와 소스 해시로 증명했다. 현재 켜져 있는 개발 백엔드(4001)는 이전 코드를 메모리에 올린 상태라 이 엔드포인트가 아직 없다 — UNIT-17 브라우저 검증 시점에 새 코드로 재시작한다.**

## 1. 구현 요약

| 구분 | 파일 | 내용 |
|---|---|---|
| 수정(추가만) | `services/public_api/db/pattern_repository.py` | UNIT-15의 `build_condition_exprs`에 이어 `SqlPatternScreenRepository`(`get_current_published_trade_date`·`readiness`·`search`·`search_statement`), `PatternFilters/Row/QueryResult`, `SORT_COLUMN_MAP`, `METRIC_KEYS` |
| 신규 | `services/public_api/schemas/pattern.py` | 응답 Pydantic 모델(**화이트리스트**: 가격·거래량 원값·`*_raw`·시가총액 원값 필드를 선언하지 않음) |
| 신규 | `services/public_api/api/pattern.py` | 엔드포인트·`parse_required`·`reason_for`·DI(`get_pattern_repository/calendar_repository/thresholds`) |
| 수정(2줄) | `services/public_api/main.py` | `pattern` import와 `include_router` |
| 신규(테스트) | `tests/unit/test_pattern_api.py`(85건), `tests/integration/test_pattern_api_db.py`(35건), `pattern_api_env.py`(임시 DB+실제 앱 헬퍼), `golden_screen_before_pattern.json` | |

- **수정하지 않은 것**: `api/screen.py`, `db/screen_repository.py`, `schemas/screen.py`(additive only). 신규 의존성 0.
- 흐름(설계서 §5-4): 기능 스위치 → 파라미터 검증 → 캘린더 → 발행 거래일 → **readiness 집계(`market` 필터 후)** → 산정 가능(OK) 행이 0이면 `424 PATTERN_DATA_NOT_READY`(검색 쿼리 실행 안 함) → 개수·정렬(2차 키 `stock_code`, `NULLS LAST`)·페이지.
- 필터와 표시가 같은 식: `required` 조건은 `expr IS TRUE`로 WHERE에 걸고, 응답의 `met`·`ma60_stage`는 같은 `build_condition_exprs`/`ma60_stage_expr`를 SELECT한 값이다. Python에서 재판정하지 않는다.
- 입력: `required`는 길이 상한(17자) 선검사 후 화이트리스트 파싱(중복·미지 ID·공백·빈 토큰·대소문자 불일치 → 400), `sort_by`는 매핑 딕셔너리로만 컬럼 선택, 알 수 없는 쿼리 파라미터·임계값 우회 시도는 무시(서버 설정 객체만 사용).
- 기동 시 `PATTERN_*` 설정을 검증한다(`api/pattern.py` import 시점에 `load_pattern_thresholds()`): 잘못된 값이면 앱이 기동하지 않는다(서브프로세스 테스트로 확인).

## 2. 문서와 달라진 점·구현 중 판단 (편차 기록)

| # | 내용 | 영향 |
|---|---|---|
| 1 | **05 TC-A15의 "T00008→전 조건 `met=null`, T00009→…" 응답 행 검증은 설계상 불가능하다.** 필수(`required`) 조건은 `IS TRUE`로 걸리므로(설계서 §5-4) 이력 부족·단절 종목은 어떤 `required`(비어있지 않은 부분집합)로도 결과 행에 나올 수 없다. 설계서 의도와 구현은 일치하며 테스트 계획 문구만 모순이다 | 검증을 둘로 나눴다: ① `reason_for()` 매핑(이력 부족/단절/METRIC_UNAVAILABLE/구 배치)과 SQL 계층(UNIT-15 `test_pattern_conditions_db.py`: 상태 게이트로 전 조건 NULL) ② 결과 행에서 null이 나오는 실제 경우 — **필수가 아닌 조건의 셀**(평탄 종목 T00010의 c2·c5 `METRIC_UNAVAILABLE`)을 API 응답으로 검증. 05 문서 정정은 UNIT-18 |
| 2 | 응답 `metrics`에 `volume_anomaly_score`(기존 컬럼)를 포함(설계서 §5-2의 11개 목록과 일치) — `pattern_metrics_status`는 응답 필드가 아니다 | 설계서 그대로 |
| 3 | `ready_ratio`는 소수 4자리 반올림(예 2650/2760 = 0.9601). 설계서 예시(0.96)는 설명용 | 정밀도 규칙은 문서에 없어 4자리로 정함 |
| 4 | `PATTERN_DATA_NOT_READY` 판정은 "OK 행 0건"(전체 행 0건 포함). 시장 필터 후 집합 기준 | 설계서 §5-4 |
| 5 | 기능 스위치 off일 때 라우터는 등록된 채 `404 FEATURE_DISABLED`를 반환(경로 자체를 제거하지 않음) | 설계서 §9와 동일 의미 |
| 6 | TC-S12(의존성 불변)는 테스트 코드가 아니라 `git diff HEAD`로 확인(`requirements*.txt`, `frontend/package*.json` 변경 0줄) | 결과: 변경 없음 |

문서의 임계값·계산 정의·응답 스키마는 바꾸지 않았다.

## 3. 테스트 결과 (실제 실행 출력)

실행: `py -3.12`, 2026-10-02 14:4x~14:5x KST.

### 3-1. 요약

| 구분 | 변경 전 | 변경 후 | 판정 |
|---|---|---|---|
| `pytest tests/unit` | 435 passed | **520 passed**(+85) | PASS, 신규 실패 0 |
| `pytest tests/integration` | 90 passed | **125 passed**(+35) | PASS |
| 이번 유닛 신규 | — | **120 passed / 0 failed / 0 skipped** | PASS |
| `ruff check shared services scripts tests db` | — | `All checks passed!` | PASS |
| 임시 DB 잔여 | — | 0개 | 정리 완료 |
| `requirements*.txt`·`package*.json`·기존 `/screen` 소스 3개 | — | `git diff HEAD` 변경 0줄 | PASS(S12·A35) |
| 개발 서버(DB·4000·4001) | — | 켜 둠, 재시작하지 않음(`/screen`·metrics 200) | 유지 |

### 3-2. TC별 결과

| TC | 시나리오 | 검증 | 결과 |
|---|---|---|---|
| A01 | 기본 호출 envelope | 단위+DB: `meta.data_freshness/disclaimer/generated_at`, `data.items/total_count/page/definition/readiness` | PASS |
| A02 | 시장 필터 | KOSPI/KOSDAQ/ALL 결과가 오라클 기대 집합과 일치, readiness도 시장 필터 후 | PASS |
| A03 | `required` 생략 = 6개 전부 | DB: 결과 = T00001 하나(오라클 기대와 일치) | PASS |
| A04 | 부분집합 | DB: `c1,c2`·`c1,c3,c9`·`c2`·`c4`·`c5`·`c9` 모두 오라클 집합과 일치, 입력 순서와 무관하게 정규 순서 | PASS |
| A05~A08 | 중복·미지 ID·빈 값·공백 | 단위: 19개 잘못된 입력(`c1,c1`·`c7`·`c6`·`C1`·``·`c1, c2`·`c1,`·`,c1`·`c1,,c2`·길이 초과·SQL 메타문자 등) → 400, **리포지토리 미호출** | PASS |
| A09·A10·A11·A12 | 정렬 4종·방향·`page_size` 상한·`page=0` | 단위: 허용 4종 200, 점수·순위·`return_pct` 등 거부, `page_size=201`·0 거부(200은 허용), `page=0/-1/x`가 기존 `/screen`과 같은 400 envelope | PASS |
| A13 | 페이지네이션 결정론 | DB: `page_size=2` 전체 순회가 중복·누락 없이 한 번에 받은 순서와 동일 | PASS |
| A14 | 정렬 NULL 처리 | DB: 상태 OK·c9 true인데 정렬 값이 NULL인 행이 `asc`·`desc` 모두 **마지막** | PASS |
| A15 | 3값 응답 매핑 | **편차 #1 참조** — 매핑 단위 7케이스 + T00010 실제 응답(c2·c5 `null`+`METRIC_UNAVAILABLE`, c4 `false`) | PASS |
| A16 | 필터는 TRUE만 통과 | DB: FALSE·NULL 행 제외(c2 필수 시 평탄 종목 제외) | PASS |
| A17 | `total_count` | DB: 실제 건수와 일치(페이지 크기와 무관) | PASS |
| A18 | `readiness` | 전체 8/10(0.8)·시장별 개수·비율 일치 | PASS |
| A19 | `PATTERN_DATA_NOT_READY` | 단위+DB: 424 + 코드 정확, 메시지 "시세 기간", **검색 쿼리 미실행**, 시장별 판정 | PASS |
| A20 | 일부 준비·결과 0건 | 단위+DB: 200 + 빈 목록(에러 아님), readiness 유지 | PASS |
| A21 | 발행 데이터 없음 | 단위+DB: 503 `DATA_PIPELINE_STALE` | PASS |
| A22 | 캘린더 오류 | 424 `CALENDAR_NOT_CONFIRMED` / 503 `SERVICE_UNAVAILABLE` | PASS |
| A23 | **응답 필드 화이트리스트** | 단위+DB(재귀): `items[*]` 키 = {stock_code,name,market,conditions,metrics,ma60_stage}, `metrics` 11개, `open/high/low/close/volume*/`*_raw`/시가총액 원값/점수·순위 키 부재 | PASS |
| A24 | `definition` | 서버 설정(사용자 지정 값 포함)과 `calc` 고정 파라미터와 일치 | PASS |
| A25 | 기능 스위치 off | 404 `FEATURE_DISABLED`, DB 미접근 | PASS |
| A26 | envelope 공통 | `data_freshness`·`disclaimer`·`generated_at`, `staleness_note`는 최신이 아닐 때만 | PASS |
| A27 | `market_cap_min`·`volume_min` | DB: 필터로만 동작(경계 포함), **응답에 원값 없음**(시총·거래량 숫자 문자열 부재) | PASS |
| A28·A29·A30·A31·A33 | 경계·3값·게이트·단계 | **SQL 계층은 UNIT-15에서 검증**(33 경계 케이스·798격자·오라클 800행 등) + 이번 API 수준 확인: `ma60_stage`↔c4 일치(응답 전수), T00005 `EXTENDED`/c4 false, 구 배치 행(상태 NULL)은 readiness 총계엔 포함·평가에서 제외·결과에 안 나옴 | PASS |
| A32 | 정렬 4종×2방향 | DB: `ma60_gap_pct`·`sideways_range_pct`·`ma_convergence_pct` 값 순서, `market_cap`은 숨은 원값 순서로 정렬하되 응답엔 미노출, 동률은 `stock_code` 오름차순 | PASS |
| A34 | 직렬화 | 응답 JSON에 NaN/Infinity 없음(엄격 파서), Decimal→수치 | PASS |
| **A35** | **기존 `/screen` 불변** | ① **골든 비교**: 변경 전(UNIT-16 시작 시점)에 생성한 5개 질의 응답과 현재 응답이 완전히 동일 ② 소스 3개의 줄바꿈 정규화 SHA-256이 시작 시점과 동일 ③ `git diff HEAD` 변경 0줄 | PASS |
| S01 | SQL 메타문자 | `required`·`sort_by`·`market`에 `'; DROP …`·`c1) OR (1=1` → 400, 테이블 행 수 불변(10) | PASS |
| S02 | `required` 1,000개 | 400, 1초 미만(길이 상한 선검사) | PASS |
| S03·S04 | 알 수 없는 파라미터·임계값 우회 | 결과·`definition`이 기본과 동일, 리포지토리에는 항상 서버 설정 객체만 전달 | PASS |
| S05 | rate limit | 신규 경로에서 분당 60회 초과 시 429(+보안 헤더, envelope) | PASS |
| S06 | 보안 헤더 | 200/400/404/424/429 응답 모두 CSP·`X-Content-Type-Options`·HSTS 부착 | PASS |
| S07 | 원본 필드 비노출 | 응답 + 스키마 파일 AST 검사(가격·`*_raw` 필드 선언 0건) | PASS |
| S08 | DB 장애 | 503 envelope, 내부 정보(비밀번호·호스트·스택트레이스) 미노출 | PASS |
| S11 | CORS | 허용 오리진만 `Access-Control-Allow-Origin`, 그 외 preflight는 헤더 없음 | PASS |
| S09·S10 | 백필 키 비노출·프런트 정적 점검 | S09는 UNIT-12 B05, S10(`dangerouslySetInnerHTML` 등)은 프런트가 생기는 UNIT-17 | 해당 유닛 |
| S12 | 의존성 불변 | `git diff HEAD` 0줄 | PASS |
| **P01** | **응답 시간** | 임시 DB에 합성 2,700종목, 5개 필수 조합 50회 요청: **median 32.7ms · p95 42.1ms · max 76.9ms**(목표 p95 ≤ 500ms) | PASS |
| **P02** | **실행 계획** | `EXPLAIN`: 기존 인덱스 `ix_derived_metrics_daily_trade_date_market`의 Bitmap Index Scan으로 단일 거래일 범위를 좁힌 뒤 필터, `stock_master`는 PK 인덱스 조인 — 새 인덱스 불필요 | PASS |
| P03 | 배치 전후 | UNIT-14에서 측정(1.19배, 2,880종목 기준 약 +2초) | 완료 |

(P01 수치는 TestClient 인프로세스 호출 기준이며 네트워크·프록시 지연은 포함하지 않는다.)

### 3-3. 테스트 유효성 검증 (변이 테스트)

구현 16곳을 하나씩 훼손해 위 테스트(+단위·통합)가 실패하는지 확인했다. **16/16 적발(생존 0)**, 모든 변이 후 원본 복원.

| 영역 | 변이 |
|---|---|
| 리포지토리 | `required` 필터 제거 / `NULLS LAST` 제거 / readiness가 시장 필터 무시 / `volume_min` 필터 누락 / `market_cap_min` `>=`→`>` / OFFSET 오류 / 정렬 방향 무시 |
| API | 중복 검사 제거 / 미지 ID 검사 제거 / readiness 판정을 총 행 수로 변경 / 기능 스위치 무시 / `reason`이 항상 METRIC_UNAVAILABLE / `definition`이 설정 오버라이드 무시 / `ready_ratio` 2자리 반올림 / `page_size` 상한 제거 |
| 스키마 | 응답 모델에 `volume_raw` 필드 추가(원값 노출) |

## 4. 보안·품질 점검

| 항목 | 결과 |
|---|---|
| 입력 검증 | 화이트리스트(`required`·`sort_by`·`sort_dir`·`market`), 길이·개수 상한, 쿼리는 SQLAlchemy 식만 사용(문자열 SQL 없음) |
| 응답 | 가격·거래량 원값·`*_raw`·시가총액 원값·점수·순위 필드 없음(스키마 + 응답 재귀 검사) |
| 임계값 | 서버 설정 전용, 사용자 입력·우회 파라미터 무시 |
| 권한 | `api_service`(읽기 전용) 세션으로 실제 SQL 실행(UNIT-14 D05가 쓰기·`raw_internal` 거부를 증명) |
| 미들웨어 | rate limit·보안 헤더·CORS·타임아웃·예외 처리 기존 계층이 신규 경로에도 적용(S05·S06·S08·S11 실측) |
| 비밀·로그 | 오류 응답에 DB URL·비밀번호·스택트레이스 없음(S08) |

## 5. 남은 위험·후속

1. **개발 백엔드(4001) 재시작 필요**: 새 엔드포인트와 `PATTERN_*` 검증은 재시작 후 반영된다. 재시작해도 `/screen`·`/stocks/{code}/metrics`가 새 모델과 함께 정상 동작하는지(0011 적용 상태)는 UNIT-17 브라우저 검증 시 실제로 확인한다. 개발 DB의 발행 데이터(09-21)는 패턴 지표가 없는 구 배치라 이 엔드포인트는 `424 PATTERN_DATA_NOT_READY`를 반환할 것이다(정상 — 백필·배치 후 해소).
2. 실데이터 임계값 적정성(Q2)과 스팩·우선주 포함 여부(Q3)는 여전히 결정 대기.
3. 05 TC-A15 문구 정정, 설계서 §2 변경 지도(`pattern_repository` 앞당김 등) 갱신은 UNIT-18.
