# 장중 재계산 — 설계·계약서 (DEC-089)

- 작성일: 2026-10-06 / 상태: **확정(병렬 개발 4개가 이 문서만 보고 진행)** / 근거·견적: `08-intraday-rescreen-estimate.md`, 준실시간 시세: `07-market-snapshot-design.md`·`api/local_market.py`
- 한 줄 요약: **로컬 모드 관리자**가 조건 스크리닝·패턴 스크리닝을 "장중 기준"으로 켜면, 서버가 직전 거래일까지의 일봉 이력에 **오늘 진행 중인 봉(현재가·누적거래량)을 붙여 지표를 다시 계산**하고, 그 값으로 **기존과 같은 SQL 판정**을 돌려 결과를 준다. 최상위 목표: 실시간 데이터를 **정확하게** 보여 준다 — 근거가 맞지 않으면 계산하지 않고 이유를 알린다.

## 0. 결정 사항(사용자 지시 "특이사항 없으면 묻지 말고 진행"에 따라 `08` §6의 권장 기본값을 채택)
| # | 결정 | 채택 |
|---|---|---|
| 1 | 범위 | 조건 스크리닝(`/screener`) + 패턴 스크리닝(`/screener/pattern`). 종목 상세 정합은 2단계(이번 제외) |
| 2 | 부분 거래량 | 보정 없이 장중 **누적 거래량을 그대로** 쓰고, 응답·화면에 "거래량 계열은 장중 부분값" 경고(`volume_partial`)를 항상 표시. 시간대 보정은 실데이터를 본 뒤 2단계 |
| 3 | 백분위 | PER·PBR·시가총액 백분위는 **일봉 고정**(장중 원천 없음). 등락률 순위 백분위는 시세 커버율 ≥ 90%일 때만 장중 값으로 재계산(모집단 = 시세를 받은 종목), 미만이면 일봉 고정 |
| 4 | 목록 변동·**자동 갱신(2026-10-06 사용자 지시: "최대한 실시간이 제일 중요")** | **자동 갱신이 기본**: 켜면 화면이 `refresh_seconds`(기본 10초, 서버가 `meta.live.refresh_seconds`로 알림, 화면 설정 5~60초)마다 **새로 계산한 결과로 목록을 제자리에서 바꾼다**(깜빡임·스크롤 위치 유지, 새로 들어온 종목 "신규"·빠진 종목은 "최근 변화"에 표시). **"일시정지" 토글**을 켜면 그 순간의 스냅샷(`snapshot_id`)에 고정되어 페이지를 안정적으로 넘길 수 있고, 끄면 다시 자동 갱신. 서버는 **최소 계산 간격**(`LIVE_SCREEN_MIN_INTERVAL`, 기본 5초) 안의 요청에는 직전 스냅샷을 재사용(여러 탭·페이지 이동이 계산을 늘리지 않는다). 서버는 최근 스냅샷 5개 보관 |
| 4-1 | **시세 갱신 속도 우선순위** | 전 종목 순환(한 바퀴 수십 초 추정)에 더해 **결과에 보이는 종목(상위 최대 200개)은 우선 순환**(`MarketSnapshotPoller.set_priority`, 기본 3초 간격, 화면이 닫히면 30초 뒤 해제): 보이는 종목의 시세는 3초 안팎으로 갱신되고, 아직 결과에 없는 종목은 전체 순환 주기로 갱신된다 |
| 5 | 시세를 못 받은 종목 | 제외하지 않고 **일봉 값 유지**, 항목마다 `basis: "daily"`로 표시(받은 종목은 `"live"`) |
| 6 | 접근 | 로컬 모드 관리자 전용(DEC-085 연장). 운영 빌드·일반 회원에는 화면·요청 없음 |
| 7 | **기준 일봉이 낡았을 때** | 발행된 일봉의 거래일이 "직전 거래일"과 다르면(데이터 지연) **재계산을 거부**한다(`LIVE_BASE_STALE`). 사이에 낀 날이 비어 있으면 이동평균·거래량 이력이 틀리기 때문이다. 데이터 지연 해소(DEC-090)가 이 기능의 선행 조건이다 |

