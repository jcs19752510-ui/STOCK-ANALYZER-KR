# 05. 테스트 계획서 — 패턴 스크리닝 "급등 전 압축주"

- 작성일: 2026-10-02 (KST) · 버전: v1 → 검증 후 v2(최종)
- 입력: [01 기획서](01-planning.md) · [02 설계서](02-system-design.md) · [03 디자인서](03-ux-design.md) · [04 개발계획](04-development-plan.md)
- 결과 기록 양식: `templates/test-report-template.md`(UNIT-18에서 작성). **근거 없는 "이상 없음" 금지, 실패는 실패 그대로 기록**한다.

## 1. 전략·환경

| 항목 | 방침 |
|---|---|
| 계층 | ① 순수 함수 단위(DB 없음) ② DB·배치 통합(임시 DB) ③ API 계약(FastAPI `TestClient` + Fake 리포지토리, 그리고 임시 DB의 실제 SQL) ④ 프런트(tsc/eslint/린트/빌드 + **실제 브라우저**) ⑤ 보안·성능·접근성 |
| **임시 DB** | 컨테이너(`stock-screener-pg`)에서 `docker exec stock-screener-pg psql -U postgres`(슈퍼유저, 2026-10-02 접속 확인)로 `stock_screener_test_<난수>` 생성 → `alembic upgrade head` → 픽스처 적재 → 테스트 → **try/finally로 DROP**(정상·중단 모두 정리, 규칙 K). **개발 DB `stock_screener`에는 합성 데이터를 넣지 않는다** |
| 오라클 | `docs/pattern-screening/prototype/pattern_rules_reference.py` — 계산 결과 교차 검증 기준 |
| 서버 | 개발 서버(DB·4001·4000)는 테스트 후에도 켜 둔다. 임시 포트가 필요하면 4001/4000을 피한다 |
| 합격 기준 | 아래 TC **전부 통과**, 기존 회귀 0건. 실패 시 근본 원인을 고치고 해당 TC와 그 하위 의존 TC를 다시 실행 |

### 1-1. 픽스처 종목 (임시 DB에 적재, 각 130거래일, 시드 고정 → 결정론적)

| 코드 | 설계 의도 | 기대 상태 / 조건 |
|---|---|---|
| `T00001` | 이상적 패턴(횡보→수렴→60일선 근접→점진 거래량) | OK, **c1·c2·c3·c4·c5·c9 모두 true** |
| `T00002` | 80일 동안 +30% 이상 상승 추세 | c1 false |
| `T00003` | 이평선이 넓게 벌어짐(수렴 폭 > 3%) | c2 false |
| `T00004` | 종가가 60일선 +9% 위 | c3 false |
| `T00005` | 최근 돌파 후 60일선 +12% 위 | c4 false(`EXTENDED`) |
| `T00006` | 오늘 거래량 8배 | c5 false |
| `T00007` | 10거래일 전 +12%·거래량 6배 | c9 false |
| `T00008` | 시세 50거래일뿐 | `INSUFFICIENT_HISTORY`, 전 조건 null |
| `T00009` | 중간에 −50% 단절 | `SUSPECT_PRICE_JUMP`, 전 조건 null |
| `T00010` | 가격·거래량 완전 평탄 | OK이지만 c2·c5 일부 값 NULL → **null/false 혼합**(3값 논리 검증) |

경계값 TC는 시계열이 아니라 **`derived_metrics_daily`에 지표 값을 직접 삽입**해 정확한 경계(예: `sideways_range_pct = 40.0` / `40.0001`)를 만든다.

## 2. 요구사항 ↔ 테스트 추적

| REQ | 검증하는 TC 그룹 |
|---|---|
| REQ-030 | TC-U01~U16·U40~U42, TC-D01~D08 |
| REQ-031 | TC-B01~B08 |
| REQ-032 | TC-A01~A35, TC-C01~C08 |
| REQ-033 | TC-F01~F26, TC-X01~X06 |
| REQ-034 | TC-R01~R06, TC-F19 |
| REQ-035 | TC-A15·A19·A20·A33, TC-F10·F11·F15·F16 |
| REQ-036 | TC-S01~S12, TC-P01~P04, TC-C01~C08 |
| 회귀 | TC-G01~G06 |
| REQ-037/038 | 해당 없음(로드맵, 설계 제외) — 구현되지 않았음을 TC-G07로 확인 |

