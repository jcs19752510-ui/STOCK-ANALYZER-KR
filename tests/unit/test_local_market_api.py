"""전 종목 시세 스냅샷 API 시험 — 실제 uvicorn 서버 + 모의 증권사 REST로 끝까지 검증한다 (DEC-084). 실제 증권사 접속·DB 없음."""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import functools
import json
import threading
import time
import types
from pathlib import Path

import httpx
import pytest
from test_realtime_connection import until
from test_realtime_stream_api import SID, UID, Stack, run_with_mp

from services.public_api.api import local_intraday, local_market, local_realtime
from services.public_api.errors import ApiError
from services.public_api.intraday import config as cfg
from services.public_api.intraday import kis_client as kc
from services.public_api.intraday.kis_client import KisClient
from services.public_api.rate_limit import reset_rate_limit_state
from services.public_api.realtime.market import MarketQuote, PollerConfig

UNIVERSE = ["005930", "000660", "035720", "000000"]  # 000000: 모의 증권사가 빈 값 행을 돌려준다(버려져야 함)
FAST = PollerConfig(cycle_pause=0.05, off_hours_cycle_interval=0.05, min_interval=0.01)  # 장 시간과 무관하게 짧은 주기로 도는 시험 설정


class MarketStack(Stack):
    """종목 유니버스를 가짜 함수로 주입한 실제 서버."""

    def __init__(self, mp: pytest.MonkeyPatch, universe: list[str] | None = None, fast: bool = False, market_open: bool | None = None, **env: str) -> None:
        super().__init__(mp, **env)
        self.universe = list(UNIVERSE if universe is None else universe)
        self.load_calls = 0
        self.load_error: Exception | None = None
        self.fast = fast
        self.market_open = market_open  # None이면 실제 시각으로 장중 여부를 판단한다
        self.runtime_after_shutdown: object = "unset"
        self.created_clients: list[object] = []

    def _load(self) -> list[str]:
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error
        return list(self.universe)

    async def __aenter__(self) -> MarketStack:
        reset_rate_limit_state()  # 파일 안 여러 시험이 같은 1분 창을 공유해 호출 한도(로컬 경로 600/분)에 걸리지 않게 한다
        local_market.reset_market_runtime()
        local_market.set_universe_loader(self._load)
        extra: dict = {}
        if self.fast:
            extra["config"] = FAST
        if self.market_open is not None:
            extra["is_market_open"] = lambda now, v=self.market_open: v  # 시험이 도는 시각과 무관하게 장중·장외 두 경우를 모두 검증한다
        if extra:
            self.mp.setattr(local_market, "MarketRuntime", functools.partial(local_market.MarketRuntime, **extra))
        stack = self

        class Counting(KisClient):
            def __init__(self, *a, **kw) -> None:
                super().__init__(*a, **kw)
                stack.created_clients.append(self)

        self.mp.setattr(local_intraday, "KisClient", Counting)
        await super().__aenter__()
        self.client = httpx.AsyncClient(base_url=self.url, timeout=10)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.aclose()
        await super().__aexit__(*exc)  # 서버를 내리며 lifespan 종료 처리가 돈다
        self.runtime_after_shutdown = local_market._runtime  # 종료 처리가 끝난 직후의 상태(정리됐다면 None)
        local_market.set_universe_loader(None)
        local_market.reset_market_runtime()

    async def quotes(self, codes: str, **kw) -> httpx.Response:
        return await self.client.get("/api/v1/local/market/quotes", params={"codes": codes}, **kw)

    async def status(self) -> dict:
        return (await self.client.get("/api/v1/local/market/status")).json()["data"]


async def wait_filled(s: MarketStack, code: str = "005930", timeout: float = 10) -> dict:
    """해당 종목 값이 채워질 때까지 `quotes`를 반복 호출한다(요청이 유휴 시간을 갱신한다). 마지막 응답의 `data`를 돌려준다."""
    end = asyncio.get_running_loop().time() + timeout
    while True:
        data = (await s.quotes(code)).json()["data"]
        if data["quotes"]:
            return data
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("값이 채워지지 않았습니다")
        await asyncio.sleep(0.1)


