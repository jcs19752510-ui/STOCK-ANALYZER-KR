"""패턴 지표 순수 함수 단위테스트 (REQ-030, 05-test-plan §3 TC-U01~U16·U40~U42).

`services/derivation_batch/compute.py`의 `compute_pattern_metrics`를 DB 없이 검증한다.
기준 구현(`docs/pattern-screening/prototype/pattern_rules_reference.py`)을 **오라클**로 불러와
합성 시계열 300건에서 11개 필드를 교차 대조한다(TC-U40). 손계산 기대값(U01·U02)은 설계서
정의를 직접 풀어 쓴 값이며 오라클 출력과도 일치해야 한다.

입력 규약: `closes`/`volumes`는 **최신순(내림차순)**, 0번 원소가 대상 거래일(T)이다.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from services.derivation_batch.compute import PatternMetrics, compute_pattern_metrics
from shared import pattern_params as P

ORACLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "pattern-screening"
    / "prototype"
    / "pattern_rules_reference.py"
)
_spec = importlib.util.spec_from_file_location("pattern_rules_reference", ORACLE_PATH)
oracle = importlib.util.module_from_spec(_spec)
sys.modules["pattern_rules_reference"] = oracle  # dataclass(from __future__ annotations) 요구
_spec.loader.exec_module(oracle)  # type: ignore[union-attr]

NUMERIC_FIELDS = (
    "sideways_range_pct",
    "sideways_net_change_pct",
    "ma_convergence_pct",
    "volatility_contraction_ratio",
    "ma60_gap_pct",
    "ma20_vs_ma60_gap_pct",
    "ma60_slope_pct",
    "volume_ratio_5_60",
)
ALL_FIELDS = (*NUMERIC_FIELDS, "ma60_cross_up_days", "recent_surge_flag", "pattern_metrics_status")
TOL = 1e-3


def D(values):
    return [Decimal(str(v)) for v in values]


def run(closes, volumes) -> PatternMetrics:
    return compute_pattern_metrics(D(closes), [int(v) for v in volumes])


def flat(n=100, close=100, volume=1000):
    return [close] * n, [volume] * n


def assert_matches_oracle(closes, volumes):
    """Decimal 구현과 float 오라클이 11개 필드·상태에서 허용오차 내 일치."""
    c_dec = D(closes)
    c_f = [float(x) for x in c_dec]  # 같은 값으로 비교(문자열→Decimal→float)
    got = compute_pattern_metrics(c_dec, [int(v) for v in volumes])
    exp = oracle.compute_pattern_metrics(c_f, [float(v) for v in volumes])
    assert got.pattern_metrics_status == exp["pattern_metrics_status"]
    for f in NUMERIC_FIELDS:
        g, e = getattr(got, f), exp[f]
        if e is None:
            assert g is None, f
        else:
            assert g is not None, f
            assert abs(float(g) - e) <= TOL, (f, g, e)
    assert got.ma60_cross_up_days == exp["ma60_cross_up_days"]
    assert got.recent_surge_flag == exp["recent_surge_flag"]


# ── 파라미터가 설계서·오라클과 같은 값인지(드리프트 방지) ──────────────────────────
def test_params_match_design_and_oracle():
    assert P.PATTERN_LOOKBACK_DAYS == oracle.LOOKBACK_DAYS == 80
    assert P.PATTERN_MIN_ROWS == oracle.MIN_ROWS == 80
    assert P.PATTERN_WINDOW_ROWS == 100
    assert P.MA60_WINDOW == oracle.MA60_WINDOW == 60
    assert P.MA60_SLOPE_DAYS == oracle.MA60_SLOPE_DAYS == 10
    assert P.CROSS_LOOKBACK_DAYS == oracle.CROSS_LOOKBACK_DAYS == 10
    assert (P.VOL_SHORT, P.VOL_LONG) == (oracle.VOL_SHORT, oracle.VOL_LONG) == (10, 60)
    assert (P.VR_SHORT, P.VR_LONG) == (oracle.VR_SHORT, oracle.VR_LONG) == (5, 60)
    assert P.SURGE_LOOKBACK_DAYS == oracle.SURGE_LOOKBACK_DAYS == 20
    assert float(P.SURGE_RETURN_PCT) == oracle.SURGE_RETURN_PCT == 10.0
    assert float(P.SURGE_VOLUME_MULT) == oracle.SURGE_VOLUME_MULT == 3.0
    assert float(P.PRICE_JUMP_LIMIT_PCT) == oracle.PRICE_JUMP_LIMIT_PCT == 31.0
    assert P.PATTERN_STATUS_OK == "OK"
    assert P.PATTERN_STATUS_INSUFFICIENT_HISTORY == "INSUFFICIENT_HISTORY"
    assert P.PATTERN_STATUS_SUSPECT_PRICE_JUMP == "SUSPECT_PRICE_JUMP"


def test_required_rows_do_not_exceed_min_rows():
    """설계서 §3-2 필요 행 수 검산: 어떤 계산도 PATTERN_MIN_ROWS(80)행을 넘겨 읽지 않는다."""
    need = {
        "ma60_cross_detect": P.MA60_WINDOW + P.CROSS_LOOKBACK_DAYS,  # 70
        "ret_std_60": P.VOL_LONG + 1,  # 61
        "surge": 1 + P.SURGE_LOOKBACK_DAYS + P.SURGE_BASELINE_DAYS,  # 41
        "sideways": P.PATTERN_LOOKBACK_DAYS,  # 80
    }
    assert max(need.values()) == P.PATTERN_MIN_ROWS


# ── U01: 완전 평탄(손계산) ────────────────────────────────────────────────────
def test_u01_flat_series_hand_calculated():
    r = run(*flat())
    assert r.pattern_metrics_status == "OK"
    assert r.sideways_range_pct == 0
    assert r.sideways_net_change_pct == 0
    assert r.ma_convergence_pct == 0
    assert r.ma60_gap_pct == 0
    assert r.ma20_vs_ma60_gap_pct == 0
    assert r.ma60_slope_pct == 0
    assert r.ma60_cross_up_days is None
    assert r.volume_ratio_5_60 == Decimal("1.0000")
    assert r.recent_surge_flag is False
    assert r.volatility_contraction_ratio is None  # 60일 수익률 표준편차 0


# ── U02: 선형 상승(손계산) ────────────────────────────────────────────────────
def test_u02_linear_rise_hand_calculated():
    closes = [200 - i for i in range(100)]
    r = run(closes, [1000] * 100)
    q = Decimal("0.001")
    assert abs(r.sideways_range_pct - Decimal("49.2212")) <= q  # 79/160.5
    assert abs(r.sideways_net_change_pct - Decimal("65.2893")) <= q  # 79/121
    assert abs(r.ma_convergence_pct - Decimal("3.9370")) <= q  # MA5=198, MA20=190.5
    assert abs(r.ma60_gap_pct - Decimal("17.3021")) <= q  # MA60=170.5
    assert abs(r.ma20_vs_ma60_gap_pct - Decimal("11.7302")) <= q
    assert abs(r.ma60_slope_pct - Decimal("6.2305")) <= q  # MA60(T-10)=160.5
    assert r.volume_ratio_5_60 == Decimal("1.0000")
    assert r.ma60_cross_up_days is None
    assert r.recent_surge_flag is False
    assert_matches_oracle(closes, [1000] * 100)  # 변동성 수축비 등 손계산 외 필드는 오라클로


# ── U03: 행 수 경계 ──────────────────────────────────────────────────────────
def test_u03_row_count_boundary_79_vs_80():
    r79 = run(*flat(79))
    assert r79.pattern_metrics_status == "INSUFFICIENT_HISTORY"
    assert all(getattr(r79, f) is None for f in ALL_FIELDS if f != "pattern_metrics_status")
    assert run(*flat(80)).pattern_metrics_status == "OK"


def test_u03_volumes_shorter_than_closes_is_insufficient():
    r = compute_pattern_metrics(D([100] * 100), [1000] * 79)
    assert r.pattern_metrics_status == "INSUFFICIENT_HISTORY"


# ── U04: 단절 경계 ±31.0 / 31.1 ──────────────────────────────────────────────
@pytest.mark.parametrize(
    ("jump_close", "status"), [(131, "OK"), (Decimal("131.1"), "SUSPECT_PRICE_JUMP")]
)
def test_u04_price_jump_boundary(jump_close, status):
    closes, volumes = flat(100)
    closes[10] = jump_close  # closes[11]=100 → 일 변동 +31.0% / +31.1%
    r = run(closes, volumes)
    assert r.pattern_metrics_status == status
    if status != "OK":
        assert all(getattr(r, f) is None for f in ALL_FIELDS if f != "pattern_metrics_status")


def test_u04_negative_jump_is_also_detected():
    closes, volumes = flat(100)
    closes[10] = 50  # 전일(과거) 100 → -50%
    assert run(closes, volumes).pattern_metrics_status == "SUSPECT_PRICE_JUMP"


def test_u04_jump_outside_lookback_is_ignored():
    closes, volumes = flat(130)
    closes[85] = 150  # 80행 구간 밖
    assert run(closes, volumes).pattern_metrics_status == "OK"


# ── U05: 종가 0 이하 ─────────────────────────────────────────────────────────
def test_u05_non_positive_close_in_window_is_suspect_without_exception():
    closes, volumes = flat(100)
    closes[50] = 0
    assert run(closes, volumes).pattern_metrics_status == "SUSPECT_PRICE_JUMP"
    closes[50] = -5
    assert run(closes, volumes).pattern_metrics_status == "SUSPECT_PRICE_JUMP"


# ── U06/U07: 분모 0 ──────────────────────────────────────────────────────────
def test_u06_zero_return_std_gives_none_ratio_but_status_ok():
    r = run(*flat())
    assert r.pattern_metrics_status == "OK" and r.volatility_contraction_ratio is None


def test_u07_zero_average_volume_gives_none_volume_ratio():
    closes, _ = flat()
    r = run(closes, [0] * 100)
    assert r.volume_ratio_5_60 is None
    assert r.pattern_metrics_status == "OK"
    assert r.recent_surge_flag is False  # 기준 거래량 0이면 해당 일 건너뜀(U13)


# ── U08/U09: MA60 상향 돌파 일수 ────────────────────────────────────────────
@pytest.mark.parametrize("k", range(10))
def test_u08_cross_up_days_for_each_k(k):
    closes, volumes = flat(100)
    for i in range(k + 1):
        closes[i] = 110  # k일 전부터 현재까지 60일선 위, 그 전날(k+1)은 60일선과 같음(<=)
    assert run(closes, volumes).ma60_cross_up_days == k


def test_u08_no_cross_returns_none_and_equal_to_ma60_is_not_a_cross():
    closes, volumes = flat(100)  # 종가 == MA60
    assert run(closes, volumes).ma60_cross_up_days is None


def test_u09_cross_outside_observation_window_is_none():
    closes, volumes = flat(100)
    for i in range(11):
        closes[i] = 110  # 돌파는 k=10(관찰창 밖)
    assert run(closes, volumes).ma60_cross_up_days is None


# ── U10~U13: 급등 플래그 ────────────────────────────────────────────────────
def _surge_series(day, ret_close, vol):
    closes, volumes = flat(100)
    closes[day] = ret_close  # closes[day+1]=100 → 일 등락률
    volumes[day] = vol  # 직전 20일 평균 1000
    return closes, volumes


def test_u10_surge_boundary_is_inclusive():
    r = run(*_surge_series(5, 110, 3000))  # +10.0%, 3.0배
    assert r.recent_surge_flag is True


@pytest.mark.parametrize(
    ("ret_close", "vol"), [(Decimal("109.99"), 3000), (110, 2999)]
)  # +9.99% / 2.999배
def test_u11_just_below_boundary_is_not_surge(ret_close, vol):
    assert run(*_surge_series(5, ret_close, vol)).recent_surge_flag is False


def test_u12_observation_window_boundary_19_vs_20_days_ago():
    assert run(*_surge_series(19, 110, 3000)).recent_surge_flag is True
    assert run(*_surge_series(20, 110, 3000)).recent_surge_flag is False


def test_u13_zero_baseline_volume_skips_day_without_zero_division():
    closes, _ = flat(100)
    closes[5] = 110
    volumes = [0] * 100
    volumes[5] = 3000
    r = run(closes, volumes)  # 직전 20일 평균 0 → 건너뜀
    assert r.recent_surge_flag is False


# ── U14: 하락 추세 부호 ─────────────────────────────────────────────────────
def test_u14_downtrend_signs():
    closes = [100 + i * 0.5 for i in range(100)]  # 과거일수록 높음 → 현재 최저
    r = run(closes, [1000] * 100)
    assert r.sideways_net_change_pct < 0
    assert r.sideways_range_pct > 0


# ── U15/U16: 정밀도·순수성 ──────────────────────────────────────────────────
def test_u15_decimal_vs_oracle_and_four_decimal_places():
    rnd = random.Random(15)
    closes = [round(10000 * (1 + 0.03 * (rnd.random() * 2 - 1)), 2) for _ in range(130)]
    volumes = [int(100000 * (1 + 0.2 * (rnd.random() * 2 - 1))) for _ in range(130)]
    assert_matches_oracle(closes, volumes)
    r = run(closes, volumes)
    for f in NUMERIC_FIELDS:
        v = getattr(r, f)
        assert v == v.quantize(Decimal("0.0001")), f  # 소수 4자리로 정규화


def test_u16_purity_same_input_same_output_and_inputs_not_mutated():
    closes = D([200 - i for i in range(100)])
    volumes = [1000 + (i % 7) for i in range(100)]
    c_copy, v_copy = list(closes), list(volumes)
    a = compute_pattern_metrics(closes, volumes)
    b = compute_pattern_metrics(closes, volumes)
    assert a == b
    assert closes == c_copy and volumes == v_copy


# ── U41: 윈도우 절단 ────────────────────────────────────────────────────────
def test_u41_window_truncation_130_vs_latest_100_rows_identical():
    rnd = random.Random(41)
    closes = [round(10000 * (1 + 0.04 * (rnd.random() * 2 - 1)), 2) for _ in range(130)]
    volumes = [int(100000 * (1 + 0.3 * (rnd.random() * 2 - 1))) for _ in range(130)]
    full = compute_pattern_metrics(D(closes), volumes)
    cut = compute_pattern_metrics(D(closes[:100]), volumes[:100])
    assert full == cut
    # 80행만으로도 동일해야 한다(80 = PATTERN_MIN_ROWS 가 필요한 최대 행 수)
    assert compute_pattern_metrics(D(closes[:80]), volumes[:80]) == full


# ── U42: 입력 규약(최신순) ──────────────────────────────────────────────────
def test_u42_input_convention_newest_first_documented_and_order_matters():
    doc = compute_pattern_metrics.__doc__ or ""
    assert "최신순" in doc
    closes = [200 - i for i in range(100)]  # 최신순
    volumes = [1000] * 100
    newest_first = run(closes, volumes)
    oldest_first = run(closes[::-1], volumes)  # 잘못된(오름차순) 입력
    assert newest_first != oldest_first


# ── U40: 오라클 교차 검증 300건 ─────────────────────────────────────────────
def _series(seed: int) -> tuple[list[float], list[float]]:
    rnd = random.Random(seed)
    kind = seed % 6
    n = rnd.randint(80, 130)
    if kind == 0:
        c, v = oracle.synth(seed, n=max(n, 80))
    elif kind == 1:
        c, v = oracle.synth(
            seed,
            n=n,
            ramp=rnd.uniform(-0.002, 0.004),
            noise=rnd.uniform(0.005, 0.08),
            tail_vol=rnd.uniform(0.5, 6.0),
        )
    else:
        c_old_to_new = [10000.0]
        sigma = rnd.uniform(0.005, 0.03)
        for _ in range(n - 1):
            c_old_to_new.append(max(50.0, c_old_to_new[-1] * (1 + rnd.gauss(0, sigma))))
        c = c_old_to_new[::-1]
        v = [max(0.0, 100000 * (1 + rnd.gauss(0, 0.4))) for _ in range(n)]
        if kind == 3:  # 뚜렷한 추세
            c = [x * (1 + 0.5 * (i / n)) for i, x in enumerate(c)]
        elif kind == 4:  # 최근 급등+거래량 폭발 주입
            d = rnd.randint(0, 25)
            c[d] *= 1.12
            v[d] *= 6
        elif kind == 5:  # 일부는 0거래량/짧은 이력/단절
            roll = rnd.random()
            if roll < 0.25:
                v = [0.0] * n
            elif roll < 0.5:
                c, v = c[: rnd.randint(40, 79)], v[: rnd.randint(40, 79)]
            elif roll < 0.75:
                c[rnd.randint(0, 70)] *= rnd.choice([1.4, 0.55])
    c = [round(x, 4) for x in c]
    v = [float(int(x)) for x in v]
    return c, v


@pytest.mark.parametrize("batch", range(10))
def test_u40_oracle_cross_check_300_series(batch):
    for seed in range(batch * 30, batch * 30 + 30):
        closes, volumes = _series(seed)
        assert_matches_oracle(closes, volumes)


def test_u40_series_cover_all_statuses_and_both_surge_outcomes():
    """교차 검증 입력이 분기를 실제로 두루 밟는지 확인(검증이 공허하지 않도록)."""
    statuses, surges, crosses = set(), set(), set()
    for seed in range(300):
        closes, volumes = _series(seed)
        r = compute_pattern_metrics(D(closes), [int(v) for v in volumes])
        statuses.add(r.pattern_metrics_status)
        surges.add(r.recent_surge_flag)
        crosses.add(r.ma60_cross_up_days is not None)
    assert statuses == {"OK", "INSUFFICIENT_HISTORY", "SUSPECT_PRICE_JUMP"}
    assert {True, False} <= surges
    assert crosses == {True, False}
