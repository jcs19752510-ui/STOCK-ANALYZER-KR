# UNIT-15 구현 노트 및 내부 테스트 결과서 — 판정 임계값 설정 + 보정 리포트 (REQ-032, REQ-036)

- 작성: 2026-10-02 14:3x KST · 대상: `services/public_api/core/pattern_config.py`, `services/public_api/db/pattern_repository.py`(조건식), `scripts/pattern_threshold_report.py` · 관련: 02 설계서 §3-3·§4-2·§5-4, 05 테스트계획 §6(TC-C01~C08)·§7(TC-A28·A29·A30·A31·A33의 SQL 계층)
- **결론: 구현·테스트 완료(신규 203건 통과, 회귀 0). 단, 이 유닛의 사용자 결정 항목인 임계값 확정(Q2)은 실데이터(80거래일 이상)가 필요해 백필 이후에 한다 — 현재 개발 DB에는 산정 가능 종목이 0건이다.**

## 1. 구현 요약

| 구분 | 파일 | 내용 |
|---|---|---|
| 신규 | `services/public_api/core/pattern_config.py` | `PATTERN_*` 환경변수 10개 + 기능 스위치 로더. 범위 검증·**기동 시 즉시 실패**(`ConfigError`). `PatternThresholds`(frozen), `definition_thresholds()`/`definition_calc()`(API 응답 `definition` 용), `THRESHOLD_RANGES`(허용 범위의 단일 출처) |
| 신규(앞당김) | `services/public_api/db/pattern_repository.py` | `build_condition_exprs()`(c1~c5·c9 SQL 식, 상태 게이트·3값 논리·경계 포함)와 `ma60_stage_expr()`(c4 단계 SQL `CASE`) — 판정 로직의 **단일 출처** |
| 신규 | `scripts/pattern_threshold_report.py` | 읽기 전용 보정 리포트: 조건별 충족 현황·전체 동시 충족·판정(0건/10% 초과)·지표 분포(p10/p50/p90)·임계값 ±20% 민감도 표 |
| 수정(테스트 보조) | `tests/integration/pg_temp_db.py` | `TempDb.api_url`(읽기 전용 `api_service` 접속) 추가 |
| 신규(테스트) | `tests/unit/test_pattern_config.py`(137건), `tests/integration/test_pattern_conditions_db.py`(55건), `tests/integration/test_pattern_report_db.py`(11건) | |

- 설정 로더 원칙(02 §3-3): 요청자는 임계값을 바꿀 수 없다(질의 파라미터 없음). 숫자는 ASCII 십진수만 허용하며 `nan`/`inf`/지수 표기/전각 숫자/빈 문자열을 거부한다(`Decimal`이 받아들이는 위험 입력 차단). 값은 `Decimal`로 보관해 `NUMERIC` 컬럼과의 경계 비교(≤, ≥)에 부동소수 오차가 없다. 오류 메시지는 해당 변수명과 입력값만 담고 다른 환경변수(비밀)는 노출하지 않는다.
- 리포트는 `PUBLIC_API_DATABASE_URL`(`api_service`, SELECT 전용·`raw_internal` 불가)로 접속하고 첫 문장으로 `SET TRANSACTION READ ONLY`를 실행한다. 판정식은 API와 **같은 함수**를 쓰므로 리포트 숫자와 실제 서비스 결과가 어긋날 수 없다. 종목 코드·이름·목록은 출력하지 않는다(식별·서열화 금지, REQ-034).
- 민감도 변형은 설정 허용 범위를 벗어나거나 `VOLUME_RATIO_MIN ≥ MAX`가 되면 **만들지 않는다**(조용한 클램프 금지).

## 2. 문서와 달라진 점·구현 중 판단 (편차 기록)