## 3. 단위 — 계산 함수 (TC-U, UNIT-13)

| ID | 시나리오 | 입력 | 기대 |
|---|---|---|---|
| U01 | **완전 평탄**(손계산) | 종가 100×100행, 거래량 1000×100행 | `range=0, net=0, conv=0, ma60_gap=0, ma20_vs_ma60=0, slope=0, cross=None, volume_ratio=1.0, surge=False, status=OK`, **`volatility_contraction_ratio=None`**(60일 표준편차 0) |
| U02 | **선형 상승**(손계산) | 종가 `c[i]=200−i`(i=0 최신, 100행), 거래량 1000 고정 | `range=49.2212`(=79/160.5), `net=65.2893`(=79/121), `conv=3.9370`(MA5=198, MA20=190.5), `ma60_gap=17.3021`(MA60=170.5), `ma20_vs_ma60=11.7302`, `slope=6.2305`(MA60(T−10)=160.5), `volume_ratio=1.0`, `cross=None`, `surge=False` (소수 4자리, 허용오차 1e-3) |
| U03 | 경계: 행 수 | 79행 / 80행 | 79 → `INSUFFICIENT_HISTORY`(전 필드 None) / 80 → `OK` |
| U04 | 경계: 단절 | 윈도우 내 단일일 변동 +31.0% / +31.1% | 31.0 → OK / 31.1 → `SUSPECT_PRICE_JUMP` |
| U05 | 종가 0 이하 | 윈도우에 0 포함 | `SUSPECT_PRICE_JUMP`, 예외 없음 |
| U06 | 분모 0: 60일 수익률 표준편차 | 가격 평탄 | `volatility_contraction_ratio=None`, status는 OK |
| U07 | 분모 0: 60일 평균 거래량 0 | 거래량 전부 0 | `volume_ratio_5_60=None` |
| U08 | MA60 상향 돌파 일수 | 돌파 시점 k=0,1,…,9 각각 / 없음 / `종가==MA60`(돌파 아님) | `cross_up_days=k` / None / None |
| U09 | 돌파 관찰창 경계 | k=10(관찰창 밖) | None |
| U10 | 급등 플래그 경계 | (일 +10.0%, 거래량 3.0배, 5일 전) | **True**(경계 포함) |
| U11 | 〃 | +9.99% / 2.99배 | False / False |
| U12 | 〃 관찰창 | 19일 전 / 20일 전 | True / False |
| U13 | 급등 기준 거래량 0 | 직전 20일 평균 거래량 0 | 해당 일 건너뜀(0나눗셈 없음) |
| U14 | 순변화·범위 부호 | 하락 추세 | `net<0`, `range>0` |
| U15 | Decimal/float 일관성 | 동일 시계열 | Decimal 구현 vs 오라클 차이 ≤ 1e-3, 4자리 반올림 |
| U16 | 순수성 | 동일 입력 2회 | 동일 출력, I/O·전역상태 변경 없음 |
| U40 | **오라클 교차 검증** | 합성 시계열 300개(시드 고정) | 11개 필드·status 전부 오라클과 허용오차 내 일치 |
| U41 | **윈도우 절단** | 130행 입력 vs 같은 시계열의 앞(최신) 100행만 입력 | 11개 필드·status **동일**(100행 밖의 오래된 데이터가 결과에 영향 없음 — 배치가 100행만 조회해도 안전함을 보장) |
| U42 | 입력 규약 | 최신순(내림차순) 입력 — 첫 원소가 대상일 | 동일 데이터를 오름차순으로 넣으면 결과가 달라짐을 확인하고, docstring·주석에 "최신순 입력" 규약을 명시(오용 방지 문서화 TC) |

## 4. 백필 (TC-B, UNIT-12)