# ── 첫 요청이 폴러를 시작하고 값이 채워진다 ─────────────────────────────────────────────────
@pytest.mark.parametrize("market_open", [True, False, None], ids=["장중", "장외", "실제시각"])
def test_첫_요청이_폴러를_시작하고_값이_채워진다(market_open: bool | None) -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp, market_open=market_open) as s:
            assert local_market._runtime is None  # 요청 전에는 폴러가 없다
            st = await s.status()  # status는 폴러를 시작하지 않는다
            assert st["configured"] is True and st["running"] is False and st["poller"]["calls_total"] == 0 and s.load_calls == 0
            r = await s.quotes("005930,000660,000000,ZZZ999")
            assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
            first = r.json()["data"]
            assert first["quotes"] == [] and first["missing"] == ["005930", "000660", "000000", "ZZZ999"]  # 첫 응답은 비어 있다(0으로 채우지 않음)
            assert first["meta"]["stale"] is True and first["meta"]["last_cycle_at"] is None and first["meta"]["running"] is True
            assert s.load_calls == 1  # 유니버스는 첫 요청 때 읽는다
            data = await wait_filled(s, "005930,000660,000000,ZZZ999")
            await until(lambda: local_market._runtime.poller.last_full_cycle_at is not None, 10)
            data = (await s.quotes("005930,000660,000000,ZZZ999")).json()["data"]
            by_code = {q["code"]: q for q in data["quotes"]}
            assert set(by_code) == {"005930", "000660"}
            q = by_code["005930"]
            assert set(q) == {"code", "price", "change", "change_pct", "volume", "open", "high", "low", "fetched_at"}
            assert q["price"] > 0 and q["volume"] >= 0 and q["high"] >= q["low"] and q["fetched_at"] > 0
            assert data["missing"] == ["000000", "ZZZ999"]  # 빈 값 행·유니버스에 없는 종목은 "없음" 목록으로
            meta = data["meta"]
            assert meta["total"] == 4 and meta["covered"] == 3 and meta["stale"] is False and meta["cycle_seconds"] > 0 and meta["last_cycle_at"] > 0
            st = await s.status()
            assert st["running"] is True and st["poller"]["calls_total"] >= 1 and st["universe"]["total"] == 4 and st["universe"]["last_error"] is None
            assert "mock" not in json.dumps(st)  # 앱키·시크릿은 응답에 나오지 않는다

    run_with_mp(scenario)


def test_요청한_순서를_지키고_중복은_한_번만_답한다() -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp, fast=True) as s:
            async def both() -> dict:
                return (await s.quotes("035720,005930,035720")).json()["data"]

            await until_async(both, lambda d: len(d["quotes"]) == 2)
            data = await both()
            assert [q["code"] for q in data["quotes"]] == ["035720", "005930"] and data["missing"] == []

    run_with_mp(scenario)


def test_값이_낡으면_stale이지만_값은_그대로_돌려준다() -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp) as s:
            await wait_filled(s)
            await until(lambda: local_market._runtime.poller.last_full_cycle_at is not None, 10)
            assert (await s.quotes("005930")).json()["data"]["meta"]["stale"] is False
            mp.setattr(local_market, "STALE_FACTOR", 0.0)  # 한 바퀴 시간의 0배 → 마지막 완주 이후 시간이 조금이라도 지났으면 stale
            await asyncio.sleep(0.05)
            data = (await s.quotes("005930")).json()["data"]
            assert data["meta"]["stale"] is True and [q["code"] for q in data["quotes"]] == ["005930"]  # 낡았어도 값을 지우지 않는다
            assert (await s.status())["stale"] is True

    run_with_mp(scenario)


# ── 입력 검증 ───────────────────────────────────────────────────────────────────────────────
def test_잘못된_입력은_400이고_폴러를_시작하지_않는다() -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp) as s:
            too_many = ",".join(f"{i:06d}" for i in range(101))
            bad = [too_many, "abc123", "00593", "0059300", "005930,", ",005930", "005930,,000660", "005930, 000660", "00593!", "005930;000660", "", "한글한글한글"]
            for codes in bad:
                r = await s.quotes(codes)
                assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PARAMETER", codes
            assert (await s.client.get("/api/v1/local/market/quotes")).status_code == 400  # 파라미터 자체가 없음
            assert local_market._runtime is None and s.load_calls == 0  # 거절된 요청은 폴러·DB를 건드리지 않는다
            exactly = ",".join(f"{i:06d}" for i in range(100))
            r = await s.quotes(exactly)
            assert r.status_code == 200 and len(r.json()["data"]["missing"]) == 100  # 100개는 허용(값은 아직 없음)
            assert (await s.quotes("00A0B0")).status_code == 200  # 영숫자 대문자 허용

    run_with_mp(scenario)


