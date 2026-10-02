"""Derivation Batch 패턴 지표 통합 순수 로직 단위테스트 (REQ-030, 05-test-plan §5 D07·D08 일부).

DB 없이 `compute_stock_day_metrics`·`build_derivation_inputs`·`_validation_passed`가 패턴 지표를
통과시키되 **기존 지표·검증 결과는 바뀌지 않음**을 확인한다. DB가 필요한 항목(마이그레이션·권한·
멱등·발행)은 `tests/integration/test_pattern_derivation_db.py`.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from services.derivation_batch import repository
from services.derivation_batch.compute import compute_pattern_metrics
from services.derivation_batch.repository import ActiveStock, OhlcvPoint
from services.derivation_batch.run_derivation import (
    StockDayMetrics,
    _validation_passed,
    build_derivation_inputs,
    compute_stock_day_metrics,
)
from shared import pattern_params as P

TARGET = date(2026, 9, 30)
STOCK = ActiveStock(stock_code="T00001", market="KOSPI")
PATTERN_FIELDS = (
    "sideways_range_pct",
    "sideways_net_change_pct",
    "ma_convergence_pct",
    "volatility_contraction_ratio",
    "ma60_gap_pct",
    "ma20_vs_ma60_gap_pct",
    "ma60_slope_pct",
    "ma60_cross_up_days",
    "volume_ratio_5_60",
    "recent_surge_flag",
    "pattern_metrics_status",
)
EXISTING_FIELDS = (
    "return_pct",
    "ma5_gap_pct",
    "ma20_gap_pct",
    "volume_anomaly_score",
    "volume_raw",
    "per_raw",
    "pbr_raw",
    "market_cap_raw_krw",
)


def _window(n: int, seed: int = 1) -> list[OhlcvPoint]:
    rnd = random.Random(seed)
    out = []
    d = TARGET
    price = 10000.0
    series = []
    for _ in range(n):
        series.append(price)
        price *= 1 + rnd.uniform(-0.02, 0.02)
    for i in range(n):
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        out.append(
            OhlcvPoint(
                trade_date=d,
                close=Decimal(round(series[i])),
                volume=int(100000 * (1 + rnd.uniform(-0.2, 0.2))),
            )
        )
        d -= timedelta(days=1)
    return out  # 최신순


def test_window_size_is_pattern_window_and_covers_existing_41():
    assert repository.OHLCV_WINDOW_SIZE == P.PATTERN_WINDOW_ROWS == 100
    assert repository.OHLCV_WINDOW_SIZE >= 41  # 기존 지표(MA20 + 기준선 20)가 필요로 하던 행 수


def test_compute_stock_day_metrics_includes_pattern_metrics_matching_pure_function():
    window = _window(100)
    result = compute_stock_day_metrics(STOCK, window, None, target_date=TARGET)
    expected = compute_pattern_metrics([p.close for p in window], [p.volume for p in window])
    assert result is not None
    for f in PATTERN_FIELDS:
        assert getattr(result, f) == getattr(expected, f), f
    assert result.pattern_metrics_status == "OK"


def test_short_history_gives_insufficient_status_but_existing_metrics_still_computed():
    window = _window(30)
    result = compute_stock_day_metrics(STOCK, window, None, target_date=TARGET)
    assert result is not None
    assert result.pattern_metrics_status == "INSUFFICIENT_HISTORY"
    pattern_values = [getattr(result, f) for f in PATTERN_FIELDS if f != "pattern_metrics_status"]
    assert all(v is None for v in pattern_values)
    assert result.return_pct is not None and result.ma20_gap_pct is not None  # 기존 지표 정상


@pytest.mark.parametrize("seed", range(5))
def test_d08_existing_metrics_identical_for_41_and_100_row_windows(seed):
    """TC-D08(순수 부분): 윈도우를 41→100으로 늘려도 기존 지표는 같은 입력에서 같은 값."""
    full = _window(100, seed)
    old = compute_stock_day_metrics(STOCK, full[:41], None, target_date=TARGET)
    new = compute_stock_day_metrics(STOCK, full, None, target_date=TARGET)
    assert old is not None and new is not None
    for f in EXISTING_FIELDS:
        assert getattr(old, f) == getattr(new, f), f


def test_stock_day_metrics_old_style_construction_still_works_with_none_defaults():
    m = StockDayMetrics(
        stock_code="A",
        market="KOSPI",
        return_pct=Decimal("1"),
        ma5_gap_pct=None,
        ma20_gap_pct=None,
        volume_anomaly_score=None,
        per_raw=None,
        pbr_raw=None,
        market_cap_raw_krw=None,
    )
    assert m.pattern_metrics_status is None
    assert all(getattr(m, f) is None for f in PATTERN_FIELDS)


def test_build_derivation_inputs_passes_all_eleven_pattern_fields_through():
    rows = [
        compute_stock_day_metrics(STOCK, _window(100), None, target_date=TARGET),
        compute_stock_day_metrics(
            ActiveStock("T00002", "KOSDAQ"), _window(30, 2), None, target_date=TARGET
        ),
    ]
    inputs = build_derivation_inputs([r for r in rows if r], target_date=TARGET)
    by_code = {i.stock_code: i for i in inputs}
    for code, row in zip(("T00001", "T00002"), rows, strict=True):
        for f in PATTERN_FIELDS:
            assert getattr(by_code[code], f) == getattr(row, f), (code, f)


def test_d07_validation_passed_ignores_pattern_metrics():
    """패턴 지표가 전부 NULL(이력 부족)이어도 기존 검증(return_pct 결측 5%) 결과는 동일."""

    def mk(status, return_pct):
        return StockDayMetrics(
            stock_code="X",
            market="KOSPI",
            return_pct=return_pct,
            ma5_gap_pct=None,
            ma20_gap_pct=None,
            volume_anomaly_score=None,
            per_raw=None,
            pbr_raw=None,
            market_cap_raw_krw=None,
            pattern_metrics_status=status,
        )

    rows_ok = [mk("INSUFFICIENT_HISTORY", Decimal("1")) for _ in range(100)]
    assert _validation_passed(rows_ok) == (True, 0)
    rows_missing = [mk("OK", Decimal("1")) for _ in range(94)] + [mk("OK", None) for _ in range(6)]
    assert _validation_passed(rows_missing) == (False, 6)  # 6% > 5%: 패턴 상태와 무관하게 실패
