# 장중 재계산(스크리닝 조건을 장중 시세로 다시 계산) — 적용 시간·영향 화면 견적

> **3줄 요약**
> 1. **필요 기간(추정)**: 권장안 ①(서버 병합 계산, 로컬 모드 전용) 개발 4 + 시험 3 = **약 7영업일(범위 6~10)**. ② 장중 배치+별도 테이블 약 10영업일(9~14), ③ 브라우저 계산(표시만) 약 5영업일(4~7). 실제 장중 검증은 사용자 PC에서 **달력상 약 1~1.5주** 별도(§5-2).
> 2. **영향 화면**: 조건 스크리닝 `/screener`, 패턴 스크리닝 `/screener/pattern`, 종목 상세의 지표 카드·조건 체크 탭은 값이 바뀜. 홈 시장 요약은 일부(등락 종목 수만) 가능하나 범위 제외 권장. 종목 검색·관심종목은 이미 현재가가 실시간이고 조건 값이 없어 영향 없음.
> 3. **권장안**: 보류 유지가 기본. 진행한다면 ① 로컬 모드 관리자 전용 + 1단계는 "등락률·이격도·거래량 이상치·패턴 지표만 재계산, PER/PBR/시총 백분위는 일봉 고정". 그 전에 **장중 실측 1회(한 바퀴 시간·필드명·한도)를 먼저** 해야 견적 폭이 줄어든다.

- 작성일: 2026-10-06 / 브랜치 PROD_SCH / 코드 수정 없음(이 문서 1개만 추가)
- 근거 표기: `파일:줄`. 읽지 못했거나 실행 확인이 안 된 것은 "확인하지 못함"으로 적었다.
- **일수는 모두 추정**이다. 기준은 "이 저장소의 기존 속도(에이전트 병렬 개발 + 내부 시험 결과서 포함)"이며, 그 근거는 §5-1.

## 1. 현재 스크리닝 파이프라인 (조사 결과)

### 1-1. 지표를 언제·어디서 계산해 어디에 저장하나
| 단계 | 내용 | 근거 |
|---|---|---|
| 계산 시점 | **일 1회 배치**(수집 → 가공). 요청 시에는 계산하지 않고 저장된 값을 SQL로 걸러서 읽기만 한다 | `scripts/run_daily_batch.py`(수집 후 `services.derivation_batch.run_derivation` 호출), `services/public_api/api/screen.py:219`(`repository.search`) |
| 입력 | `raw_internal.raw_ohlcv`의 종목당 최근 100행(종가·거래량), `raw_fundamentals`(PER·PBR·시가총액), `raw_corp_financials`(적자 사유) | `services/derivation_batch/repository.py:37`(`OHLCV_WINDOW_SIZE`=100), `:75`(`fetch_ohlcv_window`), `run_derivation.py:385-398` |
| 계산 | 순수 함수(DB·I/O 없음): 등락률 `compute_return_pct`, 이동평균 이격 `compute_ma_gap_pct`(5·20일, **당일 종가 포함**), 거래량 이상치 `compute_volume_anomaly_score`(직전 20일, 당일 제외, 표본표준편차), 백분위 `rank_percentile`, 패턴 11지표 `compute_pattern_metrics`, 시장 요약 `compute_market_summary` | `services/derivation_batch/compute.py:27, 34, 55, 77, 131, 221` |
| 조합 | 종목별 `compute_stock_day_metrics`, 전 종목 백분위 `build_derivation_inputs`(등락률·PER·PBR·시총, **코스피+코스닥 통합**) | `run_derivation.py:144, 214` |
| 저장 | `public_serving.derived_metrics_daily`(PK 종목·거래일·시장), `market_summary_daily`(3행: KOSPI/KOSDAQ/ALL), `daily_prices`(일봉 복사본, 보존 400일), 발행 포인터 `current_published_batch` | `repository.py:153, 312, 352, 355`; `run_derivation.py:419-437, 459-462`; `shared/db_models/public_serving.py:124-220` |
| 발행 검증 | 등락률 결측 5% 초과면 저장은 하되 포인터를 갱신하지 않아 직전 정상 데이터가 계속 서빙됨 | `run_derivation.py:79, 334-338, 439-462` |
| 조회 권한 | `api_service`는 `public_serving` SELECT만 가능. `raw_internal`은 못 읽는다 → API가 쓸 수 있는 일봉은 `daily_prices` 복사본뿐 | `screen_repository.py:3-4`, `shared/db_models/public_serving.py:201-207` |

