# 전 종목 시세 순환 속도 검토·수정(DEC-099) 내부테스트 결과서 (2026-10-16)

대상: "로컬 노트북에서 최대한 빨리 주식정보를 보는" 개발(DEC-097·098)이 실제로 빠른지 검토하고, 실측으로 확인된 결함을 고친다.
전제: 본인 PC 전용, KIS 실전 계좌. **실제 KIS 응답은 이 환경에서 잴 수 없다** — 모든 측정은 모의 증권사 서버(응답 지연 주입) 기준이다.

## 1. 검토 결과(요약)
| # | 발견 | 근거 | 심각도 |
|---|---|---|---|
| 1 | `KIS_MARKET_MIN_INTERVAL`을 0.12 미만으로 낮춰도 **효과가 없었다.** 운영 경로(`local_intraday.py`)가 `KisClient`를 기본 간격 0.12초로 만들어, 폴러 간격을 낮춰도 클라이언트 내부 `_throttle`이 다시 0.12초로 늦췄다. 가이드의 "0.1로 먼저 시도"는 무효였다. | 실측 §3 표 B·C(0.1·0.06 설정에서도 11.1초) | 높음(기능 무효) |
| 2 | 전 종목 순환이 **호출을 한 건씩 순서대로** 보내, 응답 지연이 간격보다 길면 한 바퀴 = 93 × 응답 지연이 된다. 문서의 12초는 지연 0일 때만 맞다. | 실측 §3 표(지연 0.15초 14.4초, 0.25초 23.7초) | 중간~높음(실제 KIS 지연에 좌우) |
| 3 | 공휴일에도 평일 08~20시면 수신기가 돈다(`default_market_open`은 달력을 모른다). | 코드 읽기(`market.py` 주석) — **이번에 수정·실측하지 않음** | 낮음 |

## 2. 변경 요약
| 파일 | 내용 |
|---|---|
| `services/public_api/realtime/market.py` | `PollerConfig.concurrency`(기본 1=기존 직렬). `run_cycle`이 호출 **시작 간격은 그대로** 지키면서 최대 `concurrency`건을 동시에 진행. 취소·정지 시 진행 중 작업 정리 |
| `services/public_api/api/local_market.py` | 환경변수 `KIS_MARKET_CONCURRENCY`(기본 4, 1~8) |
| `services/public_api/intraday/config.py`, `intraday/kis_client.py`, `scripts/start_local_api.ps1` | `client_min_interval()`: `KIS_MARKET_MIN_INTERVAL`이 0.12보다 작으면 `KisClient` 기본 간격도 같이 낮춤(명시 인자가 있으면 그 값 우선). `.env` 허용 키에 `KIS_MARKET_CONCURRENCY` 추가(하한 0.06). 더 크거나 잘못된 값이면 기존 0.12 유지 → **기본 설정에서 증권사 호출 속도는 이전과 같다** |
| `scripts/bench_market_poller.py` | 속도 측정 도구(실제 `KisClient`·폴러 + 지연 주입 모의 서버). 재현용 |
| `tests/unit/test_market_concurrency.py` | 신규 단위시험 16건 |
| `docs/ops/local-fast-realtime-guide.md`, `.env.example` | 실측 표·동시 호출 설정 반영 |

## 3. 속도 실측(모의 증권사, 전 종목 2766개 = 93호출, 2바퀴 중 빠른 값, 16코어 컨테이너)
한 바퀴(초). 이론값 = 93 × 간격(지터 포함 시 +약 5%).

**수정 전**(폴러 간격 / 클라이언트 간격 0.12 고정, 직렬)
| 응답 지연 | 0.125(기본) | 0.1 | 0.06 |
|---|---|---|---|
| 0초 | 12.2 | 11.1 | 11.1 |
| 0.08초 | 12.3 | 11.2 | 11.2 |
| 0.15초 | 14.4 | 14.4 | 14.4 |
| 0.25초 | 23.7 | 23.7 | 23.7 |

**수정 후**(동시 4, 클라이언트 간격이 설정을 따름)
| 응답 지연 | 0.125(기본) | 0.1 | 0.08 | 0.06 |
|---|---|---|---|---|
| 0초 | 12.2 | 9.7 | — | 5.9 |
| 0.08초 | 12.2 | 9.8 | — | 5.9 |
| 0.15초 | 12.3 | 9.9 | 7.9 | 6.0 |
| 0.25초 | 12.4 | 10.0 | 8.0 | 6.1 |

통제 실험: 수정 후 코드에서 동시 1(직렬)로 두면 지연 0.25초에서 23.7초 — 개선이 동시 호출에서 나온 것임을 확인.
- 실측 호출률은 설정 간격의 역수에 근접(0.1 → 9.4~9.6건/초, 0.06 → 15.2~15.7건/초). 즉 **초당 호출 수는 설정이 정한 값을 넘지 않는다**(한도 보호 유지).
- 모든 조합에서 2766종목 전부 수신(`quotes=2766`).
- 원자료: `/tmp/claude-0/bench/*.json`(컨테이너 임시, 재현은 `scripts/bench_market_poller.py`).