| # | 내용 | 영향 |
|---|---|---|
| 1 | **`build_condition_exprs()`를 UNIT-16에서 UNIT-15로 앞당겼다.** 04 개발계획은 이 함수를 UNIT-16(API) 소관으로 두었으나, 보정 리포트가 "API와 같은 판정식"을 써야 숫자가 어긋나지 않는다(설계서 §0-5 단일 출처). 같은 식을 리포트용으로 따로 쓰면 판정 로직이 두 곳이 된다 | UNIT-16은 이 함수를 import해 리포지토리 클래스만 추가하면 된다. TC-A28·A29·A30·A31·A33의 SQL 계층 검증은 이번에 끝났고 UNIT-16에서는 API 통합 수준으로 재실행 |
| 2 | 임계값을 `float`가 아니라 `Decimal`로 보관(설계서는 타입 미지정) | 경계 비교 정확성. API 응답 `definition.thresholds`에서는 `float`로 변환(JSON 수치) |
| 3 | `PATTERN_SCREEN_ENABLED`는 대소문자를 구분하지 않고 `true`/`false`만 허용(`TRUE`, ` False ` 허용, `yes`/`1`/`on`/빈 값 거부) | 설계서 "`true`/`false` 외는 ConfigError"를 운영 편의상 대소문자만 완화 |
| 4 | 리포트 판정 기준 — 기획서 §5 "0건도 아니고 전 종목의 10% 초과도 아님"을 `전체 충족 > 0` 그리고 `전체 충족 ≤ 전체 행의 10%`로 구현(분모는 시장 필터 후 전체 행, 경계 10% 포함). 산정 가능 행이 0이면 별도 상태 `NOT_READY` | 기획서의 "전 종목" 분모를 "발행 거래일의 활성 종목 행"으로 해석 |
| 5 | `THRESHOLD_RANGES`를 `pattern_config`에 공개 상수로 두어 리포트 민감도가 같은 허용 범위를 쓰게 했다 | 범위가 두 곳에서 따로 관리되지 않음 |
| 6 | 리포트 민감도 변동 폭 기본 ±20%(`--sensitivity-pct`로 조정), 정수 임계값(`CROSS_EARLY_MAX_DAYS`)은 반올림 | 설계서가 폭을 정하지 않음 — 확정 임계값이 아니라 참고 자료이므로 추천 기본값 사용 |

문서의 임계값 기본값·계산 정의는 바꾸지 않았다(기본값은 여전히 "사용자 확정 대기").

## 3. 테스트 결과 (실제 실행 출력)

실행: `py -3.12`, 2026-10-02 14:2x~14:3x KST.

### 3-1. 요약

| 구분 | 변경 전 | 변경 후 | 판정 |
|---|---|---|---|
| `pytest tests/unit` | 298 passed | **435 passed**(+137) | PASS, 신규 실패 0 |
| `pytest tests/integration` | 24 passed | **90 passed**(+66) | PASS |
| 이번 유닛 신규 | — | **203 passed / 0 failed / 0 skipped** | PASS |
| `ruff check shared services scripts tests db` | — | `All checks passed!` | PASS |
| 임시 DB 잔여 | — | 0개 | 정리 완료 |
| 개발 DB 쓰기 | — | **0건**(리포트 실행 전후 행 수·배치 이력 불변) | |

### 3-2. TC별 결과