### 1-2. 관련 파일 목록
| 구분 | 파일 |
|---|---|
| 순수 계산(derivation) | `services/derivation_batch/compute.py`, `shared/pattern_params.py`(패턴 계산 상수), `services/public_api/core/pattern_config.py`(판정 임계값 환경변수) |
| 배치 | `services/derivation_batch/{run_derivation,repository,raw_models,batch_run_repository}.py`, `scripts/run_daily_batch.py`(+`.ps1`, `register_daily_batch_task.ps1`), `shared/batch_catchup.py`, `services/derivation_batch/core/config.py` |
| 조회 저장소(SQL 판정) | `services/public_api/db/screen_repository.py`(조건 스크리닝 필터·정렬), `db/pattern_repository.py`(패턴 c1~c5·c9 판정식 **단일 출처**, `ma60_stage_expr`), `db/market_summary_repository.py`, `db/metrics_repository.py`, `db/price_repository.py` |
| API 라우터 | `api/screen.py`(`GET /screen`), `api/pattern.py`(`GET /screen/pattern`, `GET /stocks/{code}/pattern-check`), `api/metrics.py`(`GET /stocks/{code}/metrics`), `api/market_summary.py`, `api/prices.py`(`/stocks/quotes`, `/stocks/{code}/prices`) |
| 스키마 | `services/public_api/schemas/{screen,pattern,metrics,market_summary}.py` |
| 마이그레이션 | `db/alembic/versions/0006`(파생 테이블), `0007`(volume_raw), `0008`(인덱스), `0009`(market_summary), `0011`(패턴 지표 컬럼), `0012`(daily_prices), `0014`(PER/PBR 사유), `0016`(투자자 수급) |
| 준실시간 시세(이미 구현) | `realtime/market.py`, `api/local_market.py`(`/api/v1/local/market/quotes|status`), `intraday/normalize.py:227`(`normalize_multi_price`), `intraday/kis_client.py`(30종목 묶음, 최소 간격 0.12초) |
| 기존 시험 | `tests/unit/test_derivation_compute.py`, `test_run_derivation*.py`, `test_pattern_compute.py`, `test_public_api.py`, `test_market_snapshot.py`, `test_local_market_api.py`; `tests/integration/test_pattern_*_db.py`, `golden_screen_before_pattern.json`; `tests/e2e/local_mode_stack.py` |

### 1-3. 기억해야 할 설계 원칙(재계산 설계를 제약함)
- 패턴 판정은 SQL 한 곳에서만 한다. "Python에서 재판정하지 않는다" — `pattern_repository.py:1-13`, `api/pattern.py:3-5`. 서버 메모리 계산(①)은 이 원칙을 깨므로 **SQL 판정과 같은 결과가 나오는지 증명하는 동치 시험이 필수**다.
- 정렬은 `*_raw` 컬럼(인덱스 있음) 기준, 동률은 종목코드 오름차순, 페이지는 offset 방식 — `screen_repository.py:26-37, 149-157`.
- 일봉 계산에서 `window[0].trade_date != target_date`인 종목은 결과에서 제외 — `run_derivation.py:160-161`.
- 응답에 원본 시세·`*_raw`는 싣지 않는다(§4-3 가공 원칙) — `screen_repository.py:6-11`. 장중 현재가는 이미 로컬 모드 관리자에게만 별도 열로 노출 중(DEC-085).

## 2. 장중 재계산이 쓸 입력과 지표별 가능 여부

### 2-1. 입력(`MarketQuote`)
`code, price, change, change_pct, volume, open, high, low, fetched_at` (`realtime/market.py:31-43`). **거래대금·상장주식수·투자자 수급·재무는 없다.** 값은 메모리에만 있고(`market.py:8`), 프로세스 재시작 후 한 바퀴 돌 때까지 비어 있다. 전 종목 한 바퀴 = ⌈종목 수/30⌉회 호출(2,800종목이면 94회, 문서 07 §2 가정)이고 **실제 한 바퀴 시간은 측정하지 못했다**(문서 07 §6, DEC-085).

