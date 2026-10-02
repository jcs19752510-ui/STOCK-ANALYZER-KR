# 종목 상세(C안) 내부 테스트 결과서 (UNIT-19~24)

- 작성: 2026-10-02 17:40(KST) · 대상: DEC-041 종목 상세 확장(공개 일봉·차트·일자별 시세·실적 탭·조건 체크·목록 시세)
- 근거 문서: `01-design-and-plan.md`, `units-19-22-note.md`, `00-data-source-research.md`
- 원칙: 아래 수치는 이 세션에서 실제로 실행한 결과이며, 실행하지 못한 것은 "미실행/한계"로 분리해 적었다(통과로 세지 않음).

## 1. 판정 요약

| 구분 | 결과 |
|---|---|
| 전체 판정 | **PASS (조건부)** — 코드·계산·API·화면은 설계 범위에서 동작함을 실행으로 확인. 남은 조건은 모두 외부 요인(약관·법률 검토, 실기기) |
| 자동 테스트 | Python **770 passed**(단위 571 + 통합 199, 실패 0·건너뜀 0), 프론트 계산 **14 pass**(Node 내장 러너), `tsc`·`eslint`·금지표현 검사·`ruff check`(scripts services shared tests db) 통과 |
| 신규 테스트 | C안 착수 전(658) 대비 **+112건**: 일봉 API 단위 28 · 일봉/목록시세 통합 8 · 실적 통합 4 · 실적 스크립트 단위 5 · DART 파서 단위 5 · 패턴 체크 단위 3 + 통합 1 · **보안·견고성 통합 58** |
| 발견·수정한 결함 | 5건(§5) — 모두 수정·재검증 |
| 미실행·한계 | §7 |

## 2. 테스트 환경
- DB: 실제 PostgreSQL(Docker `stock-screener-pg`)에 **임시 DB**를 만들어 실제 마이그레이션(0001~0013)·실제 역할(`migrator`/`batch_worker`/`api_service`)로 검증하고 종료 시 삭제(규칙 K). 개발 DB(`stock_screener`)에는 합성 데이터를 넣지 않았다.
- 개발 DB 변경(사용자 승인 범위): 0012·0013 적용, 2026-09-21 파생 재실행(일봉 339,313행 복사), DART 실적 수집(2,613종목·7,751행).
- 앱: 실제 FastAPI 앱(읽기 전용 `api_service` 세션), 실제 Next.js 개발 서버(4000)·백엔드(4001), 실제 Chrome(자동화).
- 기존 계약 보호: `/screen`·`/screen/pattern` 응답은 golden 비교 테스트가 계속 통과(기존 `screen.py` 등 3개 파일은 git diff 0줄).

## 3. 테스트 케이스 결과

### 3-1. DB·배치 (UNIT-19, 0012) — `tests/integration/test_daily_prices_db.py`
| TC | 내용 | 결과 | 근거 |
|---|---|---|---|
| U19-01 | 컬럼 구성·PK(종목, 일자) | PASS | information_schema·pg_index 조회 |
| U19-02 | `api_service`는 SELECT만 가능, INSERT/UPDATE/DELETE는 `permission denied`, **`raw_internal.raw_ohlcv` 접근 차단 유지** | PASS | 실제 역할로 실행 |
| U19-03 | 배치가 KRX 일봉을 **값 단위로 정확히** 복사(행 수·6개 값 불일치 0) | PASS | raw↔public JOIN 불일치 0 |
| U19-04 | 재실행 멱등(중복 없음) + 원본 정정 시 덮어씀 | PASS | 행 수 동일, 종가 갱신 |
| U19-05 | NXT 세션 행·보존기간(400일) 밖 행은 복사 안 됨 | PASS | 삽입 후 배치 재실행 |
| U19-06 | 마이그레이션 downgrade/upgrade 가역, 다른 테이블 불변 | PASS | alembic 실행 |

