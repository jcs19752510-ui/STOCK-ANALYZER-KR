# UNIT-13 구현 노트 및 내부 테스트 결과서 — 패턴 지표 순수 함수 (REQ-030)

- 작성: 2026-10-02 14:1x KST · 대상: `shared/pattern_params.py`(신규), `services/derivation_batch/compute.py`(함수 추가만) · 관련: 02 설계서 §3-2·§4, 05 테스트계획 §3(TC-U01~U16·U40~U42)
- **결론: 구현·테스트 완료. 신규 46건 전부 통과, 오라클 교차 검증 300건 일치(최대 오차 5.0e-05). DB·마이그레이션·배치 연결은 UNIT-14 범위라 이번에 건드리지 않았다.**

## 1. 구현 요약

| 구분 | 파일 | 내용 |
|---|---|---|
| 신규 | `shared/pattern_params.py` | 계산 파라미터 고정 상수(설계서 §3-2 표) + 상태 값 3종. 배치와 API(`definition.calc`)가 공유 |
| 수정(추가만) | `services/derivation_batch/compute.py` | `PatternMetrics`(11개 필드 frozen dataclass), `compute_pattern_metrics()` 및 내부 헬퍼 4개. `__all__`·import 추가. **기존 함수·코드 삭제/변경 0줄**(diff에 삭제 라인 없음) |
| 신규 | `tests/unit/test_pattern_compute.py` | 46건 |

- 계산은 기준 구현(`prototype/pattern_rules_reference.py`)과 1:1이며 `Decimal`로 수행한다(기존 `compute.py` 스타일: `_QUANT` 소수 4자리 정규화, 한국어 docstring에 정의 근거).
- **입력 규약: 최신순(내림차순), 0번 = 대상 거래일.** docstring에 명시, TC-U42가 문서화와 오용 시 결과 차이를 검증.
- 산정 불가 게이트: ① 종가/거래량 80행 미만 → `INSUFFICIENT_HISTORY` ② 앞 80행에 종가 ≤ 0 또는 일 변동 |r| > 31% → `SUSPECT_PRICE_JUMP` ③ 분모 0(60일 수익률 표준편차, 60일 평균 거래량)이면 그 값만 `None`.
- 순수성: 입력 리스트 미변경, 전역 상태·I/O 없음(TC-U16). 80행 밖 데이터는 결과에 영향 없음(TC-U41).
- 성능(참고 측정, 설계 P03 선행 자료): 88행 입력 1회 0.48ms → 2,800종목 약 1.3초(계산부만, DB 제외).

## 2. 문서와 달라진 점·구현 중 판단 (편차 기록)

| # | 내용 | 영향 |
|---|---|---|
| 1 | **입력 타입**: 04 개발계획은 "입력은 최신순 `OhlcvPoint` 리스트"라고 했으나, `OhlcvPoint`는 `repository.py`(SQLAlchemy 의존)에 있어 `compute.py`가 DB 비의존 순수 모듈이라는 기존 원칙을 깬다. 그래서 `closes: list[Decimal]`, `volumes: list[int]`(최신순)를 받는다(오라클·05 TC-U01 입력 표기와 동일) | UNIT-14에서 `window: list[OhlcvPoint]` → 두 리스트로 변환하는 한 줄 매핑이 필요. 의미 변화 없음 |
| 2 | 설계서 §3-2 표에 없는 상수 2개를 이름 있는 상수로 추가: `CONVERGENCE_MA_WINDOWS=(5,10,20)`, `SURGE_BASELINE_DAYS=20`(오라클은 리터럴 5/10/20·20 사용). 값은 오라클과 동일 | 계산 파라미터 문서화 보강. 설계서 표에 두 줄 추가가 바람직(문서 갱신은 UNIT-18) |
| 3 | `SURGE_RETURN_PCT`, `SURGE_VOLUME_MULT`, `PRICE_JUMP_LIMIT_PCT`는 `Decimal`(오라클은 float) | 경계 비교(예: +10.0% 정확 일치)를 이진 부동소수 오차 없이 하기 위함 |
| 4 | 종가 길이와 거래량 길이가 다르면 둘 중 하나라도 80행 미만이면 `INSUFFICIENT_HISTORY`(오라클과 동일) | 테스트로 고정(`test_u03_volumes_shorter_…`) |

문서의 임계값·계산 정의는 **한 글자도 바꾸지 않았다.**

## 3. 테스트 결과 (실제 실행 출력)

