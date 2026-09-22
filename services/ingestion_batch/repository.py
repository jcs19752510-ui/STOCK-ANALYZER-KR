"""`raw_internal.raw_ohlcv`/`raw_fundamentals` upsert (REQ-011, §3-2).

`scripts/load_calendar.py`의 upsert 패턴(ON CONFLICT DO UPDATE)을 그대로
따른다 — 같은 (stock_code, trade_date, market)에 대해 재실행(예: 장애 복구
후 재수집)해도 중복 오류 없이 최신 값으로 갱신되어야 한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from services.ingestion_batch.dart_client import CorpFinancialsRecord
from services.ingestion_batch.gov_data_client import RawFundamentalsRecord, RawOhlcvRecord
from services.ingestion_batch.models import RawCorpFinancials, RawFundamentals, RawOhlcv
from shared.db_models.public_serving import StockMaster


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


def upsert_corp_financials(
    session: Session,
    records: list[tuple[str, CorpFinancialsRecord]],
    *,
    source_batch_id: uuid.UUID | None,
) -> int:
    """DART 재무 원문(`raw_corp_financials`)을 (stock_code) 단일 키로 upsert한다.

    `raw_fundamentals`(stock_code, trade_date 복합키)와 달리 재무제표는
    분기/연도 단위라 "가장 최근 확인된 값"만 유지한다(0010 리비전 참조).
    `records`는 (stock_code, CorpFinancialsRecord) 쌍 — DART corp_code는
    있지만 이 프로젝트의 stock_code(6자리)와는 별개 식별자라 호출자가
    corpCode 매핑으로 알아낸 stock_code를 함께 넘긴다.
    """
    affected = 0
    ingested_at = datetime.now(UTC)
    for stock_code, record in records:
        stmt = pg_insert(RawCorpFinancials).values(
            stock_code=stock_code,
            corp_code=record.corp_code,
            bsns_year=record.bsns_year,
            reprt_code=record.reprt_code,
            fs_div=record.fs_div,
            net_income=record.net_income,
            equity=record.equity,
            ingested_at=ingested_at,
            source_batch_id=source_batch_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RawCorpFinancials.stock_code],
            set_={
                "corp_code": stmt.excluded.corp_code,
                "bsns_year": stmt.excluded.bsns_year,
                "reprt_code": stmt.excluded.reprt_code,
                "fs_div": stmt.excluded.fs_div,
                "net_income": stmt.excluded.net_income,
                "equity": stmt.excluded.equity,
                "ingested_at": stmt.excluded.ingested_at,
                "source_batch_id": stmt.excluded.source_batch_id,
            },
        )
        session.execute(stmt)
        affected += 1
    return affected


def compute_per_pbr(
    market_cap: int, *, net_income: Decimal | None, equity: Decimal | None
) -> tuple[Decimal | None, Decimal | None]:
    """PER=시가총액/당기순이익, PBR=시가총액/자본총계.

    분모가 없거나 0 이하(적자기업, 완전자본잠식)이면 그 비율만 None —
    화면 "PER 산정 불가(적자기업 등)" 표시와 일치시킨다(음수/0으로 나눈
    의미 없는 값을 억지로 보여주지 않는다). DB 세션 없이 검증 가능하도록
    `apply_dart_valuation()`에서 분리했다(test_repository.py 참조).
    """
    per = Decimal(market_cap) / net_income if net_income is not None and net_income > 0 else None
    pbr = Decimal(market_cap) / equity if equity is not None and equity > 0 else None
    return per, pbr


@dataclass(frozen=True)
class ValuationUpdateResult:
    updated: int
    skipped_no_financials: int


def apply_dart_valuation(
    session: Session, *, trade_date: date, source_batch_id: uuid.UUID
) -> ValuationUpdateResult:
    """당일 `raw_fundamentals.market_cap`과 `raw_corp_financials`를 조합해
    PER/PBR을 계산하고 `raw_fundamentals.per`/`.pbr`에 반영한다.

    PER = 시가총액 / 당기순이익(지배지분 우선), PBR = 시가총액 / 자본총계(지배지분
    우선) — 분모가 0 이하(적자기업, 완전자본잠식)이면 그 비율만 None으로
    둔다(화면 "PER 산정 불가(적자기업 등)" 표시, 억지로 음수/0 값을 보여주지
    않는다). `derivation_batch`는 이 값을 그대로 읽어가므로(raw_models.py
    `raw_fundamentals_table.c.per/.pbr`) 이 함수 밖에서는 아무것도 바뀌지 않는다.
    """
    fundamentals_rows = session.execute(
        select(RawFundamentals.stock_code, RawFundamentals.market_cap).where(
            RawFundamentals.trade_date == trade_date,
            RawFundamentals.market_cap.is_not(None),
        )
    ).all()
    if not fundamentals_rows:
        return ValuationUpdateResult(updated=0, skipped_no_financials=0)

    market_cap_by_stock = {row.stock_code: row.market_cap for row in fundamentals_rows}

    financials_rows = session.execute(
        select(
            RawCorpFinancials.stock_code,
            RawCorpFinancials.net_income,
            RawCorpFinancials.equity,
        ).where(RawCorpFinancials.stock_code.in_(market_cap_by_stock.keys()))
    ).all()

    updates: list[RawFundamentalsRecord] = []
    for row in financials_rows:
        market_cap = market_cap_by_stock[row.stock_code]
        per, pbr = compute_per_pbr(market_cap, net_income=row.net_income, equity=row.equity)
        updates.append(
            RawFundamentalsRecord(
                stock_code=row.stock_code,
                trade_date=trade_date,
                per=per,
                pbr=pbr,
                market_cap=market_cap,
            )
        )

    if updates:
        upsert_fundamentals(session, updates, source_batch_id=source_batch_id)

    skipped = len(market_cap_by_stock) - len(updates)
    return ValuationUpdateResult(updated=len(updates), skipped_no_financials=skipped)


def upsert_stock_sector(session: Session, sector_by_stock_code: dict[str, str]) -> int:
    """`stock_master.sector`만 갱신한다(DART 업종코드->업종명 조회 결과).

    `scripts/seed_stock_master.py`의 `upsert_stock_master()`는 sector를
    SET 절에서 의도적으로 제외한다(그 스크립트 docstring 참조 — 다른 출처가
    채울 값을 재시드가 덮어쓰지 않도록). 이 함수가 바로 그 "다른 출처"다.
    이미 `stock_master`에 존재하는 종목만 갱신 대상이므로(DART corp_code
    매핑이 상장 종목 전체를 보장하지 않음) INSERT는 하지 않고 UPDATE만
    수행한다 — 존재하지 않는 종목코드로 새 행을 만들면 시장구분(market) 등
    필수 컬럼을 알 수 없는 상태로 남기 때문이다.
    """
    affected = 0
    for stock_code, sector in sector_by_stock_code.items():
        result = session.execute(
            StockMaster.__table__.update()
            .where(StockMaster.stock_code == stock_code)
            .values(sector=sector, updated_at=datetime.now(UTC))
        )
        affected += result.rowcount
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