## 4. 시험 케이스
| 구분 | 기대 | 실제 | 결과 |
|---|---|---|---|
| 신규 단위 `test_market_concurrency.py` | 직렬 유지(동시 1), 동시 시 지연 은닉·시작 간격 준수, 일부 묶음 실패 격리, 정지 시 진행 중 호출 대기, 환경변수 경계, 클라이언트 간격 연동 9경우 | 전부 통과 | PASS |
| 폴러 관련 기존 단위(스냅샷·우선 순환·환경설정·로컬 시세 API) | 회귀 없음 | 118건 통과(신규 포함) | PASS |
| 전체 회귀 `pytest tests` | 회귀 없음 | 1506 통과 / 1 건너뜀 / 0 실패(322초). 1차 실행의 6건 실패는 §6 | PASS |
| 화면 종단 `live_screen_stack.py` (실제 API·모의 증권사·DB·브라우저) | 기존과 동일 | 31/31 통과 | PASS |
| PowerShell 7 `ps1_scripts_check.py` | 기존과 동일 | 23/23 통과 | PASS |
| 프런트 `tsc`·`eslint`·`lint:copy`·`check-*.mjs` 16개 | 통과 | 전부 종료코드 0 | PASS |
| `ruff check` | 통과 | 변경 파일 통과 | PASS |
| 신규 단위 총 16건 | `KisClient()` 기본 간격이 환경설정을 따르고 명시값이 우선 | 통과 | PASS |

## 5. 기준선(수정 전) 재현
이 컨테이너에서 수정 전 저장소(`a4b9f6e`)로 전체 회귀: **1491 통과 / 1 건너뜀 / 0 실패**(329초) — 이전 결과서와 동일.

## 6. 전체 회귀(수정 후)
- **1차 실행(수정 직후): 1499 통과 / 6 실패.** 실패: `test_live_screen_stack_db` 2건, `test_local_intraday_client_and_api` 3건, `test_realtime_stream_api` 1건.
- **원인(제 변경의 결함):** 처음에는 운영 코드가 `KisClient(settings, min_interval=...)`로 간격을 명시해 넘겼다. 시험은 `KisClient`를 `functools.partial(KisClient, min_interval=0.0)`·`lambda settings: ...`로 대체해 두었으므로, ① partial의 0.0이 호출 인자에 덮여 0.12가 되어 시험이 느려져 시간 초과, ② lambda는 예상하지 못한 인자라 TypeError. 수정 없는 기준선에서는 이 시험이 통과함을 따로 확인했다(8건 통과).
- **수정:** 운영 호출을 `KisClient(settings)`로 되돌리고, 간격 기본값을 `KisClient` 안에서 환경설정으로 정함(명시 인자 우선). 시험 코드는 바꾸지 않았다.
- **2차 실행(수정 후): 1506 통과 / 1 건너뜀 / 0 실패.** 실패했던 5개 파일은 단독 실행에서도 65건 통과.

## 7. 확인하지 못한 것과 위험
- **실제 KIS 응답 지연·한도는 측정하지 못했다**(앱키가 이 환경에 없다). 이득의 크기는 실제 지연에 달려 있다: 지연이 작으면 변화 없음, 클수록 크다. 위 표는 "코드가 만드는 상한"이다.
- 초당 20건 한도는 검색 자료 기준이며 공식 문서로 확인하지 못했다. 동시 호출은 **초당 호출 수를 늘리지 않지만** 응답 지연이 큰 환경에서는 이전보다 실제 호출률이 설정값(8건/초)에 더 가깝게 올라간다(이전에는 지연 때문에 4~6건/초였을 수 있음). `RATE_LIMITED`가 보이면 `KIS_MARKET_CONCURRENCY=1` 또는 `KIS_MARKET_MIN_INTERVAL`을 키운다.
- 우선 순환(보이는 200종목)은 이번에 바꾸지 않았다(직렬 유지).
- 공휴일 수신기 동작(발견 3)은 미수정.
- Windows PowerShell 5.1·실제 작업 스케줄러·증권사 약관은 여전히 미확인.

## 8. 재현 방법
```
source /tmp/claude-0/pgenv.sh
python scripts/bench_market_poller.py --latency 0.25 --interval 0.1 --concurrency 4   # 수정 후
python scripts/bench_market_poller.py --latency 0.25 --interval 0.1 --client-interval 0.12 --concurrency 1   # 수정 전과 같은 동작
python -m pytest tests/unit/test_market_concurrency.py -q
```