실행: `py -3.12`, 2026-10-02 14:0x~14:1x KST.

### 3-1. 요약

| 구분 | 변경 전 | 변경 후 | 판정 |
|---|---|---|---|
| `pytest tests/unit/test_pattern_compute.py` | — | **46 passed / 0 failed** | PASS |
| `pytest tests/unit`(전체) | 241 passed | **287 passed**(+46) | PASS, 신규 실패 0 |
| `pytest tests/integration` | 15 passed | **15 passed** | PASS (회귀 0) |
| `ruff check shared services scripts tests db` | — | `All checks passed!` | PASS |
| 오라클 자체 검증(`prototype` 실행) | — | 150/300, 300/300, 300/300 … (문서 v2 기록과 동일) | 오라클 불변 확인 |
| 임시 DB 잔여 | — | 0개 | 이번 유닛은 DB 미사용 |
| 개발 서버(DB·4000·4001) | — | 켜 둠(건드리지 않음) | 유지 |

(처음 실행 시 테스트 코드의 오라클 모듈 로드 방식 오류(`sys.modules` 미등록으로 dataclass 실패)가 한 번 있었고 테스트 코드를 고쳐 해결했다. 제품 코드 결함 아님.)

### 3-2. TC별 결과 (05-test-plan §3)

| TC | 시나리오 | 검증 테스트 | 결과 |
|---|---|---|---|
| U01 | 완전 평탄(손계산) | `test_u01_flat_series_hand_calculated` — range/net/conv/gap/slope=0, cross=None, volume_ratio=1.0000, surge=False, **volatility_contraction_ratio=None**, status OK | PASS |
| U02 | 선형 상승(손계산) | `test_u02_…` — 49.2212 / 65.2893 / 3.9370 / 17.3021 / 11.7302 / 6.2305 / 1.0 (허용오차 1e-3) + 나머지 필드 오라클 대조 | PASS |
| U03 | 행 수 79/80 | `test_u03_row_count_boundary_79_vs_80`(79→INSUFFICIENT·전 필드 None, 80→OK), 거래량 길이 부족 | PASS |
| U04 | 단절 +31.0 / +31.1 | `test_u04_…` 경계(131→OK, 131.1→SUSPECT, 전 필드 None), 하락 단절, 관찰창(80행) 밖 단절 무시 | PASS |
| U05 | 종가 0 이하 | `test_u05_…` — 0, −5 모두 SUSPECT, 예외 없음 | PASS |
| U06 | 60일 수익률 표준편차 0 | `test_u06_…` — ratio=None, status OK | PASS |
| U07 | 60일 평균 거래량 0 | `test_u07_…` — volume_ratio=None, 예외 없음 | PASS |
| U08 | MA60 돌파 일수 k=0~9 / 없음 / 종가==MA60 | `test_u08_cross_up_days_for_each_k[0..9]` 10건 + 없음·동일 | PASS |
| U09 | 관찰창 밖(k=10) | `test_u09_…` — None | PASS |
| U10 | 급등 경계 포함(+10.0%·3.0배) | `test_u10_…` — True | PASS |
| U11 | +9.99% / 2.999배 | `test_u11_…[2건]` — False | PASS |
| U12 | 관찰창 19/20일 전 | `test_u12_…` — True / False | PASS |
| U13 | 기준 거래량 0 | `test_u13_…` — 건너뜀, 0 나눗셈 없음 | PASS |
| U14 | 하락 추세 부호 | `test_u14_…` — net<0, range>0 | PASS |
| U15 | Decimal vs 오라클·정밀도 | `test_u15_…` — 차이 ≤1e-3, 모든 수치 소수 4자리 | PASS |
| U16 | 순수성 | `test_u16_…` — 동일 출력, 입력 리스트 미변경 | PASS |
| U40 | **오라클 교차 검증 300건** | `test_u40_oracle_cross_check_300_series[0..9]`(30건×10) — 11개 필드·status 허용오차 내 일치 | PASS |
| U41 | 윈도우 절단 | `test_u41_…` — 130행 = 앞 100행 = 앞 80행 결과 완전 동일 | PASS |
| U42 | 입력 규약 | `test_u42_…` — docstring에 "최신순" 명시, 오름차순 입력 시 결과 상이 | PASS |
| (추가) | 파라미터 드리프트 방지 | `test_params_match_design_and_oracle` — 설계서 값·오라클 상수와 동일 | PASS |
| (추가) | 필요 행 수 검산 | `test_required_rows_do_not_exceed_min_rows` — 70/61/41/80의 최댓값 = 80 | PASS |
| (추가) | 교차 검증 입력의 분기 포괄 | `test_u40_series_cover_all_statuses_and_both_surge_outcomes` | PASS |