"오늘 진행 중인 봉" = 일봉 이력(`daily_prices` 직전 거래일까지) + 현재가를 종가 자리에, 누적거래량을 거래량 자리에 넣은 가상의 오늘 행. 패턴 지표는 **종가·거래량만** 쓰므로(`compute.py:221-300`) 시가·고가·저가는 필요 없다.

### 2-2. 지표별 표
| 지표(저장 컬럼) | 일봉 계산식 근거 | 장중 재계산 | 판단 근거·주의 |
|---|---|---|---|
| 등락률 `return_pct` | `compute.py:27` | **가능** | 현재가 vs 발행일 종가. 발행일이 직전 거래일일 때만 유효(`screen.py:235` `is_latest`). 아니면 KIS `change_pct`와 기준일이 어긋남. 수정주가(분할) 미반영 시 오차는 일봉과 동일 한계 |
| 5·20일 이격 `ma5/ma20_gap_pct` | `compute.py:34` (당일 포함 평균) | **가능** | 정의가 "당일 포함"이라 현재가를 오늘 종가로 쓰면 그대로 성립. 일봉 최소 20행 필요 |
| 거래량 이상치 `volume_anomaly_score` | `compute.py:55` (직전 20일 평균·표준편차 vs 오늘) | **계산은 가능, 의미가 왜곡** | 장중 누적거래량은 부분 값이라 장 초반일수록 점수가 낮게 나온다. 시간대 보정 정책이 필요(§6 결정 2) |
| 거래량 필터 `volume_raw`(`volume_min`) | `run_derivation.py:191` | 가능(왜곡 동일) | 누적거래량이 곧 값. 부분 거래량이라 "최소 거래량" 필터 의미가 장중에 달라짐 |
| 패턴 11지표(횡보 폭·순변화·이평 수렴·변동성 수축·60일 이격·20/60 이격·60일 기울기·돌파 경과일·거래량비 5/60·급등 이력) | `compute.py:221-300` | **가능**(종가·거래량만 사용) | 80행 미만이면 `INSUFFICIENT_HISTORY`, 일 변동 ±31% 초과 단절은 `SUSPECT_PRICE_JUMP`(`:239-244`)가 장중에도 동일 적용 → 장중 급등 종목이 일시적으로 "산정 불가"로 바뀔 수 있음. 거래량비 5/60·급등 이력(c9: 거래량 ≥ 직전 20일 평균×3)은 부분 거래량 영향 |
| 패턴 판정 c1~c5·c9, `ma60_stage` | `pattern_repository.py:50-112` (SQL) | 지표가 있으면 가능하나 **SQL 판정을 Python으로 재구현** 필요 | 원칙 위반 위험(§1-3). 임계값은 환경변수(`pattern_config.py`) |
| 등락률 순위 `return_rank_pct` | `compute.py:77` | 조건부 가능 | 전 종목 값이 모여야 의미가 있다. 한 바퀴 미완주면 모집단이 달라져 순위 의미가 바뀐다 |
| PER·PBR·시총 및 백분위 `per/pbr/market_cap_percentile` | `run_derivation.py:222-237` | **불가(일봉 고정)** | 원천은 `raw_fundamentals`의 일 값(PER·PBR·시총, `raw_models.py:48-56`). 장중 값 원천이 없다. 상장주식수 컬럼은 이 저장소에서 확인하지 못함 → 가격으로 역산하는 방식은 추측이라 제안하지 않음 |
| PER/PBR 산정 불가 사유 | `run_derivation.py:129-141` | 불가(일봉 고정) | 재무 원문 의존 |
| 시장 요약: 상승/하락/보합 수 | `compute.py:131` | 가능 | `change_pct` 부호로 집계. 모집단이 한 바퀴 완주분일 때만 일관 |
| 시장 요약: 총 거래대금·업종별 거래대금 | `compute.py:157-165` | **불가** | `MarketQuote`에 거래대금이 없고(`market.py:31-43`) 업종 `sector`는 출처 미확정으로 대부분 비어 있을 수 있음(`compute.py:114-115`) |
| 투자자 수급·기관 연속 순매수·누적(선발 기준 ⑥⑦, 프런트에서만 판정) | `frontend/src/lib/extraCriteria.ts:46-72, 91-` | **스크리닝 전 종목은 불가** | 종목별 `주식현재가 투자자` 호출이 필요(수집 스크립트 주석: 전 종목 약 2,800회·수 분, `scripts/collect_investor_flow.py:11`). 스냅샷으로 만들 수 없고 현재도 종목 상세 한 종목만 60초 폴링(`StockDetailTabs.tsx:361-364`) |
| 실적(선발 기준 ⑧) | `extraCriteria.ts` `evaluateEarnings` | 해당 없음 | 연간 재무 기준이라 장중 변화 없음 |

