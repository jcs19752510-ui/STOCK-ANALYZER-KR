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


__all__ = [
    "compute_ma_gap_pct",
    "compute_return_pct",
    "compute_volume_anomaly_score",
    "rank_percentile",
]