| ID | 시나리오 | 기대 |
|---|---|---|
| B01 | `--dry-run` | 외부 호출 0회, 대상 날짜 수·예상 호출 수 출력 |
| B02 | 이미 충분한 날짜 | 건너뜀(호출 안 함), 로그에 사유 |
| B03 | 응답 0건 날짜 | 비거래일이면 정상 스킵, **캘린더상 거래일인데 0건이면 경고** |
| B04 | **서킷브레이커 비오염** | 백필 중 일부 날짜 실패 후 `circuit_breaker.evaluate`(최근 상태 목록) 결과가 백필 때문에 `is_open=True`가 되지 않음. 백필은 `batch_run` **1행/실행** |
| B05 | **키 비노출** | 실패·예외·`--dry-run`·verbose 어느 경로의 stdout/stderr/로그에도 서비스키·키 포함 URL 없음 |
| B06 | 중단 후 재개 | 중간 예외 주입 → 일관 상태 → 재실행이 이어서 완료(중복 입력 없음, upsert 멱등) |
| B07 | `--max-calls` | 상한 도달 시 **깨끗하게 종료**하고 남은 날짜를 보고 |
| B08 | 목표 충족 검증 쿼리 | 실행 후 `n≥80` 종목 비율 ≥ 95%(실데이터 UNIT-12 승인 실행 후) |

## 5. DB·배치 (TC-D, UNIT-14)

| ID | 시나리오 | 기대 |
|---|---|---|
| D01 | `upgrade head`→`downgrade 0010`→`upgrade head` | 가역, 컬럼 11개 생성/삭제 |
| D02 | CHECK 제약 | `pattern_metrics_status='BAD'` INSERT 거부 |
| D03 | nullable·구 행 | 기존 행의 신규 컬럼 NULL, 기존 쿼리 영향 없음 |
| D04 | `run_once` 멱등 | 130행 픽스처로 2회 실행 → 동일 결과, 행 수 불변 |
| D05 | **권한** | `api_service`: 신규 컬럼 SELECT 가능, INSERT/UPDATE/DELETE **거부**. `batch_worker`: 쓰기 가능 |
| D06 | 혼합 상태 발행 | T00001~T00010 혼합에서 `SUCCESS`, `current_published_batch` 갱신 |
| D07 | `_validation_passed` 불변 | 패턴 지표가 전부 NULL이어도(이력 부족) 기존 검증·발행 로직 결과가 달라지지 않음 |
| D08 | **기존 지표 무변화** | 윈도우 41→100 변경 후에도 `return_pct`·`ma5/20_gap_pct`·`volume_anomaly_score`가 **동일 입력에서 동일 값**(변경 전후 비교) |

## 6. 설정 (TC-C, UNIT-15)

| ID | 시나리오 | 기대 |
|---|---|---|
| C01 | 환경변수 없음 | 기본값(설계서 §3-3) 적용 |
| C02 | 범위 밖 값(예: `PATTERN_RANGE_MAX_PCT=101`) | `ConfigError`, **기동 실패** |
| C03 | 타입 오류(`abc`, 빈 문자열) | `ConfigError` |
| C04 | `VOLUME_RATIO_MIN ≥ MAX` | `ConfigError` |
| C05 | `CROSS_EARLY_MAX_DAYS=11` | `ConfigError`(관찰창 10 초과) |
| C06 | 경계값 허용(범위 끝점) | 통과 |
| C07 | `PATTERN_SCREEN_ENABLED` 값 | `true/false` 외 → `ConfigError` |
| C08 | 응답 `definition`이 로드된 설정과 동일 | 일치(A24와 연계) |

## 7. API (TC-A, UNIT-16)