## 3. 영향 화면 (`frontend/src` 확인)

| 화면 | 쓰는 API·필드 | 현재(DEC-085 이후) | 장중 재계산이 들어가면 바뀌는 값·동작 |
|---|---|---|---|
| **조건 스크리닝 `/screener`** (`ScreenerClient.tsx`) | `GET /screen` → `items[].matched_metrics`(등락률 값, 이격, 거래량 이상치, 시총·PER·PBR **백분위**), `total_count`, `page`, `meta.data_freshness` (`:110`, `screenMetricFormat.ts`) | 판정은 일봉. 로컬 관리자에게만 "현재가" 열 + 안내문 "조건 판정은 일봉 기준이며 장중 값으로 다시 계산하지 않습니다"(`copy.ko.json:332`, `ScreenerClient.tsx:219`) | ① 결과 **목록 구성 자체**가 장중에 계속 변함(들어오고 나가는 종목) ② `total_count`·페이지 수 변동, offset 페이지(`screen_repository.py:151-157`)로 넘기는 중 **중복·누락** 발생 → 스냅샷 식별자 필요 ③ 정렬 키가 장중 값이면 순서가 계속 바뀜 ④ 시총·PER·PBR 백분위는 일봉 고정이라 한 행에 "장중 값 + 일봉 값"이 섞임 ⑤ `DataFreshnessBadge`(발행 거래일, `:205,212`)의 뜻이 바뀜 → "장중 기준 HH:MM:SS, 커버 N/M" 필요 ⑥ 위 안내문은 **거짓이 되므로 문구 교체** ⑦ 백분위 범위 안내 `percentileScopeNotice`(`:215`) 재검토 ⑧ 값이 없는 종목은 결과에서 빠지는 규칙(NULL 비교)이 한 바퀴 미완주 종목에도 적용되는지 결정 필요 |
| **패턴 스크리닝 `/screener/pattern`** (`PatternScreenerClient.tsx`, `PatternResultsTable/List`) | `GET /screen/pattern` → `items[].conditions{c1..c9: met/reason}`, `metrics`(11개), `ma60_stage`, `readiness{evaluated,total,ready_ratio}`, `definition`, `data_freshness` (`patternApi.ts:54-64`) | 판정은 일봉. 현재가만 덮어씀(`useQuotes`, `:103`) | ① 조건 충족/미충족/산정 불가 **배지가 장중에 뒤집힘**(특히 c4 60일선 돌파 직전·초입, c5 거래량, c9 급등 이력) ② `readiness`(평가 가능 종목 수) 의미 변화(장중 급등으로 `SUSPECT_PRICE_JUMP` 증가 가능) ③ 정렬 `ma60_gap_pct`·`sideways_range_pct`·`ma_convergence_pct`가 흔들림, `market_cap` 정렬은 일봉 고정 ④ 점수·순위 없음(REQ-034)은 유지 ⑤ 부분 거래량에 의한 c5·c9 오판정 위험 |
| **종목 상세 `/stocks/[code]`** (`app/stocks/[code]/page.tsx`, `StockDetailTabs.tsx`) | 서버 렌더 `GET /stocks/{code}/metrics`(등락률 순위, 5/20 이격, 거래량 이상치, PER·PBR·시총 백분위; `page.tsx:105-142`), 탭 "조건 체크" `GET /stocks/{code}/pattern-check`(`:96-98, 273-281`) + 선발 기준 ⑥⑦⑧(`ExtraChecks`, `:346-390`) | 현재가·호가·체결은 이미 실시간 스트림. 지표 카드·조건 체크는 일봉 기준 | 스크리너와 **같은 종목이 다른 값**을 보이면 불일치 → 상세 카드·조건 체크도 같은 출처로 바꾸거나 "일봉 기준" 표기 유지 중 선택 필요. 카드는 서버 렌더라 클라이언트 갱신 구조 추가 필요. 수급 ⑥⑦는 이미 로컬 모드에서 종목 단위 60초 폴링이라 변화 없음 |
| **홈 시장 요약 `/`** (`app/page.tsx`) | 서버 컴포넌트 `GET /market-summary` → 상승/하락/보합 수, 총 거래대금, 업종 상위(`marketSummary.ts`) | 전일 기준(`force-dynamic`, 전 회원 대상) | 상승/하락 수만 장중화 가능. 총 거래대금·업종 불가(§2-2). 서버 렌더·전 회원 대상이라 로컬 전용으로 한정하려면 클라이언트 컴포넌트 신규 → **범위 제외 권장** |
| 종목 검색 `/stocks` (`StockSearchClient.tsx`) | `GET /stocks` + `useQuotes`(`:50`) | 현재가 이미 준실시간 | **영향 없음**(조건 값을 표시하지 않음) |
| 관심종목 `/watchlist` (`WatchlistClient.tsx:39`) | 브라우저 저장 코드 + `useQuotes` | 현재가 이미 준실시간 | **영향 없음** |

