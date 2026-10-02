"""'급등 전 압축주' 패턴 지표 — 실행 가능한 기준 명세(Reference Oracle).

이 파일은 **운영 코드가 아니다.** 설계서(02-system-design.md §3~§4)의 계산 정의를 표준 라이브러리만으로
구현해 둔 기준 구현이며, 개발 단계에서 아래 두 용도로 쓴다.
  1. `services/derivation_batch/compute.py`에 구현할 순수 함수의 기대값 검증(교차 대조 오라클).
  2. 설계서의 정의가 서로 모순되지 않는지 합성 시나리오로 재현 가능하게 증명.

입력 규약: `closes`, `volumes`는 **최신순(내림차순)** 리스트, 0번 원소가 대상 거래일(T).
실행: `python docs/pattern-screening/prototype/pattern_rules_reference.py` → 자체 검증 결과 출력.
"""

from __future__ import annotations

import random
import statistics
import sys
from dataclasses import dataclass

# ── 계산 파라미터 (고정 상수: 바꾸면 배치 재계산 필요) ───────────────────────────
LOOKBACK_DAYS = 80          # L: 횡보 판정 구간(거래일)
MIN_ROWS = 80               # 이보다 적으면 INSUFFICIENT_HISTORY
MA60_WINDOW = 60
MA60_SLOPE_DAYS = 10
CROSS_LOOKBACK_DAYS = 10
VOL_SHORT, VOL_LONG = 10, 60            # 변동성 수축비: 최근 10일 / 60일 일수익률 표준편차
VR_SHORT, VR_LONG = 5, 60               # 거래량비: 5일 평균 / 60일 평균
SURGE_LOOKBACK_DAYS = 20
SURGE_RETURN_PCT = 10.0
SURGE_VOLUME_MULT = 3.0
PRICE_JUMP_LIMIT_PCT = 31.0             # 상·하한가 ±30% 초과 단절 = 수정주가 미반영 의심


@dataclass(frozen=True)
class Thresholds:
    """판정 임계값(설정값: 조회 시점에 적용, 바꿔도 재계산 불필요). 기본값은 '사용자 확정 대기' 제안값."""

    range_max_pct: float = 40.0
    net_change_max_pct: float = 15.0
    convergence_max_pct: float = 3.0
    volatility_contraction_max: float = 1.0
    ma60_approach_band_pct: float = 5.0
    ma60_early_max_gap_pct: float = 7.0
    cross_early_max_days: int = 10
    volume_ratio_min: float = 1.0
    volume_ratio_max: float = 2.5
    volume_anomaly_max: float = 3.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _ma(closes: list[float], n: int, off: int = 0) -> float | None:
    return None if len(closes) < off + n else _mean(closes[off : off + n])


def _returns(closes: list[float], n: int) -> list[float]:
    return [(closes[i] - closes[i + 1]) / closes[i + 1] * 100 for i in range(n)]


