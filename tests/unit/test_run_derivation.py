"""services/derivation_batch/run_derivation.py 단위테스트 (REQ-002).

`resolve_target_trade_date()`는 `run_ingestion.py`와 동일한 패턴으로 DB
세션이 아니라 `CalendarLookup` 프로토콜만 받아 실 DB 없이 검증 가능하다.
`compute_stock_day_metrics`/`build_derivation_inputs`/`_validation_passed`도
순수 함수라 실 DB 없이 검증한다. DB 쓰기가 포함된 `run_once()` 종단간
검증은 PostgreSQL 전용 upsert 구문을 쓰므로(unit-01/02-note.md와 동일한
이유) 로컬 Docker PostgreSQL 수동 검증으로 보완한다(`unit-06-note.md` §3).
"""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from services.derivation_batch.repository import ActiveStock, FundamentalsRow, OhlcvPoint
from services.derivation_batch.run_derivation import (
    DerivationRunError,
    _validation_passed,
    build_derivation_inputs,
    compute_stock_day_metrics,
    resolve_target_trade_date,
)
from shared.calendar_service.last_trading_day import CalendarDataError
from shared.calendar_service.types import CalendarRow

KST = ZoneInfo("Asia/Seoul")


class FakeCalendar:
    def __init__(self, rows: dict[tuple[date, str], CalendarRow]):
        self._rows = rows

    def get(self, trade_date: date, market: str) -> CalendarRow | None:
        return self._rows.get((trade_date, market))


def _row(d: date, is_trading_day: bool, close: time | None = None) -> CalendarRow:
    return CalendarRow(
        trade_date=d,
        market="KRX",
        is_trading_day=is_trading_day,
        session_close_at=close,
        holiday_name=None if is_trading_day else "휴장",
        source="test",
    )


# --- resolve_target_trade_date (run_ingestion.py와 동일한 계약 검증) ---


def test_override_short_circuits_calendar_lookup():
    calendar = FakeCalendar({})
    result = resolve_target_trade_date(calendar, override=date(2026, 9, 1))
    assert result == date(2026, 9, 1)


def test_no_override_uses_calendar(monkeypatch):
    rows = {
        (date(2026, 9, 11), "KRX"): _row(date(2026, 9, 11), True, time(15, 30)),
        (date(2026, 9, 12), "KRX"): _row(date(2026, 9, 12), False),
        (date(2026, 9, 13), "KRX"): _row(date(2026, 9, 13), False),
        (date(2026, 9, 14), "KRX"): _row(date(2026, 9, 14), True, time(15, 30)),
    }
    calendar = FakeCalendar(rows)

    import services.derivation_batch.run_derivation as run_derivation_module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 8, 0, tzinfo=KST)

    monkeypatch.setattr(run_derivation_module, "datetime", _FixedDatetime)

    assert resolve_target_trade_date(calendar, override=None) == date(2026, 9, 11)


def test_calendar_gap_raises_derivation_run_error(monkeypatch):
    calendar = FakeCalendar({})

    import services.derivation_batch.run_derivation as run_derivation_module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 8, 0, tzinfo=KST)

    monkeypatch.setattr(run_derivation_module, "datetime", _FixedDatetime)

    with pytest.raises(DerivationRunError):
        resolve_target_trade_date(calendar, override=None)


def test_calendar_integrity_error_propagates(monkeypatch):
    rows = {(date(2026, 9, 14), "KRX"): _row(date(2026, 9, 14), True, None)}
    calendar = FakeCalendar(rows)

    import services.derivation_batch.run_derivation as run_derivation_module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 8, 0, tzinfo=KST)

    monkeypatch.setattr(run_derivation_module, "datetime", _FixedDatetime)

    with pytest.raises(CalendarDataError):
        resolve_target_trade_date(calendar, override=None)


# --- compute_stock_day_metrics ---

_STOCK = ActiveStock(stock_code="005930", market="KOSPI")
_TARGET = date(2026, 9, 14)


def _points(*rows: tuple[date, str, int]) -> list[OhlcvPoint]:
    """`rows`는 (trade_date, close, volume) — 호출자가 내림차순으로 전달해야 한다."""
    return [OhlcvPoint(trade_date=d, close=Decimal(c), volume=v) for d, c, v in rows]