### 3-2. 일봉·목록 시세 API (UNIT-20) — `tests/unit/test_prices_api.py`(28) + 통합
| TC | 내용 | 결과 |
|---|---|---|
| U20-01 | 오름차순, 전일대비·등락률 계산, 첫 행 null, 전일 종가 0이면 등락률 null(0으로 나누지 않음) | PASS |
| U20-02 | `days` 경계(20/120/260 허용, 19/261/0/-1/abc/빈값 거부, 저장소 미접촉) | PASS |
| U20-03 | 없는 종목 404 `STOCK_NOT_FOUND`, 일봉 없음 200+빈 배열(신선도 null) | PASS |
| U20-04 | 신선도: 마지막 일봉이 기대일보다 오래되면 `is_latest_trading_day=false`+안내문, 캘린더 미확정 424, 이상 503 | PASS |
| U20-05 | 응답이 엄격 JSON 숫자(NaN/Infinity 없음), 내부 필드명 없음, 읽기 전용(GET만) | PASS |
| U20-06 | 실제 DB: 응답 값이 `raw_ohlcv`와 **일치**(60행 전 필드), 없는 종목 404 | PASS |
| U22-Q1~Q5 | `/stocks/quotes`: 요청 순서 유지·없는 종목 생략·중복 제거·50개 상한·6자리 영숫자만 허용(7종 비정상 입력 거부)·전일 없음/0 처리 | PASS |
| U22-Q6 | 실제 DB: 최신 종가·전일대비가 직전 2개 종가와 일치 | PASS |
| P-CHK | 종목 상세 조건 체크 `/stocks/{code}/pattern-check`: `required=()`로 6조건 모두 반환, 평가 대상 아님(스팩 등)은 `item=null`, 기능 스위치 off 404, 서열 필드 없음, 실제 DB 4종목 유형 검증 | PASS |

### 3-3. 실적 (UNIT-23) — `test_dart_client.py`(+5), `test_enrich_earnings.py`(5), `test_corp_earnings_db.py`(4)
| TC | 내용 | 결과 |
|---|---|---|
| U23-01 | 파서: 당기·전기·전전기 3개 연도 매핑, 지배주주 귀속 순이익 우선, **적자는 음수**, BS의 동명 계정 무시 | PASS |
| U23-02 | IS 없이 CIS만 제출하는 회사, 영업이익 대체 계정 | PASS |
| U23-03 | 표준 매출 계정이 없으면 **null(0 아님)**, 세 값이 모두 없는 해는 만들지 않음 | PASS |
| U23-04 | 사업보고서(11011) 호출·DART 013(자료 없음) → None | PASS |
| U23-05 | 대상 사업연도 경계(4/4→재작년, 4/5→전년) | PASS(5케이스) |
| U23-06 | DB upsert 멱등·정정 덮어쓰기, API 연도 오름차순·null 보존·404, `api_service` SELECT 전용, CHECK 제약, 가역 마이그레이션 | PASS |
| U23-07 | **실데이터**: 삼성전자 2025 매출 333,605,938,000,000원 = 화면 3,336,059억 원, 영업이익·순이익도 DART 값과 일치 | PASS |
| U23-08 | **실수집**: 2,760종목 중 2,613종목 7,751행(매출 7,503·영업이익 7,745·순이익 7,746), 고유번호 없음 114·보고서 없음 33·**오류 0** | PASS |

### 3-4. 보안·견고성 (UNIT-24) — `test_stock_detail_security_db.py`(58)
| TC | 내용 | 결과 |
|---|---|---|
| S-01 | 경로의 종목코드 8종(`'; DROP TABLE …`, `' OR '1'='1`, 퍼센트 인코딩, `../`, NUL, 한글, 5,000자, UNION) × 3 엔드포인트: 500 없음, 내부 정보(Traceback·psycopg·sqlalchemy·계정명) 노출 없음, **테이블 행 수 불변**, **입력을 응답에 되돌려 주지 않음** | PASS(24) |
| S-02 | `days` 비정상 6종(`120; DROP…`, 1e9, -1, 0x10, 초과 정수, 따옴표) → 400/422, 행 수 불변 | PASS(6) |
| S-03 | `codes` 비정상 7종(인젝션·개행·빈 토큰·와일드카드·51개) → 400, 행 수 불변, 파라미터 누락 400 | PASS(8) |
| S-04 | 쓰기 메서드(POST/PUT/PATCH/DELETE) × 4 엔드포인트 → 404/405 | PASS(16) |
| S-05 | 응답 키에 `*_raw`·`market_cap`·`per`·`pbr`·배치 ID 등 내부 필드 없음 | PASS |
| S-06 | rate limit: 61번째 요청이 429(신규 엔드포인트도 적용) | PASS |
| S-07 | CORS: 허용 목록 밖 출처에 `Access-Control-Allow-Origin` 미부여(단순·프리플라이트) | PASS |
| S-08 | 오류 응답이 공통 envelope(스택 트레이스 없음) | PASS |
| S-09 | **변형(mutation) 검증**: 에러 메시지가 입력을 반사하도록 코드를 일부러 바꾸면 S-01이 **6건 실패** → 테스트가 실제로 결함을 잡음(원복 후 전체 통과) | PASS |

