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

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import ColumnElement, Select, and_, case, func, not_, or_, select
from sqlalchemy.orm import Session

from services.public_api.core.pattern_config import PatternThresholds
from shared.db_models.public_serving import CurrentPublishedBatch, StockMaster
from shared.db_models.public_serving import DerivedMetricsDaily as D
from shared.market_types import ListedMarketFilter
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


# ── 조회 리포지토리 (REQ-032, 설계서 §5-4) ─────────────────────────────────────────────

# `sort_by` 허용값 → 정렬 컬럼. 문자열 연결 없이 화이트리스트 매핑으로만 선택한다(SQL 인젝션 차단).
# 점수·순위·충족 개수 정렬은 제공하지 않는다(REQ-034).
SORT_COLUMN_MAP = {
    "market_cap": D.market_cap_raw_krw,  # 필터·정렬 전용 — 응답에는 노출하지 않는다
    "ma60_gap_pct": D.ma60_gap_pct,
    "sideways_range_pct": D.sideways_range_pct,
    "ma_convergence_pct": D.ma_convergence_pct,
}

# 응답 `metrics`로 노출하는 11개 지표(설계서 §5-2). 가격·거래량 원값·`*_raw`·시가총액 원값은 없다.
METRIC_KEYS: tuple[str, ...] = (
    "sideways_range_pct",
    "sideways_net_change_pct",
    "ma_convergence_pct",
    "volatility_contraction_ratio",
    "ma60_gap_pct",
    "ma20_vs_ma60_gap_pct",
    "ma60_slope_pct",
    "ma60_cross_up_days",
    "volume_ratio_5_60",
    "volume_anomaly_score",
    "recent_surge_flag",
)


@dataclass(frozen=True)
class PatternFilters:
    trade_date: date
    market: ListedMarketFilter
    required: tuple[str, ...]  # 필수 조건 ID(정규 순서). 각 식이 TRUE인 종목만 통과
    market_cap_min: int | None
    volume_min: int | None
    sort_by: str
    sort_dir: str
    page: int
    page_size: int


@dataclass(frozen=True)
class PatternRow:
    stock_code: str
    name: str
    market: str
    status: str | None  # pattern_metrics_status(구 배치 행이면 None)
    stage: str | None  # ma60_stage(SQL CASE), 산정 불가면 None
    conds: dict[str, bool | None]  # c1..c9 → True/False/None(산정 불가)
    metrics: dict[str, Decimal | int | bool | None]


@dataclass(frozen=True)
class PatternQueryResult:
    items: list[PatternRow]
    total_count: int


def special_stock_expr() -> ColumnElement[bool]:
    """스팩·우선주 판별(사용자 결정 Q3, 평가 대상에서 제외).

    - 스팩: 이름에 '스팩'
    - 우선주: 이름이 우/우B/2우B/우(전환) 꼴로 끝나고 종목코드 끝자리가 0이 아님
      (보통주 코드는 끝자리 0 — 이름만 보면 '성우' 등 보통주를 잘못 제외한다)
    """
    spac = StockMaster.name.like("%스팩%")
    preferred = and_(
        StockMaster.name.op("~")(r"우(\(전환\))?[A-C]?$"),
        func.right(StockMaster.stock_code, 1) != "0",
    )
    return or_(spac, preferred)


class PatternScreenRepository(Protocol):
    def get_current_published_trade_date(self, market: str) -> date | None: ...

    def readiness(
        self, trade_date: date, market: ListedMarketFilter, thresholds: PatternThresholds
    ) -> tuple[int, int]: ...

    def search(
        self, filters: PatternFilters, thresholds: PatternThresholds
    ) -> PatternQueryResult: ...


