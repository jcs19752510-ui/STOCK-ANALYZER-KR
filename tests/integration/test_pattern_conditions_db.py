"""패턴 조건식(SQL) 임시 DB 테스트 (REQ-032, 05-test-plan §7 TC-A28·A29·A30·A31·A33 의 SQL 계층).

`services/public_api/db/pattern_repository.build_condition_exprs()`가 만드는 SQLAlchemy 식을 실제
PostgreSQL에서 평가해 (1) 임계값 경계 포함성 (2) 3값 논리(`FALSE AND NULL = FALSE`) (3) 상태 게이트
(4) `ma60_stage`와 c4의 일치 (5) 기준 구현(오라클)과의 대량 등가성을 확인한다. 지표 값은 시계열이
  아니라 `derived_metrics_daily`에 **직접 삽입**해 정확한 경계를 만든다(05 §1-1). API
  계층(UNIT-16)이 같은 식을 그대로 쓰므로 필터와 표시가 어긋날 수 없다(설계서 §0-5).
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from decimal import Decimal
from itertools import count

import pytest
from sqlalchemy import create_engine, select, text

from services.public_api.core.pattern_config import PatternThresholds, load_pattern_thresholds
from services.public_api.db.pattern_repository import build_condition_exprs, ma60_stage_expr
from shared.db_models.public_serving import DerivedMetricsDaily as D
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database
from tests.unit import test_pattern_compute as oracle_tools

TRADE_DATE = "2026-09-30"
CONDS = ("c1", "c2", "c3", "c4", "c5", "c9")
DEFAULT = load_pattern_thresholds({})

IDEAL = {  # 기본 임계값에서 c1~c5·c9가 모두 true인 행
    "pattern_metrics_status": "OK",
    "sideways_range_pct": Decimal("10"),
    "sideways_net_change_pct": Decimal("0"),
    "ma_convergence_pct": Decimal("1"),
    "volatility_contraction_ratio": Decimal("0.5"),
    "ma60_gap_pct": Decimal("-1"),
    "ma20_vs_ma60_gap_pct": Decimal("0"),
    "ma60_slope_pct": Decimal("0"),
    "ma60_cross_up_days": None,
    "volume_ratio_5_60": Decimal("1.5"),
    "volume_anomaly_score": Decimal("0.5"),
    "recent_surge_flag": False,
}


@pytest.fixture(scope="module")
def engine() -> Iterator:
    try:
        with temp_database() as tdb:
            eng = create_engine(TempDb.render(tdb.migrator_url))
            batch_id = uuid.uuid4()
            with eng.begin() as c:
                c.execute(
                    text(
                        "INSERT INTO public_serving.batch_run(batch_run_id,run_type,status)"
                        " VALUES (:i,'derive','SUCCESS')"
                    ),
                    {"i": batch_id},
                )
            eng.batch_id = batch_id  # type: ignore[attr-defined]
            yield eng
            eng.dispose()
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


_seq = count(1)


def _insert(engine, rows: list[dict]) -> list[str]:
    """rows(지표 오버라이드 dict 목록)를 삽입하고 종목코드 목록을 반환."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM public_serving.derived_metrics_daily"))
        codes = []
        payload = []
        for r in rows:
            code = f"B{next(_seq):05d}"
            codes.append(code)
            payload.append(
                {
                    "stock_code": code,
                    "trade_date": TRADE_DATE,
                    "market": "KOSPI",
                    "batch_run_id": engine.batch_id,
                    **{**IDEAL, **r},
                }
            )
        c.execute(D.__table__.insert(), payload)
    return codes


def _evaluate(engine, th: PatternThresholds, codes: list[str]) -> dict[str, dict]:
    exprs = build_condition_exprs(th)
    cols = [D.stock_code, ma60_stage_expr(th).label("stage")] + [exprs[c].label(c) for c in CONDS]
    with engine.connect() as c:
        rows = c.execute(select(*cols).where(D.stock_code.in_(codes))).mappings().all()
    return {r["stock_code"]: dict(r) for r in rows}


def _one(engine, th, **override) -> dict:
    codes = _insert(engine, [override])
    return _evaluate(engine, th, codes)[codes[0]]


