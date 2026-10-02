"""패턴 스크리닝 판정 임계값 설정 로더 (REQ-032/036, 02-system-design.md §3-3).

**판정 임계값**은 조회 시점에 SQL 조건식에 바인딩되는 설정값이다 — 바꿔도 `derived_metrics_daily`를
재계산할 필요가 없고 API 재시작만으로 반영된다(계산 파라미터 `shared/pattern_params.py`와 구분).
기본값은 "사용자 확정 대기" 제안값이다(기획서 Q2, UNIT-15 보정 리포트 후 확정).

원칙(02 §3-3):
- 요청자는 임계값을 바꿀 수 없다(질의 파라미터로 받지 않음 — 원천 데이터 역추정·비용·정의 분산
  방지).
- 설정 오류는 **기동 시 즉시 실패**한다(`ConfigError`) — 조용한 기본값 대체
  금지(`PUBLIC_API_DATABASE_URL` 과 같은 정책). 오류 메시지에는 해당 변수 이름과 입력값만 담고 다른
  환경변수는 노출하지 않는다.
- 숫자는 ASCII 십진수만 허용한다(`Decimal`이 받아들이는 `nan`/`inf`/지수 표기/전각 숫자는 거부).
  값은 `Decimal`로 보관해 `NUMERIC` 컬럼과 경계 비교(≤, ≥)를 부동소수 오차 없이 한다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from services.public_api.core.config import ConfigError
from shared import pattern_params as _pp

_DECIMAL_RE = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")
_INT_RE = re.compile(r"[+-]?[0-9]+")

# (환경변수, 필드, 기본값, 허용 최소, 허용 최대) — 설계서 §3-3 표와 동일
_DECIMAL_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    ("PATTERN_RANGE_MAX_PCT", "range_max_pct", "40.0", "5", "100"),
    ("PATTERN_NET_CHANGE_MAX_PCT", "net_change_max_pct", "15.0", "1", "50"),
    ("PATTERN_CONVERGENCE_MAX_PCT", "convergence_max_pct", "3.0", "0.5", "10"),
    ("PATTERN_VOLATILITY_CONTRACTION_MAX", "volatility_contraction_max", "1.0", "0.3", "2.0"),
    ("PATTERN_MA60_APPROACH_BAND_PCT", "ma60_approach_band_pct", "5.0", "1", "15"),
    ("PATTERN_MA60_EARLY_MAX_GAP_PCT", "ma60_early_max_gap_pct", "7.0", "1", "20"),
    ("PATTERN_VOLUME_RATIO_MIN", "volume_ratio_min", "1.0", "0.5", "3"),
    ("PATTERN_VOLUME_RATIO_MAX", "volume_ratio_max", "2.5", "1", "10"),
    ("PATTERN_VOLUME_ANOMALY_MAX", "volume_anomaly_max", "3.0", "0.5", "10"),
)
_CROSS_ENV = "PATTERN_CROSS_EARLY_MAX_DAYS"
_ENABLED_ENV = "PATTERN_SCREEN_ENABLED"

# 임계값 환경변수 → (`PatternThresholds` 필드, 허용 최소, 허용 최대). 보정 리포트의 민감도 변형이
# 설정 허용 범위를 벗어나지 않도록 같은 출처를 공유한다(범위가 두 곳에서 따로 관리되지 않게).
THRESHOLD_RANGES: dict[str, tuple[str, Decimal, Decimal]] = {
    env: (field, Decimal(lo), Decimal(hi)) for env, field, _default, lo, hi in _DECIMAL_SPECS
}
THRESHOLD_RANGES[_CROSS_ENV] = (
    "cross_early_max_days",
    Decimal(1),
    Decimal(_pp.CROSS_LOOKBACK_DAYS),
)


@dataclass(frozen=True)
class PatternThresholds:
    """판정 임계값 + 기능 스위치. 모든 비교는 경계 포함(≤, ≥)이다(설계서 §4)."""

    range_max_pct: Decimal  # c1 횡보 폭 상한
    net_change_max_pct: Decimal  # c1 순변화율 절댓값 상한
    convergence_max_pct: Decimal  # c2 이평 수렴 폭 상한
    volatility_contraction_max: Decimal  # c2 변동성 수축비 상한
    ma60_approach_band_pct: Decimal  # c3 접근 밴드, c4 돌파 직전 하단
    ma60_early_max_gap_pct: Decimal  # c4 돌파 초입 상단
    cross_early_max_days: int  # c4 돌파 후 경과일 상한
    volume_ratio_min: Decimal  # c5
    volume_ratio_max: Decimal  # c5
    volume_anomaly_max: Decimal  # c5 오늘 거래량 폭발 배제
    enabled: bool = True  # 기능 스위치(PATTERN_SCREEN_ENABLED)

    def definition_thresholds(self) -> dict[str, int | float]:
        """API 응답 `definition.thresholds`(설계서 §5-2) — 로드된 설정을 그대로 노출한다."""
        return {
            "range_max_pct": float(self.range_max_pct),
            "net_change_max_pct": float(self.net_change_max_pct),
            "convergence_max_pct": float(self.convergence_max_pct),
            "volatility_contraction_max": float(self.volatility_contraction_max),
            "ma60_approach_band_pct": float(self.ma60_approach_band_pct),
            "ma60_early_max_gap_pct": float(self.ma60_early_max_gap_pct),
            "cross_early_max_days": self.cross_early_max_days,
            "volume_ratio_min": float(self.volume_ratio_min),
            "volume_ratio_max": float(self.volume_ratio_max),
            "volume_anomaly_max": float(self.volume_anomaly_max),
        }

    @staticmethod
    def definition_calc() -> dict[str, int | float]:
        """API 응답 `definition.calc` — 고정 계산 파라미터(`shared/pattern_params.py`)."""
        return {
            "lookback_days": _pp.PATTERN_LOOKBACK_DAYS,
            "ma60_window": _pp.MA60_WINDOW,
            "cross_lookback_days": _pp.CROSS_LOOKBACK_DAYS,
            "surge_lookback_days": _pp.SURGE_LOOKBACK_DAYS,
            "surge_return_pct": float(_pp.SURGE_RETURN_PCT),
            "surge_volume_mult": float(_pp.SURGE_VOLUME_MULT),
        }


def _raw(env: Mapping[str, str], name: str) -> str | None:
    if name not in env:
        return None
    return env[name].strip()


def _parse_decimal(name: str, raw: str, lo: Decimal, hi: Decimal) -> Decimal:
    if not _DECIMAL_RE.fullmatch(raw):
        raise ConfigError(f"{name}={raw!r}: 숫자(예: 3.5)여야 합니다.")
    value = Decimal(raw)
    if not (lo <= value <= hi):
        raise ConfigError(f"{name}={raw}: 허용 범위는 {lo} ~ {hi}입니다.")
    return value


def load_pattern_thresholds(env: Mapping[str, str] | None = None) -> PatternThresholds:
    """`PATTERN_*` 환경변수를 읽어 검증한다. 잘못된 값이면 `ConfigError`(기동 실패)."""
    source: Mapping[str, str] = os.environ if env is None else env

    values: dict[str, Decimal] = {}
    for name, field, default, lo, hi in _DECIMAL_SPECS:
        raw = _raw(source, name)
        values[field] = _parse_decimal(
            name, default if raw is None else raw, Decimal(lo), Decimal(hi)
        )

    if values["volume_ratio_min"] >= values["volume_ratio_max"]:
        raise ConfigError(
            "PATTERN_VOLUME_RATIO_MIN은 PATTERN_VOLUME_RATIO_MAX보다 작아야 합니다"
            f"(현재 {values['volume_ratio_min']} / {values['volume_ratio_max']})."
        )

    raw_days = _raw(source, _CROSS_ENV)
    if raw_days is None:
        cross_days = _pp.CROSS_LOOKBACK_DAYS
    else:
        if not _INT_RE.fullmatch(raw_days):
            raise ConfigError(f"{_CROSS_ENV}={raw_days!r}: 정수여야 합니다.")
        cross_days = int(raw_days)
        if not (1 <= cross_days <= _pp.CROSS_LOOKBACK_DAYS):
            raise ConfigError(
                f"{_CROSS_ENV}={raw_days}: 허용 범위는 1 ~ {_pp.CROSS_LOOKBACK_DAYS}"
                "(돌파 관찰창)입니다."
            )

    raw_enabled = _raw(source, _ENABLED_ENV)
    if raw_enabled is None:
        enabled = True
    elif raw_enabled.lower() in ("true", "false"):
        enabled = raw_enabled.lower() == "true"
    else:
        raise ConfigError(f"{_ENABLED_ENV}={raw_enabled!r}: true 또는 false여야 합니다.")

    return PatternThresholds(cross_early_max_days=cross_days, enabled=enabled, **values)
