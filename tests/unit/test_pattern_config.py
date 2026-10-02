"""판정 임계값 설정 로더 단위테스트 (REQ-032/036, 05-test-plan §6 TC-C01~C08).

`services/public_api/core/pattern_config.py`는 `PATTERN_*` 환경변수를 읽어 범위를 검증하고, 잘못된
값이면 **기동 시 즉시 실패**(`ConfigError`, 조용한 기본값 대체 금지)한다. 사용자 요청으로는 임계값을
바꿀 수 없다(질의 파라미터 없음) — 이 로더가 서버 측 유일한 출처다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.public_api.core.config import ConfigError
from services.public_api.core.pattern_config import (
    PatternThresholds,
    load_pattern_thresholds,
)
from shared import pattern_params as P

DEFAULTS = {
    "range_max_pct": Decimal("40.0"),
    "net_change_max_pct": Decimal("15.0"),
    "convergence_max_pct": Decimal("3.0"),
    "volatility_contraction_max": Decimal("1.0"),
    "ma60_approach_band_pct": Decimal("5.0"),
    "ma60_early_max_gap_pct": Decimal("7.0"),
    "cross_early_max_days": 10,
    "volume_ratio_min": Decimal("1.0"),
    "volume_ratio_max": Decimal("2.5"),
    "volume_anomaly_max": Decimal("3.0"),
}

# 환경변수 이름 → (필드 이름, 허용 최소, 허용 최대)
RANGES = {
    "PATTERN_RANGE_MAX_PCT": ("range_max_pct", "5", "100"),
    "PATTERN_NET_CHANGE_MAX_PCT": ("net_change_max_pct", "1", "50"),
    "PATTERN_CONVERGENCE_MAX_PCT": ("convergence_max_pct", "0.5", "10"),
    "PATTERN_VOLATILITY_CONTRACTION_MAX": ("volatility_contraction_max", "0.3", "2.0"),
    "PATTERN_MA60_APPROACH_BAND_PCT": ("ma60_approach_band_pct", "1", "15"),
    "PATTERN_MA60_EARLY_MAX_GAP_PCT": ("ma60_early_max_gap_pct", "1", "20"),
    "PATTERN_VOLUME_RATIO_MIN": ("volume_ratio_min", "0.5", "3"),
    "PATTERN_VOLUME_RATIO_MAX": ("volume_ratio_max", "1", "10"),
    "PATTERN_VOLUME_ANOMALY_MAX": ("volume_anomaly_max", "0.5", "10"),
}


def test_c01_no_environment_uses_documented_defaults():
    th = load_pattern_thresholds({})
    for field, expected in DEFAULTS.items():
        assert getattr(th, field) == expected, field
    assert th.enabled is True  # PATTERN_SCREEN_ENABLED 기본 true
    assert isinstance(th, PatternThresholds)


@pytest.mark.parametrize("env", RANGES)
def test_c02_out_of_range_values_fail_fast(env):
    field, lo, hi = RANGES[env]
    below = str(Decimal(lo) - Decimal("0.01"))
    above = str(Decimal(hi) + Decimal("0.01"))
    for bad in (below, above):
        with pytest.raises(ConfigError, match=env):
            load_pattern_thresholds({env: bad})


def test_c02_example_from_test_plan_range_max_101():
    with pytest.raises(ConfigError, match="PATTERN_RANGE_MAX_PCT"):
        load_pattern_thresholds({"PATTERN_RANGE_MAX_PCT": "101"})


@pytest.mark.parametrize("env", [*RANGES, "PATTERN_CROSS_EARLY_MAX_DAYS"])
@pytest.mark.parametrize(
    "bad", ["abc", "", "   ", "nan", "NaN", "inf", "-inf", "1e1", "４０", "1,5"]
)
def test_c03_type_errors_and_non_ascii_or_non_finite_numbers_fail(env, bad):
    with pytest.raises(ConfigError, match=env):
        load_pattern_thresholds({env: bad})


def test_c04_volume_ratio_min_must_be_below_max():
    with pytest.raises(ConfigError, match="PATTERN_VOLUME_RATIO"):
        load_pattern_thresholds(
            {"PATTERN_VOLUME_RATIO_MIN": "2.0", "PATTERN_VOLUME_RATIO_MAX": "2.0"}
        )
    with pytest.raises(ConfigError, match="PATTERN_VOLUME_RATIO"):
        load_pattern_thresholds(
            {"PATTERN_VOLUME_RATIO_MIN": "2.5", "PATTERN_VOLUME_RATIO_MAX": "2.0"}
        )
    th = load_pattern_thresholds(
        {"PATTERN_VOLUME_RATIO_MIN": "1.9", "PATTERN_VOLUME_RATIO_MAX": "2.0"}
    )
    assert th.volume_ratio_min < th.volume_ratio_max


def test_c05_cross_early_max_days_cannot_exceed_observation_window():
    with pytest.raises(ConfigError, match="PATTERN_CROSS_EARLY_MAX_DAYS"):
        load_pattern_thresholds(
            {"PATTERN_CROSS_EARLY_MAX_DAYS": str(P.CROSS_LOOKBACK_DAYS + 1)}
        )  # 11
    with pytest.raises(ConfigError, match="PATTERN_CROSS_EARLY_MAX_DAYS"):
        load_pattern_thresholds({"PATTERN_CROSS_EARLY_MAX_DAYS": "0"})
    with pytest.raises(ConfigError, match="PATTERN_CROSS_EARLY_MAX_DAYS"):
        load_pattern_thresholds({"PATTERN_CROSS_EARLY_MAX_DAYS": "5.5"})  # 정수만


@pytest.mark.parametrize("env", RANGES)
def test_c06_range_endpoints_are_accepted_inclusive(env):
    field, lo, hi = RANGES[env]
    env_lo = {env: lo}
    env_hi = {env: hi}
    # 짝이 되는 값 때문에 MIN<MAX 검증에 걸리지 않도록 조정
    if env == "PATTERN_VOLUME_RATIO_MIN":
        env_hi = {env: hi, "PATTERN_VOLUME_RATIO_MAX": "10"}
    if env == "PATTERN_VOLUME_RATIO_MAX":
        env_lo = {env: lo, "PATTERN_VOLUME_RATIO_MIN": "0.5"}
    assert getattr(load_pattern_thresholds(env_lo), field) == Decimal(lo)
    assert getattr(load_pattern_thresholds(env_hi), field) == Decimal(hi)
    assert load_pattern_thresholds({"PATTERN_CROSS_EARLY_MAX_DAYS": "1"}).cross_early_max_days == 1
    assert (
        load_pattern_thresholds({"PATTERN_CROSS_EARLY_MAX_DAYS": "10"}).cross_early_max_days == 10
    )


@pytest.mark.parametrize(
    ("raw", "expected"), [("true", True), ("false", False), ("TRUE", True), (" False ", False)]
)
def test_c07_screen_enabled_accepts_only_true_or_false(raw, expected):
    assert load_pattern_thresholds({"PATTERN_SCREEN_ENABLED": raw}).enabled is expected


@pytest.mark.parametrize("bad", ["yes", "1", "0", "on", "", "  ", "truee"])
def test_c07_screen_enabled_rejects_anything_else(bad):
    with pytest.raises(ConfigError, match="PATTERN_SCREEN_ENABLED"):
        load_pattern_thresholds({"PATTERN_SCREEN_ENABLED": bad})


def test_values_are_overridable_and_decimal_exact():
    th = load_pattern_thresholds(
        {
            "PATTERN_RANGE_MAX_PCT": "35.5",
            "PATTERN_CROSS_EARLY_MAX_DAYS": "7",
            "PATTERN_VOLUME_RATIO_MAX": "3",
        }
    )
    assert th.range_max_pct == Decimal("35.5")
    assert th.cross_early_max_days == 7
    assert th.volume_ratio_max == Decimal("3")
    assert th.volume_ratio_min == Decimal("1.0")  # 지정하지 않은 값은 기본값


def test_surrounding_whitespace_is_trimmed():
    assert load_pattern_thresholds({"PATTERN_RANGE_MAX_PCT": " 30 "}).range_max_pct == Decimal("30")


def test_c08_definition_payload_equals_loaded_settings_and_fixed_calc_params():
    th = load_pattern_thresholds(
        {"PATTERN_RANGE_MAX_PCT": "35", "PATTERN_CROSS_EARLY_MAX_DAYS": "6"}
    )
    defn = th.definition_thresholds()
    assert defn == {
        "range_max_pct": 35.0,
        "net_change_max_pct": 15.0,
        "convergence_max_pct": 3.0,
        "volatility_contraction_max": 1.0,
        "ma60_approach_band_pct": 5.0,
        "ma60_early_max_gap_pct": 7.0,
        "cross_early_max_days": 6,
        "volume_ratio_min": 1.0,
        "volume_ratio_max": 2.5,
        "volume_anomaly_max": 3.0,
    }
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in defn.values())
    calc = PatternThresholds.definition_calc()
    assert calc == {
        "lookback_days": 80,
        "ma60_window": 60,
        "cross_lookback_days": 10,
        "surge_lookback_days": 20,
        "surge_return_pct": 10.0,
        "surge_volume_mult": 3.0,
    }


def test_error_message_names_variable_and_reason_without_dumping_environment():
    with pytest.raises(ConfigError) as exc:
        load_pattern_thresholds(
            {
                "PATTERN_RANGE_MAX_PCT": "abc",
                "PUBLIC_API_DATABASE_URL": "postgresql://u:SECRETPW@h/db",
            }
        )
    msg = str(exc.value)
    assert "PATTERN_RANGE_MAX_PCT" in msg and "abc" in msg
    assert "SECRETPW" not in msg  # 다른 환경변수(비밀)는 메시지에 포함되지 않는다