공통: 로컬 모드 관리자만 쓰는 기능이라 운영(Render) 화면은 변하지 않는다는 DEC-085 방침을 유지할 수 있다(`frontend/src/lib/localIntraday.ts`, `local_intraday.py:53-68`의 4중 통제 재사용 가능).

## 4. 설계 선택지

| | ① 서버 요청 시 병합 계산 (로컬 전용 신규 엔드포인트) | ② 장중 주기 배치로 별도 테이블 갱신 | ③ 브라우저에서 보이는 종목만 계산 |
|---|---|---|---|
| 방식 | `/api/v1/local/screen`, `/local/screen/pattern` 신설. 일봉 이력(`daily_prices` 100행×전 종목)을 메모리에 캐시(발행일이 바뀔 때만 재적재)하고, 스냅샷의 현재가·누적거래량으로 오늘 행을 만들어 지표 재계산 → Python으로 필터·정렬·페이지 | 장중 N분마다 배치가 같은 계산을 돌려 `derived_metrics_intraday`(신규) 같은 별도 테이블에 upsert. 기존 SQL 저장소가 테이블만 바꿔 그대로 판정 | 기존 `/screen` 결과 행(보이는 50건)에 대해 브라우저가 일봉 이력을 받아 지표를 다시 계산해 값만 갱신 |
| 장점 | DB 변경·마이그레이션 없음(운영 영향 최소). 스냅샷 신선도를 응답에 바로 실을 수 있음. 백분위·모집단 정책을 코드로 통제 | **SQL 판정 단일 출처 유지**(필터·정렬·offset 페이지 그대로). 백분위를 전 종목 기준으로 일관 계산(`build_derivation_inputs` 재사용). 결과가 한 시점으로 고정되어 페이지 이동이 안정적 | 가장 작은 변경. 서버 변경 거의 없음 |
| 단점·위험 | **Python 판정 재구현**(`pattern_repository.py` 원칙 위반) → 동치 시험 필수. 필터·정렬·총건수를 메모리에서 처리. 계산 비용은 미측정(문서 07 §4: "종목당 밀리초로 보는 것이 합리적이나 실측 필요"). `derivation_batch.compute`를 API가 import하는 경계 정리 필요(`shared/`로 이동) | 신규 테이블 + GRANT + alembic. **DB 변경 커밋은 푸시 전 Neon에 `alembic upgrade head` 선행**(`docs/HANDOFF.md` 운영 반영 방식, DEC-081). 배치 프로세스는 스냅샷(API 메모리)에 접근할 수 없다 → 배치가 증권사를 따로 호출하면 **앱키 한도를 두 프로세스가 나눠 쓰고 "앱키당 순환은 한 곳"(문서 07 §3) 원칙과 충돌**, API가 쓰게 하면 `api_service` SELECT 전용 원칙(DEC-006) 위반. 로컬 DB는 별도(`로컬서버-접속방법.md`: Docker PG)라 운영 데이터와 섞이진 않으나 마이그레이션 체인은 공유 | **목록 구성이 안 바뀐다**: 서버 결과에 없는 종목은 장중에 조건을 충족해도 안 보이고, 빠져야 할 종목은 값만 달라진 채 남음 → "재스크리닝"이 아니라 "표시값 갱신". 이력 공급용 다종목 일봉 API 신규 필요(현재 `GET /stocks/{code}/prices`는 종목당 1건 호출, `prices.py:87`), TS 재구현과 파이썬 결과의 소수점 일치(Decimal 4자리 `compute.py:23`) 시험 필요 |
| 호출 한도 영향 | 기존 순환 그대로(추가 증권사 호출 없음). 계산은 서버 CPU만 | 배치 구성에 따라 증권사 호출이 추가될 수 있음(위 충돌) | 추가 없음 |
| 백분위 일관성 | 정책 선택 가능(완주분 기준 / 일봉 고정) | 전 종목 일관 | 불가(보이는 50종목으로 백분위를 만들 수 없음 → 일봉 고정 필수) |
| 로컬 전용 여부 | 가능(4중 통제 재사용) | 로컬 DB 전용으로 가능하나 마이그레이션이 운영 체인에 포함됨 | 가능 |
| 운영 영향 | 낮음(꺼진 기능, 배포 후에도 운영 화면 불변) | 중간(DB 변경 절차, 운영 Neon에 빈 테이블 생성) | 낮음 |
| 결과가 장중에 변하는 문제 | 요청마다 달라짐 → 스냅샷 id 도입 필요 | 배치 주기마다만 변함(가장 안정) | 목록은 안 변함, 값만 변함 |

