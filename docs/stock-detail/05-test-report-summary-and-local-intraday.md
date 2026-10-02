# 내부 테스트 결과서 — 사실 서술형 차트 요약 · 개인 로컬 모드(분·틱·호가·체결) (DEC-052)

- 작성일: 2026-10-02 (KST) / 대상 브랜치: `PROD_SCH`
- 범위: ① 사실 서술형 차트 요약 ② 개인 로컬 모드 장중 시세(한국투자증권 실전 앱키, **읽기 전용**): 분봉(1·3·5·10·15·30·60분)·틱 봉·호가(10단계)·체결 목록
- 판정: **조건부 통과** — 자동 테스트·모의 서버 종단 테스트·보안 점검 모두 통과. **실제 증권사 서버로는 검증하지 못했다**(개발 환경에서 `openapi.koreainvestment.com` 접속 불가·앱키 없음). 사용자 PC에서 `scripts/kis_smoke_test.py` 1회 실행이 남은 필수 확인이다(§7).

## 1. 요구사항과 구현 대응
| ID | 요구(사용자 지시) | 구현 | 결과 |
|---|---|---|---|
| R-1 | AI 분석은 **사실 서술형 차트 요약**으로 | `frontend/src/lib/chartSummary.ts`(순수 함수), 문장 템플릿은 `copy.ko.json`(`stockDetail.summary`), 도구 줄의 "차트 요약" 버튼·패널 | ✅ |
| R-2 | **B. 개인 로컬 모드**로 진행 | API `services/public_api/intraday/*`·`api/local_intraday.py`, 프론트 호가·체결 탭·분/틱 차트 | ✅(모의 검증) |
| R-3 | 증권사: 한국투자증권 KIS, 환경: 실전 앱키 | `kis_client.py`(실전 도메인 고정) | ✅ |
| R-4 | 내부테스트 결과서 완벽 작성 | 본 문서 | ✅ |

## 2. 설계 요약
- **차트 요약**: 화면 시계열(일/주/월/분/틱 봉)에서 이동평균 위치·배열 순서·5-20 차이·60 기울기, MACD 위치·최근 교차, 최근 61봉 고저 대비 위치, 거래량 배수, 매물대 위치를 계산해 템플릿 문장으로 채운다. **전망·평가·행동 제안 없음**(강세·약세·지지·저항·전망·매수·매도 등 해석 어휘 금지), 데이터가 모자라면 그 문장을 만들지 않는다(0으로 채우지 않음).
- **개인 로컬 모드 접근 통제(모두 만족해야 응답, 아니면 존재를 숨기는 404)**: ①`LOCAL_INTRADAY_ENABLED=true` ②접속 주소가 허용 목록(기본 loopback) ③프록시·터널 헤더 없음 ④`Host` 헤더가 localhost/사설 IP. 프론트는 빌드 스위치 + 시세 공개 스위치 + 브라우저 주소가 사설일 때만 UI 노출(보조 방어선).
- **증권사 호출**: 토큰 파일 캐시(권한 0600, 앱키 지문 불일치 시 무시), 요청 간격 0.12초, 한도 초과/만료 토큰은 1회 재시도, 엔드포인트는 시세 조회 5종 상수(주문·계좌 API 없음), 기본 URL은 실전 도메인만 허용.
- **응답 가공**: 분봉 페이징(최대 14쪽)·N분봉 집계, 체결 페이징·중복 제거, 호가 10단계 정규화. 종목·종류별 짧은 TTL 캐시.

## 3. 테스트 환경
| 항목 | 값 |
|---|---|
| 백엔드 | Python 3.12, FastAPI TestClient / 실제 uvicorn(`scripts/run_public_api.py`) |
| DB | 임시 PostgreSQL 16(실제 마이그레이션 0001~0013, 시드 픽스처) |
| 증권사 | **모의 KIS 서버**(`scripts/mock_kis_server.py`, `httpx.MockTransport`) — 실제 증권사 서버 아님 |
| 프론트 | Next.js 빌드 후 `next start`, Playwright(Chromium), 360~390px 폭 |

