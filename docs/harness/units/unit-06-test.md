# 테스트 결과서 (Test Result Report) — UNIT-06

## 1. 개요
- 테스트 대상: UNIT-06(작업단위) — REQ-002 "종목별 가공 지표 요약 조회". 구체적으로 (1) `services/derivation_batch/`(Derivation Batch, 이 프로젝트 최초의 raw→public 경계 컴포넌트), (2) `public_serving.derived_metrics_daily`/`current_published_batch`(마이그레이션 0006), (3) `GET /api/v1/stocks/{code}/metrics`, (4) 프론트엔드 `/stocks/[code]`, (5) `shared/calendar_service/`로의 `SqlCalendarRepository` 승격
- 테스트 유형: 단위(Unit) — 6단계(단위 업무 직후 테스트)
- 테스트 목적: 5단계(`05-unit-developer`)의 자체 검증 결과("112개 테스트 pass", "market ENUM 버그 실발견/수정", "픽스처로 종단간 검증 후 정리")를 신뢰하지 않고 독립적으로 재현하며, 특히 REQ-022(§4-3 데이터 라이선스 준수)의 핵심인 원본 시세 미노출 원칙과 `return_rank_pct` 방향성이 실제로 지켜지는지 실 DB로 직접 검증한다.
- 관련 산출물: `docs/harness/units/unit-06-note.md`(입력 계약), `docs/harness/03-system-design.md`(v4) §1-1/§1-2/§1-3/§3-1-1/§3-2/§3-4/§4-1/§4-2/§4-3, `docs/harness/04-ux-design.md`(v3) §1-4/§2-4/§4/§5, `docs/harness/traceability.md`(REQ-002)
- 테스트 수행자(에이전트): `06-unit-tester`
- 테스트 일시: 2026-09-16 (로컬 Docker PostgreSQL `stock-screener-db`, 실 컨테이너 재사용)

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope):
  - AC-1~AC-10(unit-06-note.md §4) 전 항목의 독립 재현
  - 코디네이터가 명시적으로 지시한 6개 항목: (1) 원본 시세/원시값 미노출(스키마+API 응답 실측), (2) `return_rank_pct` 방향성/percentile 계산 실 DB 재현, (3) `raw_ohlcv.market` ENUM 버그 수정 재현, (4) REQ-006/REQ-007 이 화면에서의 정상 렌더링, (5) "실데이터 없음" 상태(EmptyState/ErrorState) 실제 렌더링 + Next.js 16 소프트 404 이슈의 결함 여부 판단, (6) REQ-001 시퀀싱 공백 인지 기록(해결은 6단계 범위 아님)
  - 위험 기반 추가 테스트: 빈/공백 종목코드, 잘못된 날짜 형식, 인증 헤더/쿠키/미지 쿼리파라미터 무관성(REQ-009 회귀), `-0%` 포맷 경계
- 제외 범위 및 사유:
  - PER/PBR/시가총액 percentile의 실제 코스피+코스닥 전종목(~2,500개) 규모 동률/경계값 검증 — UNIT-02가 `raw_fundamentals`를 실제로 적재하지 않아 실 데이터 자체가 없음(이 유닛의 결함이 아니라 UNIT-02의 알려진 범위 제한). 대신 `rank_percentile()` 단위테스트(동률 1,1,3 패턴)와 03-system-design.md 워크드 예제(125/2500*100=5.0)를 직접 재계산해 계산식 자체의 정확성은 확정했다.
  - 실제 컨테이너 이미지 빌드/배포 순서 — 10단계(배포테스트) 소관
  - Derivation Batch cron 스케줄링 — 설계서 §7-2 미명시, 후속 과제로 인계(note §3과 동일 판단)
  - REQ-001(종목 검색 프론트엔드) 시퀀싱 공백 해소 — 이 유닛의 범위가 아니며 오케스트레이터가 처리할 사안(§7 참조)

## 3. 테스트 환경
- 실행 환경: Windows 10, Python(ruff/pytest), Node.js(Next.js 16.3.5 Turbopack), Docker Desktop — 컨테이너 `stock-screener-db`(PostgreSQL, 기존 세션에서 이미 기동 중이던 실 컨테이너, 역할 `migrator`/`batch_worker`/`api_service`, 로컬 개발용 비밀번호 `devpass` — 어떤 소스 파일에도 없음, 쉘 환경변수로만 주입)
- 테스트 데이터:
  - (a) "데이터 없음" 정상 처리 검증: 실제 운영 상태 그대로(빈 `stock_master`/`raw_ohlcv`)
  - (b) 가공 로직 정확성 검증: 저장소에 커밋된 `scripts/dev_seed_fixture_metrics.py`가 생성하는 **명시적 테스트 픽스처**(종목명에 "(테스트픽스처)" 명시, 005930/000660, 2026-08-11~2026-09-14 25거래일 합성 종가/거래량/PER/PBR/시가총액) — 실제 삼성전자/SK하이닉스 시세 아님
