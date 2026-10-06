"""전 종목 준실시간 시세 스냅샷(REST 멀티종목 시세 순환 호출) — 메모리만 사용한다.

증권사 웹소켓은 한 연결에 구독 40건이라 전 종목 틱 실시간이 불가능하다. 대신 관심종목 멀티종목 시세(한 번에 30종목)를
종목 목록 전체에 걸쳐 순환 호출해 최신 값을 메모리에 모아 둔다(한 바퀴 시간 = 호출 수 × 호출 간격).

- 일부 묶음이 실패해도 순환은 멈추지 않는다(실패한 묶음은 다음 주기에 다시 시도, 그 사이 이전 값은 `fetched_at`과 함께 남는다).
- `RATE_LIMITED`·일시 오류는 연속 실패 횟수에 따라 지수 백오프(+지터)로 다음 호출을 늦춘다.
- DB·디스크에 저장하지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from services.public_api.intraday.kis_client import MULTI_PRICE_MAX_CODES, KisError

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class MarketQuote:
    """한 종목의 최신 시세. `fetched_at`은 이 값을 받은 시각(epoch 초)."""

    code: str
    price: float
    change: float
    change_pct: float
    volume: int
    open: float
    high: float
    low: float
    fetched_at: float


def chunk_codes(codes: Iterable[str], size: int = MULTI_PRICE_MAX_CODES) -> list[list[str]]:
    """목록을 `size`개씩 묶는다(마지막 묶음만 작을 수 있다). 빈 목록이면 빈 결과."""
    size = max(1, min(size, MULTI_PRICE_MAX_CODES))
    items = list(codes)
    return [items[i : i + size] for i in range(0, len(items), size)]


def calls_per_cycle(n_codes: int, batch_size: int = MULTI_PRICE_MAX_CODES) -> int:
    size = max(1, min(batch_size, MULTI_PRICE_MAX_CODES))
    return math.ceil(max(n_codes, 0) / size)


def estimate_cycle_seconds(n_codes: int, calls_per_second: float, batch_size: int = MULTI_PRICE_MAX_CODES) -> float:
    """호출 한도가 초당 `calls_per_second`건일 때 전 종목 한 바퀴 이론 시간(응답 지연 제외)."""
    if calls_per_second <= 0:
        raise ValueError("calls_per_second는 0보다 커야 합니다.")
    return calls_per_cycle(n_codes, batch_size) / calls_per_second


def default_market_open(now: datetime) -> bool:
    """평일 08:00~20:00(KST, 통합시세 NXT 포함)이면 True. 공휴일은 알지 못한다(달력 주입 필요)."""
    now = now.astimezone(KST)
    return now.weekday() < 5 and 8 <= now.hour < 20


@dataclass(frozen=True)
class PollerConfig:
    batch_size: int = MULTI_PRICE_MAX_CODES
    min_interval: float = 0.2  # 호출 시작 간 최소 간격(초). 공식 한도 미확인 → 보수적 가정값(초당 5건)
    jitter_ratio: float = 0.1  # 간격에 0~10% 무작위 지연을 더한다
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    cycle_pause: float = 0.0  # 장중 한 바퀴 끝난 뒤 추가 대기(초)
    off_hours_cycle_interval: float = 300.0  # 장 시간 밖에서 한 바퀴 시작 간격(초)
    stop_timeout: float = 5.0


class MarketSnapshotPoller:
    """종목 목록을 30개씩 순환 조회해 최신 스냅샷을 유지한다(단일 asyncio 루프에서 사용)."""

    def __init__(
        self,
        fetch: Callable[[list[str]], dict[str, MarketQuote]],
        codes: Iterable[str] = (),
        config: PollerConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
        is_market_open: Callable[[datetime], bool] = default_market_open,
    ) -> None:
        self._fetch = fetch
        self._cfg = config or PollerConfig()
        self._clock = clock
        self._wall = wall_clock
        self._custom_sleep = sleep
        self._rng = rng or random.Random()
        self._is_open = is_market_open
        self._codes: list[str] = []
        self._quotes: dict[str, MarketQuote] = {}
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_call_start = -math.inf
        self._not_before = -math.inf
        self._consecutive_errors = 0
        self._cycle_started_at: float | None = None
        # 지표
        self.calls_total = 0
        self.errors_total = 0
        self.rate_limited_total = 0
        self.missing_total = 0  # 요청했지만 응답에서 빠졌거나 값이 이상해 버려진 종목 수 누계
        self.cycles_total = 0
        self.full_cycles_total = 0
        self.last_cycle_seconds: float | None = None
        self.last_full_cycle_at: float | None = None  # 모든 묶음이 성공한 한 바퀴의 끝 시각(epoch)
        self.last_error_code: str | None = None
        self.set_codes(codes)

    # ── 종목 목록·조회 ────────────────────────────────────────────────────────
    def set_codes(self, codes: Iterable[str]) -> None:
        """종목 목록을 교체한다(중복·빈 값 제거, 순서 유지). 새 목록은 다음 바퀴부터 쓰고, 빠진 종목의 값은 즉시 버린다."""
        seen: dict[str, None] = {}
        for c in codes:
            code = str(c or "").strip()
            if code:
                seen.setdefault(code, None)
        self._codes = list(seen)
        keep = set(self._codes)
        for code in [c for c in self._quotes if c not in keep]:
            del self._quotes[code]

    @property
    def codes(self) -> list[str]:
        return list(self._codes)

    def snapshot(self) -> dict[str, MarketQuote]:
        return dict(self._quotes)

    def get(self, code: str) -> MarketQuote | None:
        return self._quotes.get(code)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def metrics(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "codes": len(self._codes),
            "quotes": len(self._quotes),
            "calls_per_cycle": calls_per_cycle(len(self._codes), self._cfg.batch_size),
            "calls_total": self.calls_total,
            "errors_total": self.errors_total,
            "rate_limited_total": self.rate_limited_total,
            "missing_total": self.missing_total,
            "cycles_total": self.cycles_total,
            "full_cycles_total": self.full_cycles_total,
            "last_cycle_seconds": self.last_cycle_seconds,
            "last_full_cycle_at": self.last_full_cycle_at,
            "consecutive_errors": self._consecutive_errors,
            "last_error_code": self.last_error_code,
        }

    # ── 대기 ──────────────────────────────────────────────────────────────────
    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self._custom_sleep is not None:
            await self._custom_sleep(seconds)
            return
        try:  # 정지 요청이 오면 바로 깨어난다
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def _pace(self) -> None:
        """직전 호출 시작으로부터 최소 간격(+지터)을 지키고, 백오프 중이면 그 시각까지 기다린다."""
        interval = self._cfg.min_interval
        jitter = self._rng.uniform(0, self._cfg.jitter_ratio * interval) if self._cfg.jitter_ratio > 0 else 0.0
        target = max(self._last_call_start + interval + jitter, self._not_before)
        await self._sleep(target - self._clock())

    def _register_failure(self, code: str) -> float:
        self._consecutive_errors += 1
        self.errors_total += 1
        self.last_error_code = code
        if code == "RATE_LIMITED":
            self.rate_limited_total += 1
        delay = min(self._cfg.backoff_base * 2 ** (self._consecutive_errors - 1), self._cfg.backoff_max)
        delay *= 1 + self._rng.uniform(0, self._cfg.jitter_ratio)
        self._not_before = self._clock() + delay
        return delay

    # ── 한 바퀴 ───────────────────────────────────────────────────────────────
    async def run_cycle(self) -> bool:
        """종목 목록 전체를 한 번 순환한다. 모든 묶음이 성공하면 True. 정지 요청이 오면 중간에 멈춘다(False)."""
        codes = list(self._codes)
        batches = chunk_codes(codes, self._cfg.batch_size)
        started = self._clock()
        failed = 0
        interrupted = False
        for batch in batches:
            if self._stop.is_set():
                interrupted = True
                break
            await self._pace()
            if self._stop.is_set():
                interrupted = True
                break
            self._last_call_start = self._clock()
            self.calls_total += 1
            try:
                quotes = await asyncio.to_thread(self._fetch, batch)
            except asyncio.CancelledError:
                raise
            except KisError as exc:
                failed += 1
                delay = self._register_failure(exc.code)
                logger.warning("시세 묶음 조회 실패(%s), %.1f초 뒤 재시도 예정", exc.code, delay)
                continue
            except Exception:  # noqa: BLE001 — 한 묶음의 예기치 못한 오류가 순환 전체를 멈추면 안 된다
                failed += 1
                delay = self._register_failure("UNEXPECTED")
                logger.exception("시세 묶음 조회 중 예기치 못한 오류, %.1f초 뒤 재시도 예정", delay)
                continue
            self._consecutive_errors = 0
            wanted = set(batch)
            accepted = 0
            keep = set(self._codes)  # 조회 중 목록이 교체됐으면 빠진 종목은 저장하지 않는다
            for code, quote in quotes.items():
                if code in wanted and code in keep:
                    self._quotes[code] = quote
                    accepted += 1
            self.missing_total += len(wanted) - accepted
        self.last_cycle_seconds = self._clock() - started
        if interrupted:
            return False
        self.cycles_total += 1
        ok = failed == 0
        if ok and batches:
            self.full_cycles_total += 1
            self.last_full_cycle_at = self._wall()
        return ok

    # ── 시작/정지 ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        """백그라운드 순환을 시작한다(이미 실행 중이면 아무것도 하지 않는다)."""
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.get_running_loop().create_task(self._run(), name="market-snapshot-poller")

    async def stop(self) -> None:
        """진행 중인 호출이 끝나면 멈춘다. `stop_timeout` 안에 끝나지 않으면 작업을 취소한다."""
        task = self._task
        self._stop.set()
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._cfg.stop_timeout)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        except asyncio.CancelledError:
            raise
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            cycle_start = self._clock()
            if not self._codes:
                await self._sleep(1.0)
                continue
            await self.run_cycle()
            if self._stop.is_set():
                break
            now_open = self._is_open(datetime.fromtimestamp(self._wall(), tz=KST))
            if now_open:
                await self._sleep(self._cfg.cycle_pause)
            else:
                # 장 시간 밖: 첫 바퀴(마감 값 채우기) 이후에는 느리게 돈다
                await self._sleep(self._cfg.off_hours_cycle_interval - (self._clock() - cycle_start))


def make_kis_fetcher(client: Any, clock: Callable[[], float] = time.time) -> Callable[[list[str]], dict[str, MarketQuote]]:
    """`KisClient.multi_price` 응답을 정규화하는 블로킹 조회 함수를 만든다(스레드에서 실행됨)."""
    from services.public_api.intraday.normalize import normalize_multi_price

    def fetch(codes: list[str]) -> dict[str, MarketQuote]:
        body = client.multi_price(codes)
        rows = body.get("output") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return {}
        return normalize_multi_price([r for r in rows if isinstance(r, dict)], fetched_at=clock())

    return fetch