| ID | 시나리오 | 기대 |
|---|---|---|
| A01 | 기본 호출 | 200, envelope 구조(`meta.data_freshness`, `disclaimer`, `data.items/total_count/page/definition/readiness`) |
| A02 | `market=KOSPI/KOSDAQ/ALL` | 해당 시장만 / 전체 |
| A03 | `required` 생략 | 6개 조건 모두 true인 종목만(픽스처: `T00001`) |
| A04 | `required=c1,c2` 부분집합 | c1·c2 true인 종목 포함(다른 조건 false여도) |
| A05 | `required` 중복(`c1,c1`) | 400 `INVALID_PARAMETER` |
| A06 | 미지 ID(`c7`, `c6`) | 400 |
| A07 | 빈 값 `required=` | 400 |
| A08 | 공백 포함 `c1, c2` | 400 |
| A09 | `sort_by` 허용값 4종 | 각각 200 / 그 외 400 |
| A10 | `sort_dir` 오류 | 400 |
| A11 | `page_size=201` | 400 |
| A12 | `page=0` | 기존 `/screen`과 동일 형식의 오류 |
| A13 | 페이지네이션 결정론 | 동률 시 `stock_code` 오름차순, 페이지 간 중복·누락 없음 |
| A14 | 정렬 NULL 처리 | 산정 불가 행이 **마지막**(NULLS LAST) |
| A15 | **3값 응답 매핑** | `T00008`→전 조건 `met=null, reason=INSUFFICIENT_HISTORY`; `T00009`→`SUSPECT_PRICE_JUMP`; `T00010`→ 값 NULL인 조건만 `null`+`METRIC_UNAVAILABLE` |
| A16 | 필터는 TRUE만 통과 | FALSE·NULL 행은 `required` 조건에서 **제외** |
| A17 | `total_count` | 필터 적용 후 실제 건수와 일치 |
| A18 | `readiness` | `evaluated_count`=status OK 행 수, `total_count`=시장 필터 후 활성 행 수, `ready_ratio` 일치 |
| A19 | **`PATTERN_DATA_NOT_READY`** | 발행일에 OK 행 0건 → 424 + 코드 정확 |
| A20 | OK 일부·결과 0건 | **200 + 빈 목록**(에러 아님) |
| A21 | 발행 데이터 없음 | 503 `DATA_PIPELINE_STALE`(기존 흐름) |
| A22 | 캘린더 오류 | 424/503 기존 코드 |
| A23 | **응답 필드 화이트리스트** | `items[*]` 키 = {stock_code,name,market,conditions,metrics,ma60_stage}, `metrics` 키 = 설계서 §5-2 11개. **`open/high/low/close`·`volume_raw`·`*_raw`·시가총액 원값 키 부재**(재귀 검사) |
| A24 | `definition` | 설정값·계산 파라미터와 일치 |
| A25 | 기능 스위치 off | 404 `FEATURE_DISABLED` |
| A26 | envelope 공통 | `data_freshness`·`disclaimer`·`generated_at` 존재, `staleness_note` 지연 시 포함 |
| A27 | `market_cap_min`·`volume_min` | 필터로만 동작, **응답에 원값 없음** |
| A28 | **임계값 경계 포함성** | 각 임계값마다 정확히 경계인 행(=)·경계 초과 행을 직접 삽입 → ≤/≥ 포함 규칙대로 true/false |
| A29 | **3값 논리** | c2: `conv`가 임계 초과(false)·`volatility_contraction_ratio` NULL → 결과 **false**(NULL 아님). `conv` 충족·ratio NULL → **null** |
| A30 | 상태 게이트 | `pattern_metrics_status≠OK`면 모든 조건 null(지표 값이 채워져 있어도) |
| A31 | **`ma60_stage`↔c4 일치** | (gap, cross_days) 격자 전수(−10…+15%, cross NULL/0…12)에서 `met(c4)=true` ⇔ stage∈{BELOW_NEAR, CROSS_EARLY} |
| A32 | 정렬 4종×2방향 | 올바른 순서 |
| A33 | 구 배치 행(status NULL) | 전 조건 null, reason `METRIC_UNAVAILABLE` |
| A34 | 직렬화 | 응답 JSON에 NaN/Infinity 없음, Decimal→수치 정상 |
| A35 | **기존 `/screen` 불변** | 동일 픽스처에서 `/screen` 응답이 변경 전과 동일(골든 비교) |

## 8. 보안 (TC-S)

