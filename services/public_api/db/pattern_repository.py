"""패턴 스크리닝 조건식 — 판정 로직의 **단일 출처** (REQ-032, 02-system-design.md §0-5·§4-2·§5-4).

`build_condition_exprs()`가 c1~c5·c9를 SQLAlchemy 식으로 한 곳에서 만든다. 필터링(WHERE)과 응답용
충족 여부(SELECT)가 **같은 식**을 쓰므로 필터와 표시가 어긋날 수 없고, Python에서 재판정하지 않는다.
`ma60_stage_expr()`도 같은 임계값·같은 경계의 SQL `CASE`라 프런트가 임계값으로 단계를 재계산할
필요가 없다(판정이 두 곳이 되는 것을 방지).

3값 논리: SQLAlchemy `and_/or_`는 SQL `AND/OR`로 컴파일되어 `FALSE AND NULL = FALSE`가 유지된다
(기준 구현 `_and3/_or3`와 동일). 산정 불가는 `NULL`로 끝까지 전달된다. 모든 식은
`pattern_metrics_status = 'OK'`로 게이트되어, 상태가 `OK`가
아니거나(`INSUFFICIENT_HISTORY`/`SUSPECT_PRICE_JUMP`) 상태가 `NULL`인 구 배치 행이면 지표 값이
채워져 있어도 결과가 `NULL`이다. 모든 비교는 경계 포함(≤, ≥)이며 거래량 이상치만 엄격
미만(<)이다(설계서 §4-2).

이 모듈은 임계값(`PatternThresholds`)을 바인딩만 하고 값을 판단하지 않는다 — 임계값은 서버 설정이
유일한 출처다(`core/pattern_config.py`). `api_service`는 `derived_metrics_daily` SELECT만
가능하다(DEC-006).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, case, func, not_, or_

from services.public_api.core.pattern_config import PatternThresholds
from shared.db_models.public_serving import DerivedMetricsDaily as D
from shared.pattern_params import PATTERN_STATUS_OK

CONDITION_IDS: tuple[str, ...] = ("c1", "c2", "c3", "c4", "c5", "c9")

# c4 단계(`ma60_stage`) 값 — 설계서 §5-2. c4 충족 ⇔ BELOW_NEAR 또는 CROSS_EARLY.
STAGE_BELOW_FAR = "BELOW_FAR"
STAGE_BELOW_NEAR = "BELOW_NEAR"
STAGE_CROSS_EARLY = "CROSS_EARLY"
STAGE_ABOVE_SETTLED = "ABOVE_SETTLED"
STAGE_EXTENDED = "EXTENDED"


def _status_gate(expr: ColumnElement) -> ColumnElement:
    return case((D.pattern_metrics_status == PATTERN_STATUS_OK, expr), else_=None)


def build_condition_exprs(th: PatternThresholds) -> dict[str, ColumnElement]:
    """c1~c5·c9 판정식(경계 포함). 값은 `True`/`False`/`NULL(산정 불가)`로 평가된다."""
    band = th.ma60_approach_band_pct
    gap = D.ma60_gap_pct

    c1 = and_(
        D.sideways_range_pct <= th.range_max_pct,
        func.abs(D.sideways_net_change_pct) <= th.net_change_max_pct,
    )
    c2 = and_(
        D.ma_convergence_pct <= th.convergence_max_pct,
        D.volatility_contraction_ratio <= th.volatility_contraction_max,
    )
    c3 = and_(
        func.abs(gap) <= band,
        func.abs(D.ma20_vs_ma60_gap_pct) <= band,
    )
    # 돌파 직전(-BAND ≤ gap < 0) 또는 돌파 초입(0 ≤ gap ≤ EARLY_MAX 이고 최근 상향 돌파가
    # N일 이내). `cross IS NOT NULL AND cross <= N`은 cross가 NULL이면
    # FALSE AND NULL = FALSE로 평가된다.
    c4 = or_(
        and_(gap >= -band, gap < 0),
        and_(
            gap >= 0,
            gap <= th.ma60_early_max_gap_pct,
            D.ma60_cross_up_days.is_not(None),
            D.ma60_cross_up_days <= th.cross_early_max_days,
        ),
    )
    c5 = and_(
        D.volume_ratio_5_60 >= th.volume_ratio_min,
        D.volume_ratio_5_60 <= th.volume_ratio_max,
        D.volume_anomaly_score < th.volume_anomaly_max,
    )
    # 급등 이력 없음: 플래그 FALSE → true, TRUE → false, NULL → NULL(`NOT NULL`은 NULL).
    c9 = not_(D.recent_surge_flag)

    exprs = {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c9": c9}
    return {cid: _status_gate(expr) for cid, expr in exprs.items()}


def ma60_stage_expr(th: PatternThresholds) -> ColumnElement:
    """c4 화면 문구용 단계(표시 전용, 서버가 c4와 같은 임계값·경계로 산출). 산정 불가면 `NULL`."""
    band = th.ma60_approach_band_pct
    gap = D.ma60_gap_pct
    stage = case(
        (gap < -band, STAGE_BELOW_FAR),
        (gap < 0, STAGE_BELOW_NEAR),
        (gap > th.ma60_early_max_gap_pct, STAGE_EXTENDED),
        (
            and_(
                D.ma60_cross_up_days.is_not(None),
                D.ma60_cross_up_days <= th.cross_early_max_days,
            ),
            STAGE_CROSS_EARLY,
        ),
        else_=STAGE_ABOVE_SETTLED,
    )
    # gap이 NULL이면 위 비교가 모두 NULL이라 else로 떨어지므로 명시적으로 NULL 처리한다.
    return case(
        (and_(D.pattern_metrics_status == PATTERN_STATUS_OK, gap.is_not(None)), stage),
        else_=None,
    )
