"""Derivation Batch DB 접근 계층 (REQ-002).

읽기: `public_serving.stock_master`(활성 종목 목록), `raw_internal.raw_ohlcv`
(종가/거래량 이력), `raw_internal.raw_fundamentals`(PER/PBR/시가총액 원문).
쓰기: `public_serving.derived_metrics_daily`, `public_serving.
current_published_batch`(검증 통과 시에만 포인터 갱신, §3-2/§5-3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from services.derivation_batch.raw_models import (
    raw_corp_financials_table,
    raw_fundamentals_table,
    raw_ohlcv_table,
)
from shared.db_models.public_serving import (
    CurrentPublishedBatch,
    DerivedMetricsDaily,
    MarketSummaryDaily,
    StockMaster,
)
from shared.pattern_params import PATTERN_WINDOW_ROWS

# 기존 지표(MA20 당일 포함 20일 + 거래량 이상치 기준선 직전 20일)는 최대 41행이면 충분했다.
# 패턴 지표(REQ-030)는 최소 80행이 필요하므로 여유(20행)를 더해 `PATTERN_WINDOW_ROWS`(100)행을
# 조회한다(설계서 02 §3-2). 기존 지표 함수는 앞쪽 필요한 행만 슬라이스해 쓰므로 값이 바뀌지
# 않는다(TC-D08).
OHLCV_WINDOW_SIZE = PATTERN_WINDOW_ROWS
VOLUME_BASELINE_WINDOW = 20


@dataclass(frozen=True)
class ActiveStock:
    stock_code: str
    market: str


@dataclass(frozen=True)
class OhlcvPoint:
    trade_date: date
    close: Decimal
    volume: int


@dataclass(frozen=True)
class FundamentalsRow:
    per: Decimal | None
    pbr: Decimal | None
    market_cap: int | None


@dataclass(frozen=True)
class CorpFinancialsRow:
    net_income: Decimal | None
    equity: Decimal | None


def fetch_active_stocks(session: Session) -> list[ActiveStock]:
    stmt = select(StockMaster.stock_code, StockMaster.market).where(
        StockMaster.is_active.is_(True)
    )
    rows = session.execute(stmt).all()
    return [ActiveStock(stock_code=row.stock_code, market=row.market) for row in rows]


def fetch_ohlcv_window(
    session: Session, stock_code: str, *, market: str, upto_date: date
) -> list[OhlcvPoint]:
    """`upto_date` 이하 최근 `OHLCV_WINDOW_SIZE`행을 최신순(내림차순)으로 반환."""
    stmt = (
        select(raw_ohlcv_table.c.trade_date, raw_ohlcv_table.c.close, raw_ohlcv_table.c.volume)
        .where(
            raw_ohlcv_table.c.stock_code == stock_code,
            raw_ohlcv_table.c.market == market,
            raw_ohlcv_table.c.trade_date <= upto_date,
        )
        .order_by(raw_ohlcv_table.c.trade_date.desc())
        .limit(OHLCV_WINDOW_SIZE)
    )
    rows = session.execute(stmt).all()
    return [OhlcvPoint(trade_date=r.trade_date, close=r.close, volume=r.volume) for r in rows]


def raw_ohlcv_has_rows(session: Session, *, market: str, on: date) -> bool:
    """그 거래일의 원본 시세가 한 줄이라도 있는가(날짜 구멍 검사용)."""
    stmt = (
        select(raw_ohlcv_table.c.stock_code)
        .where(raw_ohlcv_table.c.market == market, raw_ohlcv_table.c.trade_date == on)
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def raw_ohlcv_has_rows_before(session: Session, *, market: str, before: date) -> bool:
    """그 날짜보다 이전의 원본 시세가 있는가(DB에 이력이 시작된 뒤인지 판단)."""
    stmt = (
        select(raw_ohlcv_table.c.stock_code)
        .where(raw_ohlcv_table.c.market == market, raw_ohlcv_table.c.trade_date < before)
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def fetch_fundamentals_map(session: Session, trade_date: date) -> dict[str, FundamentalsRow]:
    stmt = select(
        raw_fundamentals_table.c.stock_code,
        raw_fundamentals_table.c.per,
        raw_fundamentals_table.c.pbr,
        raw_fundamentals_table.c.market_cap,
    ).where(raw_fundamentals_table.c.trade_date == trade_date)
    rows = session.execute(stmt).all()
    return {
        row.stock_code: FundamentalsRow(per=row.per, pbr=row.pbr, market_cap=row.market_cap)
        for row in rows
    }


def fetch_corp_financials_map(session: Session) -> dict[str, CorpFinancialsRow]:
    """DART 재무 원문(종목당 1행). PER/PBR이 비는 이유(적자 vs 데이터 없음)를 가르는 데만 쓴다."""
    stmt = select(
        raw_corp_financials_table.c.stock_code,
        raw_corp_financials_table.c.net_income,
        raw_corp_financials_table.c.equity,
    )
    return {
        row.stock_code: CorpFinancialsRow(net_income=row.net_income, equity=row.equity)
        for row in session.execute(stmt).all()
    }


@dataclass(frozen=True)
class DerivedMetricsInput:
    stock_code: str
    market: str
    trade_date: date
    return_pct: Decimal | None
    return_rank_pct: Decimal | None
    ma5_gap_pct: Decimal | None
    ma20_gap_pct: Decimal | None
    volume_anomaly_score: Decimal | None
    per_raw: Decimal | None
    pbr_raw: Decimal | None
    market_cap_raw_krw: int | None
    volume_raw: int | None = None
    per_percentile: Decimal | None = None
    pbr_percentile: Decimal | None = None
    market_cap_percentile: Decimal | None = None
    # 패턴 지표(REQ-030, 0011). 산정 불가면 status만 채워지고 나머지는 None.
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
    pattern_metrics_status: str | None = None
    per_unavailable_reason: str | None = None
    pbr_unavailable_reason: str | None = None


def upsert_derived_metrics(
    session: Session, rows: list[DerivedMetricsInput], *, batch_run_id: uuid.UUID
) -> int:
    affected = 0
    computed_at = datetime.now()
    for row in rows:
        stmt = pg_insert(DerivedMetricsDaily).values(
            stock_code=row.stock_code,
            trade_date=row.trade_date,
            market=row.market,
            return_pct=row.return_pct,
            return_rank_pct=row.return_rank_pct,
            ma5_gap_pct=row.ma5_gap_pct,
            ma20_gap_pct=row.ma20_gap_pct,
            volume_anomaly_score=row.volume_anomaly_score,
            per_raw=row.per_raw,
            pbr_raw=row.pbr_raw,
            market_cap_raw_krw=row.market_cap_raw_krw,
            volume_raw=row.volume_raw,
            per_percentile=row.per_percentile,
            pbr_percentile=row.pbr_percentile,
            market_cap_percentile=row.market_cap_percentile,
            sideways_range_pct=row.sideways_range_pct,
            sideways_net_change_pct=row.sideways_net_change_pct,
            ma_convergence_pct=row.ma_convergence_pct,
            volatility_contraction_ratio=row.volatility_contraction_ratio,
            ma60_gap_pct=row.ma60_gap_pct,
            ma20_vs_ma60_gap_pct=row.ma20_vs_ma60_gap_pct,
            ma60_slope_pct=row.ma60_slope_pct,
            ma60_cross_up_days=row.ma60_cross_up_days,
            volume_ratio_5_60=row.volume_ratio_5_60,
            recent_surge_flag=row.recent_surge_flag,
            pattern_metrics_status=row.pattern_metrics_status,
            per_unavailable_reason=row.per_unavailable_reason,
            pbr_unavailable_reason=row.pbr_unavailable_reason,
            computed_at=computed_at,
            batch_run_id=batch_run_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                DerivedMetricsDaily.stock_code,
                DerivedMetricsDaily.trade_date,
                DerivedMetricsDaily.market,
            ],
            set_={
                "return_pct": stmt.excluded.return_pct,
                "return_rank_pct": stmt.excluded.return_rank_pct,
                "ma5_gap_pct": stmt.excluded.ma5_gap_pct,
                "ma20_gap_pct": stmt.excluded.ma20_gap_pct,
                "volume_anomaly_score": stmt.excluded.volume_anomaly_score,
                "per_raw": stmt.excluded.per_raw,
                "pbr_raw": stmt.excluded.pbr_raw,
                "market_cap_raw_krw": stmt.excluded.market_cap_raw_krw,
                "volume_raw": stmt.excluded.volume_raw,
                "per_percentile": stmt.excluded.per_percentile,
                "pbr_percentile": stmt.excluded.pbr_percentile,
                "market_cap_percentile": stmt.excluded.market_cap_percentile,
                "sideways_range_pct": stmt.excluded.sideways_range_pct,
                "sideways_net_change_pct": stmt.excluded.sideways_net_change_pct,
                "ma_convergence_pct": stmt.excluded.ma_convergence_pct,
                "volatility_contraction_ratio": stmt.excluded.volatility_contraction_ratio,
                "ma60_gap_pct": stmt.excluded.ma60_gap_pct,
                "ma20_vs_ma60_gap_pct": stmt.excluded.ma20_vs_ma60_gap_pct,
                "ma60_slope_pct": stmt.excluded.ma60_slope_pct,
                "ma60_cross_up_days": stmt.excluded.ma60_cross_up_days,
                "volume_ratio_5_60": stmt.excluded.volume_ratio_5_60,
                "recent_surge_flag": stmt.excluded.recent_surge_flag,
                "pattern_metrics_status": stmt.excluded.pattern_metrics_status,
                "per_unavailable_reason": stmt.excluded.per_unavailable_reason,
                "pbr_unavailable_reason": stmt.excluded.pbr_unavailable_reason,
                "computed_at": stmt.excluded.computed_at,
                "batch_run_id": stmt.excluded.batch_run_id,
            },
        )
        session.execute(stmt)
        affected += 1
    return affected


def fetch_trading_values(
    session: Session, *, market: str, trade_date: date
) -> dict[str, int]:
    """REQ-004용 종목별 거래대금(원본, `raw_internal.raw_ohlcv.trading_value`) 조회.

    `market`은 거래소 세션 구분(KRX/NXT, §3-1-1) — `fetch_ohlcv_window()`와
    동일한 축. 이 값은 `market_summary_daily.total_trading_value_krw`/
    `top_sectors_by_value` 집계에만 쓰이고 API 응답에 원문 그대로 노출되지
    않는다(§4-3 데이터 가공 원칙 — 요약 통계로만 가공되어 나간다).
    """
    stmt = select(raw_ohlcv_table.c.stock_code, raw_ohlcv_table.c.trading_value).where(
        raw_ohlcv_table.c.market == market,
        raw_ohlcv_table.c.trade_date == trade_date,
    )
    rows = session.execute(stmt).all()
    return {row.stock_code: row.trading_value for row in rows}


def fetch_sector_map(session: Session) -> dict[str, str | None]:
    """REQ-004 업종별 거래대금 상위 집계용 `stock_master.sector` 조회.

    `sector` 출처가 아직 확정되지 않아(03-system-design.md §8-2 항목8)
    현재는 대부분/전부 `None`일 수 있다 — 값을 지어내지 않고 그대로 반환한다.
    """
    stmt = select(StockMaster.stock_code, StockMaster.sector)
    rows = session.execute(stmt).all()
    return {row.stock_code: row.sector for row in rows}


@dataclass(frozen=True)
class MarketSummaryUpsertInput:
    trade_date: date
    market: str
    advancers_count: int
    decliners_count: int
    unchanged_count: int
    top_sectors_by_value: list[dict[str, object]]
    total_trading_value_krw: int


def upsert_market_summary(
    session: Session, rows: list[MarketSummaryUpsertInput], *, batch_run_id: uuid.UUID
) -> int:
    """`market_summary_daily`(REQ-004)에 KOSPI/KOSDAQ/ALL 3개 행을 upsert한다.

    `derived_metrics_daily`와 동일하게, `validation_passed` 여부와 무관하게
    항상 기록한다 — 실제 서빙 여부는 `current_published_batch` 포인터가
    별도로 결정한다(§3-2/§5-3).
    """
    affected = 0
    computed_at = datetime.now()
    for row in rows:
        stmt = pg_insert(MarketSummaryDaily).values(
            trade_date=row.trade_date,
            market=row.market,
            advancers_count=row.advancers_count,
            decliners_count=row.decliners_count,
            unchanged_count=row.unchanged_count,
            top_sectors_by_value=row.top_sectors_by_value,
            total_trading_value_krw=row.total_trading_value_krw,
            computed_at=computed_at,
            batch_run_id=batch_run_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarketSummaryDaily.trade_date, MarketSummaryDaily.market],
            set_={
                "advancers_count": stmt.excluded.advancers_count,
                "decliners_count": stmt.excluded.decliners_count,
                "unchanged_count": stmt.excluded.unchanged_count,
                "top_sectors_by_value": stmt.excluded.top_sectors_by_value,
                "total_trading_value_krw": stmt.excluded.total_trading_value_krw,
                "computed_at": stmt.excluded.computed_at,
                "batch_run_id": stmt.excluded.batch_run_id,
            },
        )
        session.execute(stmt)
        affected += 1
    return affected


def publish_current_batch(
    session: Session, *, market: str, trade_date: date, batch_run_id: uuid.UUID
) -> None:
    """검증 통과(validation_passed=True)한 배치만 이 함수를 호출해야 한다(§3-2/§5-3)."""
    stmt = pg_insert(CurrentPublishedBatch).values(
        market=market,
        trade_date=trade_date,
        batch_run_id=batch_run_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CurrentPublishedBatch.market],
        set_={
            "trade_date": stmt.excluded.trade_date,
            "batch_run_id": stmt.excluded.batch_run_id,
            "published_at": stmt.excluded.published_at,
        },
    )
    session.execute(stmt)


__all__ = [
    "OHLCV_WINDOW_SIZE",
    "VOLUME_BASELINE_WINDOW",
    "ActiveStock",
    "DerivedMetricsInput",
    "FundamentalsRow",
    "MarketSummaryUpsertInput",
    "OhlcvPoint",
    "fetch_active_stocks",
    "fetch_fundamentals_map",
    "raw_ohlcv_has_rows",
    "raw_ohlcv_has_rows_before",
    "fetch_ohlcv_window",
    "fetch_sector_map",
    "fetch_trading_values",
    "publish_current_batch",
    "upsert_derived_metrics",
    "upsert_market_summary",
]


# 공개 일봉 보존 기간(달력일). 차트(최대 약 1년)에 충분하고 테이블이 무한히 자라지 않게 한다.
DAILY_PRICES_RETENTION_DAYS = 400


def sync_daily_prices(session: Session, *, market: str, upto_date: date) -> int:
    """`raw_ohlcv`(해당 시장 세션)의 최근 일봉을 `public_serving.daily_prices`로 복사한다(upsert).

    DEC-041: 종목 상세 차트용 공개 복사본. 같은 값이면 변화 없음(멱등)이고, 원본이 정정되면
    덮어쓴다. 보존 기간 밖 일자와 다른 세션(NXT)은 복사하지 않는다. 반환: 처리 행 수.
    """
    result = session.execute(
        text(
            "INSERT INTO public_serving.daily_prices"
            " (stock_code, trade_date, open, high, low, close, volume, trading_value)"
            " SELECT stock_code, trade_date, open, high, low, close, volume, trading_value"
            " FROM raw_internal.raw_ohlcv"
            " WHERE market = CAST(:market AS reference.market_session)"
            "   AND trade_date <= :upto AND trade_date > :floor"
            " ON CONFLICT (stock_code, trade_date) DO UPDATE SET"
            "   open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,"
            "   close = EXCLUDED.close, volume = EXCLUDED.volume,"
            "   trading_value = EXCLUDED.trading_value, updated_at = now()"
        ),
        {
            "market": market,
            "upto": upto_date,
            "floor": upto_date - timedelta(days=DAILY_PRICES_RETENTION_DAYS),
        },
    )
    return result.rowcount or 0
