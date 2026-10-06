"""장중 재계산 스냅샷 보관(최근 N개, 메모리) — 일시정지 중 페이지 이동이 같은 결과 집합을 보게 한다(계약서 §3)."""

# ruff: noqa: E501

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from services.public_api.live_screen.rows import LiveRowsResult

MAX_SNAPSHOTS = 5


@dataclass
class Snapshot:
    snapshot_id: str
    created_at: float  # epoch 초
    result: LiveRowsResult
    info: dict[str, Any]  # 날짜·시세 상태 등 이 스냅샷을 만들 때의 사실(응답 meta.live의 바탕)
    trade_key: date  # 가상 행의 trade_date 키(발행 거래일)
    matched: dict[str, frozenset[str]] = field(default_factory=dict)  # 조회 조건 키 → 조건에 맞은 종목코드(편입·이탈 비교용)
    _payload: str | None = field(default=None, repr=False)

    def payload(self, build: Callable[[], str]) -> str:
        """가상 테이블용 JSON(스냅샷마다 한 번만 만든다)."""
        if self._payload is None:
            self._payload = build()
        return self._payload


class SnapshotStore:
    def __init__(self, *, max_items: int = MAX_SNAPSHOTS, clock: Callable[[], float] = time.time) -> None:
        self._max = max_items
        self._clock = clock
        self._items: OrderedDict[str, Snapshot] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, result: LiveRowsResult, info: dict[str, Any], trade_key: date) -> Snapshot:
        snap = Snapshot(uuid.uuid4().hex, self._clock(), result, info, trade_key)
        with self._lock:
            self._items[snap.snapshot_id] = snap
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return snap

    def get(self, snapshot_id: str) -> Snapshot | None:
        with self._lock:
            return self._items.get(snapshot_id)

    def latest(self, max_age: float | None = None) -> Snapshot | None:
        """가장 최근 스냅샷. `max_age`(초)를 주면 그보다 오래됐을 때 None."""
        with self._lock:
            if not self._items:
                return None
            snap = next(reversed(self._items.values()))
        if max_age is not None and self._clock() - snap.created_at > max_age:
            return None
        return snap

    def previous(self, snapshot_id: str) -> Snapshot | None:
        """`snapshot_id` 바로 앞에 만든 스냅샷."""
        with self._lock:
            prev: Snapshot | None = None
            for sid, snap in self._items.items():
                if sid == snapshot_id:
                    return prev
                prev = snap
        return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
