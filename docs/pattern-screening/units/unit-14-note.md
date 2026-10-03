# UNIT-14 구현 노트 및 내부 테스트 결과서 — 스키마·배치 통합 (REQ-030, REQ-035)

- 작성: 2026-10-02 14:2x KST · 대상: 마이그레이션 0011, ORM 모델, derivation repository·`run_derivation` 확장 · 관련: 02 설계서 §2·§3-1·§8·§9, 05 테스트계획 §5(TC-D01~D08)
- **결론: 구현·테스트 완료(신규 20건 통과, 전체 회귀 0). 개발 DB(`stock_screener`)에는 사용자 승인 후 0011을 적용했고 기존 API 정상을 확인했다(§6-1). 개발 DB 쓰기는 이 마이그레이션(컬럼 추가)뿐이며 데이터 변경은 없다.**

## 1. 구현 요약

| 구분 | 파일 | 변경 |
|---|---|---|
| 신규 | `db/alembic/versions/0011_add_pattern_metrics_to_derived_metrics_daily.py` | 컬럼 11개 추가(전부 nullable) + `pattern_metrics_status` CHECK(`OK`/`INSUFFICIENT_HISTORY`/`SUSPECT_PRICE_JUMP`). `downgrade`로 가역. GRANT 추가 없음(0007과 같은 근거, 실제 역할로 검증 — TC-D05) |
| 수정 | `shared/db_models/public_serving.py` | `DerivedMetricsDaily`에 11개 `Mapped` 컬럼 + `CheckConstraint`(`SmallInteger` import 추가) |
| 수정 | `services/derivation_batch/repository.py` | `OHLCV_WINDOW_SIZE` 41 → `PATTERN_WINDOW_ROWS`(100), `DerivedMetricsInput`·`upsert_derived_metrics`(INSERT 값 + `ON CONFLICT DO UPDATE` 목록)에 11개 컬럼 추가 |
| 수정 | `services/derivation_batch/run_derivation.py` | `StockDayMetrics`에 11개 필드(기본값 None), `compute_stock_day_metrics`가 `compute_pattern_metrics` 호출, `build_derivation_inputs`가 전달. **`_validation_passed` 불변** |
| 신규(테스트) | `tests/unit/test_run_derivation_pattern.py`(11건), `tests/integration/test_pattern_derivation_db.py`(9건), `tests/integration/pattern_fixtures.py`(픽스처 T00001~T00010, UNIT-16 재사용), `pg_temp_db.py`에 `run_alembic()` 추가 | |

- 기존 `compute_stock_day_metrics`의 기존 지표 계산 로직은 한 줄도 바꾸지 않았다(패턴 호출과 필드 전달만 추가). 기존 지표 함수는 앞쪽 필요한 행만 슬라이스하므로 윈도우가 100행이 되어도 값이 같다(TC-D08로 증명).
- `compute_pattern_metrics`는 이력 부족·단절 의심이어도 예외 없이 상태만 채워 반환하므로 배치 전체가 한 종목 때문에 중단되지 않고, 발행 판단(`_validation_passed`: `return_pct` 결측 5%)에도 영향을 주지 않는다.
- 픽스처 T00001~T00010: 05 §1-1의 의도대로 설계했고 기준 구현(오라클)으로 기대 판정을 검증한다(`test_fixture_series_match_design_intent`) — T00001 전 조건 충족, T00002 c1 미충족, T00003 c2, T00004 c3, T00005 c4(`EXTENDED`, 8일 전 돌파), T00006 c5(거래량 8배), T00007 c9(급등 이력), T00008 이력 부족, T00009 단절, T00010 평탄(c1·c3·c9 true, c4 false, **c2·c5 null** = 3값 논리).

## 2. 문서와 달라진 점·구현 중 판단 (편차 기록)