## 4. 자동 테스트 결과
| 영역 | 파일 | 건수 | 결과 |
|---|---|---|---|
| 정규화·집계·페이징·캐시 | `tests/unit/test_local_intraday_normalize.py` | 16 | 통과 |
| 클라이언트·설정·접근 통제·종단(모의) | `tests/unit/test_local_intraday_client_and_api.py` | 39 | 통과 |
| 시세 API(기존+quotes 확장) | `tests/unit/test_prices_api.py` | 30 | 통과 |
| 차트 요약 | `frontend/scripts/check-chart-summary.mjs` | 9 | 통과 |
| 로컬 모드 프론트 순수 로직 | `frontend/scripts/check-local-intraday.mjs` | 2 | 통과 |
| 기존 프론트 지표·IP·억원 | `check-chart-indicators`(14)·`check-client-ip`(6)·`check-format-eok`(4) | 24 | 통과 |
| 전체 백엔드 | `pytest tests` | 653 통과 / 1 실패 / 194 건너뜀 | 실패 1건은 DB 접속 설정(`ALEMBIC_DATABASE_URL`) 부재로 인한 기존 환경 문제(이번 변경과 무관) |
| 정적 검사 | `ruff`, `tsc --noEmit`, `eslint`, 금지표현 검사(82파일) | — | 모두 통과 |

### 4-1. 테스트 케이스 요약(핵심)
**차트 요약(9)**: 상승·하락 일변 추세에서 이동평균 위/아래·정배열/역배열·직전 봉 대비 값이 손계산과 일치 / MACD 골든크로스 몇 개 봉 전 / 거래량 3.00배 / 매물대 위치 / 최근 61개 봉 고저 / **봉이 8개일 때 20·60 이동평균·MACD·거래량 문장 미생성** / 분·틱 봉은 시각 표기와 "봉" 단위 / **모든 문장·템플릿에 금지표현(CI 목록을 코드에서 읽어 사용)과 해석 어휘 없음, `{}`·NaN 없음**.
**정규화(16)**: 시각 변환·분 단위 감소 / 부호 코드(1상한 2상승 3보합 4하한 5하락) / 다른 날짜·결측·비정상 행 제거(0 채움 없음) / 09:00 기준 N분 집계 OHLCV 규칙 / 체결 부호·결측 / 호가 단계·총잔량·예상체결 / **30건 단위 페이징으로 장 시작까지 수집·TTL 캐시로 증권사 재호출 없음** / 당일 비면 직전 거래일(과거 엔드포인트)·날짜 지정 / 잘못된 간격·**끝없는 응답도 페이지 상한(14)에서 중단** / 같은 초 체결 중복 제거 / 과거 체결 조회 실패 시 부분 결과.
**클라이언트·접근 통제(39)**: 기본 꺼짐·`true`만 켜짐 / **실전 도메인만 허용(http·타 도메인 거부), 모의 서버는 명시 스위치로만** / 허용 IP 매트릭스(IPv4·IPv6·CIDR·잘못된 값·`127.0.0.1.evil`) / 토큰 1회 발급·파일 캐시(권한 0600·시크릿 미저장)·재시작 시 재사용·**앱키 변경 시 캐시 무시** / 만료 토큰 응답 시 1회 재발급 후 재시도 / 한도 초과 1초 대기 후 재시도·재초과 시 오류 / 요청 간격 / **예외·응답 어디에도 앱키·시크릿·토큰·원문 미노출** / 인증 실패·네트워크 장애 코드 / 앱키 없음 / 비활성·허용 IP 밖·`X-Forwarded-For` 위조·**프록시·터널 헤더 7종**·**공개 Host 헤더**에서 모두 동일한 404(존재 비노출) / 앱키 없음 503·설정 오류 503(값 비노출) / 악성 종목코드·잘못된 간격·과대 limit은 **증권사 호출 전에** 거부 / 모의 증권사 종단(502 매핑·비밀 비노출) / 로컬 경로 전용 요청 한도 버킷.

