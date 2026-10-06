"""발행 일봉이 직전 거래일보다 뒤처졌을 때 증권사 일봉으로 빠진 날만 보충한다(DEC-090, 계약서 §7). 메모리 전용 — DB에 쓰지 않는다.

- 종목당 한 번 조회(`KisClient.daily_price`, 낮은 우선순위·호출 간격 공유). 실패는 몇 번 더 시도하고 그래도 안 되면 그 종목은 뺀다.
- **교차검증**: 증권사 응답에 발행 마지막 거래일(P)의 행이 있고 종가가 발행 일봉과 같아야 보충을 믿는다(수정주가·종목 불일치 방어).
  필요한 모든 거래일(P 초과 ~ E 이하)이 응답에 있어야 한다(없으면 거래정지·상장 직후 등으로 보고 뺀다).
"""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from services.public_api.live_screen.types import DailyBar

logger = logging.getLogger(__name__)

REASON_OK = "ok"
REASON_NO_ANCHOR = "no_anchor"  # 응답에 발행 마지막 거래일(P) 행이 없다
REASON_MISMATCH = "mismatch"  # P 종가가 발행 일봉과 다르다
REASON_MISSING_DATES = "missing_dates"  # P 초과 ~ E 이하 거래일 중 응답에 없는 날이 있다


def validate_fill(
    kis_bars: Sequence[DailyBar], anchor: DailyBar, needed_dates: Sequence[date]
) -> tuple[list[DailyBar] | None, str]:
    """증권사 일봉을 교차검증하고, 통과하면 필요한 날짜의 일봉만 날짜 오름차순으로 돌려준다."""
    by_day = {b.trade_date: b for b in kis_bars}
    got = by_day.get(anchor.trade_date)
    if got is None:
        return None, REASON_NO_ANCHOR
    if got.close != anchor.close:
        return None, REASON_MISMATCH
    if any(d not in by_day for d in needed_dates):
        return None, REASON_MISSING_DATES
    return [by_day[d] for d in sorted(needed_dates)], REASON_OK


@dataclass
class FillStatus:
    key: tuple[date, date]  # (발행 거래일 P, 직전 거래일 E)
    needed_dates: tuple[date, ...]
    total: int = 0
    attempted: int = 0  # 한 번이라도 시도가 끝난 종목 수
    filled: int = 0
    mismatched: int = 0
    missing: int = 0  # 응답에 P 행이나 필요한 날짜가 없는 종목
    failed: int = 0  # 시도했지만 실패(재시도 대기 또는 횟수 소진)
    state: str = "running"  # running | ready
    started_at: float = 0.0
    finished_at: float | None = None
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        return self.attempted / self.total if self.total else 1.0


class BaseFiller:
    """(P, E) 하나에 대한 보충 작업을 백그라운드로 돌린다. `ensure`는 진행 상태를 즉시 돌려주고 작업이 없으면 시작한다."""

    def __init__(
        self,
        fetch: Callable[[str], list[DailyBar]],
        *,
        workers: int = 4,
        max_attempts: int = 3,
        retry_delay: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        self._fetch = fetch
        self._workers = max(1, workers)
        self._max_attempts = max(1, max_attempts)
        self._retry_delay = retry_delay
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._status: FillStatus | None = None
        self._bars: dict[str, list[DailyBar]] = {}
        self._task: asyncio.Task[None] | None = None
        self.fetch_calls = 0

    # ── 조회 ──────────────────────────────────────────────────────────────────
    def status(self) -> FillStatus | None:
        return self._status

    def bars(self) -> dict[str, list[DailyBar]]:
        """검증을 통과한 종목의 보충 일봉(P 초과 ~ E 이하). 작업 중에도 지금까지의 값을 돌려준다."""
        return dict(self._bars)

    # ── 시작 ──────────────────────────────────────────────────────────────────
    def ensure(
        self, key: tuple[date, date], needed_dates: Sequence[date], anchors: Mapping[str, DailyBar]
    ) -> FillStatus:
        """`key` 작업의 상태를 돌려준다. 다른 key의 작업이면 취소하고 새로 시작한다(같은 key면 이어서 쓴다)."""
        if self._status is not None and self._status.key == key:
            return self._status
        self._cancel()
        self._bars = {}
        self._status = FillStatus(
            key=key, needed_dates=tuple(needed_dates), total=len(anchors), started_at=self._clock()
        )
        if not anchors:
            self._status.state = "ready"
            self._status.finished_at = self._clock()
            return self._status
        self._task = asyncio.get_running_loop().create_task(
            self._run(self._status, dict(anchors)), name="live-base-fill"
        )
        return self._status

    def _cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def wait(self) -> None:
        """시험·종료용: 진행 중인 작업이 끝날 때까지 기다린다."""
        task = self._task
        if task is not None:
            await task

    # ── 작업 ──────────────────────────────────────────────────────────────────
    async def _run(self, st: FillStatus, anchors: dict[str, DailyBar]) -> None:
        queue: deque[tuple[str, int]] = deque((c, 1) for c in anchors)
        retry: list[tuple[str, int]] = []
        first_seen: set[str] = set()

        def settle(code: str, reason: str, attempt: int, bars: list[DailyBar] | None) -> None:
            if code not in first_seen:
                first_seen.add(code)
                st.attempted += 1
            if reason == REASON_OK and bars is not None:
                self._bars[code] = bars
                st.filled += 1
            elif reason == REASON_MISMATCH:
                st.mismatched += 1
            elif reason in (REASON_NO_ANCHOR, REASON_MISSING_DATES):
                st.missing += 1
            if reason != REASON_OK:
                st.reasons[reason] = st.reasons.get(reason, 0) + 1

        async def worker() -> None:
            while queue:
                code, attempt = queue.popleft()
                self.fetch_calls += 1
                try:
                    kis_bars = await asyncio.to_thread(self._fetch, code)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — 한 종목의 실패가 전체를 멈추면 안 된다
                    logger.warning("일봉 보충 조회 실패(%s): %s", code, type(exc).__name__)
                    if code not in first_seen:
                        first_seen.add(code)
                        st.attempted += 1
                    if attempt < self._max_attempts:
                        retry.append((code, attempt + 1))
                    else:
                        st.failed += 1
                        st.reasons["failed"] = st.reasons.get("failed", 0) + 1
                    continue
                bars, reason = validate_fill(kis_bars, anchors[code], st.needed_dates)
                settle(code, reason, attempt, bars)

        try:
            while queue or retry:
                await asyncio.gather(*(worker() for _ in range(self._workers)))
                if retry:
                    await self._sleep(self._retry_delay)
                    queue.extend(retry)
                    retry.clear()
        except asyncio.CancelledError:
            raise
        st.state = "ready"
        st.finished_at = self._clock()