def compute_pattern_metrics(closes: list[float], volumes: list[float]) -> dict:
    """DB 컬럼 11개와 1:1 대응(설계서 §3-1). 산정 불가면 status만 채우고 나머지는 None."""
    empty = dict(
        sideways_range_pct=None, sideways_net_change_pct=None, ma_convergence_pct=None,
        volatility_contraction_ratio=None, ma60_gap_pct=None, ma20_vs_ma60_gap_pct=None,
        ma60_slope_pct=None, ma60_cross_up_days=None, volume_ratio_5_60=None,
        recent_surge_flag=None,
    )
    if len(closes) < MIN_ROWS or len(volumes) < MIN_ROWS:
        return {**empty, "pattern_metrics_status": "INSUFFICIENT_HISTORY"}
    if any(c <= 0 for c in closes[:MIN_ROWS]):
        return {**empty, "pattern_metrics_status": "SUSPECT_PRICE_JUMP"}
    for i in range(LOOKBACK_DAYS - 1):
        if abs((closes[i] - closes[i + 1]) / closes[i + 1] * 100) > PRICE_JUMP_LIMIT_PCT:
            return {**empty, "pattern_metrics_status": "SUSPECT_PRICE_JUMP"}

    window = closes[:LOOKBACK_DAYS]
    mean_w = _mean(window)
    ma5, ma10, ma20 = _ma(closes, 5), _ma(closes, 10), _ma(closes, 20)
    ma60 = _ma(closes, MA60_WINDOW)
    ma60_prev = _ma(closes, MA60_WINDOW, MA60_SLOPE_DAYS)

    sd_long = statistics.pstdev(_returns(closes, VOL_LONG))
    vol_ratio = None if sd_long == 0 else statistics.pstdev(_returns(closes, VOL_SHORT)) / sd_long

    cross_days = None
    for k in range(CROSS_LOOKBACK_DAYS):
        if closes[k] > _ma(closes, MA60_WINDOW, k) and closes[k + 1] <= _ma(closes, MA60_WINDOW, k + 1):
            cross_days = k
            break

    vr_den = _mean(volumes[:VR_LONG])
    surge = False
    for d in range(SURGE_LOOKBACK_DAYS):
        ret = (closes[d] - closes[d + 1]) / closes[d + 1] * 100
        base = _mean(volumes[d + 1 : d + 21])
        if ret >= SURGE_RETURN_PCT and base > 0 and volumes[d] >= SURGE_VOLUME_MULT * base:
            surge = True
            break

    return dict(
        sideways_range_pct=(max(window) - min(window)) / mean_w * 100,
        sideways_net_change_pct=(closes[0] - closes[LOOKBACK_DAYS - 1]) / closes[LOOKBACK_DAYS - 1] * 100,
        ma_convergence_pct=(max(ma5, ma10, ma20) - min(ma5, ma10, ma20)) / ma20 * 100,
        volatility_contraction_ratio=vol_ratio,
        ma60_gap_pct=(closes[0] - ma60) / ma60 * 100,
        ma20_vs_ma60_gap_pct=(ma20 - ma60) / ma60 * 100,
        ma60_slope_pct=(ma60 - ma60_prev) / ma60_prev * 100,
        ma60_cross_up_days=cross_days,
        volume_ratio_5_60=None if vr_den == 0 else _mean(volumes[:VR_SHORT]) / vr_den,
        recent_surge_flag=surge,
        pattern_metrics_status="OK",
    )


# ── 3값 논리: SQL의 TRUE/FALSE/NULL과 동일(FALSE AND NULL = FALSE) ─────────────────
def _and3(*xs):
    if any(x is False for x in xs):
        return False
    return None if any(x is None for x in xs) else True


def _or3(*xs):
    if any(x is True for x in xs):
        return True
    return None if any(x is None for x in xs) else False


def _le(a, b):  # a <= b, a가 None이면 None
    return None if a is None else a <= b


def _ge(a, b):
    return None if a is None else a >= b


def _lt(a, b):
    return None if a is None else a < b


def evaluate_conditions(m: dict, anomaly: float | None, t: Thresholds = Thresholds()) -> dict:
    """c1~c5, c9의 충족 여부(True/False/None=산정 불가). 설계서 §4-2의 SQL 식과 동일 의미."""
    if m["pattern_metrics_status"] != "OK":
        return {k: None for k in ("c1", "c2", "c3", "c4", "c5", "c9")}
    gap, band = m["ma60_gap_pct"], t.ma60_approach_band_pct
    abs_ = lambda x: None if x is None else abs(x)  # noqa: E731
    cross_ok = m["ma60_cross_up_days"] is not None and m["ma60_cross_up_days"] <= t.cross_early_max_days
    return dict(
        c1=_and3(_le(m["sideways_range_pct"], t.range_max_pct),
                 _le(abs_(m["sideways_net_change_pct"]), t.net_change_max_pct)),
        c2=_and3(_le(m["ma_convergence_pct"], t.convergence_max_pct),
                 _le(m["volatility_contraction_ratio"], t.volatility_contraction_max)),
        c3=_and3(_le(abs_(gap), band), _le(abs_(m["ma20_vs_ma60_gap_pct"]), band)),
        c4=_or3(_and3(_ge(gap, -band), _lt(gap, 0)),
                _and3(_ge(gap, 0), _le(gap, t.ma60_early_max_gap_pct), cross_ok)),
        c5=_and3(_ge(m["volume_ratio_5_60"], t.volume_ratio_min),
                 _le(m["volume_ratio_5_60"], t.volume_ratio_max),
                 _lt(anomaly, t.volume_anomaly_max)),
        c9=None if m["recent_surge_flag"] is None else (not m["recent_surge_flag"]),
    )