# ── TC-A28: 임계값 경계 포함성(= 는 충족, 경계 초과는 미충족) ────────────────────────
BOUNDARY_CASES = [
    # (조건, 필드 값 오버라이드, 기대)
    ("c1", {"sideways_range_pct": Decimal("40.0")}, True),
    ("c1", {"sideways_range_pct": Decimal("40.0001")}, False),
    ("c1", {"sideways_net_change_pct": Decimal("15.0")}, True),
    ("c1", {"sideways_net_change_pct": Decimal("15.0001")}, False),
    ("c1", {"sideways_net_change_pct": Decimal("-15.0")}, True),
    ("c1", {"sideways_net_change_pct": Decimal("-15.0001")}, False),
    ("c2", {"ma_convergence_pct": Decimal("3.0")}, True),
    ("c2", {"ma_convergence_pct": Decimal("3.0001")}, False),
    ("c2", {"volatility_contraction_ratio": Decimal("1.0")}, True),
    ("c2", {"volatility_contraction_ratio": Decimal("1.0001")}, False),
    ("c3", {"ma60_gap_pct": Decimal("5.0")}, True),
    ("c3", {"ma60_gap_pct": Decimal("5.0001")}, False),
    ("c3", {"ma60_gap_pct": Decimal("-5.0")}, True),
    ("c3", {"ma60_gap_pct": Decimal("-5.0001")}, False),
    ("c3", {"ma20_vs_ma60_gap_pct": Decimal("5.0")}, True),
    ("c3", {"ma20_vs_ma60_gap_pct": Decimal("5.0001")}, False),
    ("c3", {"ma20_vs_ma60_gap_pct": Decimal("-5.0")}, True),
    ("c3", {"ma20_vs_ma60_gap_pct": Decimal("-5.0001")}, False),
    ("c4", {"ma60_gap_pct": Decimal("-5.0")}, True),  # 돌파 직전 하단 경계(포함)
    ("c4", {"ma60_gap_pct": Decimal("-5.0001")}, False),
    ("c4", {"ma60_gap_pct": Decimal("-0.0001")}, True),
    ("c4", {"ma60_gap_pct": Decimal("0"), "ma60_cross_up_days": 0}, True),  # 초입 하단 경계(0 포함)
    ("c4", {"ma60_gap_pct": Decimal("0"), "ma60_cross_up_days": None}, False),  # 돌파 이력 없음
    ("c4", {"ma60_gap_pct": Decimal("7.0"), "ma60_cross_up_days": 3}, True),  # 초입 상단 경계
    ("c4", {"ma60_gap_pct": Decimal("7.0001"), "ma60_cross_up_days": 3}, False),
    ("c4", {"ma60_gap_pct": Decimal("2"), "ma60_cross_up_days": 9}, True),
    ("c5", {"volume_ratio_5_60": Decimal("1.0")}, True),
    ("c5", {"volume_ratio_5_60": Decimal("0.9999")}, False),
    ("c5", {"volume_ratio_5_60": Decimal("2.5")}, True),
    ("c5", {"volume_ratio_5_60": Decimal("2.5001")}, False),
    ("c5", {"volume_anomaly_score": Decimal("2.9999")}, True),
    ("c5", {"volume_anomaly_score": Decimal("3.0")}, False),  # 엄격 미만(<)
    ("c9", {"recent_surge_flag": False}, True),
    ("c9", {"recent_surge_flag": True}, False),
]


@pytest.mark.parametrize(
    ("cond", "override", "expected"),
    BOUNDARY_CASES,
    ids=[f"{c}-{'-'.join(f'{k}={v}' for k, v in o.items())}" for c, o, _ in BOUNDARY_CASES],
)
def test_a28_threshold_boundaries_are_inclusive(engine, cond, override, expected):
    assert _one(engine, DEFAULT, **override)[cond] is expected


def test_a28_cross_early_max_days_boundary_with_custom_threshold(engine):
    th = load_pattern_thresholds({"PATTERN_CROSS_EARLY_MAX_DAYS": "5"})
    assert _one(engine, th, ma60_gap_pct=Decimal("2"), ma60_cross_up_days=5)["c4"] is True
    assert _one(engine, th, ma60_gap_pct=Decimal("2"), ma60_cross_up_days=6)["c4"] is False


def test_ideal_row_satisfies_every_condition_with_default_thresholds(engine):
    r = _one(engine, DEFAULT)
    assert [r[c] for c in CONDS] == [True] * 6
    assert r["stage"] == "BELOW_NEAR"