# ── 접근 통제 ───────────────────────────────────────────────────────────────────────────────
def test_접근_통제는_존재를_드러내지_않고_폴러를_시작하지_않는다() -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp) as s:
            for path in ("/api/v1/local/market/quotes?codes=005930", "/api/v1/local/market/status"):
                assert (await s.client.get(path, headers={"Host": "stock.example.com"})).status_code == 404, path
                for h in ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded", "X-Real-IP"):
                    assert (await s.client.get(path, headers={h: "1.2.3.4"})).status_code == 404, (path, h)
            assert local_market._runtime is None and s.load_calls == 0 and not s.created_clients

    async def off(mp) -> None:
        async with MarketStack(mp, LOCAL_INTRADAY_ENABLED="false") as s:
            assert (await s.quotes("005930")).status_code == 404
            assert (await s.client.get("/api/v1/local/market/status")).status_code == 404
            assert local_market._runtime is None and s.load_calls == 0

    async def nokey(mp) -> None:
        async with MarketStack(mp, KIS_APP_KEY="", KIS_APP_SECRET="") as s:
            r = await s.quotes("005930")
            assert r.status_code == 503 and r.json()["error"]["code"] == "LOCAL_INTRADAY_NOT_CONFIGURED"
            assert (await s.client.get("/api/v1/local/market/status")).json()["data"] == {"configured": False}
            assert local_market._runtime is None and s.load_calls == 0

    run_with_mp(scenario)
    run_with_mp(off)
    run_with_mp(nokey)


def test_로그인을_켠_환경에서는_관리자_세션만_통과한다() -> None:
    from services.public_api.auth import service as auth_service

    async def scenario(mp) -> None:
        mp.setattr(local_realtime, "internal_token_enforced", lambda: True)
        mp.setattr(local_realtime, "get_auth_session_factory", lambda: (lambda: types.SimpleNamespace(close=lambda: None)))
        mp.setattr(auth_service, "require_admin", lambda sess, uid, sid: object() if uid == UID else None)
        admin = {"x-auth-user": UID, "x-auth-session": SID}
        member = {"x-auth-user": "33333333-3333-4333-8333-333333333333", "x-auth-session": SID}
        async with MarketStack(mp) as s:
            for h in ({}, member, {"x-auth-user": "not-uuid", "x-auth-session": SID}):
                assert (await s.quotes("005930", headers=h)).status_code == 403
                assert (await s.client.get("/api/v1/local/market/status", headers=h)).status_code == 403
            assert local_market._runtime is None and s.load_calls == 0  # 관리자가 아니면 폴러도 시작하지 않는다
            assert (await s.quotes("005930", headers=admin)).status_code == 200
            assert (await s.client.get("/api/v1/local/market/status", headers=admin)).status_code == 200

    run_with_mp(scenario)


def test_두_경로_모두_소유자_확인_의존성을_쓴다() -> None:
    routes = {r.path: r for r in local_market.router.routes}
    assert set(routes) == {"/local/market/quotes", "/local/market/status"}
    for route in routes.values():
        assert local_realtime.require_owner in [d.call for d in route.dependant.dependencies]  # type: ignore[attr-defined]


# ── 수명: 유휴 정지·재시작·종료 ─────────────────────────────────────────────────────────────
def test_마지막_요청_뒤_유휴_시간이_지나면_폴러가_멈추고_다음_요청에_다시_시작한다() -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp, fast=True, KIS_MARKET_IDLE_SECONDS="0.8") as s:
            await wait_filled(s)
            rt = local_market._runtime
            assert rt.idle_seconds == 0.8
            for _ in range(5):  # 요청이 계속되면 유휴 시간이 갱신돼 멈추지 않는다(0.3초 간격 × 5 > 0.8초)
                await asyncio.sleep(0.3)
                assert (await s.quotes("005930")).status_code == 200
                assert rt.poller.running
            for _ in range(5):  # status 호출은 유휴 시간을 갱신하지 않는다
                await asyncio.sleep(0.3)
                await s.status()
            assert not rt.poller.running and rt.idle_stops_total == 1  # 마지막 quotes 뒤 0.8초 넘게 지나 멈춤
            calls = rt.poller.calls_total
            await asyncio.sleep(0.6)
            assert rt.poller.calls_total == calls  # 정지 뒤 증권사 호출 없음
            st = await s.status()
            assert st["running"] is False and st["idle_stop_in"] is None
            data = (await s.quotes("005930")).json()["data"]  # 재시작: 이전 값은 남아 있고 새 값으로 갱신된다
            assert data["meta"]["running"] is True and [q["code"] for q in data["quotes"]] == ["005930"]
            await until(lambda: rt.poller.calls_total > calls, 10)
            assert rt.starts_total == 2

    run_with_mp(scenario)