| TC | 시나리오 | 검증 | 결과 |
|---|---|---|---|
| C01 | 환경변수 없음 → 기본값 | `test_c01_…`(10개 값 + 스위치 기본 true) | PASS |
| C02 | 범위 밖 값 → `ConfigError` | 9개 변수 × (하한 미만·상한 초과) 18건 + 예시 `RANGE_MAX=101` | PASS |
| C03 | 타입 오류 | 10개 변수 × `abc`·빈 값·공백·`nan`·`inf`·`1e1`·전각 `４０`·`1,5` 등 100건 | PASS |
| C04 | `VOLUME_RATIO_MIN ≥ MAX` | 같은 값·역전 거부, 1.9/2.0 허용 | PASS |
| C05 | `CROSS_EARLY_MAX_DAYS=11` | 11·0·5.5 거부 | PASS |
| C06 | 범위 끝값 허용 | 9개 변수 하한·상한 정확히 허용 + 정수 1·10 | PASS |
| C07 | `PATTERN_SCREEN_ENABLED` | `true/false`(대소문자·공백 허용) 외 `yes/1/0/on/빈 값/truee` 거부 | PASS |
| C08 | `definition`이 로드된 설정과 동일 | `definition_thresholds()`(사용자 지정값 반영)·`definition_calc()`(고정 계산 파라미터) | PASS |
| A28 | 임계값 경계 포함성 | 33개 경계 케이스(정확히 경계=충족, 경계 초과=미충족: c1~c5·c9 전 임계값, 거래량 이상치는 엄격 미만) + 사용자 지정 `CROSS_EARLY_MAX_DAYS=5` | PASS |
| A29 | 3값 논리 | `FALSE AND NULL = FALSE`, `TRUE AND NULL = NULL`을 실제 PostgreSQL에서 c1·c2·c4·c5·c9 확인 | PASS |
| A30·A33 | 상태 게이트 | `INSUFFICIENT_HISTORY`·`SUSPECT_PRICE_JUMP`·상태 `NULL`(구 배치 행)이면 지표 값이 채워져 있어도 6개 조건·`ma60_stage` 전부 `NULL` | PASS |
| A31 | `ma60_stage`↔c4 일치 | 경계 12케이스 + **격자 전수 798건**(gap −10…+15·경계±0.0001 × cross NULL/0…12): c4 충족 ⇔ `BELOW_NEAR`/`CROSS_EARLY`, 오라클 c4와도 일치 | PASS |
| (추가) | **오라클 대량 등가성** | SQL 판정 == 기준 구현: 무작위·경계 중심(NULL 포함) 800행 × 기본·사용자 지정 임계값 2세트. 모든 조건이 true/false/null을 모두 냈음을 확인(검증이 공허하지 않음) | PASS |
| 리포트 | 숫자 정확성 | 배치로 산출한 픽스처 10종목: 조건별 충족/미충족/산정불가 수와 전체 충족 수가 오라클로 직접 센 값과 일치(1건 = T00001만), 시장 필터 | PASS |
| 리포트 | 민감도 | 기준값 변형 = 본 집계, 단조성(상한 임계값↑→충족 수 비감소, `VOLUME_RATIO_MIN`↑→비증가), 범위·짝 제약 위반 변형 미생성 | PASS |
| 리포트 | 분포 | 산정 가능 행만으로 계산(패턴 컬럼과 비 OK 행에도 값이 있는 기존 컬럼 `volume_anomaly_score` 모두 확인) | PASS |
| 리포트 | 판정 규칙 | 경계(10% 정확히 = OK, 11% = 과다, 0건, 산정 불가) | PASS |
| 리포트 | **읽기 전용** | 슈퍼유저 세션에서도 리포트 이후 `DELETE`가 `read-only transaction`으로 거부, 데이터 불변. `api_service` 계정으로 실행 | PASS |
| 리포트 | 출력 안전성 | 종목 코드·이름·"추천/순위/TOP/유력" 문자열 없음, 실행 전후 행 수 불변 | PASS |
| 리포트 | 명시적 실패 | 발행 데이터 없음 → 종료코드 1 + "발행" 메시지, 잘못된 `PATTERN_*` 값 → 종료코드 1 + 변수명, 산정 가능 0건 → 종료코드 0 + "산정 가능 종목이 없습니다" | PASS |

### 3-3. 테스트 유효성 검증 (변이 테스트)

구현 16곳을 하나씩 훼손해 테스트가 실패하는지 확인했다. **최종 16/16 적발**, 변이 후 원본과 바이트 동일 복원 확인.

