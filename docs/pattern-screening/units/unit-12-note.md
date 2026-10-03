# UNIT-12 구현 노트 및 내부 테스트 결과서 — 과거 시세 백필 (REQ-031)

- 작성: 2026-10-02 14:0x KST · 대상: `scripts/backfill_ohlcv.py`(신규) · 관련 문서: 02 설계서 §7, 05 테스트계획 §4(TC-B01~B08)
- **결론: 코드·테스트 완료(41건 전부 통과). 실제 API 백필은 아직 실행하지 않았다 — 사용자가 "일일 호출 한도 확인 후 실행"을 선택해 한도 값 대기 중. TC-B08(실데이터 완료 검증)은 미실행.**

## 1. 구현 요약

| 구분 | 파일 | 내용 |
|---|---|---|
| 신규 | `scripts/backfill_ohlcv.py` | 백필 CLI. 인자 `--days`(기본 130)/`--from`/`--to`/`--sleep`(0.3)/`--max-calls`/`--dry-run` |
| 수정(승인됨) | `services/ingestion_batch/batch_run_repository.py` | `recent_ingest_statuses`가 `error_summary`가 `BACKFILL`로 시작하는 행을 제외(+상수 `BACKFILL_ERROR_SUMMARY_PREFIX`). 아래 §3-1 |
| 신규 | `tests/unit/test_backfill_ohlcv.py` | 순수 로직 28건 |
| 신규 | `tests/integration/test_backfill_ohlcv_db.py` | 임시 DB 통합 13건 |
| 신규 | `tests/integration/pg_temp_db.py` | 임시 DB 생성→`alembic upgrade head`→finally DROP 헬퍼 |

- 재사용(수정 없음): `run_ingestion._fetch_all_ohlcv`(페이지네이션), `repository.upsert_ohlcv`, `GovDataPortalClient`. `run_once()`는 쓰지 않음(재무지표·날짜별 batch_run 때문 — 설계서 §7).
- 동작: KRX 거래일을 최신→과거로 순회 → 날짜당 전 페이지 수신 후 한 번에 upsert·**날짜 단위 커밋**(저장 실패 시 해당 날짜 전체 롤백) → `batch_run` 1행(`run_type='ingest'`, `error_summary`는 `BACKFILL…`).
- 호출 상한·간격은 `ThrottledClient`가 담당: 상한 초과 호출은 외부로 나가지 않고, 호출 사이에만 sleep. 세는 단위는 논리 페이지 요청(`GovDataPortalClient` 내부 재시도 HTTP는 별도).
- 서비스키: 모든 출력(stdout/stderr/`error_summary`)이 `mask_secrets`를 통과(키 원문·URL 인코딩 형태·`serviceKey=` 값).
- 비정상 종료(Ctrl-C 포함): `BaseException` 처리로 `batch_run`을 `FAILED/BACKFILL(중단)`으로 마감. 프로세스가 강제 종료돼도 시작 시 `BACKFILL(진행 중)` 표식이 이미 있어 서킷브레이커에서 제외됨.

## 2. 문서와 달라진 점·구현 중 판단 (편차 기록)

