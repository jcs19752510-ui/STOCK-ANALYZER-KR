"""전 종목 준실시간 스냅샷(멀티종목 시세 순환 호출) 시험 — 실제 증권사 접속 없음(가짜 클라이언트·모의 서버·가짜 시계)."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import random
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from services.public_api.intraday import config as cfg
from services.public_api.intraday.kis_client import KisClient, KisError
from services.public_api.intraday.normalize import MULTI_PRICE_FIELDS, normalize_multi_price
from services.public_api.realtime.market import (
    MarketQuote,
    MarketSnapshotPoller,
    PollerConfig,
    calls_per_cycle,
    chunk_codes,
    estimate_cycle_seconds,
    make_kis_fetcher,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import mock_kis_server  # noqa: E402


def codes_of(n: int) -> list[str]:
    return [f"{i:06d}" for i in range(1, n + 1)]


def quote(code: str, price: float = 1000.0, at: float = 1.0) -> MarketQuote:
    return MarketQuote(code=code, price=price, change=10.0, change_pct=1.0, volume=100, open=990.0, high=1010.0, low=980.0, fetched_at=at)


class FakeTime:
    """가짜 시계 + 가짜 sleep(실제로 기다리지 않고 시간만 흘린다)."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s
        await asyncio.sleep(0)


class FakeFetch:
    """호출 기록 + 시나리오별 실패를 흉내 내는 가짜 조회 함수(블로킹 시그니처)."""

    def __init__(self, ft: FakeTime | None = None) -> None:
        self.calls: list[list[str]] = []
        self.call_times: list[float] = []
        self.ft = ft
        self.fail: dict[int, Exception] = {}  # 호출 순번(0부터) → 던질 예외
        self.drop: set[str] = set()

    def __call__(self, codes: list[str]) -> dict[str, MarketQuote]:
        idx = len(self.calls)
        self.calls.append(list(codes))
        if self.ft is not None:
            self.call_times.append(self.ft.t)
        if idx in self.fail:
            raise self.fail[idx]
        return {c: quote(c, 1000.0 + idx) for c in codes if c not in self.drop}


def make_poller(fetch, codes=(), ft: FakeTime | None = None, **cfg_over):
    ft = ft or FakeTime()
    config = PollerConfig(**{"jitter_ratio": 0.0, **cfg_over})
    return MarketSnapshotPoller(
        fetch, codes, config, clock=ft.clock, wall_clock=ft.clock, sleep=ft.sleep, rng=random.Random(0), is_market_open=lambda _now: True
    ), ft


# ── 30개 경계 ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("n", "calls", "sizes"),
    [(0, 0, []), (1, 1, [1]), (29, 1, [29]), (30, 1, [30]), (31, 2, [30, 1]), (60, 2, [30, 30]), (2800, 94, [30] * 93 + [10])],
)
def test_chunk_boundaries(n, calls, sizes):
    batches = chunk_codes(codes_of(n))
    assert [len(b) for b in batches] == sizes
    assert calls_per_cycle(n) == calls == len(batches)
    assert [c for b in batches for c in b] == codes_of(n)  # 순서·누락·중복 없음


def test_batch_size_is_capped_at_30():
    assert [len(b) for b in chunk_codes(codes_of(70), 100)] == [30, 30, 10]
    assert [len(b) for b in chunk_codes(codes_of(5), 0)] == [1] * 5


def test_poller_cycle_calls_and_sizes_for_2800_codes():
    fetch = FakeFetch()
    poller, _ = make_poller(fetch, codes_of(2800), min_interval=0.0)
    assert asyncio.run(poller.run_cycle()) is True
    assert len(fetch.calls) == 94 and max(len(c) for c in fetch.calls) == 30
    assert len(poller.snapshot()) == 2800
    m = poller.metrics()
    assert m["calls_total"] == 94 and m["calls_per_cycle"] == 94 and m["full_cycles_total"] == 1 and m["errors_total"] == 0


@pytest.mark.parametrize("n", [0, 1, 30, 31])
def test_poller_small_lists(n):
    fetch = FakeFetch()
    poller, _ = make_poller(fetch, codes_of(n), min_interval=0.0)
    asyncio.run(poller.run_cycle())
    assert len(fetch.calls) == calls_per_cycle(n)
    assert len(poller.snapshot()) == n


