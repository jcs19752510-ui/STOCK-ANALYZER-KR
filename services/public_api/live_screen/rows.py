"""장중 재계산 입력 행 만들기(순수 함수, DB·네트워크 없음) — DEC-089·DEC-090.

발행된 `derived_metrics_daily` 행(공공데이터 일봉 기준)을 바탕으로, 이력(발행 일봉 + 증권사 보충 일봉)에 **오늘 진행 중인 봉**을
붙여 가격·거래량 계열 지표를 **일봉 배치와 같은 순수 함수**(`services/derivation_batch/compute.py`)로 다시 계산한다.
판정(필터·정렬·패턴 조건식)은 이 모듈이 하지 않는다 — 결과 행을 SQL 가상 테이블(`virtual.py`)로 넣어 기존 SQL이 그대로 판정한다.

날짜 규칙(계약서 §7):
- `basis_date`(P) = 발행 일봉 거래일, `expected_date`(E) = 직전 거래일(마감 뒤에는 오늘).
- 오늘 행은 `E < today`이고 오늘이 거래일이며 시세가 신선할 때만 붙인다(`basis:"live"`). 아니면 이력 끝(E)까지로 계산한다(`basis:"daily"`).
- P < E(발행이 뒤처짐)이면 모든 종목을 이력(E까지)으로 다시 계산하고, E 이력이 없는 종목은 결과에서 뺀다(`excluded`).
"""

# ruff: noqa: E501

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from services.derivation_batch.compute import (
    compute_ma_gap_pct,
    compute_pattern_metrics,
    compute_return_pct,
    compute_volume_anomaly_score,
    rank_percentile,
)
from services.derivation_batch.repository import VOLUME_BASELINE_WINDOW
from services.public_api.live_screen.types import DailyBar
from services.public_api.realtime.market import MarketQuote

STALE_QUOTE_SECONDS_DEFAULT = 300.0
COVERAGE_MIN_DEFAULT = 0.9

