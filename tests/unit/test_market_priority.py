"""시세 폴러 우선 순환(DEC-089 §6) 시험 — 보이는 종목을 더 자주 갱신하되 합산 호출률과 기존 순환은 건드리지 않는다."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import random

import pytest
from test_market_snapshot import FakeFetch, FakeTime, codes_of, make_poller, quote

from services.public_api.intraday.kis_client import KisError
from services.public_api.realtime.market import MarketSnapshotPoller, PollerConfig


def test_set_priority_filters_unknown_dedups_caps_and_returns_count():
    poller, _ = make_poller(FakeFetch(), codes_of(300), priority_max=200)
    n = poller.set_priority(["000001", "000001", "ZZZZZZ", "", "000002"] + codes_of(300)[10:])
    assert n == 200 and poller.priority_codes()[:2] == ["000001", "000002"] and len(set(poller.priority_codes())) == 200
    assert poller.set_priority([]) == 0 and poller.priority_codes() == []


def test_priority_expires_after_ttl_and_is_cleared():
    poller, ft = make_poller(FakeFetch(), codes_of(50))
    assert poller.set_priority(codes_of(5), ttl_seconds=30) == 5
    ft.t += 29
    assert len(poller.priority_codes()) == 5
    ft.t += 2
    assert poller.priority_codes() == []  # 화면이 닫히면 30초 뒤 해제
    assert poller.metrics()["priority_codes"] == 0


def test_priority_codes_drop_when_universe_changes():
    poller, _ = make_poller(FakeFetch(), codes_of(10))
    poller.set_priority(["000001", "000002"], ttl_seconds=30)
    poller.set_codes(["000002", "000003"])
    assert poller.priority_codes() == ["000002"]


def test_priority_cycle_batches_30_and_updates_only_priority_quotes():
    fetch = FakeFetch()
    poller, _ = make_poller(fetch, codes_of(500), min_interval=0.0)
    poller.set_priority(codes_of(65), ttl_seconds=30)
    assert asyncio.run(poller.run_priority_cycle()) is True
    assert [len(c) for c in fetch.calls] == [30, 30, 5]
    assert set(poller.snapshot()) == set(codes_of(65)) and poller.metrics()["priority_calls_total"] == 3
    assert poller.priority_cycle_seconds is not None and poller.metrics()["priority_cycles_total"] == 1


def test_priority_cycle_spacing_respects_share_cap():
    """우선 순환 호출 사이 간격 ≥ min_interval / priority_share(기본 0.2/0.5=0.4초) → 합산 호출률의 50% 이내."""
    fetch = FakeFetch()
    ft = FakeTime()
    poller, _ = make_poller(fetch, codes_of(100), ft=ft, min_interval=0.2, priority_share=0.5)
    fetch.ft = ft
    poller.set_priority(codes_of(90), ttl_seconds=60)
    asyncio.run(poller.run_priority_cycle())
    gaps = [b - a for a, b in zip(fetch.call_times, fetch.call_times[1:], strict=False)]
    assert len(fetch.call_times) == 3 and all(g >= 0.4 - 1e-9 for g in gaps)


def test_priority_failure_uses_shared_backoff_and_does_not_stop():
    fetch = FakeFetch()
    fetch.fail = {0: KisError("RATE_LIMITED", "x")}
    poller, ft = make_poller(fetch, codes_of(60), min_interval=0.0)
    fetch.ft = ft
    poller.set_priority(codes_of(60), ttl_seconds=60)
    assert asyncio.run(poller.run_priority_cycle()) is False
    assert poller.metrics()["errors_total"] == 1 and poller.metrics()["rate_limited_total"] == 1
    assert len(fetch.calls) == 2 and set(poller.snapshot()) == set(codes_of(60)[30:])  # 실패한 묶음만 비고 다음 묶음은 계속
    assert fetch.call_times[1] >= fetch.call_times[0] + 1.0  # 백오프(1초)를 기다린 뒤 다음 묶음


def test_older_quote_never_overwrites_newer_one():
    poller, _ = make_poller(FakeFetch(), ["000001"])
    new = quote("000001", 2000.0)
    old = quote("000001", 1000.0)
    object.__setattr__(new, "fetched_at", 200.0)
    object.__setattr__(old, "fetched_at", 100.0)
    poller._ingest(["000001"], {"000001": new})
    poller._ingest(["000001"], {"000001": old})
    assert poller.get("000001").price == 2000.0


def test_started_poller_runs_priority_loop_and_stops_cleanly():
    async def go():
        fetch = FakeFetch()
        cfg = PollerConfig(min_interval=0.01, priority_interval=0.05, cycle_pause=0.05, off_hours_cycle_interval=0.05, jitter_ratio=0.0)
        poller = MarketSnapshotPoller(fetch, codes_of(40), cfg, rng=random.Random(0), is_market_open=lambda _n: True)
        poller.start()
        poller.set_priority(codes_of(3), ttl_seconds=5)
        await asyncio.sleep(0.4)
        calls_before = poller.priority_calls_total
        assert calls_before >= 2 and poller.priority_cycles_total >= 2
        await poller.stop()
        assert poller.running is False and poller._prio_task is None
        after = poller.priority_calls_total
        await asyncio.sleep(0.15)
        assert poller.priority_calls_total == after  # 정지 뒤에는 더 부르지 않는다
        poller.start()  # 재시작 가능
        await asyncio.sleep(0.1)
        await poller.stop()

    asyncio.run(go())


def test_priority_idle_does_not_call_broker():
    async def go():
        fetch = FakeFetch()
        cfg = PollerConfig(min_interval=0.01, priority_interval=0.05, cycle_pause=5.0, off_hours_cycle_interval=5.0, jitter_ratio=0.0)
        poller = MarketSnapshotPoller(fetch, [], cfg, is_market_open=lambda _n: True)
        poller.start()
        await asyncio.sleep(0.2)
        await poller.stop()
        return len(fetch.calls)

    assert asyncio.run(go()) == 0


@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_ttl_expires_immediately(bad):
    poller, _ = make_poller(FakeFetch(), codes_of(5))
    poller.set_priority(codes_of(3), ttl_seconds=bad)
    assert poller.priority_codes() == []
