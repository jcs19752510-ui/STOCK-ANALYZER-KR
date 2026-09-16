"""Derivation Batch DB 접근 계층 (REQ-002).

읽기: `public_serving.stock_master`(활성 종목 목록), `raw_internal.raw_ohlcv`
(종가/거래량 이력), `raw_internal.raw_fundamentals`(PER/PBR/시가총액 원문).
쓰기: `public_serving.derived_metrics_daily`, `public_serving.
current_published_batch`(검증 통과 시에만 포인터 갱신, §3-2/§5-3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from services.derivation_batch.raw_models import raw_fundamentals_table, raw_ohlcv_table
from shared.db_models.public_serving import CurrentPublishedBatch, DerivedMetricsDaily, StockMaster

# MA20(당일 포함 20일) + 거래량 이상치 기준선(당일 제외 직전 20일) 양쪽을
# 한 번의 쿼리로 충족하려면 최대 1(당일) + 20(MA20 나머지) + 20(기준선) = 41행이
# 필요하다(compute.py 참조).
OHLCV_WINDOW_SIZE = 41
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
    per_percentile: Decimal | None
    pbr_percentile: Decimal | None
    market_cap_percentile: Decimal | None


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
            per_percentile=row.per_percentile,
            pbr_percentile=row.pbr_percentile,
            market_cap_percentile=row.market_cap_percentile,
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
                "per_percentile": stmt.excluded.per_percentile,
                "pbr_percentile": stmt.excluded.pbr_percentile,
                "market_cap_percentile": stmt.excluded.market_cap_percentile,
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
    "OhlcvPoint",
    "fetch_active_stocks",
    "fetch_fundamentals_map",
    "fetch_ohlcv_window",
    "publish_current_batch",
    "upsert_derived_metrics",
]
