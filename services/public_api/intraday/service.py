"""장중 시세 조합 로직(페이징·집계·짧은 캐시) — DEC-052.

KIS 분봉 API는 1회에 당일 30건·과거 120건만 주므로, 입력 시각을 거꾸로 당기며 장 시작(09:00)까지 모은 뒤 N분봉으로 묶는다.
같은 요청이 짧은 시간에 반복(화면 자동 갱신·여러 탭)돼도 증권사 호출 한도를 쓰지 않도록 종목·종류별 짧은 TTL 캐시를 둔다.
"""

# ruff: noqa: E501  (한글 설명 주석이 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol, TypeVar

from services.public_api.intraday.kis_client import KisError, kst_now
from services.public_api.intraday.normalize import (
    aggregate_minutes,
    minus_one_minute,
    normalize_minute_rows,
    normalize_orderbook,
    normalize_ticks,
)
from services.public_api.schemas.intraday import (
    MinutesData,
    OrderBookData,
    TickItem,
    TicksData,
)

VALID_INTERVALS = (1, 3, 5, 10, 15, 30, 60)
MAX_TODAY_PAGES = 14  # 390분 / 30건 = 13쪽 + 여유
MAX_PAST_PAGES = 5  # 390분 / 120건 = 4쪽 + 여유
MAX_TICK_PAGES = 12
DEFAULT_TICK_LIMIT = 120
MAX_TICK_LIMIT = 300
TTL_MINUTES = 5.0
TTL_TICKS = 2.0
TTL_ORDERBOOK = 1.0
LAST_HHMMSS = "153000"
OPEN_HHMMSS = "090000"

T = TypeVar("T")


class KisLike(Protocol):
    def minute_today(self, code: str, hhmmss: str) -> dict[str, Any]: ...
    def minute_past(self, code: str, yyyymmdd: str, hhmmss: str) -> dict[str, Any]: ...
    def orderbook(self, code: str) -> dict[str, Any]: ...
    def recent_ccnl(self, code: str) -> dict[str, Any]: ...
    def conclusion_before(self, code: str, hhmmss: str) -> dict[str, Any]: ...


class IntradayService:
    def __init__(
        self,
        client: KisLike,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._clock = clock
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: tuple, ttl: float, build: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = build()
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
            if len(self._cache) > 500:  # 메모리 무한 증가 방지
                for k in [k for k, (t, _) in self._cache.items() if now - t > 60]:
                    self._cache.pop(k, None)
        return value

    # ── 분봉 ─────────────────────────────────────────────────────────────────────────────
    def _collect_today(self, code: str, day: str):
        bars: dict = {}
        hour = LAST_HHMMSS
        for _ in range(MAX_TODAY_PAGES):
            data = self._client.minute_today(code, hour)
            page = normalize_minute_rows(data.get("output2") or [], day)
            fresh = {k: v for k, v in page.items() if k not in bars}
            if not fresh:
                break
            bars.update(fresh)
            earliest = min(bars)
            if earliest <= OPEN_HHMMSS:
                break
            hour = minus_one_minute(earliest)
        return bars

    def _collect_past(self, code: str, day: str):
        bars: dict = {}
        hour = LAST_HHMMSS
        for _ in range(MAX_PAST_PAGES):
            data = self._client.minute_past(code, day, hour)
            page = normalize_minute_rows(data.get("output2") or [], day)
            fresh = {k: v for k, v in page.items() if k not in bars}
            if not fresh:
                break
            bars.update(fresh)
            earliest = min(bars)
            if earliest <= OPEN_HHMMSS:
                break
            hour = minus_one_minute(earliest)
        return bars

    def minutes(
        self,
        code: str,
        interval: int,
        *,
        day: date | None,
        fallback_day: date | None,
    ) -> MinutesData:
        """`day`가 없으면 오늘 분봉, 비어 있으면(장 시작 전·휴장일) `fallback_day`(직전 거래일)의 분봉."""
        if interval not in VALID_INTERVALS:
            raise KisError("INVALID_INTERVAL", "지원하지 않는 분봉 간격입니다.")
        today = kst_now(self._clock).date()

        def build() -> MinutesData:
            target = day or today
            ymd = target.strftime("%Y%m%d")
            if target == today:
                bars = self._collect_today(code, ymd)
                if not bars and day is None and fallback_day is not None and fallback_day != today:
                    target = fallback_day
                    bars = self._collect_past(code, target.strftime("%Y%m%d"))
            else:
                bars = self._collect_past(code, ymd)
            return MinutesData(
                stock_code=code,
                date=target,
                interval=interval,
                bars=aggregate_minutes(bars, interval),
            )

        return self._cached(("min", code, interval, day, fallback_day), TTL_MINUTES, build)

    # ── 체결(틱) ─────────────────────────────────────────────────────────────────────────
    def ticks(self, code: str, limit: int) -> TicksData:
        limit = max(1, min(limit, MAX_TICK_LIMIT))

        def build() -> TicksData:
            first = self._client.recent_ccnl(code)
            ticks: list[TickItem] = normalize_ticks(first.get("output") or [])
            truncated = False
            pages = 0
            while len(ticks) < limit and ticks and pages < MAX_TICK_PAGES:
                pages += 1
                oldest = ticks[-1].time
                try:
                    data = self._client.conclusion_before(code, oldest.replace(":", ""))
                except KisError:
                    truncated = True  # 과거 체결 조회가 막히면 모은 만큼만 돌려준다
                    break
                rows = normalize_ticks(data.get("output2") or [])
                added = _merge_older(ticks, rows)
                if not added:
                    truncated = len(ticks) < limit
                    break
            if len(ticks) < limit:
                truncated = True
            return TicksData(stock_code=code, ticks=ticks[:limit], truncated=truncated)

        return self._cached(("ticks", code, limit), TTL_TICKS, build)

    # ── 호가 ─────────────────────────────────────────────────────────────────────────────
    def orderbook(self, code: str) -> OrderBookData:
        def build() -> OrderBookData:
            data = self._client.orderbook(code)
            return normalize_orderbook(code, data.get("output1"), data.get("output2"))

        return self._cached(("book", code), TTL_ORDERBOOK, build)


def _merge_older(ticks: list[TickItem], older: list[TickItem]) -> int:
    """이미 가진 틱(최근→과거 순) 뒤에 더 오래된 틱을 이어 붙인다. 추가한 건수를 반환한다.

    페이지가 입력 시각을 포함해 내려오므로 같은 초의 틱이 겹칠 수 있다. 시각이 같은 틱은 이미 가진 개수만큼 건너뛰어
    중복을 없앤다(같은 초 안의 순서는 증권사 응답 순서를 그대로 따른다).
    """
    oldest_time = ticks[-1].time
    have_at_oldest = sum(1 for t in ticks if t.time == oldest_time)
    seen_at_oldest = 0
    added = 0
    for t in older:
        if t.time > oldest_time:
            continue
        if t.time == oldest_time:
            seen_at_oldest += 1
            if seen_at_oldest <= have_at_oldest:
                continue
        ticks.append(t)
        added += 1
    return added