# ── TC-A29: 3값 논리 ───────────────────────────────────────────────────────────────
def test_a29_false_and_null_is_false_not_null_while_true_and_null_is_null(engine):
    # c2: conv가 임계 초과(false) + 변동성 수축비 NULL → FALSE (NULL 아님)
    r = _one(engine, DEFAULT, ma_convergence_pct=Decimal("3.5"), volatility_contraction_ratio=None)
    assert r["c2"] is False
    # c2: conv 충족(true) + 수축비 NULL → NULL
    r = _one(engine, DEFAULT, ma_convergence_pct=Decimal("2"), volatility_contraction_ratio=None)
    assert r["c2"] is None
    # c1: net NULL이어도 range가 초과면 FALSE, 충족이면 NULL
    assert (
        _one(engine, DEFAULT, sideways_range_pct=Decimal("50"), sideways_net_change_pct=None)["c1"]
        is False
    )
    assert (
        _one(engine, DEFAULT, sideways_range_pct=Decimal("10"), sideways_net_change_pct=None)["c1"]
        is None
    )
    # c5: 거래량 이상치 NULL — 거래량비가 범위 밖이면 FALSE, 안이면 NULL
    assert (
        _one(engine, DEFAULT, volume_ratio_5_60=Decimal("5"), volume_anomaly_score=None)["c5"]
        is False
    )
    assert (
        _one(engine, DEFAULT, volume_ratio_5_60=Decimal("1.5"), volume_anomaly_score=None)["c5"]
        is None
    )
    # c9: 급등 플래그 NULL → NULL
    assert _one(engine, DEFAULT, recent_surge_flag=None)["c9"] is None
    # c4: gap NULL → NULL
    assert _one(engine, DEFAULT, ma60_gap_pct=None)["c4"] is None


# ── TC-A30·A33: 상태 게이트(상태가 OK가 아니면 값이 채워져 있어도 전부 NULL) ──────────────
@pytest.mark.parametrize("status", ["INSUFFICIENT_HISTORY", "SUSPECT_PRICE_JUMP", None])
def test_a30_a33_non_ok_or_legacy_status_makes_every_condition_null(engine, status):
    r = _one(engine, DEFAULT, pattern_metrics_status=status)  # 지표 값은 이상형 그대로 채워 둠
    assert [r[c] for c in CONDS] == [None] * 6
    assert r["stage"] is None


# ── TC-A31: ma60_stage ↔ c4 일치 ───────────────────────────────────────────────────
STAGE_CASES = [
    (Decimal("-5.0001"), None, "BELOW_FAR"),
    (Decimal("-10"), 3, "BELOW_FAR"),
    (Decimal("-5.0"), None, "BELOW_NEAR"),
    (Decimal("-0.0001"), None, "BELOW_NEAR"),
    (Decimal("0"), None, "ABOVE_SETTLED"),
    (Decimal("0"), 0, "CROSS_EARLY"),
    (Decimal("3"), 9, "CROSS_EARLY"),
    (Decimal("3"), None, "ABOVE_SETTLED"),
    (Decimal("7.0"), 10, "CROSS_EARLY"),
    (Decimal("7.0"), None, "ABOVE_SETTLED"),
    (Decimal("7.0001"), 2, "EXTENDED"),
    (Decimal("12"), 8, "EXTENDED"),
]


@pytest.mark.parametrize(("gap", "cross", "stage"), STAGE_CASES)
def test_a31_stage_values_at_boundaries(engine, gap, cross, stage):
    r = _one(engine, DEFAULT, ma60_gap_pct=gap, ma60_cross_up_days=cross)
    assert r["stage"] == stage
    assert r["c4"] is (stage in ("BELOW_NEAR", "CROSS_EARLY"))


def test_a31_gap_cross_grid_c4_true_iff_stage_is_below_near_or_cross_early(engine):
    gaps = [Decimal(str(g / 2)) for g in range(-20, 31)]  # -10.0 … +15.0 (0.5 간격)
    gaps += [Decimal(x) for x in ("-5.0001", "-4.9999", "-0.0001", "0.0001", "6.9999", "7.0001")]
    crosses = [None, *range(0, 13)]
    combos = [(g, c) for g in gaps for c in crosses]
    codes = _insert(engine, [{"ma60_gap_pct": g, "ma60_cross_up_days": c} for g, c in combos])
    got = _evaluate(engine, DEFAULT, codes)
    th = oracle_tools.oracle.Thresholds()
    for code, (g, c) in zip(codes, combos, strict=True):
        r = got[code]
        assert r["c4"] is (r["stage"] in ("BELOW_NEAR", "CROSS_EARLY")), (g, c, r)
        m = {**_oracle_metrics({"ma60_gap_pct": g, "ma60_cross_up_days": c})}
        assert r["c4"] is oracle_tools.oracle.evaluate_conditions(m, 0.5, th)["c4"], (g, c)
    assert len(codes) == len(combos) == (51 + 6) * 14  # 격자 전수(성긴 샘플링이 아님)


