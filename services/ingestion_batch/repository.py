"""`raw_internal.raw_ohlcv`/`raw_fundamentals` upsert (REQ-011, §3-2).

`scripts/load_calendar.py`의 upsert 패턴(ON CONFLICT DO UPDATE)을 그대로
따른다 — 같은 (stock_code, trade_date, market)에 대해 재실행(예: 장애 복구
후 재수집)해도 중복 오류 없이 최신 값으로 갱신되어야 한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from services.ingestion_batch.gov_data_client import RawFundamentalsRecord, RawOhlcvRecord
from services.ingestion_batch.models import RawFundamentals, RawOhlcv


def upsert_ohlcv(
    session: Session,
    records: list[RawOhlcvRecord],
    *,
    market: str,
    source_batch_id: uuid.UUID,
) -> int:
    affected = 0
    ingested_at = datetime.now(UTC)
    for record in records:
        stmt = pg_insert(RawOhlcv).values(
            stock_code=record.stock_code,
            trade_date=record.trade_date,
            market=market,
            open=record.open,
            high=record.high,
            low=record.low,
            close=record.close,
            volume=record.volume,
            trading_value=record.trading_value,
            ingested_at=ingested_at,
            source_batch_id=source_batch_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RawOhlcv.stock_code, RawOhlcv.trade_date, RawOhlcv.market],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "trading_value": stmt.excluded.trading_value,
                "ingested_at": stmt.excluded.ingested_at,
                "source_batch_id": stmt.excluded.source_batch_id,
            },
        )
        session.execute(stmt)
        affected += 1
    return affected


def upsert_fundamentals(
    session: Session,
    records: list[RawFundamentalsRecord],
    *,
    source_batch_id: uuid.UUID,
) -> int:
    affected = 0
    ingested_at = datetime.now(UTC)
    for record in records:
        stmt = pg_insert(RawFundamentals).values(
            stock_code=record.stock_code,
            trade_date=record.trade_date,
            per=record.per,
            pbr=record.pbr,
            market_cap=record.market_cap,
            ingested_at=ingested_at,
            source_batch_id=source_batch_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RawFundamentals.stock_code, RawFundamentals.trade_date],
            set_={
                "per": stmt.excluded.per,
                "pbr": stmt.excluded.pbr,
                "market_cap": stmt.excluded.market_cap,
                "ingested_at": stmt.excluded.ingested_at,
                "source_batch_id": stmt.excluded.source_batch_id,
            },
        )
        session.execute(stmt)
        affected += 1
    return affected