| ID | 시나리오 | 기대 |
|---|---|---|
| S01 | `required`/`sort_by`에 SQL 메타문자(`'; DROP …`, `c1) OR (1=1`) | 400, DB 에러·500 없음 |
| S02 | `required` 1,000개 항목 | 400, 즉시 응답(파싱 상한) |
| S03 | 알 수 없는 쿼리 파라미터 | 무시, 결과에 영향 없음 |
| S04 | **임계값 우회 시도**(`range_max_pct=100`, `threshold=…`) | 무시(서버 설정만 적용) — 결과가 기본값과 동일 |
| S05 | rate limit | 신규 경로도 기존 `RateLimitMiddleware` 적용(상한 초과 시 429, 헤더 포함) |
| S06 | 보안 응답 헤더 | CSP 등 기존 헤더가 신규 경로·429·503 응답에도 부착 |
| S07 | 원본 필드 비노출 | A23 + 스키마 파일(`schemas/pattern.py`)에 가격 필드 선언 0건 |
| S08 | DB 장애 시 | 503 Envelope, DB URL·비밀번호·스택트레이스 미노출 |
| S09 | 백필 키 비노출 | B05 |
| S10 | 프런트 정적 점검 | `dangerouslySetInnerHTML` 0건, 키·시크릿 문자열 0건(grep) |
| S11 | CORS | 허용 오리진(4000) 외 preflight에 `Access-Control-Allow-Origin` 없음 |
| S12 | **의존성 불변** | `requirements*.txt`·`frontend/package.json`·`package-lock.json` 변경 0줄 |

## 9. 성능 (TC-P)

| ID | 시나리오 | 기준(제안 — 측정값을 기록하고 사용자 확정) |
|---|---|---|
| P01 | API 응답 시간 | 임시 DB에 ~2,700 종목 규모 데이터, 50회 요청 p95 ≤ 500ms |
| P02 | 실행 계획 | `EXPLAIN`으로 단일 거래일 범위 스캔(기존 인덱스 활용) 확인·기록 |
| P03 | **배치 소요 시간 전후 비교** | 윈도우 41→100 변경 전/후 `run_derivation` 시간을 같은 데이터로 측정·기록(증가분이 일일 스케줄 창을 넘지 않을 것) |
| P04 | 프런트 | 모바일 Lighthouse Performance ≥ 80(기존 KPI) — 측정·기록 |

## 10. 프론트엔드 (TC-F, UNIT-17) — 실제 브라우저로 확인(320/375/768/1024/1280px)

| ID | 시나리오 | 기대 |
|---|---|---|
| F01 | `tsc --noEmit`·`eslint`·`next build` | 전부 통과 |
| F02 | `npm run lint:copy` | `pattern.*` 카피 포함 통과 |
| F03 | **금지어 음성 검사** | `pattern.*`에 "추천"을 주입 → 빌드 실패(exit 1), 원복 후 통과 |
| F04 | 전환 링크 | 두 화면 모두 2개 링크, 현재 항목 `aria-current="page"` |
| F05 | `/screener` 불변 | 기존 동작·기본값·결과가 전환 링크 추가 외 동일 |
| F06 | 진입 시 자동 조회 | 기본값(시장 전체·500억·100,000주·6개 조건)으로 1회 조회 |
| F07 | 로딩 | 스켈레톤 행 5개·CLS 없음·필터 조작 가능·버튼 비활성 |
| F08 | ≥1024 표 | 열 6개+종목, 헤더 `scope`, `caption` |
| F09 | <1024 카드 | **320px에서 가로 스크롤 없음**(`scrollWidth ≤ clientWidth`) |
| F10 | 상태 배지 | 글리프+텍스트 동시 표기, 색만으로 구분하지 않음 |
| F11 | 산정 불가 사유 | `reason` 3종이 배지 아래 **항상 보임**(툴팁 의존 아님) |
| F12 | 정의 패널 | API `definition` 값으로 렌더 — **환경변수 값을 바꿔 재기동하면 화면 문구가 따라감** |
| F13 | 필수 조건 전부 해제 | 인라인 오류+첫 오류 필드 포커스, 요청 미전송 |
| F14 | 결과 0건 | 지정 문구, **대안 제시/추천 문구 없음** |
| F15 | `PATTERN_DATA_NOT_READY` | EmptyState `pattern-data-not-ready`(에러 스타일 아님) |
| F16 | `ready_ratio<1` | `ReadinessNote` 표시, 행은 "산정 불가(사유)" |
| F17 | 오류 3종 | 503 network / 424 calendar / 429 rate-limited 변형 |
| F18 | 기능 스위치 off | 전환 링크 미렌더, `/screener/pattern` 404 |
| F19 | **명칭 단일 출처** | "급등 전 압축주" 문자열이 소스에서 `copy.ko.json`의 `pattern.label` 1곳에만 존재(grep) — 키 값을 바꾸면 제목·링크·`metadata`가 모두 변경 |
| F20 | 키보드 전용 | Tab 순서·포커스 링 가시·바텀시트 ESC·포커스 복귀 |
| F21 | 바텀시트 포커스 트랩 | 시트 열린 동안 포커스가 시트 밖으로 나가지 않음 |
| F22 | 스크린리더 라벨 | 접근성 트리에서 배지 "충족/미충족/산정 불가, 사유", 표 `caption`, 결과 `aria-live` |
| F23 | 확대 200% | 내용 손실·가로 스크롤 없음 |
| F24 | `prefers-reduced-motion` | 스켈레톤 애니메이션 제거 |
| F25 | 면책 배너 | `DisclaimerBanner` 고정·닫기 불가가 이 화면에서도 유지 |
| F26 | 내비 활성 | `/screener/pattern`에서 "조건 스크리닝" 활성, `/screenerxyz`에서는 비활성(접두 충돌 회귀) |