def test_유휴_시간_기본값은_5분이고_환경변수가_잘못되면_기본값() -> None:
    mp = pytest.MonkeyPatch()
    try:
        mp.delenv("KIS_MARKET_IDLE_SECONDS", raising=False)
        assert local_market._idle_seconds() == 300.0
        for bad in ("abc", "", " "):
            mp.setenv("KIS_MARKET_IDLE_SECONDS", bad)
            assert local_market._idle_seconds() == 300.0
        mp.setenv("KIS_MARKET_IDLE_SECONDS", "2.5")
        assert local_market._idle_seconds() == 2.5
        mp.setenv("KIS_MARKET_IDLE_SECONDS", "0")
        assert local_market._idle_seconds() == 0.1  # 0 이하로 바쁘게 도는 것을 막는 하한
    finally:
        mp.undo()


def test_앱을_종료하면_폴러와_유지_작업이_정리된다() -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp, fast=True) as s:
            await wait_filled(s)
            rt = local_market._runtime
            assert rt.poller.running and rt._maint is not None and not rt._maint.done()
            maint = rt._maint
            s.rt = rt
        assert s.runtime_after_shutdown is None  # lifespan 종료에서 shutdown_market이 불렸다
        assert not s.rt.poller.running and maint.done()

    run_with_mp(scenario)


# ── 종목 유니버스 ───────────────────────────────────────────────────────────────────────────
def test_종목_목록은_주기적으로_다시_읽고_실패하면_이전_목록을_유지한다() -> None:
    async def scenario(mp) -> None:
        mp.setattr(local_market, "UNIVERSE_REFRESH_SECONDS", 0.4)
        mp.setattr(local_market, "UNIVERSE_RETRY_SECONDS", 0.2)
        async with MarketStack(mp, universe=["005930", "000660", "abc123", "12345", "005930"], fast=True) as s:
            await wait_filled(s, "005930")
            assert (await s.status())["universe"]["total"] == 2  # 형식이 틀린 코드·중복은 걸러진다
            s.universe = ["005930", "000660", "035720"]  # 신규 상장
            await until_async(lambda: s.status(), lambda st: st["universe"]["total"] == 3)
            data = await wait_filled(s, "035720")
            assert [q["code"] for q in data["quotes"]] == ["035720"]

            s.load_error = RuntimeError("postgresql://user:SECRET@db/x connection refused")  # DB 오류
            await until_async(lambda: s.status(), lambda st: st["universe"]["failures"] >= 2)  # 재시도 간격마다 다시 시도
            st = await s.status()
            assert st["universe"]["total"] == 3 and st["universe"]["last_error"] == "RuntimeError"  # 이전 목록 유지, 예외 종류만 노출
            assert "SECRET" not in json.dumps(st)
            kept = (await s.quotes("005930,000660,035720")).json()["data"]  # 읽기 실패 중에도 값은 계속 제공된다
            assert [q["code"] for q in kept["quotes"]] == ["005930", "000660", "035720"] and kept["meta"]["total"] == 3

            s.load_error = None
            s.universe = []  # 0건은 이상 상태 → 실패로 보고 이전 목록 유지
            failures = (await s.status())["universe"]["failures"]
            await until_async(lambda: s.status(), lambda st: st["universe"]["failures"] > failures)
            assert (await s.status())["universe"]["total"] == 3

            s.universe = ["000660"]  # 정상 복구 + 상장폐지(005930·035720 제거)
            await until_async(lambda: s.status(), lambda st: st["universe"]["total"] == 1 and st["universe"]["last_error"] is None)
            data = (await s.quotes("005930,000660")).json()["data"]
            assert data["missing"] == ["005930"] and data["meta"]["total"] == 1  # 빠진 종목의 값은 즉시 사라진다

    run_with_mp(scenario)


