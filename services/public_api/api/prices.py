"""종목 일봉 시세 API (DEC-041, UNIT-20) — 종목 상세 차트·일자별 시세용(일 단위 종가 기준)."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.public_api.data_freshness import build_staleness_note, resolve_session_close_at
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.price_repository import (
    PriceRow,
    QuoteRepository,
    SqlQuoteRepository,
    SqlStockPriceRepository,
    StockPriceRepository,
)
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import DataFreshness, Envelope, Meta
from services.public_api.schemas.prices import PricePoint, QuoteItem, QuotesData, StockPricesData
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day
from shared.calendar_service.types import CalendarLookup, Market

router = APIRouter(tags=["prices"])

KST = ZoneInfo("Asia/Seoul")
PRICE_MARKET: Market = "KRX"
DEFAULT_DAYS = 120
MAX_DAYS = 260  # 약 1년 거래일. 차트 + 이동평균 워밍업을 포함해도 충분하다.


def get_price_repository(db: Session = Depends(get_db)) -> StockPriceRepository:
    return SqlStockPriceRepository(db)


def get_price_calendar_repository(db: Session = Depends(get_db)) -> CalendarLookup:
    return SqlCalendarRepository(db)


def _points(rows: list[PriceRow]) -> list[PricePoint]:
    points: list[PricePoint] = []
    prev_close: float | None = None
    for r in rows:
        close = float(r.close)
        change = None if prev_close is None else round(close - prev_close, 4)
        change_pct = (
            None if prev_close in (None, 0) else round((close - prev_close) / prev_close * 100, 2)
        )
        points.append(
            PricePoint(
                trade_date=r.trade_date,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=close,
                volume=int(r.volume),
                trading_value=int(r.trading_value),
                change=change,
                change_pct=change_pct,
            )
        )
        prev_close = close
    return points


@router.get("/stocks/{code}/prices", response_model=Envelope[StockPricesData])
def get_stock_prices(
    code: str,
    days: int = Query(DEFAULT_DAYS, ge=20, le=MAX_DAYS, description="최근 거래일 수(20~260)"),
    repository: StockPriceRepository = Depends(get_price_repository),
    calendar: CalendarLookup = Depends(get_price_calendar_repository),
) -> Envelope[StockPricesData]:
    stock = repository.get_stock(code)
    if stock is None:
        raise ApiError(
            status_code=404,
            code="STOCK_NOT_FOUND",
            message=f"종목코드 {code!r}를 찾을 수 없습니다.",
        )

    now = datetime.now(KST)
    rows = repository.get_prices(code, days)
    generated_at = datetime.now(KST)
    freshness = None
    if rows:
        try:
            expected = get_last_trading_day(PRICE_MARKET, now, calendar)
        except CalendarIntegrityError as exc:
            raise ApiError(
                status_code=503,
                code="SERVICE_UNAVAILABLE",
                message="캘린더 데이터 이상으로 데이터 신선도를 판단할 수 없습니다.",
            ) from exc
        if expected is None:
            raise ApiError(
                status_code=424,
                code="CALENDAR_NOT_CONFIRMED",
                message="휴장일 캘린더가 아직 갱신되지 않아 직전 거래일을 계산할 수 없습니다.",
            )
        resolved = rows[-1].trade_date
        freshness = DataFreshness(
            market=PRICE_MARKET,
            trade_date=resolved,
            session_close_at=resolve_session_close_at(
                calendar, PRICE_MARKET, trade_date=resolved, tzinfo=KST
            ),
            generated_at=generated_at,
            is_latest_trading_day=resolved == expected,
            expected_last_trading_day=expected,
            staleness_note=(
                None
                if resolved == expected
                else build_staleness_note(
                    calendar, PRICE_MARKET, resolved=resolved, expected=expected
                )
            ),
        )

    return Envelope[StockPricesData](
        meta=Meta(data_freshness=freshness, generated_at=generated_at),
        data=StockPricesData(
            stock_code=stock.stock_code,
            name=stock.name,
            market=stock.market,
            prices=_points(rows),
        ),
    )


MAX_QUOTE_CODES = 50
_CODE_PATTERN = re.compile(r"^[0-9A-Za-z]{6}$")


def get_quote_repository(db: Session = Depends(get_db)) -> QuoteRepository:
    return SqlQuoteRepository(db)


def _parse_codes(raw: str) -> list[str]:
    tokens = raw.split(",")
    if any(not _CODE_PATTERN.fullmatch(t) for t in tokens):
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message="codes는 6자리 종목코드를 쉼표로 구분한 값이어야 합니다.",
        )
    unique = list(dict.fromkeys(tokens))  # 중복 제거, 요청 순서 유지
    if len(unique) > MAX_QUOTE_CODES:
        raise ApiError(
            status_code=400,
            code="INVALID_PARAMETER",
            message=f"codes는 최대 {MAX_QUOTE_CODES}개까지 조회할 수 있습니다.",
        )
    return unique


@router.get("/stocks/quotes", response_model=Envelope[QuotesData])
def get_stock_quotes(
    codes: str = Query(..., description="종목코드(쉼표 구분, 최대 50개)"),
    repository: QuoteRepository = Depends(get_quote_repository),
) -> Envelope[QuotesData]:
    """목록 화면용 최신 종가·전일대비 요약(일 단위 종가 기준)."""
    wanted = _parse_codes(codes)
    by_code = {q.stock_code: q for q in repository.get_quotes(wanted)}
    items: list[QuoteItem] = []
    for code in wanted:
        q = by_code.get(code)
        if q is None:
            continue
        close = float(q.close)
        prev = None if q.prev_close is None else float(q.prev_close)
        items.append(
            QuoteItem(
                stock_code=code,
                trade_date=q.trade_date,
                close=close,
                change=None if prev is None else round(close - prev, 4),
                change_pct=None if not prev else round((close - prev) / prev * 100, 2),
            )
        )
    return Envelope[QuotesData](
        meta=Meta(generated_at=datetime.now(KST)), data=QuotesData(quotes=items)
    )