## 1. 방식(핵심 설계): "SQL 판정은 그대로, 입력 행만 가상으로"
- 판정 SQL은 한 곳(`db/screen_repository.py`, `db/pattern_repository.py`의 `build_condition_exprs`·`ma60_stage_expr`)에만 있다는 원칙을 **지킨다**. Python에서 재판정하지 않는다.
- 대신 `public_serving.derived_metrics_daily`(발행된 일봉 지표) 자리에 **같은 열을 가진 "가상 테이블"**을 넣는다: 서버가 재계산한 행들을 JSON 한 덩어리로 보내 PostgreSQL이 `jsonb_to_recordset(:payload)`로 읽게 하고, ORM에서는 `aliased(DerivedMetricsDaily, 그 서브쿼리)`로 같은 엔티티처럼 쓴다. 필터·정렬·총건수·offset 페이지·`ma60_stage`·`readiness`가 **기존 코드 그대로** 동작한다. `api_service`는 읽기 전용이지만 `jsonb_to_recordset`은 권한이 필요 없다.
- **동치 보증(시험의 핵심)**: 가상 행 = 발행된 행(재계산 없음)이면 결과가 기존 `/screen`·`/screen/pattern`과 **정확히 같아야** 한다(필터 7종·정렬 7종·페이지·총건수·패턴 c1~c5·c9·`ma60_stage`·`readiness` 전부, 골든 `tests/integration/golden_screen_before_pattern.json` 방식).
- 가상 행 만들기: ① 발행된 행(`derived_metrics_daily`, 발행 포인터 `current_published_batch` 기준)을 바탕으로 ② 시세를 받은 종목만 **가격·거래량 계열 열을 덮어쓴다**. 덮어쓰는 열(`recomputed`): `return_pct`(+`return_pct_raw`가 있으면 같이), `ma5_gap_pct`, `ma20_gap_pct`, `volume_anomaly_score`, `volume_raw`, 패턴 지표 11개 열과 `pattern_metrics_status`, (커버율 ≥ 90%일 때) 등락률 순위 백분위. 그대로 두는 열(`fixed_daily`): PER·PBR·시가총액 및 그 백분위·사유, 종목·시장 메타.
- 재계산은 **일봉 배치와 같은 순수 함수**(`services/derivation_batch/compute.py`: `compute_return_pct`·`compute_ma_gap_pct`·`compute_volume_anomaly_score`·`compute_pattern_metrics` 등, 호출 조합은 `run_derivation.py`의 `compute_stock_day_metrics`)를 쓴다. 입력 이력은 `public_serving.daily_prices`(종목당 최근 100행; API가 읽을 수 있는 일봉은 이것뿐)에 **오늘 행**(종가=현재가, 거래량=누적거래량, 날짜=오늘)을 붙인 것. 배치와 같은 가드(80행 미만 `INSUFFICIENT_HISTORY`, 일 변동 ±31% 초과 `SUSPECT_PRICE_JUMP`)를 그대로 적용한다 — 순수 함수를 재사용하면 자동으로 같다.
- **검증 골든**: 어떤 확정 거래일 D의 일봉을 "오늘 행"으로 넣고 D-1까지를 이력으로 주면, 재계산 결과가 배치가 만든 D의 `derived_metrics_daily` 행과 같아야 한다(소수 허용오차는 배치 반올림 규칙 그대로). 이것이 정확성의 증거다.

## 2. 모듈 경계·인터페이스(병렬 개발의 접점)
```
services/public_api/live_screen/            # 새 패키지
  history.py   HistoryCache  — daily_prices 종목당 최근 100행을 메모리에 보관, 발행 거래일이 바뀔 때만 재적재(DB 접근은 주입 가능한 함수)
  rows.py      build_live_rows(published_rows, history, quotes, *, today, policy) -> LiveRowsResult
  snapshot.py  SnapshotStore — snapshot_id → LiveRowsResult 최근 5개(시계 주입). latest(max_age) — 가장 최근 스냅샷이 max_age초 이내면 재사용, 아니면 None
services/public_api/api/local_screen.py    # 라우터: GET /local/screen, GET /local/screen/pattern
```
```python
# rows.py 계약 (L1a 구현, L1b가 소비)
@dataclass
class LiveRowsResult:
    rows: list[dict[str, Any]]      # derived_metrics_daily와 같은 열 이름의 dict. 시세를 못 받은 종목은 발행 값 그대로
    basis: dict[str, str]           # stock_code -> "live" | "daily"
    meta: dict[str, Any]            # 아래 §4 meta.live 의 계산 가능한 부분(covered, total, recomputed, fixed_daily, volume_partial, percentile_policy, compute_ms)
def build_live_rows(published_rows: list[dict], history: Mapping[str, Sequence[DailyBar]],
                    quotes: Mapping[str, MarketQuote], *, today: date, coverage_min: float = 0.9) -> LiveRowsResult: ...
```
- 시세(`quotes`)는 기존 `MarketSnapshotPoller.snapshot()`(= `local_market.get_runtime(settings).poller`)에서 가져온다. **폴러가 돌고 있지 않으면 라우터가 시작시키고(`ensure_started`) 첫 바퀴가 끝날 때까지 `LIVE_QUOTES_NOT_READY`(503, "시세를 모으는 중입니다. 잠시 후 다시 시도")**를 돌려준다(커버율 0%). 커버율이 0 초과 90% 미만이면 계산은 하되 등락률 순위는 일봉 고정, `meta.live.coverage_ratio`로 알린다.
- 오래된 시세: `fetched_at`이 `STALE_QUOTE_SECONDS`(기본 300초)보다 오래된 종목은 시세를 못 받은 것으로 간주(`basis:"daily"`).

