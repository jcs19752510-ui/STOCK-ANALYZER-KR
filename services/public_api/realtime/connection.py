"""증권사 웹소켓 연결 관리자 (DEC-084).

- 앱키당 **연결 1개**를 유지한다(구독 한도 40건 = 종목 20개 × 체결·호가). 끊기면 지수 백오프로 재연결하고 구독을 복구한다.
- 화면(구독자)이 보는 종목만 구독한다. 참조 카운트가 0이 되면 `grace`초 뒤에 해지한다(화면 전환·새로고침으로 구독을 헛되이 끊었다 붙이지 않음).
- 서버가 보내는 `PINGPONG`에는 반드시 pong으로 응답한다(안 하면 연결이 끊긴다). 일정 시간 아무 것도 못 받으면(`watchdog`) 재연결한다.
- 접속키는 메모리에만 두고 로그·오류 메시지에 싣지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx
from websockets.asyncio.client import connect as ws_connect

from services.public_api.intraday.config import IntradaySettings
from services.public_api.realtime import protocol as proto

logger = logging.getLogger(__name__)

APPROVAL_PATH = "/oauth2/Approval"
APPROVAL_TTL_SECONDS = 12 * 3600
WATCHDOG_SECONDS = 90.0  # 이 시간 동안 아무 것도(PINGPONG 포함) 못 받으면 재연결
GRACE_SECONDS = 30.0
BACKOFF_MIN = 1.0
BACKOFF_MAX = 30.0
# 접속키가 무효라는 응답(증권사 메시지 코드). 접속키를 버리고 새로 받아 재연결한다.
_INVALID_APPROVAL_CODES = frozenset({"OPSP0011"})


class RealtimeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CapacityError(RealtimeError):
    def __init__(self) -> None:
        super().__init__("REALTIME_CAPACITY", f"동시에 실시간으로 볼 수 있는 종목은 {proto.MAX_CODES}개까지입니다.")


def _describe(exc: BaseException) -> str:
    """오류를 짧게 요약한다(주소·키가 섞이지 않도록 종류와 짧은 설명만)."""
    text = " ".join(str(exc).split())[:80]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class KisWsManager:
    def __init__(
        self,
        settings: IntradaySettings,
        on_data: Callable[[proto.DataFrame], None],
        on_state: Callable[[str, str | None], None] | None = None,
        *,
        connect: Callable[..., Any] = ws_connect,
        http_factory: Callable[[], httpx.AsyncClient] | None = None,
        grace: float = GRACE_SECONDS,
        watchdog: float = WATCHDOG_SECONDS,
        backoff_min: float = BACKOFF_MIN,
        backoff_max: float = BACKOFF_MAX,
        jitter: float = 0.5,
        sleep: Callable[[float], Any] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._s = settings
        self._on_data = on_data
        self._on_state = on_state
        self._connect = connect
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(timeout=10.0))
        self._grace = grace
        self._watchdog = watchdog
        self._backoff_min = backoff_min
        self._backoff_max = backoff_max
        self._jitter = jitter
        self._sleep = sleep
        self._clock = clock
        self._refs: dict[str, int] = {}
        self._codes: set[str] = set()
        self._grace_handles: dict[str, asyncio.TimerHandle] = {}
        self._changed = asyncio.Event()
        self._outbox: asyncio.Queue[str] | None = None
        self._key: str | None = None
        self._approval: tuple[str, float] | None = None
        self._task: asyncio.Task[None] | None = None
        self.state = "idle"
        self.last_error: str | None = None
        self.last_rx: float | None = None
        self.connected_since: float | None = None
        self._rx_in_conn = 0

    # ── 구독 관리 ─────────────────────────────────────────────────────────
    @property
    def codes(self) -> frozenset[str]:
        return frozenset(self._codes)

    def add(self, code: str) -> None:
        handle = self._grace_handles.pop(code, None)
        if handle is not None:
            handle.cancel()
        if code not in self._codes:
            if len(self._codes) >= proto.MAX_CODES:
                victim = next(iter(self._grace_handles), None)  # 해지 대기 중인 종목이 있으면 그 자리를 쓴다
                if victim is None:
                    raise CapacityError()
                self._drop(victim)
            self._codes.add(code)
            self._enqueue(code, subscribe=True)
        self._refs[code] = self._refs.get(code, 0) + 1
        self._changed.set()

    def remove(self, code: str) -> None:
        n = self._refs.get(code, 0) - 1
        if n > 0:
            self._refs[code] = n
            return
        self._refs[code] = 0
        if code in self._codes and code not in self._grace_handles:
            loop = asyncio.get_running_loop()
            self._grace_handles[code] = loop.call_later(self._grace, self._drop, code)

    def _drop(self, code: str) -> None:
        handle = self._grace_handles.pop(code, None)
        if handle is not None:
            handle.cancel()
        if self._refs.get(code, 0) > 0:
            return
        self._refs.pop(code, None)
        if code in self._codes:
            self._codes.discard(code)
            self._enqueue(code, subscribe=False)
        self._changed.set()

    def _enqueue(self, code: str, *, subscribe: bool) -> None:
        if self._outbox is None or self._key is None:
            return  # 연결 전이면 연결할 때 전체 목록을 한 번에 보낸다
        for tr in (proto.TR_TRADE, proto.TR_BOOK):
            self._outbox.put_nowait(proto.build_subscribe(self._key, tr, code, subscribe=subscribe))

    # ── 상태 ──────────────────────────────────────────────────────────────
    def _set_state(self, state: str, detail: str | None = None) -> None:
        if state != self.state or detail is not None:
            self.state = state
            if self._on_state is not None:
                try:
                    self._on_state(state, detail)
                except Exception:  # 상태 알림 실패가 연결을 끊지 않게
                    logger.exception("실시간 상태 알림 실패")

    def info(self) -> dict[str, Any]:
        rx_age = None if self.last_rx is None else round(self._clock() - self.last_rx, 1)
        return {
            "state": self.state,
            "codes": sorted(self._codes),
            "capacity": proto.MAX_CODES,
            "last_error": self.last_error,
            "last_rx_age_seconds": rx_age,
        }

    # ── 접속키 ────────────────────────────────────────────────────────────
    async def _approval_key(self) -> str:
        now = self._clock()
        if self._approval is not None and self._approval[1] > now:
            return self._approval[0]
        try:
            async with self._http_factory() as http:
                resp = await http.post(
                    self._s.base_url + APPROVAL_PATH,
                    json={"grant_type": "client_credentials", "appkey": self._s.app_key, "secretkey": self._s.app_secret},
                    headers={"content-type": "application/json; charset=utf-8"},
                )
        except httpx.HTTPError as exc:
            raise RealtimeError("UPSTREAM_UNAVAILABLE", "증권사 서버에 연결하지 못했습니다.") from exc
        try:
            body = resp.json()
        except ValueError as exc:
            raise RealtimeError("UPSTREAM_BAD_RESPONSE", "증권사 응답을 해석할 수 없습니다.") from exc
        key = body.get("approval_key") if isinstance(body, dict) else None
        if resp.status_code != 200 or not isinstance(key, str) or not key:
            raise RealtimeError("AUTH_FAILED", "증권사 접속키 발급에 실패했습니다(앱키·시크릿을 확인하세요).")
        self._approval = (key, now + APPROVAL_TTL_SECONDS)
        return key

    # ── 본 루프 ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run(), name="kis-ws-manager")

    async def stop(self) -> None:
        for h in self._grace_handles.values():
            h.cancel()
        self._grace_handles.clear()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def run(self) -> None:
        backoff = self._backoff_min
        while True:
            if not self._codes:
                self._set_state("idle")
                self._changed.clear()
                if not self._codes:
                    await self._changed.wait()
                continue
            self._rx_in_conn = 0
            try:
                self._set_state("connecting")
                key = await self._approval_key()
                async with self._connect(self._s.ws_url, ping_interval=None, open_timeout=10, max_size=1 << 20) as ws:
                    self._key = key
                    self._outbox = asyncio.Queue()
                    for code in sorted(self._codes):
                        for tr in (proto.TR_TRADE, proto.TR_BOOK):
                            await ws.send(proto.build_subscribe(key, tr, code))
                    self.connected_since = self._clock()
                    self._set_state("connected")
                    writer = asyncio.create_task(self._writer(ws))
                    try:
                        await self._reader(ws)
                    finally:
                        writer.cancel()
                        try:
                            await writer
                        except (asyncio.CancelledError, Exception):
                            pass
            except asyncio.CancelledError:
                raise
            except RealtimeError as exc:
                self.last_error = f"{exc.code}: {exc.message}"
                if exc.code == "AUTH_FAILED":
                    self._approval = None
            except Exception as exc:
                self.last_error = _describe(exc)
                logger.warning("실시간 연결이 끊겼습니다: %s", self.last_error)
            finally:
                self._outbox = None
                self._key = None
                self.connected_since = None
            if not self._codes:
                continue
            if self._rx_in_conn > 0:  # 이번 연결에서 무언가 받았으면 정상으로 보고 대기 시간을 처음으로 되돌린다
                backoff = self._backoff_min
            self._set_state("reconnecting", self.last_error)
            await self._sleep(backoff + random.uniform(0, self._jitter))
            backoff = min(backoff * 2, self._backoff_max)

    async def _writer(self, ws: Any) -> None:
        assert self._outbox is not None
        while True:
            await ws.send(await self._outbox.get())

    async def _reader(self, ws: Any) -> None:
        """메시지를 받아 처리한다. 연결이 닫히거나 오류·무수신 시간 초과면 예외로 끝난다(바깥 루프가 재연결)."""
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=self._watchdog)
            self._rx_in_conn += 1
            self.last_rx = self._clock()
            frame = proto.parse_message(raw)
            if frame is None:
                continue
            if isinstance(frame, proto.ControlFrame):
                if frame.kind == "pingpong":
                    await ws.pong(raw)
                elif frame.kind == "subscribe_error":
                    self.last_error = f"{frame.msg_cd}: {frame.msg}"
                    logger.warning("실시간 구독 오류 %s", self.last_error)
                    if frame.msg_cd in _INVALID_APPROVAL_CODES:
                        self._approval = None
                        raise RealtimeError("AUTH_FAILED", "접속키가 유효하지 않습니다.")
                    self._set_state(self.state, self.last_error)
                continue
            try:
                self._on_data(frame)
            except Exception:  # 한 건 처리 실패가 연결을 끊지 않게
                logger.exception("실시간 데이터 처리 실패")