## 5. 공수 견적

### 5-1. 일수 기준(근거)
- 단위: **영업일**, 이 저장소의 기존 속도 — 에이전트 병렬 개발 + 내부 시험 결과서 작성 포함. **전부 추정**이며 정확도는 아래 불확실성에 좌우된다.
- 속도 참고(커밋 시각 기준, 작업 시작 시각은 기록으로 확인 불가): 패턴 스크리닝 전 기능(계산·마이그레이션·API·프런트·시험)은 2026-10-02 한 날의 커밋(12:28~17:46)에 모였고, 준실시간 시세 모듈→API→목록 화면 연결(DEC-084/085)은 2026-10-06 07:00~08:22 커밋. 다만 이 두 작업은 계산식·SQL 판정이 이미 있는 위에 얹은 것이라, **판정을 새로 구현하는 ①②는 그보다 길게** 잡았다. 시험은 결과서(`docs/qa/`)·회귀(unit 952건, 로그인 종단 324건 — `docs/qa/2026-10-06-market-screens-test-result.md` §2)까지 포함.

### 5-2. 선택지별 작업 항목
**① 서버 병합 계산(권장)**
| # | 작업 | 산출물 | 일수 |
|---|---|---|---|
| 1 | 계산 함수 공유화(`compute.py` → `shared/`, 기존 import 유지) | 이동·재노출, 기존 시험 무수정 통과 | 0.5 |
| 2 | 일봉 이력 메모리 캐시(`daily_prices` 100행, 발행일 변경 시 재적재) | 로더·캐시 모듈 | 0.5 |
| 3 | 오늘 행 병합 + 지표 재계산(등락률·이격·거래량 이상치·패턴 11지표), 부분 거래량 정책 | 병합 모듈 | 1.0 |
| 4 | 조건 판정 Python판(screen 필터 7종, 패턴 c1~c5·c9, `ma60_stage`, readiness, 정렬·페이지·총건수) | 판정 모듈 | 1.0 |
| 5 | 백분위 정책 구현(등락률 순위 완주분/일봉 고정, 나머지 일봉 고정) | 정책 모듈 | 0.5 |
| 6 | 로컬 엔드포인트 2종 + 응답 메타(기준 시각·커버 N/M·stale·스냅샷 id) | 라우터·스키마 | 0.5 |
| 7 | 프런트: 두 스크리너의 "장중 기준" 전환·표지·안내문 교체·갱신·페이지 안정화·모바일 | 화면 변경 | 1.0 |
| 8 | 종목 상세 카드·조건 체크 탭 정합(선택) | 화면·엔드포인트 | 0.5 |
| | **개발 소계**(항목 합 5.5, 서버·프런트 병렬 반영) | | **4** |
| 9 | 동치 시험: 확정 봉을 넣으면 기존 SQL 결과와 일치(`golden_screen_before_pattern.json` 방식) | 단위·통합 시험 | 1.0 |
| 10 | 모의 증권사 서버(`scripts/mock_kis_server.py`) 종단·성능(2,800종목 계산 시간 실측) | 통합 시험 | 0.5 |
| 11 | 프런트 `check-*.mjs` + 로컬 모드 종단(`local_mode_stack.py`) | 시험 | 1.0 |
| 12 | 회귀(unit 전체·로그인 종단) + 결과서 | `docs/qa/` 결과서 | 0.5 |
| | **시험 소계** | | **3** |
| | **합계** | | **7 (범위 6~10)** |