| # | 내용 | 영향 |
|---|---|---|
| 1 | 설계서는 `OHLCV_WINDOW_SIZE`를 "`PATTERN_WINDOW_ROWS`(100)로 대체"라고 했다. 이름은 유지하고 값만 `PATTERN_WINDOW_ROWS`로 대입(`OHLCV_WINDOW_SIZE = PATTERN_WINDOW_ROWS`) | 기존 import(`repository.__all__`) 호환. 의미는 동일 |
| 2 | 설계서 §3-1은 CHECK 제약 이름을 정하지 않았다. `ck_derived_metrics_daily_pattern_metrics_status`로 명명 | 모델과 마이그레이션이 같은 이름 사용 |
| 3 | `ma60_cross_up_days`에 0~9 범위 CHECK는 **추가하지 않았다**(설계서에 없음) | 계산 코드가 범위를 보장(관찰창 10일). 필요하면 별도 결정 |
| 4 | 05 TC-D04는 "130행 픽스처로 run_once 2회 실행 → 동일"이다. 여기에 **재실행이 낡은 값을 실제로 덮어쓰는지**(ON CONFLICT 갱신 대상 포함)를 확인하는 테스트를 추가했다 | 같은 입력 재실행만으로는 UPDATE 목록 누락을 못 잡기 때문 |
| 5 | D05는 `api_service` 비밀번호 없이 슈퍼유저 세션에서 `SET ROLE api_service`로 검증했다(권한 판정은 동일). `batch_worker`는 실제 접속 계정으로 `run_once`가 성공함으로써 검증 | 비밀번호를 쓰지 않음 |

문서의 임계값·계산 정의는 바꾸지 않았다.

## 3. 테스트 결과 (실제 실행 출력)

실행: `py -3.12`, 2026-10-02 14:1x~14:2x KST.

### 3-1. 요약

| 구분 | 변경 전 | 변경 후 | 판정 |
|---|---|---|---|
| `pytest tests/unit` | 287 passed | **298 passed**(+11) | PASS, 신규 실패 0. 기존 `test_run_derivation.py`·`test_market_summary_compute.py` 무수정 통과 |
| `pytest tests/integration` | 15 passed | **24 passed**(+9) | PASS |
| `ruff check shared services scripts tests db` | — | `All checks passed!` | PASS |
| 임시 DB 잔여 | — | 0개(모든 실행 후 확인) | 정리 완료 |
| 개발 서버(DB·4000·4001) | — | 켜 둠(재시작하지 않음) | 유지 |

### 3-2. TC별 결과 (05-test-plan §5)

