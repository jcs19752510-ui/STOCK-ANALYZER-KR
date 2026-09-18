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


__all__ = [
    "MarketSummaryInput",
    "MarketSummaryResult",
    "SectorTradingValue",
    "compute_ma_gap_pct",
    "compute_market_summary",
    "compute_return_pct",
    "compute_volume_anomaly_score",
    "rank_percentile",
]