| # | 내용 | 근거 / 영향 |
|---|---|---|
| 1 | **설계서 §7·D-8의 "batch_run을 읽고 영향 없음을 입증"이 사실과 달랐다.** 백필 행(`ingest`)이 서킷브레이커 집계를 실제로 오염시킨다 | 코드 확인 결과. 사용자 결정(A안: 행 1개 기록 + 조회에서 BACKFILL 행 제외)에 따라 기존 파일 1곳 수정 |
| 2 | `raw_ohlcv.source_batch_id`는 `batch_run`에 대한 **외래키(FK)** 다(테스트 시드 중 FK 위반으로 확인). 따라서 "batch_run 행 없이 실행"(B안)은 애초에 불가능했다 | A안의 정당성을 보강 |
| 3 | 설계서가 정하지 않은 실패 정책을 구현 시 정함: ① 게이트웨이/API 오류(`GovDataApiError`: 키 오류·한도 초과 등)는 즉시 중단 ② 재시도 소진 등 날짜 단위 실패는 기록 후 계속, **연속 5회면 중단** ③ 저장 단계 예기치 못한 예외는 즉시 중단 | 같은 오류가 반복될 때 쿼터를 낭비하지 않기 위함. 임계 5회는 내가 정한 값 — 변경 원하면 알려 주세요 |
| 4 | 상태 판정: 모두 성공=SUCCESS, 일부만=PARTIAL, 무성과=FAILED. **수집 대상 날짜가 전부 0건이면 FAILED**(아무것도 적재되지 않은 채 SUCCESS로 끝나는 것 방지). `--max-calls` 도달은 PARTIAL이지만 종료코드 0 | 설계서의 "0건은 경고"는 일부 날짜가 0건인 경우에 그대로 적용 |
| 5 | `--to`가 마지막 마감 거래일보다 늦으면 요청 자체를 거부, `--days`와 `--from` 동시 지정은 오류 | 미마감 날짜는 0건이 확실하므로 쿼터 낭비 방지 |
| 6 | 건너뜀 기준 = 날짜별 적재 종목 수 ≥ 활성 종목 수(`stock_master.is_active`)의 90%(경계 포함). 호출 수 추정 페이지 수 = `ceil(max(활성 종목 수, 일일 최대 적재 행 수)/PAGE_SIZE)` | 설계서 §7 문구 구현 |
| 7 | `ruff check .` 전체는 **기존 프로토타입 `docs/pattern-screening/prototype/pattern_rules_reference.py`의 18건**(E501 등) 때문에 통과하지 않는다(작업 전 기준선과 동일). 이번 변경 범위(`scripts services shared tests db`)는 **전부 통과** | 프로토타입은 문서 산출물이라 수정하지 않았다. 처리 방침은 사용자 결정 사항(§7) |
| 8 | `ruff`는 이 PC에 설치돼 있지 않아(`requirements-dev.txt`에는 선언돼 있음) `.harness-tmp/ruff-venv`에 격리 설치해 사용 → 작업 종료 시 삭제 | 신규 의존성 아님 |
| 9 | **(사용자 승인 후) `scripts/run_daily_batch.ps1` 50행 `python`→`py -3.12` 1줄 수정**(BOM·나머지 내용 불변). 하위 프로세스(`seed_stock_master`·`run_ingestion`·`run_derivation`)는 모두 `sys.executable`을 쓰므로 이 줄만 고치면 3.12로 일관 실행됨 | 검증: `cmd /c "chcp 65001 >nul & py -3.12 -c …"`가 스케줄러와 같은 호출 형태로 `OK 3 12 2.0.51`(sqlalchemy 임포트 성공) 출력. **일일 배치 자체는 실행하지 않았다**(API 호출·DB 쓰기 발생). 다음 스케줄 실행(2026-10-03 07:00)에서 정상 동작 여부를 확인해야 함 |

## 3. 테스트 결과 (실제 실행 출력)

실행: `py -3.12`, 2026-10-02 13:5x~14:0x KST.

### 3-1. 요약

