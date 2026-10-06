"""실시간 서비스: 연결 관리자 + 허브 + 시작 값(REST) 조합 (DEC-084).

화면(구독자)이 열리면 ① 그 종목의 오늘 1분봉·최근 체결을 REST로 한 번 채우고(시작 값) ② 증권사 웹소켓 구독을 건 뒤
③ 이후는 실시간 체결·호가만으로 갱신한다. 시작 값 조회가 실패해도 실시간은 계속된다(과거 구간만 비어 있다).
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from services.public_api.intraday.config import IntradaySettings
from services.public_api.intraday.kis_client import KisError
from services.public_api.intraday.normalize import normalize_multi_price
from services.public_api.realtime import protocol as proto
from services.public_api.realtime.connection import KisWsManager
from services.public_api.realtime.hub import RealtimeHub, Subscriber

logger = logging.getLogger(__name__)

SEED_TICKS = 120


class RealtimeService:
    def __init__(
        self,
        settings: IntradaySettings,
        seed_fetcher: Callable[[str], tuple[Any, ...]] | None = None,
        *,
        manager_factory: Callable[..., KisWsManager] = KisWsManager,
    ) -> None:
        self._settings = settings
        self._seed_fetcher = seed_fetcher
        self.hub = RealtimeHub()
        self.manager = manager_factory(settings, self._on_data, self._on_state)
        self._seed_locks: dict[str, asyncio.Lock] = {}

    # ── 구독자 열기/닫기 ───────────────────────────────────────────────────
    async def open(self, code: str) -> tuple[Subscriber, dict[str, Any]]:
        """구독자를 만들고 현재 상태 스냅샷을 돌려준다. 동시 종목 한도를 넘으면 `CapacityError`."""
        self.manager.start()
        state = self.hub.state(code)
        if not state.seeded:
            lock = self._seed_locks.setdefault(code, asyncio.Lock())
            async with lock:
                if not state.seeded:
                    await self._seed(code)
        sub = self.hub.subscribe(code)
        try:
            self.manager.add(code)
        except Exception:
            self.hub.unsubscribe(sub)
            self.hub.drop_state(code)
            raise
        snapshot = state.snapshot()
        snapshot["connection"] = self.manager.info()["state"]
        return sub, snapshot

    async def close(self, sub: Subscriber) -> None:
        self.hub.unsubscribe(sub)
        self.manager.remove(sub.code)
        if self.hub.subscriber_count(sub.code) == 0:
            # 상태(최신값)는 해지 유예 시간 동안 남겨 두었다가 구독이 정말 끝나면 버린다(메모리 정리)
            loop = asyncio.get_running_loop()
            loop.call_later(self.manager._grace + 1.0, self._cleanup, sub.code)

    def _cleanup(self, code: str) -> None:
        if code not in self.manager.codes:
            self.hub.drop_state(code)
            self._seed_locks.pop(code, None)

    async def stop(self) -> None:
        await self.manager.stop()

    # ── 시작 값 ───────────────────────────────────────────────────────────
    async def _seed(self, code: str) -> None:
        state = self.hub.state(code)
        if self._seed_fetcher is None:
            state.seeded = True
            return
        try:
            fetched = await asyncio.to_thread(self._seed_fetcher, code)
            bars, ticks, business_date = fetched[0], fetched[1], fetched[2]
            quote = fetched[3] if len(fetched) > 3 else None  # (선택) REST 현재가: 첫 실시간 체결 전에도 현재가를 보여 준다
        except KisError as exc:
            logger.warning("실시간 시작 값을 가져오지 못했습니다(%s). 실시간만 표시합니다.", exc.code)
            state.seeded = False
            return
        except Exception:
            logger.exception("실시간 시작 값 조회 실패")
            state.seeded = False
            return
        if state.live_date and business_date and business_date != state.live_date:
            # 시작 값이 실시간 체결의 거래일과 다르다(장 시작 직후 오늘 분봉이 아직 비어 직전 거래일로 대체된 경우 등):
            # 어제 분봉이 오늘 것과 섞이지 않도록 버리고, 실시간으로 쌓은 오늘 상태만 쓴다.
            logger.info("시작 값의 거래일(%s)이 실시간 거래일(%s)과 달라 버립니다.", business_date, state.live_date)
            state.seeded = True
            return
        state.seed(bars, ticks, quote)
        if business_date and not state.live_date:
            state.business_date = business_date

    # ── 수신 처리 ─────────────────────────────────────────────────────────
    def _on_data(self, frame: proto.DataFrame) -> None:
        for rec in frame.records:
            if frame.tr_id == proto.TR_TRADE:
                trade = proto.parse_trade(rec)
                if trade is None or not self.hub.has_state(trade.code):
                    continue
                events = self.hub.state(trade.code).apply_trade(trade)
                if events:
                    if events[0][0] == "snapshot":  # 거래일 변경: 연결 직후 스냅샷과 같은 모양으로 보낸다
                        events[0][1]["connection"] = self.manager.info()["state"]
                    self.hub.publish(trade.code, events)
            elif frame.tr_id == proto.TR_BOOK:
                book = proto.parse_book(rec)
                if book is None or not self.hub.has_state(book.stock_code):
                    continue
                events = self.hub.state(book.stock_code).apply_book(book)
                if events:
                    self.hub.publish(book.stock_code, events)

    def _on_state(self, state: str, detail: str | None) -> None:
        self.hub.broadcast("status", {"connection": state, "detail": detail})

    def status(self) -> dict[str, Any]:
        info = self.manager.info()
        info["viewers"] = self.hub.subscriber_count()
        return info


def _rest_quote(intraday_service: Any, code: str) -> dict[str, Any] | None:
    """REST 일괄 시세(종목 1개)로 첫 현재가를 만든다. 실패하거나 값이 없으면 None(현재가는 첫 실시간 체결 때 채워진다).

    `time`은 비워 둔다(체결 시각이 아니므로 화면의 시세 순서 판단에 쓰이지 않게 한다). `source`는 값의 출처 표시다.
    """
    try:
        rows = intraday_service.client.multi_price([code]).get("output") or []
        mq = normalize_multi_price(rows).get(code)
    except Exception:  # noqa: BLE001 — 현재가 보조 조회 실패가 화면 열기를 막지 않는다
        return None
    if mq is None:
        return None
    return {
        "time": "", "price": mq.price, "change": mq.change, "change_pct": mq.change_pct, "open": mq.open, "high": mq.high, "low": mq.low,
        "ask1": None, "bid1": None, "acml_volume": mq.volume, "acml_value": None, "strength": None, "halted": False, "vi_price": None, "source": "rest",
    }


def make_seed_fetcher(intraday_service: Any, fallback_day_fn: Callable[[], Any]) -> Callable[[str], tuple[Any, ...]]:
    """REST(분봉 1분·체결 최근 120건·현재가)로 시작 값을 만드는 함수를 돌려준다(블로킹 — 스레드에서 실행).

    오늘 분봉이 비어 있을 때(장 시작 전·휴장일)에만 직전 거래일(`fallback_day_fn`, DB 조회)로 다시 조회한다.
    """

    def fetch(code: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        minutes = intraday_service.minutes(code, 1, day=None, fallback_day=None)
        if not minutes.bars:
            fallback = fallback_day_fn()
            if fallback is not None:
                minutes = intraday_service.minutes(code, 1, day=None, fallback_day=fallback)
        bars = [b.model_dump() for b in minutes.bars]
        try:
            ticks = [t.model_dump() for t in intraday_service.ticks(code, SEED_TICKS).ticks]
        except KisError:
            ticks = []  # 분봉은 받았으면 체결 목록만 비워 두고 계속한다
        return bars, ticks, minutes.date.strftime("%Y%m%d"), _rest_quote(intraday_service, code)

    return fetch