- 전제 조건: `alembic upgrade head`(0001~0006 전부 적용된 상태에서 시작), `pytest tests/unit` 112건 통과 확인 후 DB 레벨 검증 진행

## 4. 테스트 케이스 및 결과

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-001 | 정적 분석(백엔드) | 저장소 루트 | `python -m ruff check .` | 오류 0건 | `All checks passed!` | Pass | AC-10 |
| TC-002 | 전체 회귀(112건) | 위와 동일 | `python -m pytest tests/unit -q` | 112 passed | `112 passed, 1 warning in 1.89s` | Pass | AC-4. 세션 시작 시 독립 재실행(5단계 보고 재사용 아님) |
| TC-003 | compute.py 순수 함수 14건 이름 대조 | - | `pytest tests/unit/test_derivation_compute.py -v` | AC-1이 나열한 14개 시나리오(정상/음수/None×2, ma_gap 정상/부족/슬라이스, volume 정상/부족/표준편차0, rank 빈/내림/오름/동률) 전부 존재·통과 | 14개 테스트명이 AC-1 서술과 1:1 정확히 대응, 전부 PASSED | Pass | AC-1 |
| TC-004 | run_derivation.py 오케스트레이션 12건 이름 대조 | - | `pytest tests/unit/test_run_derivation.py -v` | AC-2가 나열한 12개 시나리오 전부 존재·통과 | 12개 테스트명이 AC-2 서술과 1:1 정확히 대응, 전부 PASSED | Pass | AC-2 |
| TC-005 | Public API metrics 7건 이름 대조 | - | `pytest tests/unit/test_public_api.py -v -k metrics` | AC-3이 나열한 7개 시나리오 전부 존재·통과 | 7개 테스트명이 AC-3 서술과 1:1 정확히 대응, 전부 PASSED | Pass | AC-3 |
| TC-006 | `_validation_passed` 5% 경계값 실제 코드 대조 | - | `test_validation_passed_below_threshold` 소스 열람 | 20건 중 1건 결측(정확히 5.0%)이 `<=` 임계치로 통과 처리됨 | 테스트가 정확히 1/20=5%를 넣고 `passed is True` 검증, `run_derivation.py`의 `missing/len(rows) <= MAX_MISSING_RETURN_PCT_RATIO` 구현과 일치 | Pass | AC-2 4번째 불릿. 6%(임계 초과) 케이스는 별도 테스트가 없으나 로직상 `<=` 부등호로 자명해 결함 아님(§5 커버리지 참조) |
| TC-007 | `raw_ohlcv` 스키마 컬럼 실측 — 원본 시세 컬럼 부재 확인 | alembic head | `\d public_serving.derived_metrics_daily` | open/high/low/close/volume 컬럼이 테이블에 존재하지 않음 | 컬럼 목록에 해당 필드 없음(stock_code/trade_date/market/return_pct/return_rank_pct/ma5_gap_pct/ma20_gap_pct/volume_anomaly_score/per_raw/pbr_raw/market_cap_raw_krw/per_percentile/pbr_percentile/market_cap_percentile/computed_at/batch_run_id만 존재) | Pass | **코디네이터 지시 ①**, §4-3 1차 방어(스키마 분리) 실측 확인 |
| TC-008 | `per_raw`/`pbr_raw`/`market_cap_raw_krw`가 API 응답 화이트리스트에서 제외되는지 소스 확인 | - | `services/public_api/schemas/metrics.py`(`StockMetricsData`) 및 `db/metrics_repository.py`(`DerivedMetricsRow`) 열람 | 두 곳 모두 이 3개 필드를 아예 선언하지 않음(직렬화될 코드 경로 자체가 없음) | 확인됨(§4-3 화이트리스트를 타입 레벨로 강제) | Pass | 코디네이터 지시 ① |
| TC-009 | `GET /stocks/005930/metrics` 실제 응답 바디에 원시값 없음 실측 | AC-7 픽스처 적재 후 | `TestClient`로 실제 호출 후 JSON 전체 필드 열람 | 응답에 `per_raw`/`pbr_raw`/`market_cap_raw_krw`/`open`/`close`/`volume` 등 원본·원시 필드가 전혀 없음 | 응답 필드가 `stock_code/name/market/return_pct/return_rank_pct/ma5_gap_pct/ma20_gap_pct/volume_anomaly_score/per_percentile/pbr_percentile/market_cap_percentile` 10개뿐, 원시값 0건 | Pass | 코디네이터 지시 ① — 스키마 레벨(TC-007/008)뿐 아니라 **실제 런타임 응답**까지 확인 |
| TC-010 | `rank_percentile()` 워크드 예제(03-system-design.md §3-2) 직접 재계산 | - | 2,500개 합성 종목(내림차순 값) 생성, 125위 종목의 `return_rank_pct` 계산 | `125/2500*100=5.0` | `Decimal('5.0')` 정확히 일치 | Pass | **코디네이터 지시 ②**. 5단계 note를 재사용하지 않고 6단계가 독립적으로 2,500건 데이터 생성해 재현 |
| TC-011 | `rank_percentile()` 동률 표준경쟁순위(1,1,3 패턴) 직접 재계산 | - | `[('a',10),('b',10),('c',5)]`, descending=True | a,b=33.3(공동1위, 2위 skip), c=100.0(3위) | `{'a': 33.3, 'b': 33.3, 'c': 100.0}` 정확히 일치 | Pass | 코디네이터 지시 ② |
| TC-012 | AC-6 불릿1: 활성 종목 0건 | `stock_master`/`raw_ohlcv` 완전히 빔(실제 운영 상태 그대로) | `python -m services.derivation_batch.run_derivation --trade-date 2026-09-14` | 종료코드 1, "활성 종목이 없습니다", `batch_run` 1행(FAILED) | 종료코드 1 확인, 메시지 정확히 일치, `batch_run` 조회 결과 FAILED 1행 정확히 기록 | Pass | AC-6. 5단계 보고 재사용 안 함 — 6단계가 직접 빈 상태에서 재실행 |
| TC-013 | AC-6 불릿2: 종목은 있으나 원본 시세 0건 | `stock_master`에 2종목만 삽입(`raw_ohlcv`는 빔) | 동일 CLI 재실행 | 종료코드 1, "원본 시세 데이터가 하나도 없습니다", `batch_run` 1행(FAILED) 추가 | 종료코드 1, 메시지 일치, `batch_run` 누적 2행(둘 다 FAILED) 확인 | Pass | AC-6. **이 시나리오가 `raw_ohlcv.market` ENUM 비교 쿼리(`fetch_ohlcv_window`)를 실제로 실행하는 경로임을 소스(`repository.py`/`run_derivation.py`) 대조로 확인** — 아래 TC-014로 이어짐 |
| TC-014 | `raw_ohlcv.market` ENUM 버그 수정 재현(코디네이터 지시 ③) | TC-013과 동일 상태 | TC-013 실행 시 `UndefinedFunction` 예외 발생 여부 관찰 + `raw_models.py` 소스 확인 | 예외 없이 정상적으로 "원본 시세 없음" 처리(비교 자체는 정상 실행됨) | 예외 발생 없음(정상 실패 메시지만 기록), `raw_models.py`의 `market` 컬럼이 `market_session_enum`(`reference.market_session` 재사용)으로 선언되어 있음을 소스로 확인 | Pass | **코디네이터 지시 ③.** TC-013의 쿼리가 `WHERE market = 'KRX'` 비교를 실제로 수행하는 지점이므로, 이 시나리오의 정상 통과 자체가 ENUM 수정이 실제로 유효함을 실증 |
| TC-015 | AC-7: 픽스처 적재 + 배치 실행 | 빈 `raw_internal`/`stock_master`(TC-013 데이터 정리 후) | `python scripts/dev_seed_fixture_metrics.py` → `run_derivation.py --trade-date 2026-09-14` | 종료코드 0(SUCCESS) | `[완료] status=SUCCESS trade_date=2026-09-14`, 종료코드 0 | Pass | AC-7 |
| TC-016 | AC-7: 계산값 정확성(005930/000660) | TC-015 직후 | `derived_metrics_daily` 직접 SELECT | 005930: return_rank_pct=50.0, 000660: return_rank_pct=100.0, ma5/ma20 부호가 추세와 일치, 005930 volume_anomaly_score 600대 | 005930: return_pct=4.5576/return_rank_pct=50.0/ma5=3.9446/ma20=6.7616/vol=604.3645, 000660: return_pct=-0.7687/rank=100.0/ma5=-0.8657/ma20=-2.4792/vol=1.1507 — note §7 로그와 **완전히 동일한 값**으로 재현 | Pass | AC-7. 재현성까지 확정(다른 세션, 동일 커밋된 스크립트로 동일 결과) |
| TC-017 | AC-7: `current_published_batch` 포인터 | TC-015 직후 | SELECT market, trade_date | `market='KRX', trade_date='2026-09-14'` | 정확히 일치 | Pass | AC-7 |
| TC-018 | AC-8: 정상 조회(최신 아님, 지연 감지) | TC-015 데이터 + 실제 시스템 날짜 2026-09-16 | `api_service`로 `TestClient` GET `/stocks/005930/metrics` | 200, TC-016 계산값과 일치, `is_latest_trading_day=false` + 정확한 지연 영업일수 | 200, 계산값 완전 일치, `is_latest_trading_day=false`, `expected_last_trading_day=2026-09-15`, `staleness_note="예상보다 1영업일 지연된 데이터입니다"` | Pass | AC-8. UTF-8 파일 출력으로 한글 깨짐 없이 확인(콘솔 codepage 이슈와 무관하게 원본 검증) |
| TC-019 | AC-8: 종목 없음 | - | GET `/stocks/999999/metrics` | 404 STOCK_NOT_FOUND | 정확히 일치 | Pass | AC-8 |
| TC-020 | AC-8: 발행 데이터 없음(포인터 삭제) | `current_published_batch` 행 삭제 | GET `/stocks/005930/metrics`(date 생략) | 503 DATA_PIPELINE_STALE | 정확히 일치 | Pass | AC-8 |
| TC-021 | AC-8: 명시적 date는 발행 포인터 우회 | TC-020과 동일 상태(포인터 없음) | GET `/stocks/005930/metrics?date=2026-09-14` | 200(포인터 없어도 우회) | 200, `return_pct=4.5576` 정상 반환 | Pass | AC-8. 이후 `run_derivation.py` 재실행으로 포인터 복원 확인 |
| TC-022 | AC-8: `api_service` 권한 경계(raw_internal SELECT) | - | `psql -U api_service`로 `SELECT * FROM raw_internal.raw_ohlcv` | `permission denied for schema raw_internal` | 정확히 일치 | Pass | AC-8, 1차/2차 방어 회귀 없음 |
| TC-023 | AC-8: `api_service` 권한 경계(derived_metrics_daily INSERT) | - | `psql -U api_service`로 INSERT 시도 | `permission denied` | `permission denied for table derived_metrics_daily` | Pass | AC-8 |
| TC-024 | AC-9: 정상 화면 렌더링(종단간) | `npm run build && npm run start`(3000) + `uvicorn`(8000, `NEXT_PUBLIC_API_BASE_URL` 연결) | `curl /stocks/005930` | 등락률 순위/5일·20일 이평/거래량 이상치/밸류에이션 3종 값이 TC-016과 정확히 일치해 렌더링, 지연 경고 문구 표시 | HTML에서 "상위 50%", "+3.9%"/"+6.8%"(상승 클래스 적용), "604.4", PER/PBR/시가총액 "상위 50%" 각각 확인, "예상보다 1영업일 지연된 데이터입니다" 렌더링 확인 | Pass | AC-9 |
| TC-025 | AC-9: 원본 시세 화면 미노출(교차검증) | TC-024와 동일 | 렌더링된 HTML 전체 검토 | 캔들차트/시가·고가·저가·종가 원문 표 없음(카드 5종만) | `page.tsx` 소스 및 렌더링 결과 모두 MetricCard 5종 외 원본 시세 테이블/차트 요소 없음 | Pass | §4-3 원칙의 화면 레벨 확인(코디네이터 지시 ①의 프론트엔드 대응) |
| TC-026 | AC-9: 404 커스텀 화면 | - | `curl /stocks/999999` | "요청하신 종목 정보를 찾을 수 없습니다" + "종목 검색으로 돌아가기" CTA | 정확히 일치, `disclaimer-banner`/`GlobalNav` 함께 렌더링 확인 | Pass | AC-9 |
| TC-027 | 404 실제 HTTP 상태 코드 실측(코디네이터 지시 ⑤) | TC-026과 동일 | `curl -o /dev/null -w "%{http_code}"` | (note가 예고한 대로) 200 | **실측 200 확인**, `<meta name="robots" content="noindex">` 존재 확인 | Pass(정보성) | 아래 §6/§7 "소프트 404" 판단 참조 — AC-9는 화면 내용만 요구하고 HTTP 상태코드를 명시하지 않아 AC 위반은 아님 |
| TC-028 | AC-9: EmptyState(발행 데이터 없음) | `current_published_batch` 행 삭제 | `curl /stocks/005930` | "표시할 데이터가 아직 없습니다. 서비스 데이터 준비 중입니다." | 정확히 일치, `disclaimer-banner`/`GlobalNav` 함께 렌더링 확인 | Pass | AC-9. 이후 `run_derivation.py` 재실행으로 포인터 복원 |
| TC-029 | REQ-006 회귀: `DataFreshnessBadge` 실 데이터 연결 | TC-024와 동일 | 렌더링 결과에서 지연 경고 확인(TC-024에 포함) | 백엔드 `staleness_note`를 그대로 표시(자체 계산 없음) | 확인됨(컴포넌트 자체 계산 없이 서버 값 그대로 표시, 소스 대조) | Pass | **코디네이터 지시 ④** |
| TC-030 | REQ-007 회귀: 면책 배너 상시 노출 | TC-024/026/028 전부 | 각 화면 HTML에서 `disclaimer-banner`/문구 존재 확인 | 3개 화면 모두 노출 | 3개 화면 모두 노출 확인(TC-024/026/028에 포함) | Pass | **코디네이터 지시 ④** |
| TC-031 | AC-3 5번째 불릿: 종목은 있으나 그 날짜 지표 행 없음 | TC-015 데이터 존재 | GET `/stocks/005930/metrics?date=2026-01-01` | 200 + 전 지표 필드 null | 200, `return_pct`~`market_cap_percentile` 전부 `null`, `stock_code`/`name`/`market`은 정상 값 | Pass | AC-3 |
| TC-032 | AC-3 7번째 불릿: 잘못된 날짜 형식 | - | GET `/stocks/005930/metrics?date=2026-13-99` | 400 INVALID_PARAMETER | 정확히 일치(Pydantic 파싱 오류 메시지 포함) | Pass | AC-3 |
| TC-033 | 위험 기반: 빈/공백 종목코드 | - | GET `/stocks//metrics`, GET `/stocks/%20/metrics` | 크래시 없이 명시적 에러(404 계열) | 둘 다 404, 후자는 `STOCK_NOT_FOUND` + 원인 코드 그대로 노출, 500 없음 | Pass | AC 범위 밖, 위험 기반 추가 — 결함 미발견 |
| TC-034 | REQ-009 회귀: 인증 헤더/쿠키/미지 파라미터 무관성(신규 API) | 005930 존재 | `Authorization`/`session_id`/`user_id` 쿠키 부착 요청 vs 미부착 요청, `?user_id=` 추가 요청 비교(타임스탬프 필드 정규화 후 비교) | 완전히 동일한 응답 | 최초 비교는 `generated_at` 타임스탬프 차이로 `False`가 나왔으나(가짜 양성), 타임스탬프 필드를 정규화한 재비교에서 `True`(완전 동일) | Pass | **traceability.md가 명시한 "신규 API마다 반복해야 할 검증"** 이행. 최초 결과가 오탐이었음을 원인 규명까지 완료(테스트 설계 자체의 함정을 스스로 재검증) |
| TC-035 | `-0%` 포맷 경계 | - | `formatSignedPercent(-0)` 소스 분석(JS `-0 < 0`은 false, `-0 > 0`도 false) | 부호 없는 "0.0%" 반환(음수 부호 버그 없음) | 로직 분석 결과 `sign=""`, `Math.abs(-0)=0` → `"0.0%"` — 버그 없음 | Pass | 위험 기반 추가, 코드 정적 분석으로 확인(런타임 재현은 별도 스크립트 불필요할 만큼 로직이 단순·명확) |
| TC-036 | AC-5: 마이그레이션 적용 | alembic 0005 상태에서 시작(0006 이미 적용된 상태였으므로 재확인 목적) | `alembic current` | `0006 (head)` | `0006 (head)` 확인 | Pass | AC-5 |
| TC-037 | AC-5: downgrade/upgrade 사이클 | - | `alembic downgrade 0005` → `\dt public_serving.*` → `alembic upgrade head` | downgrade 시 두 테이블 완전 제거, upgrade 시 오류 없이 복원 | downgrade 후 `stock_master`/`batch_run`만 남고 `derived_metrics_daily`/`current_published_batch` 제거 확인, upgrade 후 정상 재생성 | Pass | AC-5 |
| TC-038 | AC-5: GRANT 재적용 확인 | TC-037 upgrade 직후 | `\dp public_serving.derived_metrics_daily`, `\dp public_serving.current_published_batch` | `batch_worker=arw`, `api_service=r` 둘 다 | 두 테이블 모두 정확히 일치 확인 | Pass | AC-5 |
| TC-039 | `SqlCalendarRepository` 승격 회귀 — import 경로 소스 확인 | - | `services/public_api/db/calendar_repository.py`, `services/ingestion_batch/calendar_lookup.py` 소스 열람 | 두 파일 모두 `shared.calendar_service.sql_repository`를 재노출만 하고 자체 구현이 없음 | 확인됨(각 9~13줄짜리 얇은 re-export) | Pass | 코디네이터 지시 ⑤(소스 레벨 재확인) |
| TC-040 | `SqlCalendarRepository` 승격 회귀 — 런타임 확인 | - | 위 TC-018~023(Public API가 `services.public_api.db.calendar_repository.SqlCalendarRepository`를 통해 실제로 캘린더를 조회해 424/staleness 계산에 성공) | 재노출 경로가 실제로 정상 동작 | TC-018의 `expected_last_trading_day`/`staleness_note` 계산이 이 경로를 통해 실제로 성공적으로 수행됨 | Pass | 코디네이터 지시 ⑤. `run_ingestion.py`/`seed_stock_master.py`는 이번 유닛에서 직접 재실행하지 않았으나(범위 밖 회귀는 79건 기존 테스트로 커버, TC-002), import 경로 자체는 TC-039로 확정 |
| TC-041 | 정적 분석(프론트엔드) | - | `npx tsc --noEmit`, `npm run lint` | 오류 0건 | 둘 다 출력 없이 통과(오류 0) | Pass | AC-10 |
| TC-042 | 프로덕션 빌드 + 라우트 확인 | - | `npm run build`(prebuild 포함) | 성공, `/stocks/[code]`가 Dynamic 라우트로 포함 | "금지표현 검사 통과(검사 파일 25개)" → 빌드 성공 → 라우트 표에 `ƒ /stocks/[code]` 확인 | Pass | AC-10 |
| TC-043 | REQ-001 시퀀싱 공백 인지 확인 | - | `unit-06-note.md` §8 마지막 문단 검토 | 공백이 명시적으로 기록되어 있고 6단계가 이를 해결하려 시도하지 않음 | 노트에 명시적으로 기록됨, 이 테스트서 §7에도 그대로 인지만 기록(해결 시도 없음) | Pass(인지 완료) | 코디네이터 지시 ⑥ — 오케스트레이터 이관 사항 |