| TC | 시나리오 | 검증 | 결과 |
|---|---|---|---|
| D01 | `upgrade head`→`downgrade 0010`→`upgrade head` 가역, 컬럼 11개 생성/삭제 | `test_d01_d03_…` — 독립 임시 DB에서 head의 11개 컬럼(**타입 포함**) 확인 → downgrade 후 11개 전부 부재·기존 컬럼 보존 → upgrade 후 재생성 | PASS |
| D02 | CHECK 제약 | `test_d02_…` — `'BAD'` INSERT는 `IntegrityError`, `OK`/`INSUFFICIENT_HISTORY`/`SUSPECT_PRICE_JUMP`/`NULL`은 허용 | PASS |
| D03 | nullable·구 행 | `test_d01_d03_…` — 0010 상태에서 넣은 구 행이 upgrade 후 보존(`return_pct=1.5`)되고 신규 11개 컬럼은 전부 NULL | PASS |
| D04 | `run_once` 멱등 | `test_d04_d06_…`(10종목, 2회 실행: 행 수·11개 컬럼 값 불변) + `test_d04_rerun_overwrites_stale_pattern_columns_…`(낡은 값 11개를 주입한 뒤 재실행 시 전부 복구) | PASS |
| D05 | 권한 | `test_d05_…` — `api_service`: 신규 컬럼 SELECT 가능(10행), INSERT·UPDATE(상태)·UPDATE(신규 컬럼)·DELETE 전부 `permission denied`, `raw_internal` 접근 거부(DEC-006 유지). `batch_worker`: 신규 컬럼 포함 upsert 성공(`run_once`가 이 계정으로 실행됨) | PASS |
| D06 | 혼합 상태 발행 | `test_d04_d06_…` — T00001~T00010 혼합에서 `SUCCESS`, `current_published_batch`가 대상 거래일로 갱신, 상태별 컬럼 값(이력 부족=지표 NULL, 단절=전부 NULL) 확인 | PASS |
| D07 | `_validation_passed` 불변 | `test_d07_all_history_short_…`(전 종목이 이력 부족이어도 `SUCCESS`·발행 1건) + 단위 `test_d07_validation_passed_ignores_pattern_metrics`(5% 경계: 패턴 상태와 무관하게 6% 결측이면 실패) | PASS |
| D08 | 기존 지표 무변화 | 단위 `test_d08_…[0..4]`(41행 vs 100행 윈도우에서 기존 8개 필드 동일, 시드 5종) + DB `test_d08_existing_metrics_in_db_…`(10종목의 `return_pct`·MA 괴리율·거래량 이상치·`volume_raw`·시가총액이 41행 이하만 쓴 직접 계산과 동일) | PASS |
| (추가) | 배치→DB 경로 종단 | `test_stored_pattern_values_match_oracle_for_fixture_stocks` — DB에 저장된 패턴 지표가 오라클과 허용오차 내 일치 | PASS |
| (추가) | 픽스처 의도 검증 | `test_fixture_series_match_design_intent` | PASS |
| (추가) | 윈도우·입력 규약 | `test_window_size_is_pattern_window_and_covers_existing_41`, `compute_stock_day_metrics` 패턴 필드 전달, 이력 부족 시 기존 지표 정상 계산, `StockDayMetrics` 기존 방식 생성 호환, `build_derivation_inputs` 11개 필드 전달 | PASS |

### 3-3. 테스트 유효성 검증 (변이 테스트)

구현 9곳을 하나씩 훼손해 위 테스트(+기존 `test_run_derivation.py`)가 실패하는지 확인했다. **8/9 적발**, 모든 변이 후 소스 내용이 원본과 동일함을 확인했다.

| # | 변이 | 결과 |
|---|---|---|
| 1 | 윈도우 100 → 41 | 적발 |
| 2 | `build_derivation_inputs`에서 `recent_surge_flag` 전달 누락 | 적발 |
| 3 | upsert INSERT 값에서 `ma60_cross_up_days` 누락 | 적발 |
| 4 | `ON CONFLICT` 갱신 목록에서 `pattern_metrics_status` 누락 | 적발 |
| 5 | `ON CONFLICT` 갱신 목록에서 `volume_ratio_5_60` 누락 | 적발 |
| 6 | 마이그레이션에서 CHECK 제약 생성 제거 | 적발 |
| 7 | `downgrade`에서 CHECK 제약 명시 삭제 제거 | **생존 — 동등 변이** |
| 8 | `_validation_passed`가 패턴 상태에 의존하도록 변경 | 적발 |
| 9 | `compute_stock_day_metrics`가 `pattern_metrics_status`를 전달하지 않음 | 적발 |

- #7이 살아남은 이유: PostgreSQL은 컬럼을 `DROP COLUMN`하면 그 컬럼만 참조하는 CHECK 제약을 함께 제거한다(임시 테이블로 실제 확인: 컬럼 삭제 후 제약 0개). 즉 명시적 `drop_constraint`는 동작에 영향이 없는 중복이며, 의도를 드러내려고 코드에 남겨 둔다. 테스트 결함이 아니다.

## 4. 성능 측정 (TC-P03 선행 자료, 설계서 §8)

임시 DB, 합성 400종목 × 130거래일, `run_once` 3회 중앙값(로컬 PostgreSQL, 컨테이너):

| 구성 | 실행 시간(중앙값) |
|---|---|
| 변경 전(41행 윈도우, 패턴 계산 없음) | 1.63 s |
| 변경 후(100행 윈도우 + 패턴 계산) | 1.93 s |
| 비율 | **1.19배** |