# ── KisClient.multi_price ────────────────────────────────────────────────────────────────
def _settings(tmp_path: Path, base: str | None = None):
    env = {cfg.ENABLED_ENV: "true", cfg.APP_KEY_ENV: "mock", cfg.APP_SECRET_ENV: "mock", cfg.TOKEN_CACHE_ENV: str(tmp_path / "tok.json")}
    if base:
        env |= {cfg.BASE_URL_ENV: base, cfg.ALLOW_CUSTOM_BASE_ENV: "true"}
    return cfg.get_settings(env)


def test_client_multi_price_params_and_limits(tmp_path):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "0", "output": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = KisClient(_settings(tmp_path), http, clock=lambda: 1_000_000.0, sleep=lambda s: None)
    client.multi_price(["005930", "000660"])
    req = seen[-1]
    assert req.url.path.endswith("/intstock-multprice") and req.headers["tr_id"] == "FHKST11300006"
    q = dict(req.url.params)
    assert q == {
        "FID_COND_MRKT_DIV_CODE_1": "J", "FID_INPUT_ISCD_1": "005930",
        "FID_COND_MRKT_DIV_CODE_2": "J", "FID_INPUT_ISCD_2": "000660",
    }
    client.multi_price(codes_of(30))
    assert len(dict(seen[-1].url.params)) == 60
    with pytest.raises(ValueError):
        client.multi_price(codes_of(31))
    with pytest.raises(ValueError):
        client.multi_price([])