def test_첫_종목_목록_읽기가_실패해도_요청은_성공하고_복구되면_채워진다() -> None:
    async def scenario(mp) -> None:
        mp.setattr(local_market, "UNIVERSE_RETRY_SECONDS", 0.2)
        mp.setattr(local_market, "UNIVERSE_REFRESH_SECONDS", 0.4)
        async with MarketStack(mp, fast=True) as s:
            s.load_error = ConnectionError("down")
            r = await s.quotes("005930")
            assert r.status_code == 200 and r.json()["data"]["missing"] == ["005930"] and r.json()["data"]["meta"]["total"] == 0
            s.load_error = None
            data = await wait_filled(s, "005930", timeout=15)
            assert data["meta"]["total"] == 4

    run_with_mp(scenario)


# ── 호출 한도 공유 ──────────────────────────────────────────────────────────────────────────
def test_폴러와_상세_화면은_같은_증권사_클라이언트를_쓴다() -> None:
    async def scenario(mp) -> None:
        async with MarketStack(mp) as s:
            await wait_filled(s)
            rt = local_market._runtime
            shared = local_intraday._service[1]
            assert rt.service is shared and rt.service.client is shared.client
            client = shared.client
            assert len(s.created_clients) == 1 and client._token == "mock-token" and client._last_call > 0  # 폴러의 호출이 이 클라이언트의 토큰·호출 간격을 썼다
            before = client._last_call
            r = await s.client.get("/api/v1/local/stocks/005930/orderbook")  # 상세 화면 REST
            assert r.status_code == 200 and len(s.created_clients) == 1  # 새 클라이언트를 만들지 않는다
            assert client._last_call >= before

    run_with_mp(scenario)


async def until_async(fetch, pred, timeout: float = 10.0) -> None:
    """`fetch()`(코루틴) 결과가 `pred`를 만족할 때까지 반복한다(요청이 유휴 시간을 갱신한다)."""
    end = asyncio.get_running_loop().time() + timeout
    while True:
        if pred(await fetch()):
            return
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("조건이 시간 안에 충족되지 않았습니다")
        await asyncio.sleep(0.1)


class _FastClient:
    def multi_price(self, codes):  # pragma: no cover — 호출되지 않는 자리 표시
        return {}


def _runtime(**over) -> local_market.MarketRuntime:
    kw: dict = dict(idle_seconds=300, universe_refresh=3600, universe_retry=30, is_market_open=lambda now: True, wall_clock=lambda: 1_000.0)
    kw.update(over)
    service = types.SimpleNamespace(client=_FastClient())
    return local_market.MarketRuntime(service, **kw)  # type: ignore[arg-type]


# ── 단위: 입력 검증·stale 경계·보기 ──────────────────────────────────────────────────────────
def test_종목코드_파싱() -> None:
    assert local_market.parse_codes("005930,000660,005930") == ["005930", "000660"]
    assert local_market.parse_codes("A1B2C3") == ["A1B2C3"]
    assert len(local_market.parse_codes(",".join(f"{i:06d}" for i in range(100)))) == 100
    for bad in ("", "a00000", "00000", "0000000", "00000a", "000000,", " 005930", "005930 ", ",".join(f"{i:06d}" for i in range(101))):
        with pytest.raises(ApiError) as e:
            local_market.parse_codes(bad)
        assert e.value.status_code == 400, bad


def test_stale_판정_경계_장중과_장외() -> None:
    rt = _runtime()
    rt.poller.last_cycle_seconds = 2.0
    rt.poller.last_full_cycle_at = 1_000.0 - 6.0  # 정확히 주기(2초)의 3배
    assert rt.meta({})["stale"] is False and rt.meta({})["cycle_seconds"] == 2.0
    rt.poller.last_full_cycle_at = 1_000.0 - 6.01
    assert rt.meta({})["stale"] is True
    off = _runtime(is_market_open=lambda now: False)  # 장 시간 밖: 주기는 300초
    off.poller.last_cycle_seconds = 2.0
    off.poller.last_full_cycle_at = 1_000.0 - 899
    assert off.meta({})["cycle_seconds"] == 300.0 and off.meta({})["stale"] is False
    off.poller.last_full_cycle_at = 1_000.0 - 901
    assert off.meta({})["stale"] is True
    fresh = _runtime()  # 아직 한 바퀴도 못 돌았다 → stale, 주기·완주 시각 없음
    m = fresh.meta({})
    assert m["stale"] is True and m["cycle_seconds"] is None and m["last_cycle_at"] is None