## 3. API
공통: 관리자 전용(`local_realtime.require_owner`), `Cache-Control: no-store`, 응답 봉투는 기존과 같다(`{data, meta, error}`). 웹 서버 대행 허용 경로(`bffPaths.ts`의 `LOCAL_ALLOWED`·`LOCAL_ADMIN_ONLY`)에 `/api/v1/local/screen`과 `/api/v1/local/screen/pattern` 추가(긴 쿼리 허용 한도 확인).
- **`snapshot_id` 의미**: 없으면 "최신" — 서버가 최소 계산 간격 안이면 직전 스냅샷을 재사용하고, 아니면 새로 계산한다(자동 갱신의 기본 요청). 있으면 그 스냅샷 그대로(일시정지 중 페이지 이동). 만료·없음은 410.
- `GET /api/v1/local/screen` — **쿼리 파라미터·검증·응답 모양이 기존 `GET /api/v1/screen`과 같다** + 선택 `snapshot_id`. `data`는 `ScreenData`에 항목별 `basis`("live"|"daily")를 더한 것.
- `GET /api/v1/local/screen/pattern` — **기존 `GET /api/v1/screen/pattern`과 같다** + 선택 `snapshot_id`. 항목별 `basis` 추가.
- 응답 `meta`에 기존 `data_freshness` 외 `live`를 더한다:
```ts
interface LiveMeta {
  snapshot_id: string;            // 이 결과가 속한 스냅샷(페이지 이동에 같은 값을 보냄)
  as_of: number;                  // 스냅샷 계산 시각 epoch 초
  basis_trade_date: string;       // 기준 일봉 거래일 "YYYY-MM-DD"(발행된 값)
  expected_trade_date: string;    // 직전 거래일
  today: string;                  // 오늘 날짜(오늘 행의 날짜)
  quotes_covered: number; quotes_total: number; coverage_ratio: number; // 시세를 받은 종목 수/활성 종목 수
  oldest_quote_age_seconds: number | null;
  stale: boolean;                 // 시세 폴러 주기의 3배를 넘게 갱신 안 됨(local_market meta.stale와 같은 판정)
  volume_partial: true;           // 항상 true: 거래량 계열은 장중 부분값
  recomputed: string[]; fixed_daily: string[];
  return_rank_policy: "live" | "daily";
  compute_ms: number;
  refresh_seconds: number;        // 화면이 다음 요청을 보낼 권장 간격(기본 10, 서버 최소 계산 간격 이상)
  priority_codes: number;         // 이번 응답으로 우선 순환에 등록된 종목 수(상한 200)
  priority_cycle_seconds: number | null; // 우선 순환의 최근 한 바퀴 시간(초), 아직 모르면 null
  changes: { entered: string[]; left: string[] } | null; // 직전 스냅샷 대비 이 페이지 조건 결과의 편입·이탈 종목코드(첫 계산이면 null; 최대 100개씩)
}
```
| 상황 | HTTP | error.code |
|---|---|---|
| 일봉 발행 거래일 ≠ 직전 거래일 | 409 | `LIVE_BASE_STALE` — "일봉 데이터가 직전 거래일(YYYY-MM-DD)까지 갱신되지 않아 장중 재계산을 쓸 수 없습니다. (현재 YYYY-MM-DD)" |
| 시세를 아직 한 바퀴도 못 모음 | 503 | `LIVE_QUOTES_NOT_READY` |
| 장 시간 밖(평일 08:00~20:00 KST 밖) | 200 | 거부하지 않는다. 시세가 마지막 값이므로 `stale`로 알린다 |
| 지정한 `snapshot_id`가 없거나 만료 | 410 | `SNAPSHOT_EXPIRED` — 화면이 새로 계산하도록 |
| 그 밖 | 기존 `/screen`과 같은 오류 코드(400 `INVALID_PARAMETER` 등), 앱키·로컬 모드·관리자 오류는 `local_market`과 같다 |

