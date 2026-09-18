"""`services/derivation_batch/compute.py` 순수 함수 단위테스트 (REQ-002).

DB/외부 의존성 없이 픽스처 값만으로 검증한다 — raw_internal.raw_ohlcv에
실제 데이터가 없는 현재 상태에서도 계산 로직 자체의 정확성을 독립적으로
확인할 수 있다(코디네이터 지시 대응, `unit-06-note.md` §3 참조).
"""

from decimal import Decimal

from services.derivation_batch.compute import (
    compute_ma_gap_pct,
    compute_return_pct,
    compute_volume_anomaly_score,
    rank_percentile,
)


def test_compute_return_pct_normal():
    assert compute_return_pct(Decimal("110"), Decimal("100")) == Decimal("10.0000")


def test_compute_return_pct_negative():
    assert compute_return_pct(Decimal("90"), Decimal("100")) == Decimal("-10.0000")


def test_compute_return_pct_no_previous_close_returns_none():
    assert compute_return_pct(Decimal("100"), None) is None


def test_compute_return_pct_zero_previous_close_returns_none():
    assert compute_return_pct(Decimal("100"), Decimal("0")) is None


def test_compute_ma_gap_pct_exact_window():
    # 최근 5일 종가(당일 포함, 내림차순): 110,100,100,100,100 -> MA5=102
    closes = [Decimal("110"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100")]
    result = compute_ma_gap_pct(closes, window=5)
    # (110-102)/102*100
    assert result == ((Decimal("110") - Decimal("102")) / Decimal("102") * 100).quantize(
        Decimal("0.0001")
    )


def test_compute_ma_gap_pct_insufficient_history_returns_none():
    closes = [Decimal("110"), Decimal("100")]
    assert compute_ma_gap_pct(closes, window=5) is None


def test_compute_ma_gap_pct_uses_only_window_slice():
    # window=3 이므로 앞 3개만 사용해야 한다(뒤 데이터는 무시).
    closes = [Decimal("100"), Decimal("100"), Decimal("100"), Decimal("999")]
    result = compute_ma_gap_pct(closes, window=3)
    assert result == Decimal("0.0000")


def test_compute_volume_anomaly_score_normal():
    baseline = [100] * 19 + [200]  # mean/stdev 계산용 20개
    score = compute_volume_anomaly_score(500, baseline, window=20)
    assert score is not None
    assert score > 0


def test_compute_volume_anomaly_score_insufficient_history_returns_none():
    assert compute_volume_anomaly_score(500, [100] * 19, window=20) is None


def test_compute_volume_anomaly_score_zero_stdev_returns_none():
    assert compute_volume_anomaly_score(500, [100] * 20, window=20) is None


def test_rank_percentile_empty_returns_empty():
    assert rank_percentile([], descending=True) == {}


def test_rank_percentile_descending_worked_example():
    # 03-system-design.md §3-2 worked example 형태 축소판:
    # 전체 4종목 중 1등(내림차순) -> 1/4*100 = 25.0
    pairs = [("A", Decimal("10")), ("B", Decimal("5")), ("C", Decimal("1")), ("D", Decimal("-2"))]
    result = rank_percentile(pairs, descending=True)
    assert result["A"] == Decimal("25.0")
    assert result["B"] == Decimal("50.0")
    assert result["C"] == Decimal("75.0")
    assert result["D"] == Decimal("100.0")


def test_rank_percentile_ascending_for_per_pbr_style_metrics():
    # PER/PBR처럼 "작을수록 상위"인 지표: 오름차순 순위.
    pairs = [("A", Decimal("20")), ("B", Decimal("5"))]
    result = rank_percentile(pairs, descending=False)
    assert result["B"] == Decimal("50.0")  # 가장 작은 값이 1등
    assert result["A"] == Decimal("100.0")


def test_rank_percentile_ties_use_standard_competition_ranking():
    # 동률(1,1,3) 표준경쟁순위: 공동 1등 두 종목은 같은 순위, 다음은 3위로 건너뜀.
    pairs = [("A", Decimal("10")), ("B", Decimal("10")), ("C", Decimal("5"))]
    result = rank_percentile(pairs, descending=True)
    assert result["A"] == result["B"] == Decimal("33.3")  # rank=1, 1/3*100
    assert result["C"] == Decimal("100.0")  # rank=3, 3/3*100