class SqlPatternScreenRepository:
    """`public_serving.derived_metrics_daily` 패턴 조회.

    `api_service`는 SELECT만 가능하다(DEC-006).
    """

    def __init__(self, session: Session):
        self._session = session

    def get_current_published_trade_date(self, market: str) -> date | None:
        row = self._session.get(CurrentPublishedBatch, market)
        return row.trade_date if row is not None else None

    def readiness(
        self, trade_date: date, market: ListedMarketFilter, thresholds: PatternThresholds
    ) -> tuple[int, int]:
        """(발행 거래일의 행 수, 산정 가능(`OK`) 행 수).

        `market` 필터와 평가 대상 제외(스팩·우선주) 적용 후 집합 기준이다(설계서 §5-4).
        """
        stmt = (
            select(
                func.count(),
                func.count().filter(D.pattern_metrics_status == PATTERN_STATUS_OK),
            )
            .select_from(D)
            .join(StockMaster, StockMaster.stock_code == D.stock_code)
            .where(D.trade_date == trade_date)
        )
        if thresholds.exclude_special_stocks:
            stmt = stmt.where(not_(special_stock_expr()))
        if market != "ALL":
            stmt = stmt.where(D.market == market)
        total, ok = self._session.execute(stmt).one()
        return int(total), int(ok)

    def _where(self, filters: PatternFilters, th: PatternThresholds) -> list[ColumnElement]:
        exprs = build_condition_exprs(th)
        where: list[ColumnElement] = [D.trade_date == filters.trade_date]
        if th.exclude_special_stocks:
            where.append(not_(special_stock_expr()))
        if filters.market != "ALL":
            where.append(D.market == filters.market)
        if filters.market_cap_min is not None:
            where.append(D.market_cap_raw_krw >= filters.market_cap_min)
        if filters.volume_min is not None:
            where.append(D.volume_raw >= filters.volume_min)
        # 필수 조건은 `IS TRUE`로 건다(FALSE·NULL 모두 제외).
        # 응답의 met는 같은 식을 SELECT한 값이다.
        where.extend(exprs[cid].is_(True) for cid in filters.required)
        return where

    def search_statement(self, filters: PatternFilters, th: PatternThresholds) -> Select:
        """페이지 조회 SELECT(실행 계획 점검용으로 공개).

        조건식은 `build_condition_exprs` 한 곳에서만 만든다.
        """
        exprs = build_condition_exprs(th)
        sort_column = SORT_COLUMN_MAP[filters.sort_by]
        order = sort_column.desc() if filters.sort_dir == "desc" else sort_column.asc()
        return (
            select(
                D.stock_code,
                StockMaster.name,
                D.market,
                D.pattern_metrics_status.label("status"),
                ma60_stage_expr(th).label("stage"),
                *[exprs[cid].label(cid) for cid in CONDITION_IDS],
                *[getattr(D, key) for key in METRIC_KEYS],
            )
            .join(StockMaster, StockMaster.stock_code == D.stock_code)
            .where(*self._where(filters, th))
            # 산정 불가(NULL) 값은 방향과 무관하게 뒤로,
            # 동률은 stock_code 오름차순(결정론적 페이지네이션)
            .order_by(order.nulls_last(), D.stock_code.asc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )

    def search(self, filters: PatternFilters, thresholds: PatternThresholds) -> PatternQueryResult:
        count_stmt = (
            select(func.count())
            .select_from(D)
            .join(StockMaster, StockMaster.stock_code == D.stock_code)
            .where(*self._where(filters, thresholds))
        )
        total = self._session.execute(count_stmt).scalar_one()
        rows = self._session.execute(self.search_statement(filters, thresholds)).mappings().all()
        items = [
            PatternRow(
                stock_code=r["stock_code"],
                name=r["name"],
                market=r["market"],
                status=r["status"],
                stage=r["stage"],
                conds={cid: r[cid] for cid in CONDITION_IDS},
                metrics={key: r[key] for key in METRIC_KEYS},
            )
            for r in rows
        ]
        return PatternQueryResult(items=items, total_count=int(total))
