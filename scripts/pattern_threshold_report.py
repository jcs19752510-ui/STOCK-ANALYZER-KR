#!/usr/bin/env python
"""패턴 스크리닝 판정 임계값 보정 리포트 (REQ-032/036, 04-development-plan §2 UNIT-15).

기본 임계값이 실제 종목 분포에서 적정한지(0건도 아니고 전 종목의 10% 초과도 아닌지) 사용자가
판단하도록 **조건별 충족 수·전체 조건 동시 충족 수·지표 분포(p10/p50/p90)·임계값 ±민감도 표**를
출력한다. 기획서 §5 성공 기준과 Q2(임계값 확정)의 근거 자료이며, 이 리포트가 임계값을 정하지는
않는다.

사용법: py -3.12 scripts/pattern_threshold_report.py py -3.12 scripts/pattern_threshold_report.py
--market KOSPI --sensitivity-pct 20 py -3.12 scripts/pattern_threshold_report.py --trade-date
2026-09-30

**읽기 전용**이다: DB 접속은 `PUBLIC_API_DATABASE_URL`(`api_service` — `derived_metrics_daily`
SELECT 권한뿐, `raw_internal` 접근 불가)을 쓰고, 첫 문장으로 `SET TRANSACTION READ ONLY`를 실행한다.
임계값은 공개 API와 같은 `PATTERN_*` 환경변수(`core/pattern_config.py`)를 읽으며, 판정식은 API와
**같은 함수** (`pattern_repository.build_condition_exprs`)를 써서 리포트 숫자와 실제 서비스 결과가
어긋날 수 없다.

종목 코드·이름·목록은 출력하지 않는다(종목을 식별하거나 서열화하지 않는다 — REQ-034).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import Float, and_, cast, create_engine, func, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.public_api.core.config import ConfigError, get_settings  # noqa: E402
from services.public_api.core.pattern_config import (  # noqa: E402
    THRESHOLD_RANGES,
    PatternThresholds,
    load_pattern_thresholds,
)
from services.public_api.db.pattern_repository import (  # noqa: E402
    CONDITION_IDS,
    build_condition_exprs,
)
from shared.db_models.public_serving import CurrentPublishedBatch  # noqa: E402
from shared.db_models.public_serving import DerivedMetricsDaily as D  # noqa: E402
from shared.pattern_params import PATTERN_STATUS_OK  # noqa: E402

PUBLISH_MARKET = "KRX"  # `current_published_batch`의 거래소 세션 구분(MVP: KRX만, DEC-010)
DEFAULT_SENSITIVITY_PCT = 20
TOO_MANY_RATIO = Decimal("0.10")  # 기획서 §5: 전체 충족이 전 종목의 10% 초과면 과다

CONDITION_LABELS = {
    "c1": "긴 횡보",
    "c2": "이평선 수렴",
    "c3": "60일선 접근",
    "c4": "60일선 돌파 단계",
    "c5": "거래량",
    "c9": "급등 이력 없음(대리 지표)",
}

# 민감도 표 순서: (환경변수, 영향받는 조건)
SENSITIVITY_PARAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("PATTERN_RANGE_MAX_PCT", ("c1",)),
    ("PATTERN_NET_CHANGE_MAX_PCT", ("c1",)),
    ("PATTERN_CONVERGENCE_MAX_PCT", ("c2",)),
    ("PATTERN_VOLATILITY_CONTRACTION_MAX", ("c2",)),
    ("PATTERN_MA60_APPROACH_BAND_PCT", ("c3", "c4")),
    ("PATTERN_MA60_EARLY_MAX_GAP_PCT", ("c4",)),
    ("PATTERN_CROSS_EARLY_MAX_DAYS", ("c4",)),
    ("PATTERN_VOLUME_RATIO_MIN", ("c5",)),
    ("PATTERN_VOLUME_RATIO_MAX", ("c5",)),
    ("PATTERN_VOLUME_ANOMALY_MAX", ("c5",)),
)

# 지표 분포 대상(산정 가능 `OK` 행만)
QUANTILE_METRICS = (
    "sideways_range_pct",
    "sideways_net_change_pct",
    "ma_convergence_pct",
    "volatility_contraction_ratio",
    "ma60_gap_pct",
    "ma20_vs_ma60_gap_pct",
    "ma60_slope_pct",
    "volume_ratio_5_60",
    "volume_anomaly_score",
)


class ReportError(RuntimeError):
    """리포트를 만들 수 없는 전제 오류(발행 데이터 없음 등). 조용히 넘어가지 않는다."""


@dataclass(frozen=True)
class CondCounts:
    true: int
    false: int
    null: int


@dataclass(frozen=True)
class QuantileRow:
    n: int
    p10: float | None
    p50: float | None
    p90: float | None


@dataclass(frozen=True)
class SensVariant:
    label: str  # "-20%" / "기준" / "+20%"
    value: Decimal | int
    cond_true: dict[str, int]
    all_met: int


@dataclass(frozen=True)
class SensRow:
    param: str
    conditions: tuple[str, ...]
    variants: list[SensVariant]


@dataclass
class ReportData:
    trade_date: date
    market: str
    total_rows: int
    ok_rows: int
    condition_counts: dict[str, CondCounts]
    all_met: int
    quantiles: dict[str, QuantileRow]
    sensitivity: list[SensRow] = field(default_factory=list)
    verdict: str = "OK"


def judge(*, all_met: int, total_rows: int, ok_rows: int) -> str:
    """기획서 §5: 전체 충족이 '0건도 아니고 전 종목의 10% 초과도 아님'이면 OK."""
    if ok_rows == 0:
        return "NOT_READY"
    if all_met == 0:
        return "ZERO"
    if Decimal(all_met) > TOO_MANY_RATIO * Decimal(total_rows):
        return "TOO_MANY"
    return "OK"


def _market_filter(market: str):
    return [] if market == "ALL" else [D.market == market]


def _published_trade_date(session: Session) -> date:
    published = session.execute(
        select(CurrentPublishedBatch.trade_date).where(
            CurrentPublishedBatch.market == PUBLISH_MARKET
        )
    ).scalar_one_or_none()
    if published is None:
        raise ReportError(
            "발행된 거래일이 없습니다(current_published_batch 비어 있음) — "
            "Derivation Batch가 정상 발행한 뒤 다시 실행하세요."
        )
    return published


def _counts(session: Session, th: PatternThresholds, trade_date: date, market: str):
    """한 임계값 세트에 대한 집계 1회(조건별 true/false/null, 전체 충족, 행 수)."""
    exprs = build_condition_exprs(th)
    cols = [
        func.count().label("total"),
        func.count().filter(D.pattern_metrics_status == PATTERN_STATUS_OK).label("ok"),
        func.count().filter(and_(*[exprs[c].is_(True) for c in CONDITION_IDS])).label("all_met"),
    ]
    for cid in CONDITION_IDS:
        cols += [
            func.count().filter(exprs[cid].is_(True)).label(f"{cid}_t"),
            func.count().filter(exprs[cid].is_(False)).label(f"{cid}_f"),
            func.count().filter(exprs[cid].is_(None)).label(f"{cid}_n"),
        ]
    row = (
        session.execute(select(*cols).where(D.trade_date == trade_date, *_market_filter(market)))
        .one()
        ._mapping
    )
    return {
        "total": row["total"],
        "ok": row["ok"],
        "all_met": row["all_met"],
        "cond": {
            cid: CondCounts(row[f"{cid}_t"], row[f"{cid}_f"], row[f"{cid}_n"])
            for cid in CONDITION_IDS
        },
    }


def _quantiles(session: Session, trade_date: date, market: str) -> dict[str, QuantileRow]:
    ok_only = D.pattern_metrics_status == PATTERN_STATUS_OK
    cols = []
    for name in QUANTILE_METRICS:
        col = cast(getattr(D, name), Float)
        cols.append(func.count(getattr(D, name)).filter(ok_only).label(f"{name}__n"))
        for label, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
            cols.append(
                func.percentile_cont(q).within_group(col).filter(ok_only).label(f"{name}__{label}")
            )
    row = (
        session.execute(select(*cols).where(D.trade_date == trade_date, *_market_filter(market)))
        .one()
        ._mapping
    )
    return {
        name: QuantileRow(
            n=row[f"{name}__n"],
            p10=row[f"{name}__p10"],
            p50=row[f"{name}__p50"],
            p90=row[f"{name}__p90"],
        )
        for name in QUANTILE_METRICS
    }


def _variant_value(base: Decimal | int, factor: Decimal, is_int: bool) -> Decimal | int:
    raw = Decimal(base) * factor
    if is_int:
        return int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _sensitivity(
    session: Session,
    th: PatternThresholds,
    trade_date: date,
    market: str,
    pct: int,
    base_counts: dict,
) -> list[SensRow]:
    rows: list[SensRow] = []
    for env, conds in SENSITIVITY_PARAMS:
        field_name, lo, hi = THRESHOLD_RANGES[env]
        is_int = field_name == "cross_early_max_days"
        base_value = getattr(th, field_name)
        variants = [
            SensVariant(
                "기준",
                base_value,
                {c: base_counts["cond"][c].true for c in conds},
                base_counts["all_met"],
            )
        ]
        for label, sign in ((f"-{pct}%", -1), (f"+{pct}%", 1)):
            value = _variant_value(base_value, Decimal(1) + sign * Decimal(pct) / 100, is_int)
            # 설정 허용 범위를 벗어나거나 기준과 같은 변형은 만들지 않는다(조용한 클램프 금지).
            if not (lo <= Decimal(value) <= hi) or value == base_value:
                continue
            variant = replace(th, **{field_name: value})
            if variant.volume_ratio_min >= variant.volume_ratio_max:
                continue
            counts = _counts(session, variant, trade_date, market)
            variants.append(
                SensVariant(
                    label, value, {c: counts["cond"][c].true for c in conds}, counts["all_met"]
                )
            )
        variants.sort(key=lambda v: {f"-{pct}%": 0, "기준": 1, f"+{pct}%": 2}[v.label])
        rows.append(SensRow(param=env, conditions=conds, variants=variants))
    return rows


def generate_report(
    session: Session,
    th: PatternThresholds,
    *,
    market: str,
    trade_date: date | None,
    sensitivity_pct: int,
) -> ReportData:
    """리포트 데이터를 만든다. **세션당 1회만** 호출한다(첫 문장이 `SET TRANSACTION READ ONLY`).

    호출 뒤에도 트랜잭션이 열려 있어 같은 세션에서 쓰기를 시도하면 PostgreSQL이 거부한다.
    """
    session.execute(text("SET TRANSACTION READ ONLY"))
    target = trade_date or _published_trade_date(session)

    base = _counts(session, th, target, market)
    if base["total"] == 0:
        raise ReportError(f"{target}({market})의 derived_metrics_daily 행이 없습니다.")

    data = ReportData(
        trade_date=target,
        market=market,
        total_rows=base["total"],
        ok_rows=base["ok"],
        condition_counts=base["cond"],
        all_met=base["all_met"],
        quantiles=_quantiles(session, target, market),
    )
    data.verdict = judge(all_met=data.all_met, total_rows=data.total_rows, ok_rows=data.ok_rows)
    if data.ok_rows > 0:
        data.sensitivity = _sensitivity(session, th, target, market, sensitivity_pct, base)
    return data


# ── 출력 ────────────────────────────────────────────────────────────────────────
VERDICT_TEXT = {
    "OK": "OK — 전체 충족이 0건도 아니고 전 종목의 10% 이하입니다.",
    "ZERO": "주의 — 전체 충족이 0건입니다(임계값이 너무 엄격하거나 데이터가 부족할 수 있음).",
    "TOO_MANY": "주의 — 전체 충족이 전 종목의 10%를 넘습니다(임계값이 너무 느슨할 수 있음).",
    "NOT_READY": "산정 가능 종목이 없습니다 — 시세 이력(80거래일)이 아직 부족합니다.",
}


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "해당 없음"


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def render_report(data: ReportData, th: PatternThresholds, sensitivity_pct: int) -> str:
    n, ok = data.total_rows, data.ok_rows
    lines = [
        "패턴 스크리닝 임계값 보정 리포트 (읽기 전용)",
        f"거래일: {data.trade_date}   시장: {data.market}",
        f"평가 대상: 전체 {n}행 중 산정 가능 {ok}행({_pct(ok, n)}), "
        f"산정 불가 {n - ok}행(이력 부족·단절 의심·구 배치)",
        "",
        "[조건별 충족 현황] (산정 불가 행은 '산정불가'로 센다)",
    ]
    for cid in CONDITION_IDS:
        c = data.condition_counts[cid]
        lines.append(
            f"  {cid} {CONDITION_LABELS[cid]:<16} 충족 {c.true:>5}  미충족 {c.false:>5}"
            f"  산정불가 {c.null:>5}  (충족률 {_pct(c.true, n)})"
        )
    lines += [
        "",
        f"[전체 조건 동시 충족] {data.all_met}건 (전체의 {_pct(data.all_met, n)}, "
        f"산정 가능의 {_pct(data.all_met, ok)})",
        f"[판정] {VERDICT_TEXT[data.verdict]}",
    ]
    if data.verdict == "NOT_READY":
        lines += [
            "",
            "(이력이 쌓인 뒤 다시 실행하세요.",
            " 민감도·분포는 산정 가능 종목이 있을 때만 출력합니다.)",
        ]
    else:
        lines += ["", "[지표 분포] (산정 가능 종목 기준, p10 / p50 / p90)"]
        for name in QUANTILE_METRICS:
            q = data.quantiles[name]
            lines.append(
                f"  {name:<30} n={q.n:<5} {_fmt(q.p10):>9} / {_fmt(q.p50):>9} / {_fmt(q.p90):>9}"
            )
        lines += [
            "",
            f"[임계값 민감도 (±{sensitivity_pct}%)] 영향받는 조건 충족 수 / 전체 동시 충족 수",
        ]
        for row in data.sensitivity:
            parts = []
            for v in row.variants:
                cond_text = ",".join(f"{c}={v.cond_true[c]}" for c in row.conditions)
                parts.append(f"{v.label} {v.value}: {cond_text} / 전체 {v.all_met}")
            lines.append(f"  {row.param}")
            lines.append("      " + "  |  ".join(parts))
    lines += [
        "",
        "이 리포트는 사용자의 임계값 확정(기획서 Q2)을 위한 참고 자료이며, 종목 코드·이름·목록은 "
        "출력하지 않습니다.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--market", choices=("ALL", "KOSPI", "KOSDAQ"), default="ALL")
    parser.add_argument(
        "--trade-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="대상 거래일(기본: 현재 발행된 거래일)",
    )
    parser.add_argument(
        "--sensitivity-pct",
        type=int,
        default=DEFAULT_SENSITIVITY_PCT,
        help=f"민감도 변동 폭 %%(기본 {DEFAULT_SENSITIVITY_PCT})",
    )
    args = parser.parse_args(argv)
    if not (1 <= args.sensitivity_pct <= 90):
        parser.error("--sensitivity-pct는 1~90이어야 합니다.")

    try:
        settings = get_settings()
        th = load_pattern_thresholds()
    except ConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            try:
                data = generate_report(
                    session,
                    th,
                    market=args.market,
                    trade_date=args.trade_date,
                    sensitivity_pct=args.sensitivity_pct,
                )
            except ReportError as exc:
                print(f"[실패] {exc}", file=sys.stderr)
                return 1
            print(render_report(data, th, args.sensitivity_pct))
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