| 구분 | 변경 전 | 변경 후 | 판정 |
|---|---|---|---|
| `pytest tests/unit` | 213 passed | **241 passed**(신규 28) | PASS, 신규 실패 0 |
| `pytest tests/integration` | 2 passed(기존 `test_rate_limit_proxy_trust`) | **15 passed**(신규 13) | PASS |
| 이번 유닛 신규 테스트 합계 | — | **41 passed / 0 failed / 0 skipped** | PASS |
| `ruff check scripts services shared tests db` | — | `All checks passed!` | PASS |
| `ruff check .`(전체) | 18건(전부 프로토타입 문서) | 18건 + 신규 0건 | 기준선과 동일(편차 #7) |
| 임시 DB 잔여(`stock_screener_test_%`) | — | 0개 | 정리 완료 |
| 개발 서버 | — | 4001 `/docs` 200, 4000 `/screener` 200 | 유지 |

### 3-2. TC별 결과 (05-test-plan §4)

| TC | 시나리오 | 검증 테스트 | 결과 |
|---|---|---|---|
| B01 | `--dry-run`: 외부 호출 0회, 대상 날짜·예상 호출 수 출력 | `test_b01_dry_run_makes_no_external_call_and_writes_nothing`(클라이언트 생성 시 AssertionError, 서비스키 없이 실행, DB 쓰기 0건 확인) + **실 개발 DB 대상 dry-run**(§4) | PASS |
| B02 | 이미 충분한 날짜 건너뜀(경계 90% 포함) | `test_b02_…`(통합), `test_split_existing_…`(단위, 90/89/0건) | PASS |
| B03 | 거래일인데 0건 → 경고, 실패 아님 | `test_b03_…`(통합: exit 0·경고 출력·status SUCCESS), `test_zero_rows_…`(단위) | PASS |
| B04 | 서킷브레이커 비오염 | `test_b04_successful_…`, `test_b04_failed_…`, `test_b04_in_progress_…`, `test_b04_regular_ingest_rows_…`(4건). 백필 SUCCESS/FAILED/비정상종료 행 모두 집계 불변, `batch_run` 1행/실행, 일반 행(NULL 요약) 회귀 없음 | PASS |
| B05 | 서비스키 비노출 | `test_b05_service_key_never_appears_…`(HTTP 오류 메시지에 키가 포함된 상황에서 stdout/stderr/`error_summary` 전부 키 없음), `test_b05_dry_run_…`, `test_mask_secrets_…` 2건 | PASS |
| B06 | 중단 후 재개 | `test_b06_resume_after_midway_db_failure_…`(2번째 날짜에서 일부 행 저장 후 예외 → 해당 날짜 0행으로 롤백, 재실행 시 이미 끝난 날짜 재호출 없음, 최종 30행·중복 없음, BACKFILL 행 2개) + 단위 재개 테스트 | PASS |
| B07 | `--max-calls` 상한 | `test_b07_max_calls_…`(호출 정확히 4회, 미완료 날짜 미저장, 남은 날짜 보고, status PARTIAL, exit 0), `test_throttled_client_blocks_call_beyond_max_calls_…`(상한 초과 호출이 외부로 나가지 않음) | PASS |
| B08 | 실행 후 `n≥80` 종목 비율 ≥ 95% | 검증 쿼리 로직은 `test_coverage_ratio_counts_stocks_with_enough_rows`로 확인 | **미실행 — 실제 백필 실행 후에만 측정 가능(사용자 승인 대기). 통과로 세지 않음** |

추가 검증(계획 외): 다중 페이지 수신(PAGE_SIZE 4로 낮춰 3페이지)·최신→과거 호출 순서·`source_batch_id`가 실행의 batch_run id와 일치·`batch_worker` 역할로 읽기/쓰기 성공(권한)·호출 간격(첫 호출 전 sleep 없음)·연속 실패 중단·게이트웨이 오류 즉시 중단·상태/종료코드 규칙.

### 3-3. 테스트 유효성 검증 (변이 테스트)

테스트가 실제로 결함을 잡는지 확인하려고 서킷브레이커 제외 `WHERE` 조건만 임시 제거했다(상수는 유지):

| 상태 | B04 4건 결과 |
|---|---|
| 제외 조건 제거(결함 주입) | **3 failed**, 1 passed(일반 행 회귀 테스트는 정상적으로 통과) |
| 원복 후 | 13건 전부 passed |

(첫 시도는 상수까지 지워 import 오류로 무효였고, 두 번째 시도는 줄바꿈(CRLF) 때문에 변이가 적용되지 않아 그 "4 passed"를 근거에서 제외했다. 세 번째 시도에서 정상 적용·실패를 확인했다.)

## 4. 실 개발 DB 대상 `--dry-run` (읽기 전용, API 호출 0회)

명령: `scripts/backfill_ohlcv.py --days 130 --sleep 0.3 --dry-run` (`BATCH_DATABASE_URL`은 `.env`에서 로드, 값 비출력)

```text
(--dry-run) 외부 API 호출·DB 쓰기 없이 계획만 출력합니다.
대상 거래일 130개: 2026-03-24 ~ 2026-10-01
  이미 충분(활성 2760종목의 90% 이상)해 건너뜀: 25개
  수집 대상: 105개
예상 호출 수: 315회 (수집 대상 105일 × 일당 3페이지, 재시도 제외)
최소 소요 시간: 호출 간격 0.3초 기준 약 94초 + API 응답 시간(별도)
현재 80일 이상 보유 종목: 0/2880 (0.0%)
외부 호출 0회, DB 쓰기 0건.
```

- 쓰기 0건 확인: 실행 후 `raw_ohlcv` 71,824행·마지막 적재일 2026-09-21 불변, `batch_run` 44행·마지막 2026-09-23 07:00 불변·BACKFILL 행 0개.
- **소요 시간 추정(실측 보강)**: 임시 DB에서 2,870행 upsert+commit을 3회 측정 = 5.43s / 5.47s / 5.14s(≈5.3s/일, API 시간 제외). 105일 ≈ **DB 약 9~10분** + 호출 간격 약 1.6분 + API 응답 시간(미측정, 날짜당 3콜). 합산 대략 **15~25분(추정)**. 일일 호출 한도는 아직 모름(§5).
- 참고: `--days 130`의 시작일이 2026-03-24로 나온다(UNIT-11에서는 −130거래일을 03-23으로 산정). 기준일 계산 방식 차이(−130번째 vs 130개 포함)일 뿐 목표 "130거래일"은 충족한다.
- `--max-calls 400`: 한도 이내로 표시됨.

## 5. 정리(규칙 K)와 작업 중 발생한 사고 기록

- **사고 1 — 테스트 멈춤**: 통합 테스트 작성 초기에 내 테스트 코드가 DB 연결을 닫지 않아 열린 트랜잭션이 다음 테스트의 `TRUNCATE`를 락에 걸리게 했고 pytest가 멈췄다. 코드(`_rows` 헬퍼에서 `with`로 연결 종료)를 고쳐 해결했다. 제품 코드 결함이 아니라 테스트 코드 결함.
- **사고 2 — 프로세스 정리 시 범위 과다**: 멈춘 pytest를 끄려고 명령줄에 `test_backfill_ohlcv_db`가 들어간 프로세스를 전부 종료했는데, 그 문자열을 포함한 내 셸 래퍼 프로세스 등 6개가 같이 종료됐다. 다른 작업 프로세스(개발 서버 4000/4001, DB)는 영향받지 않았다(이후 200 응답 확인). 앞으로 PID를 특정해 종료한다.
- **사고 3 — 임시 DB 잔여**: 위 강제 종료로 `stock_screener_test_e768c60ecd`가 남았다. 접속 0건을 확인하고 **그 DB만** `DROP … WITH (FORCE)`로 삭제. 이후 모든 실행에서 잔여 0개 확인. (임시 DB는 정상·실패 시 finally로 삭제되나, 프로세스 강제 종료 시에는 남을 수 있다 → 점검 쿼리 `SELECT datname FROM pg_database WHERE datname LIKE 'stock_screener_test_%'`, 헬퍼 `leftover_temp_databases()`.)
- 개발 DB `stock_screener`에는 합성 데이터를 넣지 않았다(읽기 전용 dry-run만). 스크래치 스크립트는 삭제했다. `.harness-tmp/ruff-venv`는 이 유닛 종료 시 삭제한다.

## 6. 보안 점검

| 항목 | 결과 |
|---|---|
| 서비스키 비노출 | B05 통과(HTTP 오류 메시지에 키·`serviceKey=` URL 포함 상황에서 stdout/stderr/DB 모두 미노출). 코드·문서·테스트 상수에 실제 키 없음(테스트는 가짜 값 `SECRET/KEY+VALUE==`) |
| 외부 호출 | dry-run 0회. 실제 실행은 `--max-calls`·`--sleep`으로 제어 |
| 입력 검증 | 날짜 형식·`--days/--sleep/--max-calls` 범위 argparse 검증, 미래 날짜 거부 |
| 권한 | `batch_worker` 역할로 읽기(`stock_master`·캘린더·`raw_ohlcv`)·쓰기 모두 성공 확인(임시 DB에 실제 GRANT 적용) |
| 응답/로그 가격 원문 | 로그에는 날짜·건수만 출력, 가격 원문 출력 없음 |
| 의존성 | 신규 패키지 0(`requirements*.txt`, `package*.json` 변경 없음) |

## 7. 남은 위험·사용자 결정 대기

1. **실제 백필 실행**: 사용자 결정 = "한도 확인 후 실행". 포털 마이페이지에서 서비스키의 **일일 호출 한도**를 알려 주시면 그 값으로 `--max-calls`를 정해 실행한다(예상 315회·약 15~25분, 한도가 315회 미만이면 며칠에 나눠 실행). **한도 값 대기 중.**
2. ~~스케줄러 수정 승인~~ → **승인됨·반영 완료**(편차 #9). 다음 스케줄(2026-10-03 07:00) 결과 확인 필요.
3. ~~프로토타입 ruff 18건~~ → **사용자 결정: 그대로 둠.** 변경 범위만 ruff 통과를 확인한다.
4. Q3(스팩·우선주 포함 여부)은 UNIT-15 전까지 미결.
5. 구현 판단 #3의 "연속 실패 5회 중단" 값은 내가 정함 — 조정 필요 시 알려 주세요.
6. 실 API 응답으로는 날짜 단위 파싱 오류(`basDt` 불일치 등)가 날 가능성을 완전히 배제하지 못함 — 실제 실행 시 첫 몇 날짜의 결과를 바로 보고한다.
