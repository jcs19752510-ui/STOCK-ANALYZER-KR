# 최신 데이터 강화(DEC-097) 내부테스트 결과서 (2026-10-07)

대상: ① 장중 기준 기본 켜짐 ② 시세 호출 간격(실전 계좌 기준) ③ KIS 일봉 DB 캐시(수집 스크립트·배치 연결·API 우선 사용).
전제(사용자 확인): 서비스는 본인 PC 전용, KIS 계정은 실전투자용.

## 구현 요약
| 항목 | 내용 |
|---|---|
| ① | 저장된 설정이 없으면 장중 기준 켜짐(사용자가 끄면 `"0"` 유지). 접근 권한(로컬+관리자)이 없으면 켜지지 않음 |
| ② | `KIS_MARKET_MIN_INTERVAL` 기본 0.125초(초당 8건 = 실전 기본 한도 20건/초의 40%, 하한 0.06). 전 종목 한 바퀴 이론 ≈12초(기존 ≈19초) |
| ③-a | 테이블 `public_serving.kis_daily_bar`(마이그레이션 0019). batch_worker 쓰기, api_service SELECT만 |
| ③-b | `scripts/collect_kis_daily_bars.py`: 발행일 P < 직전 거래일 E일 때 P~E 일봉 upsert(증분), `trade_date <= P` 행 삭제(확정 데이터가 대신), 실패 재시도·연속 20건 실패 시 중단, `--dry-run/--limit`. `run_daily_batch.py`가 KIS 키+`LOCAL_INTRADAY_ENABLED=true`일 때만 부가 단계로 호출(실패해도 배치 종료코드 불변) |
| ③-c | API `BaseFiller(cache_loader)`: 캐시를 교차검증(P 종가 일치·필요 날짜 존재) 후 KIS 호출 없이 사용, 불일치·누락·로더 예외는 KIS 조회로 폴백. `meta.live.base_fill.from_cache` 추가 |

## 시험 결과
| 구분 | 결과 |
|---|---|
| 전체 회귀 `pytest tests` | 1381 통과 / 1 실패(아래 별도 설명) — 실패 이후는 `-x`로 중단했으므로 아래 개별 재실행으로 보완 |
| 프론트 `check-live-screen` | 39 통과 / 0 실패, `tsc --noEmit` 통과 |
| ruff | 변경 파일 통과(저장소의 기존 오류는 `docs/pattern-screening/prototype/*` 만) |
| 호출 간격 단위 시험 | 기본값·환경 덮어쓰기·하한·잘못된 값 3건 통과 |
| 캐시 연동(단위 4 + 통합 1) | 캐시 전부 사용(KIS 호출 0), 부분 캐시, 앵커 불일치/날짜 누락/빈 목록 폴백, 로더 예외 폴백, DB 캐시로 보충 완료(`filled=10, from_cache=10`) 통과 |
| 수집 스크립트(단위·통합) | upsert, 증분 건너뛰기, E 증가 시 재조회, 정리 삭제, 종목 실패 계수·재시도, 종료코드 0/1/2, dry-run·limit, P>=E 정리만, 권한(api_service SELECT만, 쓰기 거부), 배치 부가 단계 3건 통과 |
| 사고 재현 `incident_repro.py` (PowerShell 7 + 실제 배치) | 8/8 통과(발행일 2026-10-06, 진단 `[정상]`) — 이번 변경 후에도 회귀 없음 |

### 알려진 실패 1건 (이번 변경과 무관)
- `tests/unit/test_realtime_stream_api.py::test_스트림은_스냅샷을_보내고_실시간_체결_호가를_밀어준다`는 변경 전 커밋(DEC-096)에서도 같은 방식으로 실패한다. 시험이 현재 시각(한국 시간 새벽·장 시작 전)에 따라 분봉 이력이 비는 시각 의존 시험으로 보이며(스냅샷 `bars`가 빈 목록), 낮 시간에는 통과했던 것으로 기억한다(원인 확정은 못 함). 별도 작업으로 분리한다.

## 이 환경에서 검증하지 못한 것 (사용자 PC에서 확인 필요, 읽기 전용 도구 제공됨)
1. **실제 KIS 응답·한도**: `py -3.12 scripts\kis_smoke_test.py`, `scripts\kis_daily_price_smoke_test.py`. 한도 20건/초는 검색 자료 기준이며 공식 문서 직접 확인값이 아니다. 계정 한도가 다르면 `KIS_MARKET_MIN_INTERVAL` 조정.
2. 사용자 PC의 Windows PowerShell 5.1·실제 작업 스케줄러.
3. 마이그레이션 0019는 `start_local_api.ps1`이 시작할 때 `alembic upgrade head`로 자동 적용한다(배치만 먼저 돌면 캐시 단계는 경고 후 건너뜀, 데이터 처리에는 영향 없음).
4. 약관: 증권사 일봉의 DB 캐시 보관은 본인 PC·본인 사용 전제이며, 약관 문구는 확인하지 못했다.

## 보안 점검
- 앱키·시크릿·토큰은 출력·로그에 나오지 않음(수집 스크립트 출력 문구 점검). 주문·계좌 호출 없음(읽기 전용).
- API 계정은 새 테이블 SELECT만 가능(권한 시험 통과). 캐시는 확정 데이터(발행 포인터·daily_prices·raw_ohlcv)를 건드리지 않음.