## 11. 접근성 수동 점검 (TC-X)

| ID | 점검 | 방법 |
|---|---|---|
| X01 | 명도 대비(본문 4.5:1·UI 3:1) | 렌더된 색으로 계산 |
| X02 | 터치 타깃 ≥ 44px | 컴퓨티드 크기 측정 |
| X03 | 헤딩 구조 | `h1`→`h2` 순서 |
| X04 | 폼 라벨 연결 | 모든 입력에 `label`/`aria-label` |
| X05 | 오류 연결 | `aria-invalid`·`aria-describedby` |
| X06 | 언어 속성 | `lang="ko"` 유지 |

## 12. 규제·표현 (TC-R)

| ID | 점검 | 기대 |
|---|---|---|
| R01 | 금지어 린트 | 통과(공백 제거 후 `FORBIDDEN_TERMS`·정규식) |
| R02 | **비예측 고지 상시 노출** | `PatternNotice`가 정상·로딩·빈·준비중·오류 모든 상태에서 DOM에 존재, 닫기 컨트롤 없음 |
| R03 | 서열 표현 부재 | 소스·화면에 "TOP", "1위", "유력", "BEST", "점수", "순위" 0건(grep, 허용 예외 명시) |
| R04 | "급등" 사용처 | 허용 목록(`pattern.label`, `recent_surge` 근거 문장, 문서) 외 0건 |
| R05 | **REQ-022 범위** | 기획서·`traceability.md` 갱신본에 "패턴 명칭·표현이 확인 범위에 포함"이 명시됨 |
| R06 | 정의 패널 고지 | 대리 지표·수급/실적 미반영 안내 2줄 존재 |

## 13. 회귀 (TC-G)

| ID | 점검 | 기대 |
|---|---|---|
| G01 | `pytest tests/unit` 전체 | 변경 전 통과 수와 동일 이상, 신규 실패 0(전후 개수 기록) |
| G02 | `ruff check .` | 통과 |
| G03 | `tsc`·`eslint`·`next build` | 통과 |
| G04 | 기존 스크리너 | 기본 조회 정상, `/screen` 골든 일치(A35) |
| G05 | 기존 API | `/stocks`·`/stocks/{code}/metrics`·`/market-summary`·`/health` 200 |
| G06 | 마이그레이션 체인 | 임시 DB에서 `downgrade base`→`upgrade head` 성공 |
| G07 | 범위 밖 미구현 확인 | c6·c7·c8 관련 코드·엔드포인트·화면 요소 없음 |

## 14. 결함 처리·보고

- 심각도: Critical(규제·보안·데이터 노출) / High(판정 오류·회귀) / Medium / Low. Critical·High는 **수정 후 해당 TC와 의존 TC 재실행**, Medium·Low는 사유와 함께 기록(배포 차단 여부 명시).
- 모든 결과는 **실제 실행 출력**을 근거로 기록한다. 실행하지 못한 TC는 "미실행(사유)"로 남기고 통과로 세지 않는다.
- 최종 보고에 포함: TC 총수·통과·실패·미실행, 신규 결함, 사용자 결정 대기 항목(Q2·Q4·Q5).