### 3-5. 차트·프론트 (UNIT-21/22)
| TC | 내용 | 결과 | 근거 |
|---|---|---|---|
| F-01 | SMA/EMA 손계산·워밍업 null·기간 오류, MACD(상수열=0, 상승 추세>0, 독립 EMA12−EMA26 대조), 주/월봉 집계(월요일 기준·연말 경계·원본 불변), 범위 계산 | PASS | Node 10 pass |
| F-02 | 억 원 표기: null/NaN은 "-", 반올림(절반은 0에서 먼 쪽), 적자 부호, "-0" 방지 | PASS | Node 4 pass |
| F-03 | 타입·린트·금지표현(추천/매수신호 등) | PASS | tsc·eslint·lint-forbidden-copy |
| F-04 | 실브라우저(실데이터): 헤더 가격·전일대비, 캔들·MA5/10/20/60·거래량·MACD, 일/주/월 전환 | PASS | 삼성전자·LG유플러스 |
| F-05 | 키보드: 차트 ←→ 날짜 이동·Esc 해제, 탭 방향키 전환 | PASS | 값 변화 확인 |
| F-06 | **모바일 실제 뷰포트**(iframe, 미디어쿼리 적용 확인 innerWidth 375/360/320): 종목 상세 5개 탭 모두 가로 넘침 0, 탭·봉 단위 버튼 높이 44px, 차트 폭 자동 축소(326/271px) | PASS | DOM 측정 |
| F-07 | 패턴 결과 카드(360px)·종목 검색(360px, 26건 전부 시세 표시): 가로 넘침 0 | PASS | DOM 측정 |
| F-08 | 접근성: 탭 `tablist/tab/tabpanel`·`aria-selected`·roving tabindex, 표 `caption`·`scope`, 등락은 색+▲▼+스크린리더 텍스트, 차트 대체(표) 제공, 표 영역 포커스 가능 | PASS | 코드·DOM 확인 |
| F-09 | **서버 호출 수**: 상세 화면 서버 렌더 호출 2건(메트릭·일봉)만, 실적·조건 체크는 탭을 처음 열 때 브라우저가 1회 호출(재열기 추가 호출 0) | PASS | 네트워크 항목 확인 |

### 3-6. 성능 (개발 DB, 읽기 전용 계정, 각 30회)
| 쿼리 | p50 | p95 | 실행계획 |
|---|---|---|---|
| 목록 시세(50종목) | 9.7ms | 10.3ms | `daily_prices_pkey` 인덱스 스캔 |
| 일봉 260일 | 2.5ms | 3.4ms | 인덱스 스캔, 0.26ms 실행 |
| 실적 | 1.1ms | 1.4ms | PK |

## 4. 비기능·정책 점검
- **원값 노출**: 사용자 승인(DEC-041)에 따라 신규 엔드포인트에서만 일봉 원값을 공개. `raw_internal` 차단은 유지, 기존 `/screen`·`/screen/pattern`·`/stocks/{code}/metrics` 계약 불변(golden·화이트리스트 테스트 통과).
- **표현 금지**: 점수·순위·"추천/유력/TOP" 없음(금지표현 검사 통과), 비예측 고지 유지(조건 체크 탭 문구 포함), 수급은 "준비 중" 안내, 호가·뉴스 미제공.
- **새 의존성 없음**: `requirements*.txt`·`frontend/package*.json` 변경 0.

## 5. 발견한 결함과 조치
| # | 심각도 | 내용 | 조치·재검증 |
|---|---|---|---|
| D1 | High | `DailyPrice` 모델에 `schema` 지정 누락 → 실제 DB 조회 시 `relation "daily_prices" does not exist`(503). 통합 테스트로 발견 | `__table_args__`에 `public_serving` 지정 → 통합 테스트 통과 |
| D2 | **High(설계)** | 상세 화면이 서버에서 API를 4회 호출하면, **IP 기준 분당 60회 제한이 방문자 전체에 합산**되어(서버 한 IP) 사실상 분당 15화면만 가능 | 실적·조건 체크를 **탭 첫 열기 시 브라우저가 호출**하도록 변경(서버 호출 4→2건, 방문자별 집계). 아래 R1 참고 |
| D3 | Medium | 신규 404 메시지가 입력값을 그대로 반사(초장문·인젝션 문자열 에코) | `require_stock_code`(6자리 영숫자 검증)·고정 메시지로 변경, 변형 검증으로 테스트 유효성 확인 |
| D4 | Low | 실적 upsert 반환 건수가 psycopg `rowcount=-1` 때문에 음수 | 처리 건수를 직접 집계 |
| D5 | Low(테스트) | 보안 테스트의 NUL 문자가 HTTP 클라이언트에서 거부되어 테스트 자체가 실패 | `%00` 인코딩으로 수정 |

