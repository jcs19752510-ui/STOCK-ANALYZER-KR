"""발행 일봉 이력(`public_serving.daily_prices`, 종목당 최근 100행) 메모리 캐시 — 발행 거래일이 바뀔 때만 다시 읽는다."""

# ruff: noqa: E501

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date

from services.public_api.live_screen.types import DailyBar

HISTORY_ROWS_PER_STOCK = 100  # 배치가 지표 계산에 쓰는 창(PATTERN_WINDOW_ROWS)과 같다


class HistoryCache:
    def __init__(self, loader: Callable[[date], dict[str, list[DailyBar]]]) -> None:
        self._loader = loader
        self._lock = threading.Lock()
        self._key: date | None = None
        self._data: dict[str, list[DailyBar]] = {}
        self.loads_total = 0

    def get(self, published_date: date) -> dict[str, list[DailyBar]]:
        """`published_date`(발행 거래일) 이하의 종목별 일봉(날짜 오름차순). 같은 날짜로 다시 부르면 DB를 읽지 않는다(동기 — 스레드에서 호출)."""
        with self._lock:
            if self._key != published_date:
                self._data = self._loader(published_date)
                self._key = published_date
                self.loads_total += 1
            return self._data

    def invalidate(self) -> None:
        with self._lock:
            self._key = None
            self._data = {}