## 5. 커버리지
- 인수 조건(AC-1~AC-10) 커버리지: **10/10 (100%)** — 각 AC의 모든 불릿에 대응하는 TC가 최소 1개 이상 존재(추적표는 아래 참조)
  - AC-1→TC-003, AC-2→TC-004/006, AC-3→TC-005/031/032, AC-4→TC-002, AC-5→TC-036~038, AC-6→TC-012/013, AC-7→TC-015~017, AC-8→TC-018~023, AC-9→TC-024~028/030, AC-10→TC-001/041/042
- 코디네이터 지시 6개 항목 커버리지: **6/6** — ①TC-007~009/025, ②TC-010/011, ③TC-013/014, ④TC-024/029/030, ⑤TC-027(판단은 §7), ⑥TC-043
- 커버되지 않은 부분과 사유:
  - PER/PBR/시가총액 percentile의 실 규모(~2,500종목) 동률/경계 검증 — `raw_fundamentals` 실 데이터 부재(UNIT-02 범위 제한)로 물리적으로 불가능. 계산식 자체(TC-010/011)는 100% 검증됨.
  - `_validation_passed`의 "5% 초과 시 실패" 경계값(예: 6/100=6%)의 별도 실측 테스트는 추가하지 않음 — 코드 로직(`<=` 부등호)이 단순 산술 비교라 5.0%(TC-006) 통과 확인만으로 초과 시 실패는 자명하다고 판단(2차 검증에서 재검토, §9 참조).
  - `run_ingestion.py`/`scripts/seed_stock_master.py`의 실제 CLI 재실행을 통한 승격 회귀 확인 — 기존 79개 자동화 테스트(TC-002에 포함)와 import 경로 소스 확인(TC-039)으로 대체, 실제 CLI 수동 재실행은 UNIT-01/02 담당 범위와 중복이라 생략(위험 낮음으로 판단)

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도(Critical/High/Medium/Low) | 상태(Open/Fixed/Deferred) | 조치 내용 |
|----|------|-----------|-----------------------------------|----------------------------|-----------|
| DEF-010 | `/stocks/{code}` 라우트가 `loading.tsx`(Suspense 자동 경계) 존재로 인해 `notFound()` 호출 시 실제 HTTP 상태 코드가 200으로 응답됨(소프트 404). Next.js 16 공식 문서화된 프레임워크 트레이드오프이며 `noindex` 메타 태그는 자동 부여됨(TC-027 실측). | `curl -o /dev/null -w "%{http_code}" http://localhost:3000/stocks/999999` → 200 (본문은 정상 커스텀 404 화면) | Low | Deferred | 코드 결함이 아니라 설계 트레이드오프. §7 판단 참조 — 현 시점에서는 수정하지 않고 리스크로만 기록. `loading.tsx` 제거 시 해결 가능하나 로딩 스켈레톤(04-ux-design.md §2-4 요구사항)을 포기해야 함 |