## 5. 종단(E2E) 시험 — 실제 API(uvicorn) + 실제 DB + 모의 KIS + 빌드된 프론트(Playwright)
| # | 시나리오 | 결과 |
|---|---|---|
| E-1 | 탭 구성(로컬 모드 켬) | `호가 · 차트 · 체결 · 일자별 시세 · 실적 · 투자자 · 조건 체크` ✅ |
| E-2 | 호가 탭 | 20행(매도 10 + 매수 10), 잔량 막대·총잔량 ✅ |
| E-3 | 체결 탭 | 120건 ✅ |
| E-4 | 분▾ → 5분 | 5분봉 차트, X축 시각(`09:20, 11:00`) ✅ |
| E-5 | 틱▾ → 10틱 | 틱 묶음 봉, 읽기 줄에 시각(`10:58:53`) ✅ |
| E-6 | 차트 요약 | 항목 9개, 기준 문구 `10틱봉 기준 · 최근 봉 10:58:53` ✅ |
| E-7 | 가로 넘침 | 없음(390px) ✅ |
| E-8 | 로컬 모드 끔(기본 빌드) | 탭 `차트 · 일자별 시세 · 실적 · 투자자 · 조건 체크`, 분·틱 비활성, **`/local/` 요청 0건** ✅ |
| E-9 | 실서버 보안: loopback 200 / `X-Forwarded-For` 404 / 공개 `Host` 404 / `CF-Connecting-IP` 404 | ✅ |
| E-10 | API 로그에 토큰·시크릿 문자열 | 0건 ✅ |
| E-11 | 스모크(`kis_smoke_test.py`) ↔ 모의 서버 | 호가·체결·1분봉·5분봉 `[OK]`, 종료코드 0 ✅ |

## 6. 발견한 결함과 조치
| # | 심각도 | 내용 | 발견 방법 | 조치·재검증 |
|---|---|---|---|---|
| D1 | **High(보안)** | 로컬 모드를 켠 채 터널·리버스 프록시로 노출하면 모든 요청이 127.0.0.1로 보여 **접근 통제가 우회**될 수 있음 | 설계 검토(위협 모델링) | 프록시 헤더 10종·공개 Host 거부 추가, 단위 테스트 + 실서버 확인(E-9) |
| D2 | High | 분봉 → 틱 전환 직후 한 번 렌더되는 동안 이전 경로 데이터가 남아 `Cannot read properties of undefined` 오류로 차트 소멸 | **E2E(Playwright)** | `useIntradayPoll`이 상태에 경로를 기록해 다른 경로 데이터는 내보내지 않음. E2E 재통과 |
| D3 | Medium | 분·틱을 고른 직후 로딩 중에 **일봉 차트가 그대로 보여** 선택과 불일치 | E2E | 분·틱 선택 시 일봉으로 대체하지 않고 빈 차트 + 상태 문구 |
| D4 | Medium | 분봉 수집(최대 14회 호출)이 기본 요청 타임아웃 4.5초에 걸릴 수 있음 | 코드 검토 | 로컬 경로만 30초, 다른 경로는 4.5초 유지 |
| D5 | Medium | 로컬 경로가 일반 한도(분당 60회)에 걸려 호가 2초 갱신이 막힘 | 코드 검토 | 로컬 경로 전용 버킷(분당 600) — 다른 경로 한도 불변(테스트) |
| D6 | Low | 오류 응답에 `Cache-Control: no-store`가 빠짐(정상 응답만 설정됨) | 테스트 | 보안 헤더 미들웨어에서 경로 단위로 항상 설정 |
| D7 | Low | 단위 테스트의 기본 Host가 `testserver`라 새 Host 검사에 걸림 / 문서용 IP(203.0.113.x)가 사설로 분류됨 | 테스트 | 테스트 클라이언트 base_url 지정, 공인 IP(8.8.8.8)로 교체 |