| 영역 | 변이 | 결과 |
|---|---|---|
| 설정 | 숫자 정규식이 전각 숫자 허용 / `MIN<MAX` 검사 제거 / 교차 일수 상한 +1 / 스위치가 `yes` 허용 / 범위 하한을 미포함으로 | 5/5 적발 |
| 조건식 | c1 `<=`→`<` / c5 이상치 `<`→`<=` / c4의 `cross IS NOT NULL` 제거 / c9를 `IS FALSE`로 / 상태 게이트 제거 / `ma60_stage`의 `gap<0`→`<=0` | 6/6 적발 |
| 리포트 | `SET TRANSACTION READ ONLY` 제거 / 판정 `>`→`>=` / 분포 OK-전용 필터 제거 / 민감도 범위 검사 제거 / 시장 필터 무시 | 5/5 적발(분포 필터 변이는 **첫 시도에서 생존** — 패턴 컬럼은 비 OK 행에서 이미 NULL이라 차이가 없었다. 기존 컬럼 `volume_anomaly_score`를 검증하도록 테스트를 보강한 뒤 적발됨) |

## 4. 실제 개발 DB 대상 리포트 실행(읽기 전용, 실제 `api_service` 계정)

`scripts/pattern_threshold_report.py` 출력 요약(실제 출력):

```text
거래일: 2026-09-21   시장: ALL
평가 대상: 전체 2760행 중 산정 가능 0행(0.0%), 산정 불가 2760행(이력 부족·단절 의심·구 배치)
  c1~c9: 충족 0 · 미충족 0 · 산정불가 2760
[전체 조건 동시 충족] 0건
[판정] 산정 가능 종목이 없습니다 — 시세 이력(80거래일)이 아직 부족합니다.
```

- 실행 전후 `derived_metrics_daily` 5,521행·마지막 거래일 2026-09-21·최근 1시간 `batch_run` 0건 — 쓰기 없음 확인.
- 의미: 개발 DB의 발행분(09-21)은 패턴 지표 도입 전의 구 배치 행이고 보유 시세도 25거래일이라, **지금은 보정 리포트가 아무 분포도 보여줄 수 없다.** 백필(호출 한도 확인 대기) → 배치 재실행 후에야 실데이터 보정이 가능하다.
- 합성 픽스처 10종목으로 렌더링한 리포트(형식 검증용)는 조건별 표·분포·민감도 표가 모두 정상 출력됨을 확인했다(임계값 적정성 판단 자료가 아님).

## 5. 보안·품질 점검

| 항목 | 결과 |
|---|---|
| 읽기 전용 | 트랜잭션 레벨(`SET TRANSACTION READ ONLY`) + 역할 레벨(`api_service` SELECT 전용) 이중 |
| 입력 검증 | 환경변수 ASCII 숫자·범위·짝 제약, 위반 시 기동 실패(조용한 기본값 대체 없음) |
| 비밀 | 오류 메시지에 다른 환경변수 미포함(테스트 확인), 리포트는 DB URL·키를 출력하지 않음 |
| 응답/출력 | 종목 식별·서열화 정보 없음 |
| 의존성 | 신규 0 |
| 기존 코드 변경 | `tests/integration/pg_temp_db.py`에 속성 추가뿐(제품 코드는 신규 파일만) |

## 6. 남은 위험·사용자 결정 대기

1. **(특별 사안·사용자 결정) Q2 임계값 확정**: 백필 후 `py -3.12 scripts/pattern_threshold_report.py`로 실제 분포를 만들어 사용자에게 보고하고 확정 결정을 받는다. 지금은 불가.
2. 백필 실행은 서비스키 일일 호출 한도 확인 대기(UNIT-12 이월). 이 한도 값이 정해지면 백필 → 배치 재실행 → 리포트 순으로 진행한다.
3. Q3(스팩·우선주 포함 여부)는 UNIT-16(API) 착수 전까지 정해야 하나, 이번 설계(조회 시점 필터 가능)로 계산 결과에는 영향이 없다 — 보정 리포트를 "포함/제외" 두 경우로 비교해 보여 줄 수 있도록 실데이터 단계에서 추가 옵션을 검토한다.
4. 설계서 §2 변경 지도와 04 개발계획에 `build_condition_exprs` 앞당김(편차 #1)·`THRESHOLD_RANGES`를 반영하는 문서 갱신은 UNIT-18.