- **그 외 결함 없음.** 근거: §4 TC-001~TC-043(총 43개 테스트 케이스, AC 10개 전항목 + 코디네이터 지시 6개 항목 + 위험 기반 6개 항목)이 전부 Pass. 특히 코디네이터가 "5단계 자체 검증을 신뢰하지 말라"고 명시한 5개 핵심 항목(원본 미노출/방향성/ENUM버그/REQ-006·007/EmptyState·ErrorState)을 전부 실 DB·실 HTTP·실 렌더링으로 재현해 5단계 note의 수치·문구와 정확히 일치함을 확인했다(TC-016 등).

## 7. 리스크 및 잔존 이슈
- **DEF-010(소프트 404) 판단**: 20년차 QA/개발 관점에서, 이 이슈는 (a) AC-9가 HTTP 상태 코드를 명시적으로 요구하지 않아 AC 위반은 아니고, (b) `noindex`가 자동 부여되어 SEO 오염(검색엔진이 존재하지 않는 종목 페이지를 인덱싱하는 것) 리스크는 실질적으로 차단되지만, (c) 향후 운영 모니터링(업타임/에러율 대시보드)이 HTTP 상태 코드 기반으로 이상 탐지를 한다면 "종목 대량 조회 실패"가 4xx/5xx 급증으로 잡히지 않고 200으로 은폐될 수 있다는 잠재 리스크가 있다. 이는 코드 버그가 아니라 **loading.tsx(로딩 스켈레톤 UX) vs 정확한 HTTP 상태 코드** 사이의 사업적 트레이드오프이며, 되돌리기 쉬운 결정(loading.tsx 파일 삭제/복원)이라 규칙 A의 "비가역적 결정" 기준에는 해당하지 않는다고 판단했다. **결론: 이번 유닛의 PASS 판정을 막는 결함으로 취급하지 않되(Low/Deferred), 9단계(보안/SEO 검증) 및 운영 모니터링 설계 시점에 재확인이 필요한 항목으로 명시적으로 인계한다.** 코디네이터가 다른 판단(즉시 수정 강제)을 원하면 규칙 A에 따라 재지시 바란다.
- **PER/PBR/시가총액 percentile 실 규모 미검증**: `raw_fundamentals`가 실제로 적재되기 전까지는 2종목 픽스처 검증(TC-016)이 유일한 실측 근거다. UNIT-02가 이 테이블을 채우는 로직을 구현하면(범위 확장 시) 반드시 재검증이 필요하다.
- **PER≤0(적자기업 등) 결측 처리 규칙의 책임 경계**: 03-system-design.md §3-2는 "PER≤0은 null로 저장"을 명시하지만, 이 규칙이 실제로 적용되는 지점은 `raw_fundamentals` 적재(Ingestion Batch, UNIT-02 소관)이지 Derivation Batch(`compute.py`/`run_derivation.py`)가 아니다 — Derivation Batch는 `fundamentals.per`를 그대로 통과시킬 뿐 자체적으로 PER≤0을 필터링하지 않는다(소스 확인). `raw_fundamentals`가 실제로 적재되지 않은 현재 상태(§2 제외범위)라 이 경계 자체를 실측할 데이터가 없다 — UNIT-02가 이 컬럼을 채우는 로직을 구현하는 시점에 어느 유닛이 이 규칙을 실제로 구현했는지 재확인이 필요하다(2차 내부검증에서 발견, `verify-log_unit-06-test.md` 참조).
- **REQ-001 시퀀싱 공백(코디네이터 지시 ⑥, 그대로 인계)**: `02-planning.md` §9 작업 단위 목록에 REQ-001(종목 검색)의 **프론트엔드 화면**을 배정한 유닛이 없다. `/stocks`(검색 목록)는 UNIT-05의 플레이스홀더 상태로 남아 있어, 사용자가 UI만으로 종목 코드를 몰라도 `/stocks/{code}`(이번 유닛)에 도달할 UI 경로가 없다. **6단계는 이 공백을 해결하지 않으며, 어느 유닛에 배정할지는 오케스트레이터가 결정해야 한다** — unit-06-note.md §8이 이미 이 사실을 기록했고, 이 테스트서도 그대로 인지만 기록한다(TC-043).
- **`SqlCalendarRepository` 승격의 CLI 레벨 실제 재실행 미검증**: import 경로 소스 확인(TC-039)과 기존 79개 자동화 테스트 재통과(TC-002)로 회귀 없음을 확인했으나, `run_ingestion.py`/`scripts/seed_stock_master.py`를 실제로 CLI 재실행해 승격 이후에도 동일하게 동작하는지는 이번 6단계에서 직접 재현하지 않았다(UNIT-01/02가 이미 검증한 CLI 경로와 중복 실행이라 판단, 위험 낮음). UNIT-07/08이 이 재노출 경로를 추가로 사용하게 되면 그때 재확인 권장.
- **Derivation Batch cron 스케줄링/컨테이너 배포**: note와 동일하게 10단계 영역으로 남긴다.