def test_client_multi_price_rate_limited_error_code(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과"})

    client = KisClient(_settings(tmp_path), httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: 1_000_000.0, sleep=lambda s: None)
    with pytest.raises(KisError) as ei:
        client.multi_price(["005930"])
    assert ei.value.code == "RATE_LIMITED"


# ── 정규화 ──────────────────────────────────────────────────────────────────────────────
def _row(**over):
    f = MULTI_PRICE_FIELDS
    base = {f["code"]: "005930", f["price"]: "70,000", f["change"]: "500", f["sign"]: "5", f["change_pct"]: "0.71", f["volume"]: "1234567",
            f["open"]: "70500", f["high"]: "71000", f["low"]: "69800"}
    for k, v in over.items():
        base[f[k]] = v
    return base


def test_normalize_valid_row_applies_sign():
    out = normalize_multi_price([_row()], fetched_at=42.0)
    q = out["005930"]
    assert (q.price, q.change, q.change_pct, q.volume, q.open, q.high, q.low, q.fetched_at) == (70000.0, -500.0, -0.71, 1234567, 70500.0, 71000.0, 69800.0, 42.0)
    up = normalize_multi_price([_row(sign="2")])["005930"]
    assert up.change == 500.0 and up.change_pct == 0.71


@pytest.mark.parametrize("field", ["price", "change", "change_pct", "volume", "open", "high", "low", "code"])
@pytest.mark.parametrize("bad", ["", None, "abc", "N/A"])
def test_normalize_drops_empty_or_non_numeric(field, bad):
    good = _row()
    good[MULTI_PRICE_FIELDS["code"]] = "000660"
    out = normalize_multi_price([_row(**{field: bad}), good])
    assert list(out) == ["000660"]  # 이상한 행만 버리고 정상 행은 남는다


def test_normalize_drops_nonpositive_price_and_negative_volume_without_zero_fill():
    out = normalize_multi_price([_row(price="0"), _row(price="-5"), _row(volume="-1")])
    assert out == {}


def test_normalize_missing_keys_and_empty_input():
    assert normalize_multi_price([]) == {}
    assert normalize_multi_price([{}]) == {}


# ── 순환 주기 계산(가짜 시계) ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rate", [5, 8, 10, 20])
def test_cycle_time_matches_rate_limit(rate):
    ft = FakeTime()
    fetch = FakeFetch(ft)
    poller, _ = make_poller(fetch, codes_of(2800), ft, min_interval=1 / rate)
    asyncio.run(poller.run_cycle())
    asyncio.run(poller.run_cycle())
    assert len(fetch.calls) == 188
    # 첫 호출 시작 → 94번째 호출 시작까지 93 간격, 다음 바퀴 첫 호출까지 포함해 한 바퀴 주기 = 94 / rate
    period = fetch.call_times[94] - fetch.call_times[0]
    assert period == pytest.approx(94 / rate)
    assert poller.last_cycle_seconds == pytest.approx(94 / rate)  # 둘째 바퀴: 직전 호출 간격부터 센 한 바퀴
    assert estimate_cycle_seconds(2800, rate) == pytest.approx(94 / rate)


def test_estimate_table_values():
    assert [round(estimate_cycle_seconds(2800, r), 1) for r in (5, 8, 10, 20)] == [18.8, 11.8, 9.4, 4.7]
    with pytest.raises(ValueError):
        estimate_cycle_seconds(10, 0)


def test_jitter_only_adds_delay_never_below_min_interval():
    ft = FakeTime()
    fetch = FakeFetch(ft)
    poller, _ = make_poller(fetch, codes_of(300), ft, min_interval=0.5, jitter_ratio=0.2)
    asyncio.run(poller.run_cycle())
    gaps = [b - a for a, b in zip(fetch.call_times, fetch.call_times[1:], strict=False)]
    assert all(0.5 - 1e-9 <= g <= 0.6 + 1e-9 for g in gaps)
    assert len({round(g, 6) for g in gaps}) > 1  # 실제로 흩어진다


# ── 실패·백오프 ─────────────────────────────────────────────────────────────────────────
def test_failed_batch_does_not_stop_cycle_and_is_retried_next_cycle():
    fetch = FakeFetch()
    fetch.fail[1] = KisError("UPSTREAM_UNAVAILABLE", "x")  # 두 번째 묶음만 실패
    poller, _ = make_poller(fetch, codes_of(90), min_interval=0.0, backoff_base=0.0)
    assert asyncio.run(poller.run_cycle()) is False
    assert len(fetch.calls) == 3  # 실패해도 나머지 묶음은 이번 바퀴에서 조회
    snap = poller.snapshot()
    assert set(snap) == set(codes_of(30)) | set(codes_of(90)[60:])  # 실패한 묶음(31~60)은 비어 있다
    assert poller.full_cycles_total == 0 and poller.last_full_cycle_at is None and poller.errors_total == 1
    assert asyncio.run(poller.run_cycle()) is True  # 다음 바퀴: 모두 성공
    assert len(fetch.calls) == 6 and fetch.calls[4] == codes_of(90)[30:60]
    assert len(poller.snapshot()) == 90 and poller.full_cycles_total == 1 and poller.last_full_cycle_at is not None
    assert poller.metrics()["consecutive_errors"] == 0


def test_stale_values_are_kept_when_batch_fails():
    fetch = FakeFetch()
    poller, _ = make_poller(fetch, codes_of(40), min_interval=0.0, backoff_base=0.0)
    asyncio.run(poller.run_cycle())
    before = poller.get("000035")
    fetch.fail[3] = RuntimeError("boom")  # 2번째 바퀴의 두 번째 묶음(호출 순번 3)
    assert asyncio.run(poller.run_cycle()) is False
    assert poller.get("000035") == before  # 실패한 묶음의 이전 값은 그대로(fetched_at으로 낡음을 알 수 있다)
    assert poller.last_error_code == "UNEXPECTED"


def test_rate_limited_backoff_grows_exponentially_and_resets():
    ft = FakeTime()
    fetch = FakeFetch(ft)
    for i in range(3):
        fetch.fail[i] = KisError("RATE_LIMITED", "한도")
    poller, _ = make_poller(fetch, codes_of(150), ft, min_interval=0.1, backoff_base=1.0, backoff_max=60.0)
    asyncio.run(poller.run_cycle())
    t = fetch.call_times
    # 호출0 실패(1초) → 호출1까지 ≥1초, 호출1 실패(2초) → 호출2까지 ≥2초, 호출2 실패(4초) → 호출3까지 ≥4초
    assert t[1] - t[0] == pytest.approx(1.0) and t[2] - t[1] == pytest.approx(2.0) and t[3] - t[2] == pytest.approx(4.0)
    assert t[4] - t[3] == pytest.approx(0.1)  # 성공 후 정상 간격으로 복귀
    assert poller.rate_limited_total == 3 and poller.errors_total == 3 and poller.last_error_code == "RATE_LIMITED"
    assert poller.metrics()["consecutive_errors"] == 0


def test_backoff_is_capped():
    ft = FakeTime()
    fetch = FakeFetch(ft)
    for i in range(8):
        fetch.fail[i] = KisError("RATE_LIMITED", "한도")
    poller, _ = make_poller(fetch, codes_of(300), ft, min_interval=0.0, backoff_base=1.0, backoff_max=5.0)
    asyncio.run(poller.run_cycle())
    gaps = [b - a for a, b in zip(fetch.call_times, fetch.call_times[1:], strict=False)]
    assert max(gaps) == pytest.approx(5.0) and gaps[:3] == pytest.approx([1.0, 2.0, 4.0])


# ── 종목 목록 교체 ───────────────────────────────────────────────────────────────────────
def test_replace_codes_adds_new_and_drops_removed():
    fetch = FakeFetch()
    poller, _ = make_poller(fetch, ["000001", "000002", "000003"], min_interval=0.0)
    asyncio.run(poller.run_cycle())
    assert set(poller.snapshot()) == {"000001", "000002", "000003"}
    poller.set_codes(["000002", "000003", "000004", "000004", " ", ""])  # 상장폐지(1)·신규(4), 중복·빈 값 제거
    assert poller.codes == ["000002", "000003", "000004"]
    assert set(poller.snapshot()) == {"000002", "000003"}  # 빠진 종목 값은 즉시 제거
    asyncio.run(poller.run_cycle())
    assert set(poller.snapshot()) == {"000002", "000003", "000004"}
    assert fetch.calls[-1] == ["000002", "000003", "000004"]


def test_codes_replaced_during_fetch_are_not_stored():
    holder: dict[str, MarketSnapshotPoller] = {}

    def fetch(codes):
        holder["p"].set_codes(["000002"])  # 조회 도중 목록 교체
        return {c: quote(c) for c in codes}

    poller, _ = make_poller(fetch, ["000001", "000002"], min_interval=0.0)
    holder["p"] = poller
    asyncio.run(poller.run_cycle())
    assert set(poller.snapshot()) == {"000002"}


def test_unrequested_or_dropped_codes_are_counted():
    fetch = FakeFetch()
    fetch.drop = {"000002"}
    poller, _ = make_poller(fetch, ["000001", "000002"], min_interval=0.0)
    asyncio.run(poller.run_cycle())
    assert set(poller.snapshot()) == {"000001"} and poller.missing_total == 1


# ── 시작/정지, 장 시간 ────────────────────────────────────────────────────────────────────
def test_start_stop_is_clean_and_idempotent():
    async def scenario():
        fetch = FakeFetch()
        ft = FakeTime()
        poller = MarketSnapshotPoller(
            fetch, codes_of(100), PollerConfig(min_interval=0.01, jitter_ratio=0.0, stop_timeout=2.0),
            clock=ft.clock, wall_clock=ft.clock, rng=random.Random(0), is_market_open=lambda _n: True,
        )
        poller.start()
        poller.start()  # 두 번 불러도 작업은 하나
        await asyncio.sleep(0.15)
        assert poller.running and len(fetch.calls) > 0
        await poller.stop()
        assert not poller.running and poller._task is None
        n = len(fetch.calls)
        await asyncio.sleep(0.1)
        assert len(fetch.calls) == n  # 정지 뒤 호출 없음
        await poller.stop()  # 이중 정지도 안전
        poller.start()  # 재시작 가능
        await asyncio.sleep(0.05)
        assert poller.running
        await poller.stop()
        assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []

    asyncio.run(scenario())


def test_stop_interrupts_long_wait_immediately():
    async def scenario():
        fetch = FakeFetch()
        poller = MarketSnapshotPoller(
            fetch, codes_of(10), PollerConfig(off_hours_cycle_interval=3600.0, stop_timeout=2.0), is_market_open=lambda _n: False
        )
        poller.start()
        await asyncio.sleep(0.1)
        assert len(fetch.calls) == 1  # 장 시간 밖이어도 첫 바퀴는 돈다
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await poller.stop()
        assert loop.time() - t0 < 1.0 and not poller.running

    asyncio.run(scenario())


def test_off_hours_runs_slowly_after_first_cycle():
    async def scenario(open_now: bool):
        ft = FakeTime()
        fetch = FakeFetch(ft)
        poller = MarketSnapshotPoller(
            fetch, codes_of(30), PollerConfig(min_interval=0.2, jitter_ratio=0.0, off_hours_cycle_interval=300.0, cycle_pause=0.0, stop_timeout=2.0),
            clock=ft.clock, wall_clock=ft.clock, sleep=ft.sleep, rng=random.Random(0), is_market_open=lambda _n: open_now,
        )
        poller.start()
        for _ in range(200):
            await asyncio.sleep(0)
            if len(fetch.calls) >= 3:
                break
        await poller.stop()
        return fetch.call_times

    closed = asyncio.run(scenario(False))
    opened = asyncio.run(scenario(True))
    assert closed[1] - closed[0] >= 299.0  # 장 밖: 5분 간격
    assert opened[1] - opened[0] < 1.0  # 장중: 호출 간격만큼


def test_poller_without_codes_does_not_call_and_waits():
    async def scenario():
        fetch = FakeFetch()
        poller = MarketSnapshotPoller(fetch, [], PollerConfig(stop_timeout=2.0))
        poller.start()
        await asyncio.sleep(0.05)
        poller.set_codes(["000001"])
        await poller.stop()
        return fetch

    assert asyncio.run(scenario()).calls == []


# ── 모의 서버 끝까지(HTTP) ──────────────────────────────────────────────────────────────
@pytest.fixture
def mock_rest(monkeypatch):
    monkeypatch.setattr(mock_kis_server.Handler, "fixed_now", mock_kis_server.datetime(2026, 10, 7, 11, 0, tzinfo=mock_kis_server.KST))
    server = ThreadingHTTPServer(("127.0.0.1", 0), mock_kis_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_mock_server_end_to_end_with_poller(mock_rest, tmp_path):
    client = KisClient(_settings(tmp_path, mock_rest), min_interval=0.0)
    codes = codes_of(70) + ["000000"]  # 마지막은 값이 빈 행 → 버려져야 한다
    poller = MarketSnapshotPoller(
        make_kis_fetcher(client), codes, PollerConfig(min_interval=0.0, jitter_ratio=0.0), is_market_open=lambda _n: True
    )
    assert asyncio.run(poller.run_cycle()) is True
    snap = poller.snapshot()
    assert len(snap) == 70 and "000000" not in snap and poller.missing_total == 1
    q = snap["000001"]
    assert q.price > 0 and q.low <= q.price <= q.high and q.volume > 0
    assert (q.change >= 0) == (q.price >= mock_kis_server._base_price("000001"))  # 부호 적용


def test_mock_server_rejects_more_than_30(mock_rest, tmp_path):
    http = httpx.Client()
    tok = http.post(mock_rest + "/oauth2/tokenP", json={"grant_type": "client_credentials"}).json()["access_token"]
    params = {f"FID_INPUT_ISCD_{i}": c for i, c in enumerate(codes_of(31), start=1)}
    resp = http.get(mock_rest + "/uapi/domestic-stock/v1/quotations/intstock-multprice", params=params, headers={"authorization": f"Bearer {tok}"})
    body = resp.json()
    assert body["rt_cd"] == "1" and "output" not in body
    ok = http.get(mock_rest + "/uapi/domestic-stock/v1/quotations/intstock-multprice", params={"FID_INPUT_ISCD_1": "005930"}, headers={"authorization": f"Bearer {tok}"}).json()
    assert ok["rt_cd"] == "0" and ok["output"][0]["inter_shrn_iscd"] == "005930"
    again = http.get(mock_rest + "/uapi/domestic-stock/v1/quotations/intstock-multprice", params={"FID_INPUT_ISCD_1": "005930"}, headers={"authorization": f"Bearer {tok}"}).json()
    assert json.dumps(ok["output"], sort_keys=True) == json.dumps(again["output"], sort_keys=True)  # 시각 고정 시 결정적