### 3-3. 오라클 교차 검증 증거 (TC-U40)

- 300개 합성 시계열(시드 고정 0~299, 6종: 오라클 기본형·변형형·랜덤워크·추세·급등 주입·0거래량/짧은 이력/단절)에서 **수치 필드 2,206건 비교, 최대 절대 오차 4.994e-05**(= 소수 4자리 반올림 한계 0.5e-4, 허용오차 1e-3의 5%) — `ma60_gap_pct`(seed 248).
- 상태 분포: OK 277 · INSUFFICIENT_HISTORY 15 · SUSPECT_PRICE_JUMP 8. OK 중 급등 True 30 / False 247, MA60 돌파 있음 58 / 없음 219, 거래량비 None 10건. (변동성 수축비 None은 랜덤 시계열에선 0건 — 해당 분기는 U01·U06 손계산 TC가 담당)
- 한계: 오라클과 구현은 같은 정의를 두 번 쓴 것이라 **정의 자체의 오류는 이 검증이 못 잡는다**(손계산 U01·U02가 일부 보완). 정의의 타당성(예: 임계값이 실제 분포에 맞는지)은 UNIT-15 보정 리포트에서 다룬다.

### 3-4. 테스트 유효성 검증 (변이 테스트)

구현의 경계 조건 12곳을 하나씩 바꿔 테스트 파일이 실패하는지 확인했다. **12/12 적발(생존 0)**, 실행 후 원본과 바이트 동일 복원 확인.

| # | 변이 | 결과 |
|---|---|---|
| 1 | 급등 수익률 `>=` → `>` | 적발 |
| 2 | 급등 거래량 `>=` → `>` | 적발 |
| 3 | 단절 `>` → `>=` | 적발 |
| 4 | 돌파 전일 `<=` → `<` | 적발 |
| 5 | 돌파 관찰창 10 → 11 | 적발 |
| 6 | 횡보 구간 80 → 79 | 적발 |
| 7 | MA60 기울기 오프셋 제거 | 적발 |
| 8 | 모표준편차 → 표본표준편차 | 적발 |
| 9 | 거래량비 분모 0 가드 제거 | 적발 |
| 10 | 급등 기준 거래량 0 가드 제거 | 적발 |
| 11 | 급등 관찰창 20 → 21 | 적발 |
| 12 | 행 수 게이트 `<` → `<=` | 적발 |

## 4. 보안·품질 점검

| 항목 | 결과 |
|---|---|
| 외부 호출·DB 접근 | 없음(순수 함수) |
| 서비스키·비밀 | 코드·테스트·문서에 없음 |
| 신규 의존성 | 0(표준 라이브러리 `statistics`·`decimal` + 기존 모듈). `requirements*.txt` 변경 없음 |
| 기존 코드 변경 | `compute.py`에 추가만(삭제 0줄). 기존 `test_derivation_compute.py` 무수정 통과 |
| 가격 원문 노출 | 해당 없음(계산 결과는 비율·배수·불리언·일수만 반환) |
| 요청 범위 밖 변경 | 없음(UNIT-14 항목인 DB 컬럼·repository·`run_derivation` 미변경) |

## 5. 정리(규칙 K)

- `.harness-tmp/ruff-venv`(ruff 검증용 임시 venv)와 변이 테스트 스크래치 파일 삭제 완료(`.harness-tmp` 비어 있음). 임시 DB 미사용·잔여 0.

## 6. 남은 위험·후속

1. UNIT-14에서 `OhlcvPoint` 리스트를 `closes`/`volumes`로 변환할 때 **최신순 정렬 보장**이 핵심. 기존 `fetch_ohlcv_window`는 `ORDER BY trade_date DESC`로 최신순을 반환함을 코드로 확인했다(`repository.py`). UNIT-14에서 윈도우 크기를 100으로 바꾼 뒤에도 이 정렬이 유지됨을 TC로 고정한다(TC-U42는 함수 쪽 규약만 검증).
2. 거래정지 등으로 행이 빠진 종목의 "80거래일"은 달력 기간과 다를 수 있다(설계서 §4-1-4 알려진 한계, 변경 없음).
3. 위 편차 #2의 설계서 표 갱신은 UNIT-18 문서 갱신 때 처리.
