"""`GET /api/v1/screen/pattern` 응답 스키마 (REQ-032, 02-system-design.md §5-2).

**화이트리스트 스키마다.** 가격(open/high/low/close)·거래량 원값·`*_raw`·시가총액 원값 필드는
선언조차 하지 않는다(`schemas/screen.py`와 같은 원칙, §4-3) — 노출하는 값은
비율(%)·배수·불리언·일수뿐이다. 점수·순위·충족 개수 같은 서열 필드도 없다(REQ-034). 테스트가 필드
집합을 고정한다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class ConditionResult(BaseModel):
    """조건 1개의 결과. `met=None`이면 산정 불가이며 `reason`에 사유가 담긴다."""

    met: bool | None
    reason: str | None = None  # INSUFFICIENT_HISTORY | SUSPECT_PRICE_JUMP | METRIC_UNAVAILABLE


class PatternMetricsOut(BaseModel):
    sideways_range_pct: float | None
    sideways_net_change_pct: float | None
    ma_convergence_pct: float | None
    volatility_contraction_ratio: float | None
    ma60_gap_pct: float | None
    ma20_vs_ma60_gap_pct: float | None
    ma60_slope_pct: float | None
    ma60_cross_up_days: int | None
    volume_ratio_5_60: float | None
    volume_anomaly_score: float | None
    recent_surge_flag: bool | None


class PatternItem(BaseModel):
    stock_code: str
    name: str
    market: str
    conditions: dict[str, ConditionResult]
    metrics: PatternMetricsOut
    # c4 화면 문구용 단계(표시 전용):
    # BELOW_FAR | BELOW_NEAR | CROSS_EARLY | ABOVE_SETTLED | EXTENDED
    ma60_stage: str | None


class PatternUniverse(BaseModel):
    """평가 대상에서 제외한 종목 유형(SPAC·PREFERRED). 조용한 제외 금지 — 항상 공개."""

    excluded_types: list[str]


class PatternDefinition(BaseModel):
    """서버 설정을 그대로 노출 — 화면의 조건 설명이 문서·코드와 어긋나지 않게 하는 단일 출처."""

    version: str
    thresholds: dict[str, int | float]
    calc: dict[str, int | float]
    universe: PatternUniverse


class PatternReadiness(BaseModel):
    evaluated_count: int
    total_count: int
    ready_ratio: float


class PatternScreenData(BaseModel):
    items: list[PatternItem]
    total_count: int
    page: int
    definition: PatternDefinition
    readiness: PatternReadiness


class PatternCheckData(BaseModel):
    """`GET /api/v1/stocks/{code}/pattern-check` — 한 종목의 조건별 충족 여부(DEC-041).

    `item`이 None이면 이 종목은 평가 대상이 아니거나(스팩·우선주 등) 발행 거래일 데이터가 없다.
    점수·순위·충족 개수 같은 서열 필드는 없다(REQ-034).
    """

    trade_date: date  # 판정 기준 거래일(발행 거래일)
    item: PatternItem | None
    definition: PatternDefinition