# ── 자체 검증용 합성 시계열 ───────────────────────────────────────────────────
def synth(seed: int, n: int = 130, ramp: float = 0.001, noise: float = 0.03, tail_vol: float = 1.3):
    """횡보(±noise) 후 마지막 10일 완만 상승, 마지막 5일 거래량 소폭 증가. 최신순으로 반환."""
    rnd = random.Random(seed)
    cl: list[float] = []
    vol: list[float] = []
    for i in range(n):
        cl.append(10000 * (1 + noise * (rnd.random() * 2 - 1)) if i < n - 10 else cl[-1] * (1 + ramp))
        vol.append(100000 * (1 + 0.2 * (rnd.random() * 2 - 1)) * (tail_vol if i >= n - 5 else 1.0))
    return cl[::-1], vol[::-1]


def _anomaly(v: list[float]) -> float | None:
    base = v[1:21]
    sd = statistics.stdev(base)
    return None if sd == 0 else (v[0] - statistics.mean(base)) / sd


def selfcheck(n: int = 300) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []

    def run(c, v):
        m = compute_pattern_metrics(c, v)
        return m, evaluate_conditions(m, _anomaly(v) if len(v) > 21 else None)

    ok = sum(all(x is True for x in run(*synth(s))[1].values()) for s in range(n))
    out.append(("이상 패턴 합성: 전 조건 충족(나머지는 합성 노이즈로 일부 조건 이탈)", ok, n))

    def vol_blast(s):
        c, v = synth(s); v[0] *= 8; return run(c, v)[1]["c5"] is False
    out.append(("당일 거래량 8배 → c5 미충족", sum(vol_blast(s) for s in range(n)), n))

    def jump(s):
        c, v = synth(s); c[0] *= 1.18; return run(c, v)[1]["c4"] is False
    out.append(("당일 +18% → c4 미충족(60일선 크게 이탈 상단)", sum(jump(s) for s in range(n)), n))

    def split(s):
        c, v = synth(s); c[3:] = [x * 0.5 for x in c[3:]]
        return run(c, v)[0]["pattern_metrics_status"] == "SUSPECT_PRICE_JUMP"
    out.append(("액면분할 의심(-50% 단절) → SUSPECT_PRICE_JUMP", sum(split(s) for s in range(n)), n))

    def short(s):
        c, v = synth(s); c, v = c[:30], v[:30]
        return run(c, v)[0]["pattern_metrics_status"] == "INSUFFICIENT_HISTORY"
    out.append(("30거래일치 → INSUFFICIENT_HISTORY(전 조건 산정 불가)", sum(short(s) for s in range(n)), n))

    def old_surge(s):
        c, v = synth(s); c[40] *= 1.12; v[40] *= 6
        return run(c, v)[1]["c9"] is True
    out.append(("40일 전 급등(관찰창 20일 밖) → c9 충족 유지", sum(old_surge(s) for s in range(n)), n))

    def trend(s):  # 80일 동안 뚜렷한 상승 추세 → 횡보 아님
        c, v = synth(s)
        c = [x * (1 + 0.5 * (i / 129)) for i, x in enumerate(c)]
        return run(c, v)[1]["c1"] is False
    out.append(("뚜렷한 상승 추세 → c1 미충족(순변화율 조건이 차단)", sum(trend(s) for s in range(n)), n))
    return out


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    for label, hit, total in selfcheck():
        print(f"{hit:3d}/{total}  {label}")