## 8. 결론 및 판정
- [x] PASS — 다음 단계 진행 가능
- [ ] CONDITIONAL PASS — 조건:
- [ ] FAIL — 사유 및 재작업 요청 사항:

**판정 근거**: AC-1~AC-10 전 항목과 코디네이터 지시 6개 항목을 5단계의 자체 보고를 신뢰하지 않고 독립적으로(실 PostgreSQL 쿼리, 실 HTTP 호출, 실 렌더링 HTML 검사) 재현했다. 43개 테스트 케이스 전부 Pass, 결함은 DEF-010(Low, Deferred, AC 비위반, 코드 버그 아닌 프레임워크 트레이드오프) 1건뿐이며 배포 차단 사유가 아니다. 특히 REQ-022(데이터 라이선스 준수)의 핵심인 "원본 시세 재게시 금지"가 스키마(TC-007)·타입 계약(TC-008)·실제 런타임 응답(TC-009)·화면(TC-025) 네 겹 모두에서 실측 확인됐고, `return_rank_pct` 방향성이 설계서 워크드 예제와 정확히 일치(TC-010)함을 확인했다. **다음 단계(07 업무단위 통합테스트)로 진행 가능.**

## 9. 내부 검증 (최소 2회, `verification-log-template.md` 사용)
- 1차 검증 결과 요약: 작성자(6단계) 관점 자가 재검토 — AC 10개 전항목과 코디네이터 지시 6개 항목의 커버리지가 TC 목록과 1:1 대응함을 표(§5)로 재확인. 결함 없음 판정에 근거(43개 TC Pass)가 있음을 확인. 오탈자/형식 점검 완료.
- 2차 검증 결과 요약: 독립 심사자 관점 — "이 테스트를 07단계에 넘겨도 되는가"를 의심하며 재검토한 결과, ①`_validation_passed` 6% 초과 경계 미실측(§5에 사유 명시, 낮은 위험으로 수용), ②REQ-009 재검증에서 최초 비교가 타임스탬프 차이로 인한 가양성이었음을 스스로 발견하고 원인까지 규명(TC-034)해 테스트 설계 결함을 자체 교정, ③DEF-010의 심각도 판단(Low/Deferred, AC 비위반 근거 명시)이 타당함을 재확인. 2차 검증에서 추가 결함은 발견되지 않았다.
- 검증 로그 파일 경로: `docs/harness/units/verify-log_unit-06-test.md`