**② 장중 배치 + 별도 테이블**
| # | 작업 | 산출물 | 일수 |
|---|---|---|---|
| 1 | 신규 테이블·GRANT·alembic(0019) + 운영 Neon 선행 절차 | 마이그레이션 | 0.5 |
| 2 | 스냅샷 공급 방식 설계·구현(배치가 API 로컬 엔드포인트를 읽는 방식 등, 한도 충돌 해소) | 수집부 | 1.5 |
| 3 | 장중 계산 배치(`compute_stock_day_metrics`·`build_derivation_inputs` 재사용) + upsert | 배치 스크립트 | 1.0 |
| 4 | 조회 저장소 2종에 장중 모드(테이블·기준 시각) + 신선도 메타 | 저장소 변경 | 1.0 |
| 5 | API 파라미터·라우터(로컬 전용) | 라우터 | 0.5 |
| 6 | 프런트(① 7번과 동일 범위) | 화면 변경 | 1.0 |
| 7 | 스케줄·운영(작업 스케줄러, 장 시간·휴장일 달력, 중복 실행 락) | 스크립트·가이드 | 0.5 |
| | **개발 소계** | | **6** |
| 8 | 마이그레이션·권한 시험, 통합(`pg_temp_db`) | 시험 | 1.5 |
| 9 | 종단(배치→API→화면), 장애(배치 지연·중단 시 stale 표시) | 시험 | 1.0 |
| 10 | 회귀 + 결과서 | `docs/qa/` | 1.5 |
| | **시험 소계** | | **4** |
| | **합계** | | **10 (범위 9~14)** |

**③ 브라우저 계산(표시만)**
| # | 작업 | 산출물 | 일수 |
|---|---|---|---|
| 1 | 다종목 일봉 이력 조회 API(로컬, 보이는 종목용) | 라우터·저장소 | 0.5 |
| 2 | TS 계산 포팅(등락률·이격·거래량 이상치, 선택: 패턴) | `frontend/src/lib/` | 1.0 |
| 3 | 표시 변경(값 갱신, "표시값만 장중" 안내) | 화면 | 1.0 |
| 4 | 파이썬 결과와의 일치 시험(소수 4자리) | 시험 | 1.0 |
| 5 | `check-*.mjs`·종단·결과서 | 시험 | 1.0 |
| | **합계**(개발 3 + 시험 2) | | **5 (범위 4~7)** |

범위 축소 가감(추정): 패턴 스크리닝을 제외하고 조건 스크리닝(등락률·이격·거래량 이상치)만 하면 ①에서 약 2일 감소. 종목 상세 정합(8번)을 빼면 약 0.5~1일 감소.

### 5-3. 불확실성이 견적에 주는 폭
| 불확실성 | 확인 상태 | 견적 영향(추정) |
|---|---|---|
| 실제 증권사 응답(필드명, 시가·고가·저가 0, 장 시작 전 값) | 확인하지 못함(앱키 없음, 문서 07 §6) | 정규화 수정·시험 재작업 +0.5~1일 |
| 2,800종목 한 바퀴 시간·호출 한도 | 미측정(5/8/10/20건/초 가정표만 있음, 문서 07 §2) | 한 바퀴가 길면(완주 지연) 모집단·stale 정책이 복잡해져 +1~2일. 짧아도 일수는 거의 안 줄고 시험이 단순해질 뿐 |
| Python 판정과 SQL 판정의 동치 | 시험 전에는 알 수 없음 | 경계 조건 불일치 발견 시 +0.5~1일(①) |
| 계산 비용(2,800종목 × 지표, 요청마다/주기마다) | 미실측 | 느리면 캐시·증분 계산 추가 +1일(①) |
| 상장주식수·장중 PER 원천 | 확인하지 못함 | 견적에 넣지 않음(범위 제외로 가정). 넣으면 별도 조사 필요 |