# 다시 계산하는 열(가격·거래량 계열). 등락률 순위 백분위는 정책이 live일 때만 추가된다.
PATTERN_COLUMNS: tuple[str, ...] = (
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
RECOMPUTED_COLUMNS: tuple[str, ...] = (
    "return_pct",
    "ma5_gap_pct",
    "ma20_gap_pct",
    "volume_anomaly_score",
    "volume_raw",
    *PATTERN_COLUMNS,
)
# 일봉(발행) 값을 그대로 쓰는 열: 장중 원천이 없다.
FIXED_DAILY_COLUMNS: tuple[str, ...] = (
    "per_raw",
    "pbr_raw",
    "market_cap_raw_krw",
    "per_percentile",
    "pbr_percentile",
    "market_cap_percentile",
    "per_unavailable_reason",
    "pbr_unavailable_reason",
)


@dataclass
class LiveRowsResult:
    rows: list[dict[str, Any]]  # derived_metrics_daily와 같은 열 이름의 dict. 결과에서 뺀 종목은 들어 있지 않다
    basis: dict[str, str]  # stock_code -> "live" | "daily"
    meta: dict[str, Any] = field(default_factory=dict)
    excluded: list[str] = field(default_factory=list)  # E 이력이 없어 뺀 종목코드


def _decimal(value: float | int | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def quote_is_usable(quote: MarketQuote | None, *, now_ts: float, stale_seconds: float) -> bool:
    """시세가 있고 너무 오래되지 않았으며 값이 쓸 만하면 True(0·음수 가격/거래량 거부)."""
    if quote is None or quote.price <= 0 or quote.volume < 0:
        return False
    return (now_ts - quote.fetched_at) <= stale_seconds


def compute_row_metrics(closes_desc: Sequence[Decimal], volumes_desc: Sequence[int]) -> dict[str, Any]:
    """종가·거래량(최신순, 0번이 기준일)으로 다시 계산하는 열들의 값. `run_derivation.compute_stock_day_metrics`와 같은 호출 조합이다."""
    closes = list(closes_desc)
    volumes = list(volumes_desc)
    ret = compute_return_pct(closes[0], closes[1] if len(closes) >= 2 else None)
    ma5 = compute_ma_gap_pct(closes, window=5)
    ma20 = compute_ma_gap_pct(closes, window=20)
    vas = compute_volume_anomaly_score(
        volumes[0], volumes[1 : 1 + VOLUME_BASELINE_WINDOW], window=VOLUME_BASELINE_WINDOW
    )
    pat = compute_pattern_metrics(closes, volumes)
    return {
        "return_pct": ret,
        "ma5_gap_pct": ma5,
        "ma20_gap_pct": ma20,
        "volume_anomaly_score": vas,
        "volume_raw": volumes[0],
        "sideways_range_pct": pat.sideways_range_pct,
        "sideways_net_change_pct": pat.sideways_net_change_pct,
        "ma_convergence_pct": pat.ma_convergence_pct,
        "volatility_contraction_ratio": pat.volatility_contraction_ratio,
        "ma60_gap_pct": pat.ma60_gap_pct,
        "ma20_vs_ma60_gap_pct": pat.ma20_vs_ma60_gap_pct,
        "ma60_slope_pct": pat.ma60_slope_pct,
        "ma60_cross_up_days": pat.ma60_cross_up_days,
        "volume_ratio_5_60": pat.volume_ratio_5_60,
        "recent_surge_flag": pat.recent_surge_flag,
        "pattern_metrics_status": pat.pattern_metrics_status,
    }


def _series_through(bars: Sequence[DailyBar], end: date) -> list[DailyBar]:
    """날짜 오름차순 `bars`에서 `end` 이하만, 중복 날짜는 앞의 값을 우선해 남긴다."""
    seen: dict[date, DailyBar] = {}
    for b in bars:
        if b.trade_date <= end and b.trade_date not in seen:
            seen[b.trade_date] = b
    return [seen[d] for d in sorted(seen)]


def build_live_rows(
    published_rows: Sequence[Mapping[str, Any]],
    history: Mapping[str, Sequence[DailyBar]],
    quotes: Mapping[str, MarketQuote],
    *,
    today: date,
    basis_date: date,
    expected_date: date,
    trading_today: bool,
    now_ts: float | None = None,
    stale_quote_seconds: float = STALE_QUOTE_SECONDS_DEFAULT,
    coverage_min: float = COVERAGE_MIN_DEFAULT,
) -> LiveRowsResult:
    """발행 행에서 장중 재계산 행을 만든다.

    - `history`: 종목코드 → 일봉(날짜 오름차순, 발행 일봉 + 보충 일봉). 발행 날짜가 겹치면 앞(발행) 값을 쓴다.
    - 입력 `published_rows`는 바꾸지 않는다(복사본을 돌려준다).
    """
    started = time.perf_counter()
    stamp = time.time() if now_ts is None else now_ts
    gap = basis_date < expected_date
    live_possible = trading_today and expected_date < today

    live_codes: set[str] = set()
    computed: dict[str, dict[str, Any]] = {}
    excluded: list[str] = []
    rows: list[dict[str, Any]] = []
    basis: dict[str, str] = {}

    # 1) 종목별 재계산
    plan: list[tuple[dict[str, Any], str | None]] = []  # (행 복사본, 재계산 종류: "live"|"daily"|None=발행 그대로)
    for src in published_rows:
        row = dict(src)
        code = row["stock_code"]
        quote = quotes.get(code)
        use_live = live_possible and quote_is_usable(quote, now_ts=stamp, stale_seconds=stale_quote_seconds)
        if not use_live and not gap:
            plan.append((row, None))
            continue
        series = _series_through(history.get(code, ()), expected_date)
        if not series or series[-1].trade_date != expected_date:
            excluded.append(code)  # 직전 거래일 일봉을 못 구한 종목(보충 실패·교차검증 불일치·거래정지 등)
            continue
        closes = [b.close for b in reversed(series)]
        volumes = [b.volume for b in reversed(series)]
        if use_live:
            assert quote is not None
            closes.insert(0, _decimal(quote.price))
            volumes.insert(0, int(quote.volume))
        computed[code] = compute_row_metrics(closes, volumes)
        plan.append((row, "live" if use_live else "daily"))
        if use_live:
            live_codes.add(code)

    # 2) 등락률 순위 정책: 오늘 행 기준 시세 커버율 ≥ coverage_min이면 시세를 받은 종목끼리 다시 순위를 매긴다
    total = len(published_rows)
    covered = len(live_codes)
    coverage = covered / total if total else 0.0
    rank_live = live_possible and covered > 0 and coverage >= coverage_min
    live_ranks: dict[str, Decimal] = {}
    if rank_live:
        live_ranks = rank_percentile(
            [(c, computed[c]["return_pct"]) for c in live_codes if computed[c]["return_pct"] is not None],
            descending=True,
        )
    daily_ranks: dict[str, Decimal] = {}
    if gap:  # 발행 순위(P 기준)는 낡았으므로 E 기준 등락률로 다시 매긴다
        daily_ranks = rank_percentile(
            [
                (c, m["return_pct"])
                for c, m in computed.items()
                if c not in live_codes and m["return_pct"] is not None
            ],
            descending=True,
        )

    # 3) 결과 행 조립
    for row, kind in plan:
        code = row["stock_code"]
        if kind is None:
            basis[code] = "daily"
            rows.append(row)
            continue
        row.update(computed[code])
        if kind == "live":
            if rank_live:
                row["return_rank_pct"] = live_ranks.get(code)
        elif gap:
            row["return_rank_pct"] = daily_ranks.get(code)
        basis[code] = kind
        rows.append(row)

    recomputed = list(RECOMPUTED_COLUMNS) + (["return_rank_pct"] if rank_live or (gap and daily_ranks) else [])
    meta: dict[str, Any] = {
        "covered": covered,
        "total": total,
        "coverage_ratio": round(coverage, 4),
        "recomputed": recomputed,
        "fixed_daily": list(FIXED_DAILY_COLUMNS),
        "volume_partial": True,
        "return_rank_policy": "live" if rank_live else "daily",
        "excluded": len(excluded),
        "compute_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    return LiveRowsResult(rows=rows, basis=basis, meta=meta, excluded=excluded)