- 개발 DB 규모(약 2,880종목)로 선형 외삽: 변경 전 약 12초 → 변경 후 약 14초(**증가 약 2초**). 일일 배치 스케줄 창에 비해 무시 가능. (외삽이며 실제 2,880종목 실측은 아님. 쿼리 수는 종목당 1회로 동일, 행 수만 2.4배.)
- 설계서 §8의 "벌크 조회 최적화"는 이 측정 결과로 불필요하다고 판단한다(범위 밖 개선 유지).

## 5. 보안·품질 점검

| 항목 | 결과 |
|---|---|
| 응답 노출 | 이번 유닛은 API를 건드리지 않음. 신규 컬럼은 비율·배수·일수·불리언뿐이며 가격 원문 컬럼 없음(§4-3 유지) |
| 권한 경계 | `api_service`는 SELECT만, `raw_internal` 불가(D05). `batch_worker`만 쓰기 |
| 비밀 | 코드·테스트·문서에 키 없음. 임시 DB 접속 문자열 비출력 |
| 신규 의존성 | 0 |
| 기존 코드 변경 | 추가 위주. 변경 라인은 윈도우 상수 1곳과 import 정리뿐 |
| 개발 DB 쓰기 | **0건**(임시 DB만 사용) |

## 6. 남은 위험과 사용자 결정 필요 사항

### 6-1. 개발 DB 스키마와 코드의 불일치 — **해결됨(사용자 승인 후 0011 적용, 2026-10-02 14:25)**
- 문제: 개발 DB `stock_screener`가 0010인 채 코드만 11개 컬럼을 쓰도록 바뀌면, `GET /screen`·`GET /stocks/{code}/metrics`(둘 다 `select(DerivedMetricsDaily)`로 전체 컬럼 조회)가 백엔드 재시작 시 오류가 나고, 다음 일일 배치(2026-10-03 07:00)의 Derivation 단계가 INSERT 실패한다.
- 조치(사용자 선택: "적용 승인"): `alembic upgrade head`로 0010 → 0011 적용.
- 적용 전후 검증(실제 출력):

| 항목 | 적용 전 | 적용 후 |
|---|---|---|
| `alembic_version` | 0010 | **0011** |
| `derived_metrics_daily` 컬럼 수 | 17 | **28**(+11) |
| 행 수 / 기간 | 5,521 / 2026-09-14~09-21 | 5,521 / 2026-09-14~09-21 (불변) |
| 신규 컬럼에 값이 있는 행 | — | **0**(전부 NULL, 구 배치 행) |
| CHECK 제약 `ck_derived_metrics_daily_pattern_metrics_status` | 없음 | 존재 |
| `GET /screen?market=KOSPI` | 200 | 200 |
| `GET /stocks/005930/metrics` | 200 | 200 |
| 프론트 `/screener` | 200 | 200 |

- 새 코드(ORM 모델)가 실제 개발 DB에서 읽히는지: 실제 `api_service` 계정으로 `select(DerivedMetricsDaily)`(전체 컬럼) 성공, 5,521행 조회, 신규 컬럼 값 NULL 확인.
- 서버는 재시작하지 않았고 계속 켜 둔 상태다(재시작 시에도 이제 정상 동작 기대 — 새 코드로 재시작한 실측은 아직 없음).
- 다음 일일 배치(2026-10-03 07:00)에서는 패턴 지표가 `INSUFFICIENT_HISTORY`(보유 25거래일 < 80)로 기록될 것으로 예상된다(백필 전).

### 6-2. 그 외
1. 실제 데이터(80거래일 이상)가 아직 없어 개발 DB에서는 패턴 지표가 `INSUFFICIENT_HISTORY`로 채워질 것이다(백필 후 정상화). 백필 실행은 호출 한도 확인 대기 중.
2. 외삽 성능 수치는 UNIT-18의 TC-P03에서 실제 규모 근사 데이터로 다시 기록한다.
3. 설계서 §2 변경 지도에는 `pattern_fixtures.py`·`run_alembic` 등 테스트 보조 파일이 없다 — 문서 갱신은 UNIT-18.