## 4. 화면 규칙(프런트)
- `/screener`·`/screener/pattern`에 **"장중 기준" 전환**(로컬 모드 관리자에게만; `useLocalMode`와 `localIntradayAvailable()` 재사용, 일반 회원·운영 빌드에는 전환이 없고 요청도 없음). 켜면 `/api/v1/local/screen*`을 부르고 **`refresh_seconds` 간격(탭이 가려지면 중지, 복귀 시 즉시)으로 자동 갱신**한다 — 응답이 오면 목록을 제자리에서 교체(스크롤 위치·선택 페이지 유지), 직전 대비 새로 들어온 종목에 "신규" 글자 표지(약 60초), `changes.left`는 "최근 변화" 목록에. **"일시정지"** 토글: 켜면 현재 `snapshot_id`로 고정(페이지 이동은 같은 `snapshot_id`), 끄면 자동 갱신 재개. "새로 계산" 버튼은 즉시 한 번 갱신. "조건 적용"은 자동 갱신 요청을 새로 시작. 실패 시 간격을 늘려 재시도(상한 30초)하며 마지막 값을 "지연" 표시로 유지. 켜진 상태는 이 브라우저에만 기억(localStorage, 실패해도 동작).
- 결과 위에 **기준 배너**(DataFreshnessBadge 자리 대체): "장중 기준 · 계산 HH:MM:SS(N초 전) · 시세 수신 covered/total종목 · 기준 일봉 YYYY-MM-DD" + 항상 경고 "거래량 계열(거래량·거래량 이상치·거래량비·급등 이력)은 장중 누적 부분값이며 PER·PBR·시가총액 순위는 일봉 기준입니다." `stale`이면 "시세 갱신이 지연되고 있습니다", 커버율 < 90%이면 "등락률 순위는 일봉 기준" 안내. `basis:"daily"` 항목은 "일봉" 작은 표지. 기존 "조건 판정은 일봉 기준" 안내문(`broker`·`liveQuoteNotice`)은 전환이 켜진 동안 교체.
- 오류 상태: `LIVE_BASE_STALE`·`LIVE_QUOTES_NOT_READY`·`SNAPSHOT_EXPIRED`·403/404/503은 각각 안내(일봉 기준으로 되돌리는 버튼 포함). "마지막 계산 시각"과 "N초 전"을 초 단위로 보여 주고, 갱신이 지연되면(마지막 성공이 `refresh_seconds`의 3배 초과) 눈에 띄게 "지연" 표시한다(최상위 목표: 지연·불일치는 숨기지 않는다). 투자 권유·수익 보장 표현 금지(`lint:copy`).

## 5. 시험 기준
- **동치**(가상 행 = 발행 행 → 기존 API와 완전 동일), **재계산 골든**(확정일을 오늘 행으로 → 배치 행과 일치), 커버율·오래된 시세·`basis` 구분, 등락률 순위 정책(≥90% / <90%), `LIVE_BASE_STALE`·`LIVE_QUOTES_NOT_READY`·`SNAPSHOT_EXPIRED`, 최소 계산 간격 안의 재사용(연속 요청에도 계산 1번)·간격 뒤 재계산·`snapshot_id` 고정(일시정지 중 페이지 이동에서 시세가 바뀌어도 결과 집합 동일)·보관 5개·`changes`(편입·이탈) 정확성, 접근 통제(404·403), 응답에 원본 시세·비밀값 없음, **성능 실측**(2,800종목 재계산 시간·JSON 크기·쿼리 시간을 결과서에 숫자로).
- 최종 종단(로그인 + 웹 서버 대행 + API + 모의 증권사 + 브라우저)과 운영 빌드 비노출은 합치는 단계에서 메인이 수행.

## 6. 우선 순환(보이는 종목을 더 빨리) 계약 — 담당 M
`services/public_api/realtime/market.py`의 `MarketSnapshotPoller`에 다음을 **하위 호환으로** 추가한다(기존 순환·시험 불변):
```python
poller.set_priority(codes: Iterable[str], *, ttl_seconds: float = 30.0) -> int   # 등록된 종목 수(상한 max_priority, 기본 200, 환경변수 KIS_MARKET_PRIORITY_MAX)
poller.priority_codes() -> list[str]
poller.priority_cycle_seconds -> float | None   # 우선 순환 최근 한 바퀴 시간
```
- 우선 종목(발행 목록에 있는 코드만)은 별도 주기(`KIS_MARKET_PRIORITY_SECONDS`, 기본 3초)로 30종목씩 묶어 조회한다. **같은 `KisClient`의 호출 간격(throttle)을 공유**하므로 합산 호출률은 변하지 않고(상세 화면 호출에 계속 양보: `low_priority`), 우선 순환이 차지한 만큼 전체 순환이 느려진다 → 우선 순환 호출 수는 전체 한도의 일정 비율(기본 50%)을 넘지 않게 제한한다.
- `ttl_seconds` 안에 다시 `set_priority`가 오지 않으면 자동 해제(화면이 닫히면 증권사 호출이 원래대로 돌아간다). 폴러 정지 시 함께 정리. 시세 `fetched_at`은 어느 쪽 조회든 최신 값으로 갱신. 한 묶음 실패는 다음 주기에 재시도(기존 규칙).
- `api/local_market.py`의 `/quotes`에도 선택 쿼리 `priority=1`을 두어(관리자 전용) 목록 화면의 현재가 조회가 보이는 종목을 우선 순환에 올릴 수 있게 한다(기본 꺼짐).
