"""장중 재계산 서비스 — 발행 행·이력·일봉 보충·시세를 모아 스냅샷을 만든다(DEC-089·090). DB·증권사는 주입받는다(시험 가능)."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from services.public_api.live_screen.fill import BaseFiller, FillStatus
from services.public_api.live_screen.history import HistoryCache
from services.public_api.live_screen.rows import build_live_rows
from services.public_api.live_screen.snapshot import Snapshot, SnapshotStore
from services.public_api.live_screen.types import DailyBar
from services.public_api.realtime.market import MarketQuote

MIN_INTERVAL_DEFAULT = 5.0  # 이 간격 안의 요청은 직전 스냅샷을 재사용한다(LIVE_SCREEN_MIN_INTERVAL)
REFRESH_SECONDS_DEFAULT = 10.0
MAX_GAP_DAYS = 5
FILL_READY_RATIO = 0.9


class LiveScreenError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


@dataclass
class PublishedContext:
    published_date: date
    expected_date: date
    today: date
    trading_today: bool
    needed_dates: list[date]  # 발행일 초과 ~ 직전 거래일 이하의 거래일(오름차순). 뒤처지지 않았으면 빈 목록
    rows: list[dict[str, Any]]  # 발행 행(`derived_metrics_daily`, 발행 거래일)


@dataclass
class QuoteState:
    quotes: Mapping[str, MarketQuote]
    stale: bool
    running: bool = False
    universe_total: int = 0


@dataclass
class ServiceDeps:
    load_context: Callable[[], PublishedContext]
    load_history: Callable[[date], dict[str, list[DailyBar]]]
    quote_state: Callable[[], Any]  # async 또는 sync 둘 다 허용: QuoteState를 돌려준다(폴러 시작 포함)
    filler: BaseFiller | None = None
    clock: Callable[[], float] = time.time
    min_interval: float = MIN_INTERVAL_DEFAULT
    refresh_seconds: float = REFRESH_SECONDS_DEFAULT
    max_gap_days: int = MAX_GAP_DAYS
    fill_ready_ratio: float = FILL_READY_RATIO
    store: SnapshotStore | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class LiveScreenService:
    def __init__(self, deps: ServiceDeps) -> None:
        self._d = deps
        self.store = deps.store or SnapshotStore(clock=deps.clock)
        self.history = HistoryCache(deps.load_history)
        self._lock = asyncio.Lock()
        self.computes_total = 0

    # ── 공개 ──────────────────────────────────────────────────────────────────
    async def acquire(self, snapshot_id: str | None) -> Snapshot:
        """`snapshot_id`가 있으면 그 스냅샷(없으면 410), 없으면 최신(최소 간격 안이면 재사용, 아니면 새로 계산)."""
        if snapshot_id:
            snap = self.store.get(snapshot_id)
            if snap is None:
                raise LiveScreenError(410, "SNAPSHOT_EXPIRED", "계산 결과가 만료되었습니다. 새로 계산하세요.")
            return snap
        snap = self.store.latest(self._d.min_interval)
        if snap is not None:
            return snap
        async with self._lock:  # 동시 요청이 계산을 여러 번 하지 않도록 한 번에 하나만
            snap = self.store.latest(self._d.min_interval)
            if snap is not None:
                return snap
            return await self._compute()

    async def recompute(self) -> Snapshot:
        """최소 간격과 상관없이 새로 계산한다(화면의 "새로 계산" 버튼)."""
        async with self._lock:
            return await self._compute()

    # ── 계산 ──────────────────────────────────────────────────────────────────
    async def _quote_state(self) -> QuoteState:
        res = self._d.quote_state()
        if asyncio.iscoroutine(res):
            res = await res
        return res

    async def _compute(self) -> Snapshot:
        d = self._d
        ctx: PublishedContext = await asyncio.to_thread(d.load_context)
        gap = ctx.published_date < ctx.expected_date
        if len(ctx.needed_dates) > d.max_gap_days:
            raise LiveScreenError(
                409,
                "LIVE_BASE_STALE",
                f"일봉 데이터가 직전 거래일({ctx.expected_date.isoformat()})보다 {d.max_gap_days}거래일 넘게 뒤처져 "
                f"장중 재계산을 쓸 수 없습니다. (현재 {ctx.published_date.isoformat()})",
            )
        live_possible = ctx.trading_today and ctx.expected_date < ctx.today
        qs = await self._quote_state()

        history = await asyncio.to_thread(self.history.get, ctx.published_date)
        fill_status: FillStatus | None = None
        merged: Mapping[str, list[DailyBar]] = history
        if gap:
            if d.filler is None:
                raise LiveScreenError(
                    409, "LIVE_BASE_STALE", "일봉 보충을 쓸 수 없어 장중 재계산을 쓸 수 없습니다."
                )
            anchors: dict[str, DailyBar] = {}
            for row in ctx.rows:
                code = row["stock_code"]
                bars = history.get(code)
                if bars and bars[-1].trade_date == ctx.published_date:
                    anchors[code] = bars[-1]
            fill_status = d.filler.ensure(
                (ctx.published_date, ctx.expected_date), ctx.needed_dates, anchors
            )
            if fill_status.ratio < d.fill_ready_ratio:
                raise LiveScreenError(
                    503,
                    "LIVE_BASE_FILLING",
                    "직전 거래일 일봉을 증권사에서 보충하는 중입니다"
                    f"({fill_status.attempted}/{fill_status.total}). 잠시 후 다시 시도하세요.",
                    {"done": fill_status.attempted, "total": fill_status.total, "gap_days": len(ctx.needed_dates)},
                )
            extra = d.filler.bars()
            merged = {c: (b + extra[c] if c in extra else b) for c, b in history.items()}

        # 일봉 보충과 시세 수집은 동시에 진행되므로, 보충 진행 여부를 먼저 알리고 그다음에 시세 준비를 확인한다.
        if live_possible and not qs.quotes:
            raise LiveScreenError(
                503, "LIVE_QUOTES_NOT_READY", "시세를 모으는 중입니다. 잠시 후 다시 시도하세요."
            )

        now_ts = d.clock()
        result = await asyncio.to_thread(
            lambda: build_live_rows(
                ctx.rows,
                merged,
                qs.quotes,
                today=ctx.today,
                basis_date=ctx.published_date,
                expected_date=ctx.expected_date,
                trading_today=ctx.trading_today,
                now_ts=now_ts,
            )
        )
        self.computes_total += 1
        published_codes = {r["stock_code"] for r in ctx.rows}
        ages = [now_ts - q.fetched_at for c, q in qs.quotes.items() if c in published_codes]
        info: dict[str, Any] = {
            "as_of": now_ts,
            "basis_trade_date": ctx.published_date.isoformat(),
            "expected_trade_date": ctx.expected_date.isoformat(),
            "today": ctx.today.isoformat(),
            "quotes_covered": result.meta["covered"],
            "quotes_total": result.meta["total"],
            "coverage_ratio": result.meta["coverage_ratio"],
            "oldest_quote_age_seconds": round(max(ages), 1) if ages else None,
            "stale": bool(qs.stale),
            "volume_partial": True,
            "recomputed": result.meta["recomputed"],
            "fixed_daily": result.meta["fixed_daily"],
            "return_rank_policy": result.meta["return_rank_policy"],
            "compute_ms": result.meta["compute_ms"],
            "refresh_seconds": max(d.refresh_seconds, d.min_interval),
            "base_fill": _fill_meta(len(ctx.needed_dates), fill_status, result.meta["excluded"]),
        }
        return self.store.add(result, info, ctx.published_date)


def _fill_meta(gap_days: int, st: FillStatus | None, excluded: int) -> dict[str, Any]:
    if st is None or gap_days == 0:
        return {
            "gap_days": 0, "state": "none", "done": 0, "total": 0, "filled": 0,
            "excluded": 0, "mismatched": 0, "pending": 0, "source": None,
        }
    return {
        "gap_days": gap_days,
        "state": st.state,
        "done": st.attempted,
        "total": st.total,
        "filled": st.filled,
        "excluded": excluded,
        "mismatched": st.mismatched,
        "pending": max(0, st.total - st.filled - st.mismatched - st.missing - st.failed),
        "source": "kis_daily_price",
    }