def test_장중_첫_바퀴의_짧은_측정_시간은_호출_간격_하한으로_보정한다() -> None:
    # 회귀: 첫 바퀴는 호출 간격 대기가 없어 측정 시간이 0.01초로 나오고, 그 3배(0.03초)만으로 stale을 판정하면 정상 상태가 늘 stale로 보였다
    rt = _runtime(config=PollerConfig(min_interval=0.2, cycle_pause=0.0))
    rt.poller.set_codes([f"{i:06d}" for i in range(60)])  # 2묶음
    rt.poller.last_cycle_seconds = 0.01
    rt.poller.last_full_cycle_at = 1_000.0 - 1.0
    m = rt.meta({})
    assert m["cycle_seconds"] == 0.4 and m["stale"] is False  # 3 × 0.4 = 1.2초 이내
    rt.poller.last_full_cycle_at = 1_000.0 - 1.3
    assert rt.meta({})["stale"] is True


def test_보기는_값이_없는_종목을_missing으로_알린다() -> None:
    rt = _runtime()
    rt.poller.set_codes(["005930", "000660"])
    rt.poller._quotes["005930"] = MarketQuote("005930", 70000.0, -500.0, -0.71, 1234, 70500.0, 71000.0, 69800.0, 999.0)
    view = rt.view(["000660", "005930", "999999"])
    assert [q["code"] for q in view["quotes"]] == ["005930"] and view["missing"] == ["000660", "999999"]
    assert view["quotes"][0]["change"] == -500.0 and view["quotes"][0]["fetched_at"] == 999.0
    assert view["meta"]["covered"] == 1 and view["meta"]["total"] == 2


# ── 단위: 호출 우선순위(상세 화면이 먼저) ───────────────────────────────────────────────────
def _kis(tmp_path: Path, handler, **kw) -> KisClient:
    settings = cfg.get_settings({cfg.ENABLED_ENV: "true", cfg.APP_KEY_ENV: "K" * 12, cfg.APP_SECRET_ENV: "S" * 20, cfg.TOKEN_CACHE_ENV: str(tmp_path / "t.json")})
    return KisClient(settings, httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0, **kw)


def test_낮은_우선순위_호출은_일반_호출이_진행_중이면_양보한다(tmp_path: Path) -> None:
    order: list[str] = []
    release = threading.Event()
    started = threading.Event()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        if req.url.path.endswith("inquire-asking-price-exp-ccn"):
            started.set()
            release.wait(5)  # 상세 화면 호출이 진행 중(응답 대기)
            order.append("detail-done")
            return httpx.Response(200, json={"rt_cd": "0", "output1": {}, "output2": {}})
        order.append("multi")
        return httpx.Response(200, json={"rt_cd": "0", "output": []})

    client = _kis(tmp_path, handler)
    t_detail = threading.Thread(target=lambda: client.orderbook("005930"))
    t_detail.start()
    assert started.wait(5)
    t_multi = threading.Thread(target=lambda: client.multi_price(["005930"]))
    t_multi.start()
    time.sleep(0.3)
    assert "multi" not in order  # 상세 화면 호출이 끝나기 전에는 순환 호출이 나가지 않는다
    release.set()
    t_detail.join(5)
    t_multi.join(5)
    assert order == ["detail-done", "multi"] and client._priority_pending == 0


def test_양보는_최대_2초로_제한되고_일반_호출끼리는_서로_기다리지_않는다(tmp_path: Path) -> None:
    sleeps: list[float] = []
    client = _kis(tmp_path, lambda req: httpx.Response(200, json={"access_token": "t", "expires_in": 1, "rt_cd": "0", "output": []}), sleep=sleeps.append)
    client._priority_pending = 1  # 일반 호출이 끝나지 않는 상황
    client.multi_price(["005930"])
    assert len(sleeps) == kc.LOW_PRIORITY_MAX_YIELDS and abs(sum(sleeps) - 2.0) < 1e-6  # 굶지 않고 2초 뒤 진행
    sleeps.clear()
    client._priority_pending = 0
    client.orderbook("005930")
    client.multi_price(["005930"])
    assert sleeps == []  # 일반 호출은 양보하지 않고, 대기 중인 일반 호출이 없으면 낮은 우선순위도 기다리지 않는다


def test_일반_호출이_예외로_끝나도_우선순위_카운터가_돌아온다(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "X", "msg1": "거절"})

    client = _kis(tmp_path, handler)
    with pytest.raises(kc.KisError):
        client.orderbook("005930")
    assert client._priority_pending == 0
