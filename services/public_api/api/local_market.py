"""본인 전용 전 종목 준실시간 시세 스냅샷 API (DEC-084). **내 PC 전용**, 기본 꺼짐, 소유자(관리자)만.

- `GET /api/v1/local/market/quotes?codes=005930,000660` — 요청한 종목의 최신 시세(최대 100개). 값이 없는 종목은 `missing`에 적는다(0으로 채우지 않음).
- `GET /api/v1/local/market/status` — 순환 상태(폴러를 시작하지도, 유휴 시간을 늘리지도 않는다).
접근 통제는 `local_realtime.require_owner`를 그대로 쓴다(개인 로컬 모드 4중 통제 + 로그인을 켠 환경은 관리자만).

수명: 폴러는 `quotes`의 첫 요청 때 시작하고, 마지막 `quotes` 요청 뒤 `KIS_MARKET_IDLE_SECONDS`(기본 300초)가 지나면 멈춘다(증권사 호출 중단).
종목 유니버스(활성 종목 코드)는 시작 때와 이후 1시간마다 다시 읽고, 읽기에 실패하거나 0건이면 이전 목록을 유지한다.
증권사 클라이언트는 `shared_intraday_service`가 가진 인스턴스를 그대로 써서 토큰·호출 간격을 상세 화면(REST)과 공유한다.
앱키·접속키는 응답·로그에 나오지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from services.public_api.api.local_intraday import shared_intraday_service
from services.public_api.api.local_realtime import KST, require_owner
from services.public_api.db.session import get_session_factory
from services.public_api.db.stock_repository import list_active_stock_codes
from services.public_api.errors import ApiError
from services.public_api.intraday import config as cfg
from services.public_api.intraday.service import IntradayService
from services.public_api.realtime.market import (
    MarketQuote,
    MarketSnapshotPoller,
    PollerConfig,
    calls_per_cycle,
    default_market_open,
    make_kis_fetcher,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/local/market", tags=["local-market"])

MAX_CODES = 100
CODE_RE = re.compile(r"[0-9A-Z]{6}")
IDLE_SECONDS_DEFAULT = 300.0
UNIVERSE_REFRESH_SECONDS = 3600.0
UNIVERSE_RETRY_SECONDS = 30.0  # 읽기에 실패했을 때 다시 시도하기까지(갱신 주기보다 길지 않게 제한됨)
STALE_FACTOR = 3.0  # 마지막 갱신이 주기의 이 배수보다 오래되면 stale


def load_active_codes() -> list[str]:
    """DB(`public_serving.stock_master`, `api_service`는 SELECT 권한)에서 활성 종목 코드를 읽는다(동기 — 스레드에서 실행)."""
    session = get_session_factory()()
    try:
        return list_active_stock_codes(session)
    finally:
        session.close()


_universe_loader: Callable[[], list[str]] = load_active_codes


def set_universe_loader(loader: Callable[[], list[str]] | None) -> None:
    """종목 유니버스 읽기 함수를 바꾼다(시험용 주입). None이면 DB 읽기로 되돌린다. 이미 만들어진 런타임에도 즉시 적용된다."""
    global _universe_loader
    _universe_loader = loader or load_active_codes


def _idle_seconds() -> float:
    raw = os.environ.get("KIS_MARKET_IDLE_SECONDS", "").strip()
    try:
        return max(0.1, float(raw)) if raw else IDLE_SECONDS_DEFAULT
    except ValueError:
        return IDLE_SECONDS_DEFAULT


class MarketRuntime:
    """폴러·종목 유니버스·유휴 정지를 묶는다(단일 asyncio 루프에서 사용)."""

    def __init__(
        self,
        service: IntradayService,
        *,
        idle_seconds: float,
        universe_refresh: float,
        universe_retry: float,
        config: PollerConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        is_market_open: Callable[[datetime], bool] = default_market_open,
    ) -> None:
        self.service = service
        self.idle_seconds = idle_seconds
        self._refresh = universe_refresh
        self._retry = universe_retry
        self._cfg = config or PollerConfig()
        self._clock = clock
        self._wall = wall_clock
        self._is_open = is_market_open
        self.poller = MarketSnapshotPoller(
            make_kis_fetcher(service.client), (), self._cfg, wall_clock=wall_clock, is_market_open=is_market_open
        )
        self._lock = asyncio.Lock()
        self._maint: asyncio.Task[None] | None = None
        self._last_touch = clock()
        self._next_refresh_at = -float("inf")
        self.universe_loaded_at: float | None = None  # epoch 초
        self.universe_failures = 0
        self.universe_error: str | None = None  # 마지막 읽기 실패의 예외 종류(메시지는 싣지 않는다)
        self.starts_total = 0
        self.idle_stops_total = 0

    # ── 종목 유니버스 ─────────────────────────────────────────────────────────
    async def refresh_universe(self) -> bool:
        """종목 목록을 다시 읽는다. 실패하거나 0건이면 이전 목록을 그대로 두고 False."""
        try:
            raw = await asyncio.to_thread(_universe_loader)
            codes = [c for c in dict.fromkeys(str(c) for c in raw) if CODE_RE.fullmatch(c)]
            if not codes:
                raise ValueError("종목 목록이 비어 있습니다.")
        except Exception as exc:  # noqa: BLE001 — DB 오류 종류는 다양하다. 이전 목록을 유지하고 계속한다
            self.universe_failures += 1
            self.universe_error = type(exc).__name__
            self._next_refresh_at = self._clock() + min(self._retry, self._refresh)
            logger.warning("종목 목록 읽기 실패(%s), 이전 목록(%d개) 유지", type(exc).__name__, len(self.poller.codes))
            return False
        self.poller.set_codes(codes)
        self.universe_loaded_at = self._wall()
        self.universe_error = None
        self._next_refresh_at = self._clock() + self._refresh
        return True

    # ── 수명 ──────────────────────────────────────────────────────────────────
    def touch(self) -> None:
        self._last_touch = self._clock()

    async def ensure_started(self) -> None:
        """마지막 요청 시각을 갱신하고, 멈춰 있으면 폴러를 (다시) 시작한다."""
        self.touch()
        async with self._lock:
            if self._clock() >= self._next_refresh_at:
                await self.refresh_universe()
            if not self.poller.running:
                self.poller.start()
                self.starts_total += 1
            if self._maint is None or self._maint.done():
                self._maint = asyncio.get_running_loop().create_task(self._maintain(), name="market-runtime-maintenance")

    async def _maintain(self) -> None:
        tick = min(5.0, max(0.05, self.idle_seconds / 4))
        while True:
            await asyncio.sleep(tick)
            if self._clock() - self._last_touch >= self.idle_seconds:
                async with self._lock:
                    if self._clock() - self._last_touch >= self.idle_seconds:  # 잠금을 기다리는 사이 새 요청이 왔으면 계속
                        await self.poller.stop()
                        self.idle_stops_total += 1
                        self._maint = None
                        logger.info("전 종목 시세 순환 정지(마지막 요청 후 %.0f초 경과)", self.idle_seconds)
                        return
                continue
            if self._clock() >= self._next_refresh_at:
                async with self._lock:
                    if self._clock() >= self._next_refresh_at:
                        await self.refresh_universe()

    async def close(self) -> None:
        maint, self._maint = self._maint, None
        if maint is not None and maint is not asyncio.current_task():
            maint.cancel()
            try:
                await maint
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self.poller.stop()

    # ── 조회 ──────────────────────────────────────────────────────────────────
    def cycle_seconds(self) -> float | None:
        """한 바퀴 시작 간격의 현재 추정치(초). 아직 한 바퀴도 돌지 않았으면 None."""
        last = self.poller.last_cycle_seconds
        if last is None:
            return None
        if self._is_open(datetime.fromtimestamp(self._wall(), tz=KST)):
            # 첫 바퀴는 호출 간격 대기가 없어 측정 시간이 실제 주기보다 짧을 수 있으므로, 호출 수 × 최소 간격을 하한으로 둔다
            floor = calls_per_cycle(len(self.poller.codes), self._cfg.batch_size) * self._cfg.min_interval
            return max(last, floor) + self._cfg.cycle_pause
        return max(self._cfg.off_hours_cycle_interval, last)

    def meta(self, snapshot: dict[str, MarketQuote]) -> dict[str, Any]:
        cycle = self.cycle_seconds()
        last = self.poller.last_full_cycle_at  # 모든 묶음이 성공한 마지막 한 바퀴의 끝(일부 묶음이 계속 실패하면 갱신되지 않아 stale로 보인다)
        stale = last is None or cycle is None or (self._wall() - last) > STALE_FACTOR * cycle
        return {
            "cycle_seconds": None if cycle is None else round(cycle, 3),
            "last_cycle_at": last,
            "covered": len(snapshot),
            "total": len(self.poller.codes),
            "stale": stale,
            "running": self.poller.running,
        }

    def view(self, codes: list[str]) -> dict[str, Any]:
        snapshot = self.poller.snapshot()
        quotes: list[dict[str, Any]] = []
        missing: list[str] = []
        for code in codes:
            q = snapshot.get(code)
            if q is None:
                missing.append(code)
                continue
            quotes.append(
                {
                    "code": code, "price": q.price, "change": q.change, "change_pct": q.change_pct, "volume": q.volume,
                    "open": q.open, "high": q.high, "low": q.low, "fetched_at": q.fetched_at,
                }
            )
        return {"quotes": quotes, "missing": missing, "meta": self.meta(snapshot)}

    def status(self) -> dict[str, Any]:
        snapshot = self.poller.snapshot()
        return {
            "configured": True,
            **self.meta(snapshot),
            "idle_seconds": self.idle_seconds,
            "idle_stop_in": max(0.0, round(self.idle_seconds - (self._clock() - self._last_touch), 3)) if self.poller.running else None,
            "universe": {
                "total": len(self.poller.codes),
                "loaded_at": self.universe_loaded_at,
                "failures": self.universe_failures,
                "last_error": self.universe_error,
            },
            "starts_total": self.starts_total,
            "idle_stops_total": self.idle_stops_total,
            "poller": self.poller.metrics(),
        }


_runtime: MarketRuntime | None = None


def get_runtime(settings: cfg.IntradaySettings) -> MarketRuntime:
    """프로세스당 하나. 증권사 클라이언트를 가진 서비스가 바뀌면(앱키·주소 변경) 새로 만들고 옛것은 정리한다."""
    global _runtime
    service = shared_intraday_service(settings)  # 상세 화면 REST·실시간 시작 값과 같은 KisClient(토큰·호출 간격 공유)
    if _runtime is None or _runtime.service is not service:
        old = _runtime
        _runtime = MarketRuntime(
            service, idle_seconds=_idle_seconds(), universe_refresh=UNIVERSE_REFRESH_SECONDS, universe_retry=UNIVERSE_RETRY_SECONDS
        )
        if old is not None:
            asyncio.get_running_loop().create_task(old.close())
    return _runtime


async def shutdown_market() -> None:
    """앱 종료 때 폴러와 유지 작업을 정리한다."""
    global _runtime
    if _runtime is not None:
        runtime, _runtime = _runtime, None
        await runtime.close()


def reset_market_runtime() -> None:
    """테스트 전용: 런타임을 버린다(정리는 호출 쪽 책임)."""
    global _runtime
    _runtime = None


def parse_codes(raw: str) -> list[str]:
    """쉼표로 구분한 종목코드를 검증한다(6자리 영숫자 대문자, 최대 100개). 중복은 처음 한 번만 남긴다."""
    parts = raw.split(",") if raw else []
    if not parts or len(parts) > MAX_CODES:
        raise ApiError(status_code=400, code="INVALID_PARAMETER", message=f"종목코드를 1~{MAX_CODES}개 입력하세요.")
    if any(not CODE_RE.fullmatch(p) for p in parts):
        raise ApiError(status_code=400, code="INVALID_PARAMETER", message="종목코드는 6자리 영숫자 대문자여야 합니다.")
    return list(dict.fromkeys(parts))


def _not_configured() -> ApiError:
    return ApiError(
        status_code=503,
        code="LOCAL_INTRADAY_NOT_CONFIGURED",
        message="증권사 앱키가 설정되지 않았습니다. KIS_APP_KEY·KIS_APP_SECRET을 확인하세요.",
    )


@router.get("/quotes")
async def market_quotes(
    response: Response,
    codes: str = Query("", description="쉼표로 구분한 종목코드(최대 100개)"),
    settings: cfg.IntradaySettings = Depends(require_owner),
) -> dict[str, Any]:
    wanted = parse_codes(codes)
    if not settings.configured:
        raise _not_configured()
    response.headers["Cache-Control"] = "no-store"
    runtime = get_runtime(settings)
    await runtime.ensure_started()
    return {"data": runtime.view(wanted), "error": None}


@router.get("/status")
async def market_status(response: Response, settings: cfg.IntradaySettings = Depends(require_owner)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    if not settings.configured:
        return {"data": {"configured": False}, "error": None}
    runtime = get_runtime(settings)
    return {"data": runtime.status(), "error": None}
