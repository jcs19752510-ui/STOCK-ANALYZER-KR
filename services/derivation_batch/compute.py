"""가공 지표 순수 계산 로직 (REQ-002).

DB/외부 의존성이 전혀 없는 순수 함수만 담는다 — 6단계가 실제 raw_ohlcv
데이터 없이도(픽스처 값만으로) 이 계산 로직을 독립적으로 검증할 수 있게
하기 위함이다(코디네이터 지시: "raw_internal.raw_ohlcv에 실제 데이터가
없을 것" 대응).

**설계서(03-system-design.md §3-2)가 정확한 계산식까지 못박지 않은 값들
(이동평균 괴리율의 "이동평균"이 당일을 포함하는지, 거래량 이상치 스코어의
"20일 평균/표준편차"가 당일을 포함하는지)은 이 모듈이 직접 확정한다.**
증권가에서 통용되는 표준 정의("이격도")를 따랐다 — 아래 각 함수 docstring에
근거를 남긴다. `unit-06-note.md` §2 참조.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal

from shared import pattern_params as _pp

_QUANT = Decimal("0.0001")
_PCT_QUANT = Decimal("0.1")


def compute_return_pct(close_today: Decimal, close_prev: Decimal | None) -> Decimal | None:
    """당일 등락률(%). 전일 종가가 없으면(신규 상장 첫날 등) None."""
    if close_prev is None or close_prev == 0:
        return None
    return ((close_today - close_prev) / close_prev * 100).quantize(_QUANT)


def compute_ma_gap_pct(closes_including_today: list[Decimal], window: int) -> Decimal | None:
    """N일 이동평균 대비 괴리율(%) — 흔히 "이격도"로 불리는 표준 정의를 따른다.

    이동평균은 **당일 종가를 포함한** 최근 N거래일 종가의 평균이다(당일을
    제외하면 "이격도"의 통상적 의미와 달라진다 — 이 함수 시그니처의
    `closes_including_today`가 그 결정을 명시한다). `closes_including_today`는
    가장 최근 값이 마지막 원소일 필요는 없다(순서 무관, 평균만 계산).

    데이터가 window 미만이면(신규 상장 등) None — 03-system-design.md §3-2
    결측치 처리 원칙("계산 불가능한 필드는 null").
    """
    if len(closes_including_today) < window:
        return None
    window_values = closes_including_today[:window]
    ma = sum(window_values) / Decimal(window)
    if ma == 0:
        return None
    today_close = closes_including_today[0]
    return ((today_close - ma) / ma * 100).quantize(_QUANT)


def compute_volume_anomaly_score(
    today_volume: int, baseline_volumes: list[int], *, window: int = 20
) -> Decimal | None:
    """거래량 이상치 스코어 = (당일 거래량 - 평균) / 표준편차.

    `baseline_volumes`는 당일을 **제외한** 직전 `window`거래일 거래량이다 —
    "오늘이 평소 패턴에서 얼마나 벗어났는지"를 재는 것이 목적이므로, 오늘
    자신을 기준(평균/표준편차) 계산에 포함하지 않는다(포함하면 이상치일수록
    기준 자체가 이상치 쪽으로 끌려가 스코어가 항상 과소평가된다).
    표준편차는 표본표준편차(`statistics.stdev`, n-1)를 사용한다.

    데이터 부족(window 미만) 또는 표준편차 0(전부 동일 거래량)이면 None.
    """
    if len(baseline_volumes) < window:
        return None
    stdev = statistics.stdev(Decimal(v) for v in baseline_volumes)
    if stdev == 0:
        return None
    mean = statistics.mean(Decimal(v) for v in baseline_volumes)
    return ((Decimal(today_volume) - mean) / stdev).quantize(_QUANT)


def rank_percentile[KeyT](
    pairs: list[tuple[KeyT, Decimal]], *, descending: bool
) -> dict[KeyT, Decimal]:
    """표준경쟁순위(RANK()) 기반 백분위. 03-system-design.md §3-2 공식 그대로.

    `percentile = ROUND(rank / total_count * 100, 1)`. 동률은 같은 순위를
    받고 다음 순위는 건너뛴다(예: 1, 1, 3, 4...). `pairs`는 이미 None이
    제거된(값이 있는) 항목만 전달해야 한다 — null 항목은 애초에 순위 계산
    대상이 아니다(§3-2 결측치 처리 원칙).

    `descending=True`: 값이 클수록 상위(예: return_pct, market_cap_raw_krw).
    `descending=False`: 값이 작을수록 상위(예: per_raw, pbr_raw — 저평가일수록
    상위이므로 오름차순 순위).
    """
    if not pairs:
        return {}
    ordered = sorted(pairs, key=lambda item: item[1], reverse=descending)
    total = Decimal(len(ordered))
    result: dict[KeyT, Decimal] = {}
    current_rank = 0
    previous_value: Decimal | None = None
    for index, (key, value) in enumerate(ordered, start=1):
        if previous_value is None or value != previous_value:
            current_rank = index
            previous_value = value
        result[key] = (Decimal(current_rank) / total * 100).quantize(_PCT_QUANT)
    return result


@dataclass(frozen=True)
class SectorTradingValue:
    sector: str
    trading_value_krw: int


@dataclass(frozen=True)
class MarketSummaryInput:
    """시장 동향 요약(REQ-004) 집계 대상 종목 1건. `sector`는 `stock_master.sector`
    출처가 아직 확정되지 않아(03-system-design.md §8-2 항목8) `None`일 수 있다."""

    return_pct: Decimal | None
    trading_value_krw: int
    sector: str | None


@dataclass(frozen=True)
class MarketSummaryResult:
    advancers_count: int
    decliners_count: int
    unchanged_count: int
    top_sectors_by_value: list[SectorTradingValue]
    total_trading_value_krw: int


def compute_market_summary(
    rows: list[MarketSummaryInput], *, top_n: int = 5
) -> MarketSummaryResult:
    """REQ-004 시장 동향 요약 통계(03-system-design.md §3-2 `market_summary_daily`).

    상승/하락/보합은 `return_pct`가 있는 종목만 집계 대상이다 — 결측(신규
    상장 첫날 등, §3-2 결측치 처리 원칙)은 상승도 하락도 보합도 아니므로
    셋 중 어디에도 포함하지 않는다(0이나 보합으로 임의 대체하지 않음).

    업종별 거래대금은 `sector`가 있는 종목만 합산한다. `sector` 출처가
    아직 확정되지 않아(§8-2 항목8) 현재는 전 종목이 `sector=None`일 수
    있으며, 그 경우 빈 리스트를 반환한다(04-ux-design.md §2-1 "업종 정보를
    준비 중입니다" 부분 실패 표시로 이어짐 — 존재하지 않는 업종을 지어내지
    않는다). 총 거래대금은 `sector` 유무와 무관하게 전달된 모든 종목을
    합산한다(업종 미분류와 무관하게 실제로 거래된 금액이므로).

    이 함수는 DB 접근이 없는 순수 함수라, 호출자가 KOSPI/KOSDAQ/ALL 어느
    범위의 `rows`를 넘기든 그대로 그 범위만 집계한다 — `ALL` 집계는
    KOSPI/KOSDAQ 결과를 사후 합산하는 방식이 아니라, 호출자가 전체 종목
    목록을 직접 넘겨 이 함수가 한 번에 재집계하는 방식으로 이뤄져야 한다
    (DEC-016 — 업종 상위 리스트처럼 부분 상위 N의 합으로 전체 상위 N을
    복원할 수 없는 값이 있기 때문).
    """
    advancers_count = sum(1 for r in rows if r.return_pct is not None and r.return_pct > 0)
    decliners_count = sum(1 for r in rows if r.return_pct is not None and r.return_pct < 0)
    unchanged_count = sum(1 for r in rows if r.return_pct is not None and r.return_pct == 0)
    total_trading_value_krw = sum(r.trading_value_krw for r in rows)

    sector_totals: dict[str, int] = {}
    for row in rows:
        if row.sector is None:
            continue
        sector_totals[row.sector] = sector_totals.get(row.sector, 0) + row.trading_value_krw

    top_sectors = sorted(sector_totals.items(), key=lambda item: item[1], reverse=True)[:top_n]

    return MarketSummaryResult(
        advancers_count=advancers_count,
        decliners_count=decliners_count,
        unchanged_count=unchanged_count,
        top_sectors_by_value=[
            SectorTradingValue(sector=sector, trading_value_krw=value)
            for sector, value in top_sectors
        ],
        total_trading_value_krw=total_trading_value_krw,
    )


# ── 패턴 스크리닝 "급등 전 압축주" 지표 (REQ-030, 02-system-design.md §3~§4) ─────────────
# 아래 정의는 `docs/pattern-screening/prototype/pattern_rules_reference.py`(기준 구현)와 1:1이며
# `tests/unit/test_pattern_compute.py`가 합성 시계열 300건으로 교차 검증한다.
# 기존 함수는 바꾸지 않았다.


@dataclass(frozen=True)
class PatternMetrics:
    """`derived_metrics_daily` 패턴 지표 11개 컬럼과 1:1(설계서 §3-1).

    산정 불가(`INSUFFICIENT_HISTORY`/`SUSPECT_PRICE_JUMP`)면 `pattern_metrics_status`만 채우고
    나머지는 전부 `None`이다. 상태가 `OK`여도 분모 0인 개별 값은 `None`일 수 있다
    (3값 논리, 설계서 §4-1-3).
    """

    sideways_range_pct: Decimal | None = None
    sideways_net_change_pct: Decimal | None = None
    ma_convergence_pct: Decimal | None = None
    volatility_contraction_ratio: Decimal | None = None
    ma60_gap_pct: Decimal | None = None
    ma20_vs_ma60_gap_pct: Decimal | None = None
    ma60_slope_pct: Decimal | None = None
    ma60_cross_up_days: int | None = None
    volume_ratio_5_60: Decimal | None = None
    recent_surge_flag: bool | None = None
    pattern_metrics_status: str = _pp.PATTERN_STATUS_OK


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def _ma(closes: list[Decimal], window: int, offset: int = 0) -> Decimal:
    """`closes[offset:offset+window]`의 단순평균. 호출자가 길이 충분을 보장한다(MIN_ROWS 게이트)."""
    return _mean(closes[offset : offset + window])


def _daily_returns_pct(closes: list[Decimal], count: int) -> list[Decimal]:
    """최신순 `closes`의 최근 `count`개 일수익률(%): (closes[i]-closes[i+1])/closes[i+1]*100."""
    return [(closes[i] - closes[i + 1]) / closes[i + 1] * 100 for i in range(count)]


def compute_pattern_metrics(closes: list[Decimal], volumes: list[int]) -> PatternMetrics:
    """패턴 스크리닝 지표 11개를 계산한다(순수 함수, I/O·전역 상태 변경 없음).

    **입력 규약: `closes`·`volumes`는 최신순(내림차순)이며 0번 원소가 대상 거래일(T)이다.**
    오름차순(과거→최신)으로 넘기면 결과가 달라지므로(오용 방지, TC-U42) 호출자가 순서를 맞춘다.
    배치는 종목당 `PATTERN_WINDOW_ROWS`(100)행을 최신순으로 조회해 넘기지만 이 함수는 앞쪽
    `PATTERN_MIN_ROWS`(80)행만 쓴다 — 그보다 오래된 행은 결과에 영향이 없다(TC-U41).

    산정 불가 게이트(설계서 §4-1):
    1. 종가·거래량 중 하나라도 80행 미만 → `INSUFFICIENT_HISTORY`.
    2. 앞 80행 종가에 0 이하가 있거나, 앞 80행의 일 변동률 절댓값이 31%를 넘는 날이 있음
       → `SUSPECT_PRICE_JUMP`(액면분할 등 수정주가 미반영 의심).
    3. 개별 지표의 분모가 0이면(60일 수익률 표준편차 0, 60일 평균 거래량 0) 그 값만 `None`.
    모든 수치는 소수 4자리로 정규화한다. 비교는 경계 포함이다(예: 급등 +10.0%·3.0배는 충족).
    """
    p = _pp
    if len(closes) < p.PATTERN_MIN_ROWS or len(volumes) < p.PATTERN_MIN_ROWS:
        return PatternMetrics(pattern_metrics_status=p.PATTERN_STATUS_INSUFFICIENT_HISTORY)
    if any(c <= 0 for c in closes[: p.PATTERN_MIN_ROWS]):
        return PatternMetrics(pattern_metrics_status=p.PATTERN_STATUS_SUSPECT_PRICE_JUMP)
    for i in range(p.PATTERN_LOOKBACK_DAYS - 1):
        if abs((closes[i] - closes[i + 1]) / closes[i + 1] * 100) > p.PRICE_JUMP_LIMIT_PCT:
            return PatternMetrics(pattern_metrics_status=p.PATTERN_STATUS_SUSPECT_PRICE_JUMP)

    window = closes[: p.PATTERN_LOOKBACK_DAYS]
    short_ma, mid_ma, long_ma = (_ma(closes, n) for n in p.CONVERGENCE_MA_WINDOWS)
    ma20 = long_ma
    ma60 = _ma(closes, p.MA60_WINDOW)
    ma60_prev = _ma(closes, p.MA60_WINDOW, p.MA60_SLOPE_DAYS)

    # 변동성 수축비: 최근 10일 / 60일 일수익률 모표준편차. 60일 표준편차 0이면 None.
    sd_long = statistics.pstdev(_daily_returns_pct(closes, p.VOL_LONG))
    volatility_ratio = (
        None
        if sd_long == 0
        else statistics.pstdev(_daily_returns_pct(closes, p.VOL_SHORT)) / sd_long
    )

    # 최근 10거래일 내 종가가 60일선을 상향 돌파한 가장 최근 시점(0=오늘). 종가==MA60은 돌파 아님.
    cross_days: int | None = None
    for k in range(p.CROSS_LOOKBACK_DAYS):
        if closes[k] > _ma(closes, p.MA60_WINDOW, k) and closes[k + 1] <= _ma(
            closes, p.MA60_WINDOW, k + 1
        ):
            cross_days = k
            break

    vol_dec = [Decimal(v) for v in volumes[: p.PATTERN_MIN_ROWS]]
    vr_den = _mean(vol_dec[: p.VR_LONG])
    volume_ratio = None if vr_den == 0 else _mean(vol_dec[: p.VR_SHORT]) / vr_den

    # 급등 이력(뉴스 반영 대리 지표): 일 등락률 ≥ +10% 그리고 거래량 ≥ 직전 20일 평균 × 3.
    # 직전 20일 평균 거래량이 0이면 그 날은 건너뛴다(0 나눗셈 방지·기준 부재).
    surge = False
    for d in range(p.SURGE_LOOKBACK_DAYS):
        ret = (closes[d] - closes[d + 1]) / closes[d + 1] * 100
        base = _mean(vol_dec[d + 1 : d + 1 + p.SURGE_BASELINE_DAYS])
        if ret >= p.SURGE_RETURN_PCT and base > 0 and vol_dec[d] >= p.SURGE_VOLUME_MULT * base:
            surge = True
            break

    def q(value: Decimal | None) -> Decimal | None:
        return None if value is None else value.quantize(_QUANT)

    oldest = closes[p.PATTERN_LOOKBACK_DAYS - 1]
    return PatternMetrics(
        sideways_range_pct=q((max(window) - min(window)) / _mean(window) * 100),
        sideways_net_change_pct=q((closes[0] - oldest) / oldest * 100),
        ma_convergence_pct=q(
            (max(short_ma, mid_ma, long_ma) - min(short_ma, mid_ma, long_ma)) / ma20 * 100
        ),
        volatility_contraction_ratio=q(volatility_ratio),
        ma60_gap_pct=q((closes[0] - ma60) / ma60 * 100),
        ma20_vs_ma60_gap_pct=q((ma20 - ma60) / ma60 * 100),
        ma60_slope_pct=q((ma60 - ma60_prev) / ma60_prev * 100),
        ma60_cross_up_days=cross_days,
        volume_ratio_5_60=q(volume_ratio),
        recent_surge_flag=surge,
        pattern_metrics_status=p.PATTERN_STATUS_OK,
    )


__all__ = [
    "MarketSummaryInput",
    "MarketSummaryResult",
    "PatternMetrics",
    "SectorTradingValue",
    "compute_ma_gap_pct",
    "compute_market_summary",
    "compute_pattern_metrics",
    "compute_return_pct",
    "compute_volume_anomaly_score",
    "rank_percentile",
]