## 7. 보안 점검(위협 모델)
| 위협 | 대응 | 근거 |
|---|---|---|
| 앱키·시크릿·토큰 노출(응답·로그·예외·브라우저) | 서버 환경변수에만 보관, 예외는 안전 문구만, 토큰 파일에 시크릿 미저장·0600, 프론트 코드에 키 없음 | 테스트 `errors_never_leak…`, E-10, 토큰 캐시 테스트 |
| 앱키 오설정으로 엉뚱한 서버에 전송(SSRF·자격 유출) | 기본 URL은 `https://openapi.koreainvestment.com`만 허용, 모의는 명시 스위치 | 설정 테스트 |
| 비인가 접근(외부 사용자·터널) | 4중 접근 통제 + 존재 비노출 404, 프론트 사설 주소 제한 | §4-1, E-9 |
| 입력 인젝션·반사 | 종목코드 6자리 영숫자 검증(호출 전 거부), 입력 반사 없음, 간격·limit 화이트리스트 | 테스트 `hostile_codes…` |
| 서비스 거부·증권사 한도 소진 | 요청 간격, TTL 캐시, 페이지 상한, 한도 초과 시 백오프(프론트 3배) | 테스트·코드 |
| 시세 재배포 | 기본 꺼짐·개인 PC 한정·화면 안내 문구, 공개 배포 시 끄도록 체크리스트·가이드에 명시 | 가이드 §8 |
| 응답 캐시 | `no-store`(오류 포함) | D6 |
| 잔여 위험 | 같은 PC에서 다른 프로그램이 `127.0.0.1`로 호출하면 응답함(허용 목록이 PC 단위) — 개인 PC 전제. 허용 IP를 넓히면 그 대역 전체가 접근 가능 | 가이드 §8 |

## 8. 한계·미검증(정직한 기록)
1. **실제 증권사 응답으로 검증하지 못함.** 응답 필드명은 공식 샘플 저장소의 점검 코드를 근거로 했으나, 호가의 예상체결(`antc_*`)·시간대별 체결 일부 필드는 샘플이 컬럼을 명시하지 않아 일부 추정이다. 필드가 어긋나면 해당 값이 비거나(0으로 채우지 않음) 행이 버려진다. → **사용자 PC에서 `py -3.12 scripts\kis_smoke_test.py`(장중) 실행 후 결과 확인 필요.**
2. 증권사 약관 원문(재배포·호출 한도 수치)은 이 환경에서 접속이 차단돼 직접 읽지 못했다(검색 요약만). 초당 한도는 보수적으로 8건/초 이하로 제한했다.
3. 틱 차트는 "최근 체결 최대 300건"을 묶은 근사다(하루 전체 틱 이력 아님). 체결 페이징은 같은 초 체결의 순서를 응답 순서로 가정한다.
4. 웹소켓 실시간(푸시)은 사용하지 않고 REST 폴링(호가 2초·체결 3초·분봉 10초)이다.
5. 실기기(휴대폰) 터치 조작·픽셀 단위 시각 비교는 하지 않았다(360~390px 폭 브라우저 렌더링까지).
6. 차트 요약은 일·주·월·분·틱 봉을 모두 지원하지만, 문장은 사실 서술이며 증권사 앱의 "AI 분석"과 내용이 다르다(의도된 차이).

## 9. 재현 방법
```
py -3.12 -m pytest tests/unit/test_local_intraday_normalize.py tests/unit/test_local_intraday_client_and_api.py tests/unit/test_prices_api.py -q
cd frontend && node --experimental-strip-types --test scripts/*.mjs && npx tsc --noEmit && npx eslint src
# 종단: 모의 KIS 서버 + API + 프론트
py -3.12 scripts/mock_kis_server.py --port 9100
#  API 환경변수: LOCAL_INTRADAY_ENABLED=true KIS_APP_KEY=mock KIS_APP_SECRET=mock KIS_BASE_URL=http://127.0.0.1:9100 KIS_ALLOW_CUSTOM_BASE_URL=true
#  프론트 빌드:  NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true
py -3.12 scripts/kis_smoke_test.py          # 실제 앱키 확인(사용자 PC)
```

## 10. 변경 파일
- 백엔드: `services/public_api/intraday/{config,kis_client,normalize,service}.py`, `api/local_intraday.py`, `schemas/intraday.py`, `main.py`(라우터), `middleware.py`(no-store·타임아웃), `rate_limit.py`(로컬 버킷)
- 프론트: `lib/{chartSummary,localIntraday,privateHost,useIntradayPoll}.ts`, `components/{OrderBookPanel,TickPanel,LocalModeNotice}.tsx`, `StockChart.tsx`·`StockDetailTabs.tsx`, `copy.ko.json`, `globals.css`, `chartIndicators.ts`(Candle.time), `types.ts`, `tsconfig.json`(`allowImportingTsExtensions`)
- 도구·문서: `scripts/{mock_kis_server,kis_smoke_test}.py`, `.env.example`(2종), `.gitignore`(`.local/`), `docs/ops/local-intraday-guide.md`, `docs/stock-detail/04-intraday-options.md`