## 6. 변경 파일 요약
- DB: `0012_create_public_serving_daily_prices.py`, `0013_create_public_serving_corp_earnings.py`, `shared/db_models/public_serving.py`(DailyPrice·CorpEarnings)
- 배치: `services/derivation_batch/repository.py`·`run_derivation.py`(`sync_daily_prices`), `services/ingestion_batch/dart_client.py`·`repository.py`(연간 실적), `scripts/enrich_earnings.py`
- API: `api/prices.py`·`earnings.py`·`common.py`·`pattern.py`(pattern-check), `db/price_repository.py`·`earnings_repository.py`, `schemas/prices.py`·`earnings.py`·`pattern.py`
- 프론트: `StockChart`·`StockDetailTabs`·`QuoteText`, `lib/chartIndicators.ts`·`formatEok.ts`·`useQuotes.ts`·`useLazyApi.ts`·`stockDetailApi.ts`, `app/stocks/[code]/page.tsx`, 목록 컴포넌트 4종, `copy.ko.json`, `globals.css`

## 7. 미실행·한계·잔존 위험
| # | 항목 | 설명 | 조치 주체 |
|---|---|---|---|
| R1 | **rate limit의 프록시 구조** — **해소(DEC-045, 2026-10-02)** | 서버 렌더 호출(메트릭·일봉)이 프론트 서버 한 IP로 합산되던 한계를 내부 토큰 + 신뢰 프록시 단수 방식으로 해결(방문자별 집계, 스푸핑 불가). 단위 테스트 `test_rate_limit_internal_token.py`(토큰 유효·무효·미설정, 잘못된 IP, 공용 버킷, IPv6)와 `check-client-ip.mjs`(오른쪽 N번째 선택·형식 검증) 통과. **배포 시 운영자 설정 필요**: `PUBLIC_API_INTERNAL_TOKEN`(API·프론트 동일 값), `FRONTEND_TRUSTED_PROXY_HOPS`(프론트 앞 신뢰 프록시 단수), 필요 시 `PUBLIC_API_TRUSTED_PROXY_IPS` | 배포 시 설정(Runbook) |
| R2 | 기존 400 응답의 입력 반사 — **해소(DEC-046, 2026-10-02)** | 전역 핸들러·라우트 메시지·`metrics` 404에서 사용자 입력값 반사 제거(파라미터 이름만 안전 문자 검증 후 표기). 반사 부재 회귀 테스트 추가, 동결 해시 1회 갱신 | 완료 |
| R3 | 시세·재무 공시 재배포 약관, Q4 명칭 법률 검토 | 사용자 몫(REQ-022 게이트), 배포 승인 전 필수 | 사용자 |
| R4 | 실기기(실제 모바일 브라우저) | 뷰포트 375/360/320 DOM 측정까지만 수행. 터치 제스처(차트 터치 이동)·실제 단말 렌더링은 미확인 | 사용자 또는 후속 |
| R5 | 일봉 최신성 | 개발 DB 기준일이 2026-09-21이라 "7영업일 지연" 안내가 정상 표시됨. 일 배치 스케줄링은 사용자 보류 사항이라 자동 갱신 없음 | 사용자(보류) |
| R6 | 실적 재수집 | 연 1회(매년 4월 5일경 이후) `scripts/enrich_earnings.py` 수동 실행 필요, 금융회사 등은 매출 항목이 없어 "-"로 표시 | 운영 절차(Runbook) |
| R7 | 수급·호가·뉴스 | 사용자 결정으로 미구현(수급 "준비 중", 호가·뉴스 제외) | 사용자 |
| R8 | 시각적 비교 | 자동화 브라우저로 화면 캡처는 일부만 육안 확인(차트·헤더). 모든 화면의 픽셀 단위 시각 검수는 하지 않음 | 사용자 확인 |

## 8. 재현 방법
```
py -3.12 -m pytest tests/unit tests/integration -q                    # 770 passed
cd frontend && node --experimental-strip-types --test scripts/check-chart-indicators.mjs scripts/check-format-eok.mjs   # 14 pass
cd frontend && npx tsc --noEmit && npx eslint src && node scripts/lint-forbidden-copy.mjs
```
