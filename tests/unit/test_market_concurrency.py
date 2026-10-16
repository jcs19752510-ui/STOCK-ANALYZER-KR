"""전체 시세 순환의 동시 호출(DEC-099): 호출 시작 간격은 지키고, 응답 대기 중 다음 호출을 시작해 응답 지연을 가린다.

실제 시간(짧은 대기)으로 돌린다 — 스레드에서 도는 조회 함수의 동시 진행 수와 시작 시각을 직접 센다.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from services.public_api.api.local_market import DEFAULT_ENV_CONCURRENCY, poller_config_from_env
from services.public_api.intraday import config as intraday_cfg
from services.public_api.intraday.kis_client import KisError
from services.public_api.realtime.market import MarketQuote, MarketSnapshotPoller, PollerConfig


def _quote(code: str) -> MarketQuote:
    return MarketQuote(code=code, price=1000.0, change=0.0, change_pct=0.0, volume=1, open=1.0, high=1.0, low=1.0, fetched_at=time.time())


class Probe:
    """조회 함수 대역: 응답 지연을 흉내 내고 동시 진행 수·시작 시각을 기록한다."""

    def __init__(self, latency: float, fail_calls: frozenset[int] = frozenset()) -> None:
        self.latency = latency
        self.fail_calls = fail_calls
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.starts: list[float] = []
        self.calls = 0

    def __call__(self, codes: list[str]) -> dict[str, MarketQuote]:
        with self.lock:
            idx = self.calls
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.starts.append(time.monotonic())
        try:
            time.sleep(self.latency)
            if idx in self.fail_calls:
                raise KisError("UPSTREAM_ERROR", "모의 실패")
            return {c: _quote(c) for c in codes}
        finally:
            with self.lock:
                self.active -= 1


def _codes(n: int) -> list[str]:
    return [f"{i:06d}" for i in range(1, n + 1)]


def _poller(fetch: Probe, n_codes: int, **over) -> MarketSnapshotPoller:
    cfg = PollerConfig(**{"jitter_ratio": 0.0, "min_interval": 0.01, **over})
    return MarketSnapshotPoller(fetch, _codes(n_codes), cfg, is_market_open=lambda _n: True)


def test_serial_when_concurrency_is_one():
    probe = Probe(latency=0.03)
    poller = _poller(probe, 150, concurrency=1)  # 5묶음
    assert asyncio.run(poller.run_cycle()) is True
    assert probe.max_active == 1  # 기존 동작(직렬) 유지
    assert probe.calls == 5 and len(poller.snapshot()) == 150


def test_concurrent_hides_latency_but_keeps_start_spacing():
    probe = Probe(latency=0.2)
    poller = _poller(probe, 600, concurrency=4, min_interval=0.02)  # 20묶음
    t0 = time.monotonic()
    assert asyncio.run(poller.run_cycle()) is True
    took = time.monotonic() - t0
    assert 1 < probe.max_active <= 4  # 동시 진행 수는 상한을 넘지 않는다
    serial_floor = 20 * 0.2  # 직렬이면 최소 4초
    assert took < serial_floor * 0.5  # 지연이 가려졌다(이론 ≈ 20×0.2/4 = 1초)
    gaps = [b - a for a, b in zip(probe.starts, probe.starts[1:], strict=False)]
    assert min(gaps) >= 0.02 - 0.004  # 호출 시작 간격(초당 호출 수 상한)은 지켜진다
    assert probe.calls == 20 and len(poller.snapshot()) == 600


def test_failure_in_one_batch_does_not_stop_others_and_is_counted():
    probe = Probe(latency=0.02, fail_calls=frozenset({3}))
    poller = _poller(probe, 300, concurrency=4)  # 10묶음
    assert asyncio.run(poller.run_cycle()) is False
    m = poller.metrics()
    assert probe.calls == 10 and m["errors_total"] == 1 and m["full_cycles_total"] == 0
    assert len(poller.snapshot()) == 270  # 실패한 한 묶음(30종목)만 비어 있다


def test_stop_during_cycle_returns_false_and_waits_for_inflight():
    probe = Probe(latency=0.05)
    poller = _poller(probe, 3000, concurrency=4, min_interval=0.01)  # 100묶음, 정지 없으면 약 1.2초 이상

    async def scenario() -> bool:
        task = asyncio.get_running_loop().create_task(poller.run_cycle())
        await asyncio.sleep(0.1)
        poller._stop.set()  # noqa: SLF001 — 정지 요청과 같은 효과
        return await task

    assert asyncio.run(scenario()) is False
    assert probe.active == 0  # 진행 중이던 호출은 끝까지 기다린 뒤 돌아온다
    assert probe.calls < 100


def test_env_concurrency_default_bounds_and_invalid(monkeypatch):
    monkeypatch.delenv("KIS_MARKET_CONCURRENCY", raising=False)
    assert poller_config_from_env().concurrency == DEFAULT_ENV_CONCURRENCY == 4
    monkeypatch.setenv("KIS_MARKET_CONCURRENCY", "1")
    assert poller_config_from_env().concurrency == 1
    monkeypatch.setenv("KIS_MARKET_CONCURRENCY", "99")
    assert poller_config_from_env().concurrency == 8  # 상한
    monkeypatch.setenv("KIS_MARKET_CONCURRENCY", "0")
    assert poller_config_from_env().concurrency == 1  # 하한
    monkeypatch.setenv("KIS_MARKET_CONCURRENCY", "abc")
    assert poller_config_from_env().concurrency == DEFAULT_ENV_CONCURRENCY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0.12),  # 설정 없음 → 기존 기본값
        ("0.125", 0.12),  # 기본 설정(폴러 0.125)에서도 클라이언트는 기존 0.12 그대로
        ("0.1", 0.1),  # 더 빠르게 → 클라이언트도 같이 빨라진다(이전에는 0.12에 막혔다)
        ("0.06", 0.06),
        ("0.001", 0.06),  # 하한
        ("0.5", 0.12),  # 더 느리게 → 상세 화면 호출을 늦추지 않는다
        ("abc", 0.12),
        ("nan", 0.12),
        ("-1", 0.06),
    ],
)
def test_client_min_interval_follows_market_setting(raw, expected):
    env = {} if raw is None else {"KIS_MARKET_MIN_INTERVAL": raw}
    assert intraday_cfg.client_min_interval(env) == expected


def test_kis_client_default_interval_follows_env_and_explicit_wins(monkeypatch, tmp_path):
    """운영 경로는 KisClient(settings)로 만든다 → 간격 기본값이 환경설정을 따르고, 명시한 값은 그대로 쓴다(시험 대역 호환)."""
    from services.public_api.intraday.config import IntradaySettings
    from services.public_api.intraday.kis_client import KisClient

    settings = IntradaySettings(enabled=True, app_key="k", app_secret="s", base_url="http://x", allowed_networks=(), token_cache_path=tmp_path / "t.json")
    monkeypatch.delenv("KIS_MARKET_MIN_INTERVAL", raising=False)
    assert KisClient(settings)._min_interval == 0.12  # noqa: SLF001
    monkeypatch.setenv("KIS_MARKET_MIN_INTERVAL", "0.1")
    assert KisClient(settings)._min_interval == 0.1  # noqa: SLF001
    assert KisClient(settings, min_interval=0.0)._min_interval == 0.0  # noqa: SLF001 — partial(min_interval=0.0) 같은 명시값 우선
