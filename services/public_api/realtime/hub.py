"""실시간 허브: 종목별 최신 상태 + 구독자(브라우저 연결)별 전달 버퍼 (DEC-084).

- 최신값은 **메모리에만** 둔다(틱을 디스크·DB에 저장하지 않는다 — 용량·재배포·재배포(약관) 위험 최소화).
- 1분봉은 체결의 **당일 누적 거래량 차이**로 만든다. 체결이 일부 빠지거나 중복돼도(재연결·시작 직후) 봉의 거래량 합이 증권사 누적과 어긋나지 않는다.
- 구독자(브라우저)마다 "최신값만 남기는 버퍼"를 둔다: 시세·호가·분봉은 최신 것만, 체결은 순서대로 최대 500건. 느린 화면이 서버 메모리를 키우지 않는다.
단일 이벤트 루프에서만 쓴다(락 없음).
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from services.public_api.realtime.protocol import Trade, trade_tick
from services.public_api.schemas.intraday import OrderBookData

TICK_KEEP = 300  # 종목당 보관하는 최근 체결 수
SNAPSHOT_TICKS = 120  # 연결 직후 보내는 최근 체결 수(REST 체결 탭과 같음)
SUBSCRIBER_TICK_BUFFER = 500
DEDUPE_KEEP = 600
# 시작할 때 REST로 받아 둔 오늘 분봉의 거래량 합이 첫 실시간 체결의 누적 거래량과 이 정도 이내로 맞으면 그 합을 기준선으로 쓴다.
COVERAGE_TOLERANCE_MIN = 5_000
COVERAGE_TOLERANCE_RATIO = 0.02


@dataclass
class CodeState:
    code: str
    quote: dict[str, Any] | None = None
    book: dict[str, Any] | None = None
    ticks: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=TICK_KEEP))  # 최신이 앞
    bars: dict[str, dict[str, Any]] = field(default_factory=dict)  # "HH:MM" → 1분봉
    covered: int | None = None  # 이미 봉에 반영한 누적 거래량(기준선)
    seed_total: int | None = None
    business_date: str | None = None
    live_date: str | None = None  # 실시간 체결로 확인한 거래일(시작 값의 날짜와 구분: 시작 값이 직전 거래일일 수 있다)
    seeded: bool = False
    _seen: set[tuple] = field(default_factory=set)
    _seen_order: deque[tuple] = field(default_factory=deque)

    # ── 시작 값(REST) ─────────────────────────────────────────────────────
    def seed(self, bars: list[dict[str, Any]], ticks: list[dict[str, Any]], quote: dict[str, Any] | None = None) -> None:
        """오늘 1분봉과 최근 체결(최신이 앞), (있으면) REST 현재가로 채운다. 보통 실시간 체결이 오기 전에 한 번 부른다.

        이미 실시간 체결을 받은 뒤(다시 연결·거래일 변경 직후)에 불리면 **실시간 값이 우선**한다: 같은 시각의 봉은 실시간 것을 두고,
        체결 목록·기준선(covered)은 건드리지 않는다. 호출하는 쪽이 날짜가 다른 시작 값은 미리 버린다(`RealtimeService._seed`).
        """
        if quote is not None and self.quote is None:
            self.quote = dict(quote)  # 첫 실시간 체결 전에도 현재가를 보여 주기 위한 REST 값
        if self.live_date is not None:
            merged = {b["time"]: dict(b) for b in bars}
            merged.update(self.bars)
            self.bars = dict(sorted(merged.items()))
            if not self.ticks:
                self.ticks = deque((dict(t) for t in ticks), maxlen=TICK_KEEP)
            self.seeded = True
            return
        self.bars = {b["time"]: dict(b) for b in sorted(bars, key=lambda b: b["time"])}
        self.ticks = deque((dict(t) for t in ticks), maxlen=TICK_KEEP)
        self.seed_total = sum(int(b["volume"]) for b in self.bars.values()) if self.bars else None
        self.covered = None
        self.seeded = True

    def reset_day(self) -> None:
        self.quote = None
        self.book = None
        self.ticks.clear()
        self.bars.clear()
        self.covered = None
        self.seed_total = None
        self.seeded = False
        self._seen.clear()
        self._seen_order.clear()

    # ── 실시간 체결 ───────────────────────────────────────────────────────
    def _remember(self, key: tuple) -> bool:
        """처음 보는 체결이면 True."""
        if key in self._seen:
            return False
        self._seen.add(key)
        self._seen_order.append(key)
        if len(self._seen_order) > DEDUPE_KEEP:
            self._seen.discard(self._seen_order.popleft())
        return True

    def _volume_delta(self, trade: Trade) -> int | None:
        """이번 체결로 새로 반영할 거래량. 이미 반영된(또는 오래된) 체결이면 None."""
        acml = trade.acml_volume
        if acml is None:
            return trade.volume
        if self.covered is None:
            baseline = acml - trade.volume
            seed = self.seed_total
            if seed is not None and abs(baseline - seed) <= max(COVERAGE_TOLERANCE_MIN, int(acml * COVERAGE_TOLERANCE_RATIO)):
                self.covered = seed  # 시작 봉과 이어 붙임: 그 사이 놓친 체결도 이번 봉에 합산된다
            else:
                self.covered = baseline
        if acml <= self.covered:
            return None
        delta = acml - self.covered
        self.covered = acml
        return delta

    def apply_trade(self, trade: Trade) -> list[tuple[str, dict[str, Any]]]:
        """체결 하나를 반영하고 구독자에게 보낼 이벤트를 돌려준다.

        새 거래일의 첫 체결이면 어제(또는 시작 값의) 상태를 버리고 **`snapshot` 이벤트 하나**로 알린다(새 날짜·새 상태 전체).
        화면은 연결이 몇 시간 이어져 날이 바뀌어도 이전 날의 분봉·체결을 끌고 가지 않는다.
        """
        rolled = False
        if trade.business_date and self.business_date and trade.business_date != self.business_date:
            self.reset_day()  # 새 거래일: 어제 값을 끌고 가지 않는다
            rolled = True
        if trade.business_date:
            self.business_date = trade.business_date
            self.live_date = trade.business_date
        events = self._apply_trade_events(trade)
        if rolled:
            return [("snapshot", self.snapshot())]
        return events

    def _apply_trade_events(self, trade: Trade) -> list[tuple[str, dict[str, Any]]]:
        if not self._remember((trade.time, trade.price, trade.volume, trade.acml_volume)):
            return []
        delta = self._volume_delta(trade)
        if delta is None:
            return []
        tick = trade_tick(trade).model_dump()
        tick["acml_volume"] = trade.acml_volume
        self.ticks.appendleft(tick)
        quote = {
            "time": trade.time,
            "price": trade.price,
            "change": trade.change,
            "change_pct": trade.change_pct,
            "open": trade.open,
            "high": trade.high,
            "low": trade.low,
            "ask1": trade.ask1,
            "bid1": trade.bid1,
            "acml_volume": trade.acml_volume,
            "acml_value": trade.acml_value,
            "strength": trade.strength,
            "halted": trade.halted,
            "vi_price": trade.vi_price,
        }
        self.quote = quote
        key = trade.time[:5]
        bar = self.bars.get(key)
        if bar is None:
            bar = {"time": key, "open": trade.price, "high": trade.price, "low": trade.price, "close": trade.price, "volume": 0}
            self.bars[key] = bar
            self.bars = dict(sorted(self.bars.items()))  # 시간 오름차순 유지
            bar = self.bars[key]
        bar["high"] = max(bar["high"], trade.price)
        bar["low"] = min(bar["low"], trade.price)
        if key >= max(self.bars):  # 늦게 도착한 이전 분의 체결이 종가를 되돌리지 않는다
            bar["close"] = trade.price
        bar["volume"] += delta
        return [("tick", tick), ("bar", dict(bar)), ("quote", dict(quote))]

    def apply_book(self, book: OrderBookData) -> list[tuple[str, dict[str, Any]]]:
        data = book.model_dump(mode="json")
        if data == self.book:
            return []
        self.book = data
        return [("book", data)]

    def snapshot(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "quote": self.quote,
            "book": self.book,
            "ticks": list(self.ticks)[:SNAPSHOT_TICKS],
            "bars": [self.bars[k] for k in sorted(self.bars)],
            "seeded": self.seeded,
            "business_date": self.business_date,
        }


class Subscriber:
    """브라우저 연결 하나의 전달 버퍼."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.wake = asyncio.Event()
        self._latest: dict[str, dict[str, Any]] = {}
        self._bars: dict[str, dict[str, Any]] = {}
        self._ticks: deque[dict[str, Any]] = deque(maxlen=SUBSCRIBER_TICK_BUFFER)
        self._snapshot: dict[str, Any] | None = None
        self.closed = False

    def push(self, event: str, data: dict[str, Any]) -> None:
        if self.closed:
            return
        if event == "snapshot":
            # 거래일이 바뀌어 상태 전체를 다시 보낸다: 아직 못 보낸 이전 날 체결·분봉·시세·호가는 버리고 이 스냅샷부터 보낸다
            self._ticks.clear()
            self._bars.clear()
            self._latest.pop("quote", None)
            self._latest.pop("book", None)
            self._snapshot = data
        elif event == "tick":
            self._ticks.append(data)
        elif event == "bar":
            self._bars[data["time"]] = data
        else:
            self._latest[event] = data
        self.wake.set()

    def drain(self) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        if self._snapshot is not None:
            out.append(("snapshot", self._snapshot))  # 항상 맨 앞(이후 이벤트는 새 날 것)
            self._snapshot = None
        out += [("tick", t) for t in self._ticks]
        out += [("bar", self._bars[k]) for k in sorted(self._bars)]
        out += list(self._latest.items())
        self._ticks.clear()
        self._bars.clear()
        self._latest.clear()
        self.wake.clear()
        return out


class RealtimeHub:
    def __init__(self) -> None:
        self._states: dict[str, CodeState] = {}
        self._subs: dict[str, set[Subscriber]] = {}

    def state(self, code: str) -> CodeState:
        st = self._states.get(code)
        if st is None:
            st = self._states[code] = CodeState(code)
        return st

    def has_state(self, code: str) -> bool:
        return code in self._states

    def subscribe(self, code: str) -> Subscriber:
        sub = Subscriber(code)
        self._subs.setdefault(code, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        sub.closed = True
        subs = self._subs.get(sub.code)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                del self._subs[sub.code]

    def subscriber_count(self, code: str | None = None) -> int:
        if code is not None:
            return len(self._subs.get(code, ()))
        return sum(len(s) for s in self._subs.values())

    def drop_state(self, code: str) -> None:
        if code not in self._subs:
            self._states.pop(code, None)

    def publish(self, code: str, events: list[tuple[str, dict[str, Any]]]) -> None:
        for sub in tuple(self._subs.get(code, ())):
            for event, data in events:
                sub.push(event, data)

    def broadcast(self, event: str, data: dict[str, Any]) -> None:
        for subs in self._subs.values():
            for sub in tuple(subs):
                sub.push(event, data)