def test_compute_stock_day_metrics_no_data_today_returns_none():
    # window[0]이 target_date보다 이전 날짜 -> 오늘 시세 자체가 없음(거래정지 등)
    window = _points((date(2026, 9, 11), "100", 1000))
    assert compute_stock_day_metrics(_STOCK, window, None, target_date=_TARGET) is None


def test_compute_stock_day_metrics_empty_window_returns_none():
    assert compute_stock_day_metrics(_STOCK, [], None, target_date=_TARGET) is None


def test_compute_stock_day_metrics_ipo_first_day_return_pct_none():
    window = _points((_TARGET, "100", 1000))
    result = compute_stock_day_metrics(_STOCK, window, None, target_date=_TARGET)
    assert result is not None
    assert result.return_pct is None  # 전일 종가 없음
    assert result.ma5_gap_pct is None  # 5일치도 없음
    assert result.per_raw is None  # fundamentals 없음


def test_compute_stock_day_metrics_with_fundamentals():
    window = _points((_TARGET, "110", 1000), (date(2026, 9, 11), "100", 900))
    fundamentals = FundamentalsRow(per=Decimal("15.5"), pbr=Decimal("1.2"), market_cap=1_000_000)
    result = compute_stock_day_metrics(_STOCK, window, fundamentals, target_date=_TARGET)
    assert result is not None
    assert result.return_pct == Decimal("10.0000")
    assert result.per_raw == Decimal("15.5")
    assert result.pbr_raw == Decimal("1.2")
    assert result.market_cap_raw_krw == 1_000_000


# --- build_derivation_inputs / _validation_passed ---


def test_build_derivation_inputs_computes_cross_sectional_percentiles():
    from services.derivation_batch.run_derivation import StockDayMetrics

    rows = [
        StockDayMetrics(
            stock_code="A",
            market="KOSPI",
            return_pct=Decimal("10"),
            ma5_gap_pct=None,
            ma20_gap_pct=None,
            volume_anomaly_score=None,
            per_raw=Decimal("5"),
            pbr_raw=None,
            market_cap_raw_krw=1000,
        ),
        StockDayMetrics(
            stock_code="B",
            market="KOSDAQ",
            return_pct=Decimal("-5"),
            ma5_gap_pct=None,
            ma20_gap_pct=None,
            volume_anomaly_score=None,
            per_raw=Decimal("20"),
            pbr_raw=None,
            market_cap_raw_krw=2000,
        ),
    ]
    inputs = build_derivation_inputs(rows, target_date=_TARGET)
    by_code = {i.stock_code: i for i in inputs}
    assert by_code["A"].return_rank_pct == Decimal("50.0")  # 2종목 중 등락률 1등
    assert by_code["B"].return_rank_pct == Decimal("100.0")
    assert by_code["A"].per_percentile == Decimal("50.0")  # PER 낮을수록 상위
    assert by_code["B"].per_percentile == Decimal("100.0")
    assert by_code["A"].market_cap_percentile == Decimal("100.0")  # 시총 클수록 상위
    assert by_code["B"].market_cap_percentile == Decimal("50.0")


def test_validation_passed_below_threshold():
    from services.derivation_batch.run_derivation import StockDayMetrics

    def _row_with_return(code, return_pct):
        return StockDayMetrics(
            stock_code=code,
            market="KOSPI",
            return_pct=return_pct,
            ma5_gap_pct=None,
            ma20_gap_pct=None,
            volume_anomaly_score=None,
            per_raw=None,
            pbr_raw=None,
            market_cap_raw_krw=None,
        )

    rows = [_row_with_return(str(i), Decimal("1")) for i in range(19)]
    rows.append(_row_with_return("19", None))  # 20건 중 1건 결측 = 5% 이하
    passed, missing = _validation_passed(rows)
    assert passed is True
    assert missing == 1


def test_validation_passed_all_missing_fails():
    from services.derivation_batch.run_derivation import StockDayMetrics

    rows = [
        StockDayMetrics(
            stock_code=str(i),
            market="KOSPI",
            return_pct=None,
            ma5_gap_pct=None,
            ma20_gap_pct=None,
            volume_anomaly_score=None,
            per_raw=None,
            pbr_raw=None,
            market_cap_raw_krw=None,
        )
        for i in range(5)
    ]
    passed, missing = _validation_passed(rows)
    assert passed is False
    assert missing == 5


def test_validation_passed_empty_rows_fails():
    passed, missing = _validation_passed([])
    assert passed is False
    assert missing == 0