### 5-4. 실제 장중 검증에 필요한 달력상 기간(개발·시험일과 별도)
개발 환경에서는 실제 증권사에 접속하지 못하므로(앱키 없음), **사용자 PC에서 증권사 앱키로 장중에 확인**해야 한다. 평일 장중만 가능하다(폴러 기본 장 시간 평일 08:00~20:00 KST, `market.py:65-68`; 공휴일은 모름).

| 단계 | 내용 | 필요 장중 | 비고 |
|---|---|---|---|
| A. 선행 실측(재계산 결정과 무관, 지금 가능) | `/api/v1/local/market/status`의 `cycle_seconds`·`covered/total`, 응답 필드명, 한도, 장 시작 전 시가·고가·저가 값(문서 07 §4-4) | 1회(약 1거래일, 장 시작 전 포함) | 이 결과로 §5-3의 폭이 가장 크게 줄어든다 |
| B. 개발 후 1차 | 실제 응답으로 재계산 값 육안·수치 점검, 완주·stale 거동 | 1 거래일 | 필드 불일치 발견 시 수정 후 재확인 |
| C. 마감 대조 | 마지막 장중 재계산 값 vs 마감 후 일일 배치가 만든 `derived_metrics_daily` 값 비교(등락률·이격·패턴 지표 일치 여부) | 1 거래일 + 배치 완료 후 | 이 대조가 정확성의 최종 증거 |

달력상 약 **1~1.5주**(추정): 사용자가 연속 영업일에 PC·앱키로 B·C를 수행하고, 불일치 수정이 한 번 있다고 가정. 개발·시험 7영업일(①)과는 겹치지 않는 사용자 시간이 필요하다.

## 6. 결정이 필요한 사항 (사용자에게 물어야 할 것만)
| # | 질문 | 선택지 | 영향 |
|---|---|---|---|
| 1 | 재계산 범위 | (가) 조건 스크리닝만 (나) +패턴 (다) +종목 상세 정합 | 일수 ±2일, 화면 수 |
| 2 | 장중 **부분 거래량**을 어떻게 다룰까(거래량 이상치·거래량비·급등 이력 c5/c9, `volume_min`) | 시간대 보정 / 보정 없이 "장중 부분값" 경고 표시 / 거래량 계열은 일봉 고정 | 판정 결과 신뢰도, 개발 +0.5~1일 |
| 3 | 백분위(등락률 순위)와 시총·PER·PBR 처리 | 시총·PER·PBR은 일봉 고정(원천 없음) 동의 여부, 등락률 순위는 완주분 기준 재계산 vs 일봉 고정 | 한 행에 장중 값+일봉 값 혼재 허용 여부 |
| 4 | 결과 목록이 장중에 계속 변하는 것을 허용? | 자동 갱신 / "이 시점으로 고정" 버튼 / 수동 새로고침 | 페이지 안정화 구현량, 선택지 ①/② 선호 |
| 5 | 한 바퀴를 못 끝낸 종목 | 결과에서 제외 / 일봉 값 유지(혼합) | 목록 신뢰도 |
| 6 | 로컬 모드 관리자 전용 유지 확정? | 유지(DEC-085 연장, 약관 미확인) / 운영 노출 검토 | 운영 노출은 이 견적 범위 밖(약관·앱키 공유·서버 IP 확인 필요) |
| 7 | (선택지 ② 채택 시만) 마이그레이션 체인에 장중 테이블 추가 허용? | 허용 / 불허(→ ① 또는 ③) | 운영 Neon 선행 절차 |

## 7. 확인하지 못한 것
- 실제 증권사 응답·호출 한도·전 종목 한 바퀴 시간(앱키 없음). 활성 종목 수의 실측값(문서의 2,800은 가정).
- 서버 메모리 계산의 실제 CPU 시간(미실측). 로컬 PC 사양에 따른 차이.
- `daily_prices`에 종목당 100행이 항상 있는지(보존 400일 설정은 확인 `repository.py:352`, 종목별 실보유는 DB 미조회).
- 상장주식수·장중 PER 원천(저장소에서 찾지 못함).
- 수정주가(액면분할) 반영 방식이 장중 병합에서 어떻게 보일지(일봉과 같은 한계로 가정, 실데이터 미확인).
- 일수는 모두 이 저장소의 과거 속도에서 유추한 추정이며, 실제 소요는 §5-3 불확실성에 따라 달라진다.