# ── 오라클 대량 등가성: SQL 판정 == 기준 구현(무작위·경계 중심, NULL 포함) ─────────────────
def _oracle_metrics(row: dict) -> dict:
    merged = {**IDEAL, **row}
    out = {}
    for k, v in merged.items():
        out[k] = float(v) if isinstance(v, Decimal) else v
    return out


_CHOICES = {
    "sideways_range_pct": ["0", "10", "30", "40", "40.0001", "50", "30.0", None],
    "sideways_net_change_pct": ["0", "-15", "15", "15.0001", "-15.0001", "-30", "3", None],
    "ma_convergence_pct": ["0", "1", "3", "3.0001", "2.0", "5", None],
    "volatility_contraction_ratio": ["0.1", "1", "1.0001", "0.5", "0.9999", "2", None],
    "ma60_gap_pct": ["-8", "-5", "-5.0001", "-2.5", "0", "2", "3", "5", "7", "7.0001", "12", None],
    "ma20_vs_ma60_gap_pct": ["0", "5", "-5", "5.0001", "-5.0001", "2", "-3", None],
    "ma60_cross_up_days": [None, None, 0, 3, 4, 5, 9, 10],
    "volume_ratio_5_60": ["0.5", "0.9999", "1", "1.2", "2", "2.5", "2.5001", "3", None],
    "volume_anomaly_score": ["-1", "0", "1.9999", "2", "2.9999", "3", "5", None],
    "recent_surge_flag": [True, False, False, None],
    "pattern_metrics_status": ["OK"] * 12 + ["INSUFFICIENT_HISTORY", "SUSPECT_PRICE_JUMP", None],
}


def _random_rows(n: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    rows = []
    for _ in range(n):
        row = {}
        for k, choices in _CHOICES.items():
            v = rnd.choice(choices)
            is_number = isinstance(v, str) and k != "pattern_metrics_status"
            row[k] = Decimal(v) if is_number else v
        rows.append(row)
    return rows


@pytest.mark.parametrize(
    "env",
    [
        {},
        {
            "PATTERN_RANGE_MAX_PCT": "30",
            "PATTERN_NET_CHANGE_MAX_PCT": "10",
            "PATTERN_CONVERGENCE_MAX_PCT": "2",
            "PATTERN_VOLATILITY_CONTRACTION_MAX": "0.9",
            "PATTERN_MA60_APPROACH_BAND_PCT": "3",
            "PATTERN_MA60_EARLY_MAX_GAP_PCT": "5",
            "PATTERN_CROSS_EARLY_MAX_DAYS": "4",
            "PATTERN_VOLUME_RATIO_MIN": "1.2",
            "PATTERN_VOLUME_RATIO_MAX": "2",
            "PATTERN_VOLUME_ANOMALY_MAX": "2",
        },
    ],
    ids=["default-thresholds", "custom-thresholds"],
)
def test_sql_conditions_match_oracle_on_800_random_boundary_rows(engine, env):
    th = load_pattern_thresholds(env)
    ot = oracle_tools.oracle.Thresholds(
        range_max_pct=float(th.range_max_pct),
        net_change_max_pct=float(th.net_change_max_pct),
        convergence_max_pct=float(th.convergence_max_pct),
        volatility_contraction_max=float(th.volatility_contraction_max),
        ma60_approach_band_pct=float(th.ma60_approach_band_pct),
        ma60_early_max_gap_pct=float(th.ma60_early_max_gap_pct),
        cross_early_max_days=th.cross_early_max_days,
        volume_ratio_min=float(th.volume_ratio_min),
        volume_ratio_max=float(th.volume_ratio_max),
        volume_anomaly_max=float(th.volume_anomaly_max),
    )
    rows = _random_rows(800, seed=28)
    codes = _insert(engine, rows)
    got = _evaluate(engine, th, codes)
    outcomes = {c: set() for c in CONDS}
    for code, row in zip(codes, rows, strict=True):
        m = _oracle_metrics(row)
        anomaly = m.get("volume_anomaly_score")
        want = oracle_tools.oracle.evaluate_conditions(m, anomaly, ot)
        for cond in CONDS:
            assert got[code][cond] is want[cond], (cond, row, got[code][cond], want[cond])
            outcomes[cond].add(want[cond])
    # 입력이 공허하지 않은지: 모든 조건이 true/false/null 세 결과를 모두 냈다
    for cond in CONDS:
        assert {True, False} <= outcomes[cond], cond
    assert None in outcomes["c1"] and None in outcomes["c2"] and None in outcomes["c5"]
