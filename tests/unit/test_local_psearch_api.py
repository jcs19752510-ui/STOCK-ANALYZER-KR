"""증권사 조건검색 API 시험 — 실제 uvicorn 서버 + 모의 증권사 REST로 끝까지 검증한다 (DEC-088, 계약서 docs/stock-detail/09-psearch-api-contract.md).

실제 증권사 접속·DB 없음. 시계는 주입(`local_psearch.set_clock`)해 캐시 만료를 결정적으로 시험한다.
증권사 쪽 실패(한도·거절 문구)는 `KisClient.psearch_*`를 감싸 순서대로 주입하고, 연결 불가는 모의 서버를 실제로 내려서 만든다.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import logging
import types

import httpx
import pytest
from test_realtime_stream_api import (  # mock_kis_server: scripts 경로를 잡아 둔 같은 모듈 객체
    SID,
    UID,
    Stack,
    mock_kis_server,
    run_with_mp,
)

from services.public_api.api import local_psearch, local_realtime
from services.public_api.intraday import config as cfg
from services.public_api.intraday.kis_client import KisClient, KisError
from services.public_api.rate_limit import reset_rate_limit_state

APP_KEY = "APPKEY-SECRET-1234"
APP_SECRET = "APPSECRET-SECRET-5678"
HTS = "myhtsid77"
SECRETS = (APP_KEY, APP_SECRET, HTS)
T0 = 1_800_000_000.0
RESULT_KEYS = {"seq", "items", "count", "capped", "empty", "empty_message", "changes", "fields", "fetched_at", "age_seconds", "cache_ttl_seconds", "stale"}
ITEM_KEYS = {"code", "name", "market", "entered_at"}


class FakeClock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> float:
        return self.t

    def advance(self, sec: float) -> None:
        self.t += sec


def codes(n: int, last: int | None = None) -> list[str]:
    return [f"{i:06d}" for i in range(n, (last if last is not None else n))]


class PStack(Stack):
    """모의 증권사 + 실제 API 서버. 시계·종목 마스터를 주입하고 증권사 호출 횟수를 센다."""

    def __init__(self, mp: pytest.MonkeyPatch, **env: str) -> None:
        base = {"KIS_APP_KEY": APP_KEY, "KIS_APP_SECRET": APP_SECRET, "KIS_HTS_ID": HTS, "KIS_PSEARCH_CACHE_SECONDS": "5"}
        base.update(env)
        super().__init__(mp, **base)
        self.clock = FakeClock()
        self.master: dict[str, tuple[str, str]] = {f"{i:06d}": (f"마스터{i:06d}", "KOSPI" if i % 2 else "KOSDAQ") for i in range(1, 200)}
        self.master_calls: list[list[str]] = []
        self.master_error: Exception | None = None
        self.result_calls: list[str] = []
        self.titles_calls = 0
        self.script: list[object] = []  # Exception이면 던지고, dict면 그 본문을 돌려주고, 아니면(None) 모의 증권사로 보낸다

    def _master(self, wanted: list[str]) -> dict[str, tuple[str, str]]:
        self.master_calls.append(list(wanted))
        if self.master_error is not None:
            raise self.master_error
        return {c: self.master[c] for c in wanted if c in self.master}

    def _next(self) -> object:
        return self.script.pop(0) if self.script else None

    async def __aenter__(self) -> PStack:
        reset_rate_limit_state()
        mock_kis_server.PSEARCH_CALLS.clear()
        local_psearch.reset_psearch_state()
        local_psearch.set_clock(self.clock)
        local_psearch.set_cache_seconds(None)
        local_psearch.set_master_loader(self._master)
        stack = self
        orig_result, orig_titles = KisClient.psearch_result, KisClient.psearch_titles

        def result(client, user_id, seq, **kw):
            stack.result_calls.append(seq)
            step = stack._next()
            if isinstance(step, Exception):
                raise step
            if isinstance(step, dict):
                return step
            return orig_result(client, user_id, seq, **kw)

        def titles(client, user_id, **kw):
            stack.titles_calls += 1
            step = stack._next()
            if isinstance(step, Exception):
                raise step
            if isinstance(step, dict):
                return step
            return orig_titles(client, user_id, **kw)

        self.mp.setattr(KisClient, "psearch_result", result)
        self.mp.setattr(KisClient, "psearch_titles", titles)
        await super().__aenter__()
        self.client = httpx.AsyncClient(base_url=self.url, timeout=15)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.aclose()
        await super().__aexit__(*exc)
        local_psearch.set_clock(None)
        local_psearch.set_cache_seconds(None)
        local_psearch.set_master_loader(None)
        local_psearch.reset_psearch_state()

    async def results(self, seq: str = "0", **kw) -> httpx.Response:
        return await self.client.get("/api/v1/local/psearch/results", params={"seq": seq}, **kw)

    async def data(self, seq: str = "0") -> dict:
        r = await self.results(seq)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    async def conditions(self, **kw) -> httpx.Response:
        return await self.client.get("/api/v1/local/psearch/conditions", **kw)

    def kill_broker(self) -> None:
        self.rest.shutdown()
        self.rest.server_close()  # 이후 증권사 호출은 연결 거절(실제 연결 실패)


def ids(data: dict) -> list[str]:
    return [i["code"] for i in data["items"]]


def no_secret(*texts: str) -> None:
    blob = "\n".join(texts)
    for s in SECRETS:
        assert s not in blob, "비밀값이 노출됨"


# ── 설정(IntradaySettings) ─────────────────────────────────────────────────────────────────────
def test_설정은_hts_id를_읽고_공백을_없애고_repr에_드러내지_않는다() -> None:
    base = {"LOCAL_INTRADAY_ENABLED": "false"}
    assert cfg.get_settings(dict(base)).hts_id is None
    assert cfg.get_settings({**base, "KIS_HTS_ID": ""}).hts_id is None
    assert cfg.get_settings({**base, "KIS_HTS_ID": "   "}).hts_id is None
    s = cfg.get_settings({**base, "KIS_HTS_ID": "  myid  ", "KIS_APP_KEY": "KEY1", "KIS_APP_SECRET": "SEC1"})
    assert s.hts_id == "myid"
    assert "myid" not in repr(s) and "myid" not in str(s) and "hts_id" not in repr(s)
    # 기존 생성처(hts_id 인자 없음)와 호환
    legacy = cfg.IntradaySettings(enabled=True, app_key="a", app_secret="b", base_url="http://x", allowed_networks=(), token_cache_path=__import__("pathlib").Path("t"))
    assert legacy.hts_id is None and legacy.configured


@pytest.mark.parametrize(
    "raw,want",
    [(None, 5.0), ("", 5.0), ("  ", 5.0), ("abc", 5.0), ("nan", 5.0), ("1", 2.0), ("0", 2.0), ("-3", 2.0), ("2", 2.0), ("2.5", 2.5), (" 7 ", 7.0), ("30", 30.0), ("60", 60.0), ("61", 60.0), ("100000", 60.0), ("inf", 60.0)],
)
def test_캐시_시간은_환경변수로_정하고_2에서_60초로_보정한다(raw: str | None, want: float) -> None:
    mp = pytest.MonkeyPatch()
    try:
        if raw is None:
            mp.delenv("KIS_PSEARCH_CACHE_SECONDS", raising=False)
        else:
            mp.setenv("KIS_PSEARCH_CACHE_SECONDS", raw)
        assert local_psearch._env_cache_seconds() == want
    finally:
        mp.undo()


def test_로그_필터는_user_id를_가린다() -> None:
    f = local_psearch._RedactUserId()
    rec = logging.LogRecord("httpx", logging.INFO, "x", 1, 'HTTP Request: GET %s "HTTP/1.1 200 OK"', ("http://h/p?user_id=myhtsid77&seq=0",), None)
    assert f.filter(rec) and "myhtsid77" not in rec.getMessage() and "user_id=***&seq=0" in rec.getMessage()
    plain = logging.LogRecord("httpx", logging.INFO, "x", 1, "no secret here", (), None)
    assert f.filter(plain) and plain.getMessage() == "no secret here"


# ── 조건 목록 ────────────────────────────────────────────────────────────────────────────────────
def test_조건_목록은_모양이_맞고_60초_캐시되며_만료_뒤_다시_읽는다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            r = await s.conditions()
            assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
            body = r.json()
            assert body["error"] is None and set(body["data"]) == {"conditions", "fetched_at"}
            assert body["data"]["conditions"] == [
                {"seq": "0", "group": "모의그룹", "name": "모의 변동 조건"},
                {"seq": "1", "group": "모의그룹", "name": "모의 빈 조건"},
                {"seq": "2", "group": "모의그룹", "name": "모의 100건 조건"},
            ]
            assert body["data"]["fetched_at"] == T0
            replies = await asyncio.gather(*[s.conditions() for _ in range(8)])  # 여러 화면이 열려도 증권사 호출은 늘지 않는다
            assert all(x.json() == body for x in replies) and s.titles_calls == 1
            s.clock.advance(59.9)
            assert (await s.conditions()).json() == body and s.titles_calls == 1
            s.clock.advance(0.2)  # 60초 경과
            r2 = await s.conditions()
            assert s.titles_calls == 2 and r2.json()["data"]["fetched_at"] == T0 + 60.1

    run_with_mp(scenario)


def test_조건_목록이_비었거나_일부_행이_이상해도_안전하다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            s.script = [{"rt_cd": "0", "output2": []}]
            r = await s.conditions()
            assert r.status_code == 200 and r.json()["data"]["conditions"] == []  # 서버저장한 조건이 없음
            s.clock.advance(61)
            s.script = [{"rt_cd": "0", "output2": [{"seq": "3", "grp_nm": "가", "condition_nm": "나"}, {"grp_nm": "seq없음"}, {"seq": "bad seq!"}, "문자열", {"seq": 7, "grp_nm": None}]}]
            assert (await s.conditions()).json()["data"]["conditions"] == [{"seq": "3", "group": "가", "name": "나"}, {"seq": "7", "group": "", "name": ""}]
            s.clock.advance(61)
            s.script = [{"rt_cd": "0"}]  # output2 자체가 없음
            assert (await s.conditions()).json()["data"]["conditions"] == []

    run_with_mp(scenario)


def test_조건_목록_조회_실패의_오류_코드와_비밀값_가리기() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            s.script = [KisError("UPSTREAM_ERROR", f"증권사가 요청을 거절했습니다. {HTS} 서버저장 조건 없음 {APP_KEY}")]
            r = await s.conditions()
            e = r.json()["error"]
            assert r.status_code == 502 and e["code"] == "PSEARCH_REJECTED" and "서버저장 조건 없음" in e["message"] and r.json()["data"] is None
            no_secret(r.text)
            r = await s.conditions()  # 방금 거절됐다: 증권사를 다시 두드리지 않고 같은 오류
            assert r.status_code == 502 and s.titles_calls == 1
            s.clock.advance(11)
            s.script = [KisError("RATE_LIMITED", "한도")]
            assert (await s.conditions()).status_code == 429
            s.clock.advance(11)
            s.script = [KisError("AUTH_FAILED", "증권사 인증에 실패했습니다(앱키·시크릿을 확인하세요).")]
            r = await s.conditions()
            assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
            s.clock.advance(11)
            s.script = [RuntimeError(f"예상 밖 {HTS} {APP_SECRET}")]
            r = await s.conditions()
            assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
            no_secret(r.text)
            s.clock.advance(11)
            assert (await s.conditions()).status_code == 200  # 회복

    run_with_mp(scenario)


# ── 결과: 모양·캐시·편입 이탈 ────────────────────────────────────────────────────────────────────────
def test_결과_모양과_필드와_이름_시장_보충() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            r = await s.results("0")
            assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
            body = r.json()
            assert body["error"] is None
            d = body["data"]
            assert set(d) == RESULT_KEYS and d["seq"] == "0"
            assert ids(d) == ["000001", "000002", "000003", "000004", "000005"] and d["count"] == 5  # 증권사 순서 유지
            for it in d["items"]:
                assert set(it) == ITEM_KEYS and it["entered_at"] == T0
            assert d["items"][0] == {"code": "000001", "name": "모의000001", "market": "KOSPI", "entered_at": T0}  # 이름: 증권사 행 우선, 시장: 마스터
            assert d["items"][1]["market"] == "KOSDAQ"
            assert d["capped"] is False and d["empty"] is False and d["empty_message"] is None and d["stale"] is False
            assert d["changes"] == [] and d["fields"] == ["code", "name", "price", "chgrate", "acml_vol"]
            assert d["fetched_at"] == T0 and d["age_seconds"] == 0 and d["cache_ttl_seconds"] == 5
            s.clock.advance(2.5)
            d2 = await s.data("0")
            assert d2["age_seconds"] == 2.5 and d2["fetched_at"] == T0  # 캐시 응답은 받은 시각을 그대로, 나이만 늘어난다
            assert all(set(i) == ITEM_KEYS for i in d2["items"])  # 가격은 이 API에 없다(필드 이름 목록 `fields`는 진단용)

    run_with_mp(scenario)


def test_캐시_동시_요청이_여러_번_와도_증권사_호출은_한_번() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            replies = await asyncio.gather(*[s.results("0") for _ in range(25)])
            assert {r.status_code for r in replies} == {200}
            assert mock_kis_server.PSEARCH_CALLS == {"0": 1} and s.result_calls == ["0"]
            assert len({json.dumps(r.json()["data"], sort_keys=True) for r in replies}) == 1  # 모두 같은 결과
            for _ in range(5):
                await s.data("0")
            assert mock_kis_server.PSEARCH_CALLS == {"0": 1}
            s.clock.advance(4.99)
            await s.data("0")
            assert mock_kis_server.PSEARCH_CALLS == {"0": 1}  # 경계 직전: 아직 재사용
            s.clock.advance(0.02)  # 5.01초
            await asyncio.gather(*[s.results("0") for _ in range(10)])
            assert mock_kis_server.PSEARCH_CALLS == {"0": 2}  # 만료 뒤 동시 요청도 한 번
            # 조건별 캐시: 다른 seq는 따로 호출한다
            await asyncio.gather(s.results("1"), s.results("2"), s.results("1"))
            assert mock_kis_server.PSEARCH_CALLS == {"0": 2, "1": 1, "2": 1}

    run_with_mp(scenario)


def test_캐시_시간_환경변수가_반영되고_범위로_보정된다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp, KIS_PSEARCH_CACHE_SECONDS="30") as s:
            d = await s.data("0")
            assert d["cache_ttl_seconds"] == 30
            s.clock.advance(29)
            await s.data("0")
            assert mock_kis_server.PSEARCH_CALLS == {"0": 1}
            s.clock.advance(1.5)
            await s.data("0")
            assert mock_kis_server.PSEARCH_CALLS == {"0": 2}

    async def low(mp) -> None:
        async with PStack(mp, KIS_PSEARCH_CACHE_SECONDS="0.1") as s:  # 2초로 올려 쓴다
            assert (await s.data("0"))["cache_ttl_seconds"] == 2
            s.clock.advance(1.9)
            await s.data("0")
            assert mock_kis_server.PSEARCH_CALLS == {"0": 1}

    run_with_mp(scenario)
    run_with_mp(low)


def test_캐시_만료_뒤_편입_이탈을_기록하고_entered_at을_유지한다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            d = await s.data("0")  # 호출 1: 1..5
            assert d["changes"] == []  # 첫 조회는 변화로 치지 않는다
            for _ in range(2):  # 호출 2·3: 같은 결과
                s.clock.advance(6)
                d = await s.data("0")
                assert ids(d) == codes(1, 6) and d["changes"] == []
            s.clock.advance(6)  # 호출 4: 000006 편입, 000001 이탈
            t4 = s.clock.t
            d = await s.data("0")
            assert ids(d) == codes(2, 7)
            assert d["changes"] == [{"at": t4, "added": ["000006"], "removed": ["000001"]}]
            by = {i["code"]: i["entered_at"] for i in d["items"]}
            assert by["000002"] == T0 and by["000005"] == T0 and by["000006"] == t4  # 남은 종목은 처음 본 시각 유지, 새 종목은 지금
            for _ in range(5):  # 호출 5~9: 호출 7에서 또 한 번 바뀐다
                s.clock.advance(6)
                d = await s.data("0")
            assert ids(d) == codes(3, 8) and mock_kis_server.PSEARCH_CALLS == {"0": 9}
            assert [(c["added"], c["removed"]) for c in d["changes"]] == [(["000007"], ["000002"]), (["000006"], ["000001"])]  # 최신이 앞
            assert d["changes"][0]["at"] > d["changes"][1]["at"]
            assert d["fields"] == ["code", "name", "price", "chgrate", "acml_vol"]

    run_with_mp(scenario)


def test_변화_기록은_최대_20건이고_이탈한_종목이_다시_들어오면_새_편입_시각() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            await s.data("0")
            for k in range(1, 26):  # 25번 바뀐 결과를 만든다
                s.script = [{"rt_cd": "0", "output2": [{"code": f"{900000 + k:06d}"}]}]
                s.clock.advance(6)
                d = await s.data("0")
            assert len(d["changes"]) == 20 and d["changes"][0]["added"] == ["900025"] and d["changes"][-1]["added"] == ["900006"]
            # 재진입: A가 빠졌다가 다시 들어오면 entered_at은 다시 센다
            s.script = [{"rt_cd": "0", "output2": [{"code": "AAAAAA"}, {"code": "BBBBBB"}]}]
            s.clock.advance(6)
            first = (await s.data("0"))["items"][0]["entered_at"]
            s.script = [{"rt_cd": "0", "output2": [{"code": "BBBBBB"}]}]
            s.clock.advance(6)
            await s.data("0")
            s.script = [{"rt_cd": "0", "output2": [{"code": "AAAAAA"}, {"code": "BBBBBB"}]}]
            s.clock.advance(6)
            again = {i["code"]: i["entered_at"] for i in (await s.data("0"))["items"]}
            assert again["AAAAAA"] == s.clock.t > first and again["BBBBBB"] == first

    run_with_mp(scenario)


def test_증권사_HTTP_장애는_0건이_아니라_실패로_보고_이전_결과를_stale로_유지한다() -> None:
    """HTTP 200인 업무 거절(rt_cd≠0)만 0건으로 본다. HTTP 5xx·인증 오류(`http_status`≠200)를 0건으로 오인해 전부 이탈로 기록하면 안 된다."""

    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            before = await s.data("0")
            assert before["items"]
            s.script = [KisError("UPSTREAM_ERROR", "증권사가 요청을 거절했습니다. 서버 오류", http_status=500)]
            s.clock.advance(6)
            d = await s.data("0")
            assert d["stale"] is True and d["empty"] is False and ids(d) == ids(before)
            assert d["changes"] == before["changes"]  # 이탈로 기록되지 않았다

    run_with_mp(scenario)


# ── 0건·100건 ─────────────────────────────────────────────────────────────────────────────────────
def test_0건은_오류가_아니라_200_empty이고_직전_종목은_모두_이탈로_기록한다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            r = await s.results("1")  # 모의 증권사: seq 1은 처음부터 0건 오류
            assert r.status_code == 200
            d = r.json()["data"]
            assert d["empty"] is True and d["items"] == [] and d["count"] == 0 and d["empty_message"] == "검색 결과가 없습니다."
            assert d["stale"] is False and d["changes"] == [] and d["fields"] == [] and d["capped"] is False  # 첫 조회는 변화 없음
            first_at = d["fetched_at"]
            # 종목이 있던 조건이 0건이 되면: 전부 이탈
            await s.data("0")
            s.script = [KisError("UPSTREAM_ERROR", "증권사가 요청을 거절했습니다. 검색 결과가 없습니다.")]
            s.clock.advance(6)
            d = await s.data("0")
            assert d["empty"] is True and d["items"] == [] and d["stale"] is False and d["empty_message"] == "검색 결과가 없습니다."
            assert d["changes"] == [{"at": s.clock.t, "added": [], "removed": codes(1, 6)}]
            assert d["fields"] == ["code", "name", "price", "chgrate", "acml_vol"]  # 진단용 필드 목록은 첫 비어 있지 않은 응답 기준으로 남는다
            # 다시 종목이 생기면 전부 편입으로 기록
            s.clock.advance(6)
            d = await s.data("0")
            assert d["empty"] is False and ids(d) == codes(1, 6) and d["empty_message"] is None
            assert d["changes"][0] == {"at": s.clock.t, "added": codes(1, 6), "removed": []} and len(d["changes"]) == 2
            assert all(i["entered_at"] == s.clock.t for i in d["items"])
            # 0건도 캐시된다(증권사 호출 1번)
            s.clock.advance(6)
            await asyncio.gather(*[s.results("1") for _ in range(6)])
            assert mock_kis_server.PSEARCH_CALLS["1"] == 2 and (await s.data("1"))["fetched_at"] > first_at

    run_with_mp(scenario)


def test_0건_문구는_비밀값을_가리고_120자로_자른다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            long = "가" * 300
            s.script = [KisError("UPSTREAM_ERROR", f"증권사가 요청을 거절했습니다. {HTS} 사용자 {APP_KEY} 조건 {APP_SECRET} {long}")]
            r = await s.results("5")
            d = r.json()["data"]
            assert r.status_code == 200 and d["empty"] is True and len(d["empty_message"]) <= 120
            assert "***" in d["empty_message"]
            no_secret(r.text)
            s.script = [KisError("UPSTREAM_ERROR", "증권사가 요청을 거절했습니다.")]
            s.clock.advance(6)
            assert (await s.data("5"))["empty_message"] is None  # 증권사 문구가 없으면 null

    run_with_mp(scenario)


def test_성공이지만_행이_하나도_없으면_empty이고_문구는_null() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            s.script = [{"rt_cd": "0", "output2": []}]
            d = await s.data("0")
            assert d["empty"] is True and d["empty_message"] is None and d["items"] == []

    run_with_mp(scenario)


def test_100건이면_capped이고_순서와_개수를_지킨다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            d = await s.data("2")
            assert d["capped"] is True and d["count"] == 100 and len(d["items"]) == 100 and ids(d) == codes(1, 101)
            assert d["empty"] is False
            # 증권사가 100건을 넘겨도 100건에서 자른다
            s.script = [{"rt_cd": "0", "output2": [{"code": f"{i:06d}"} for i in range(1, 131)]}]
            s.clock.advance(6)
            d = await s.data("2")
            assert d["capped"] is True and d["count"] == 100 and ids(d)[-1] == "000100"
            # 99건은 capped가 아니다
            s.script = [{"rt_cd": "0", "output2": [{"code": f"{i:06d}"} for i in range(1, 100)]}]
            s.clock.advance(6)
            d = await s.data("2")
            assert d["capped"] is False and d["count"] == 99

    run_with_mp(scenario)


# ── 증권사 행 해석 ─────────────────────────────────────────────────────────────────────────────────
def test_종목코드_필드를_이름_순서대로_찾고_없으면_6자리_값을_쓰며_이상한_행은_버린다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            rows = [
                {"stck_shrn_iscd": "000010", "hts_kor_isnm": "엑스", "x": "000011"},
                {"mksc_shrn_iscd": "000020", "stock_name": "와이"},
                {"jong_code": " 000030 "},
                {"stock_code": "00004A", "name": ""},
                {"code": "000050", "stck_shrn_iscd": "000051"},  # code가 먼저
                {"zzz": "abc", "who": "000060", "n": "5"},  # 알려진 이름 없음 → 6자리 영숫자 값을 가진 첫 필드
                {"zzz": "abc12"},  # 코드 없음 → 버림
                {"code": "12345"},  # 5자리 → 버림
                {"code": "0000700"},  # 7자리 → 버림
                {"code": "00008!"},  # 영숫자 아님 → 버림
                {"code": "000010"},  # 중복 → 처음 한 번만
                {"code": ""},
                "문자열행", None, 7,
            ]
            s.script = [{"rt_cd": "0", "output2": rows}]
            d = await s.data("0")
            assert ids(d) == ["000010", "000020", "000030", "00004A", "000050", "000060"]
            assert [i["name"] for i in d["items"]][:3] == ["엑스", "와이", "마스터000030"]  # 행의 이름 → 없으면 마스터
            assert d["items"][3]["name"] is None  # 마스터에 없는 코드, 행의 이름은 빈 값
            assert d["fields"] == ["stck_shrn_iscd", "hts_kor_isnm", "x"]
            # output2가 리스트가 아니거나 없으면 0건 취급
            s.script = [{"rt_cd": "0", "output2": "이상함"}]
            s.clock.advance(6)
            assert (await s.data("0"))["empty"] is True

    run_with_mp(scenario)


# ── 종목 이름·시장 보충 ────────────────────────────────────────────────────────────────────────────
def test_이름은_행에_없으면_마스터에서_시장은_마스터에서_보충하고_캐시한다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            s.script = [{"rt_cd": "0", "output2": [{"code": "000001"}, {"code": "000002", "name": "행의 이름"}, {"code": "ZZ9999"}]}]
            d = await s.data("0")
            assert d["items"] == [
                {"code": "000001", "name": "마스터000001", "market": "KOSPI", "entered_at": T0},
                {"code": "000002", "name": "행의 이름", "market": "KOSDAQ", "entered_at": T0},  # 행의 이름이 우선
                {"code": "ZZ9999", "name": None, "market": None, "entered_at": T0},  # 마스터에 없음 → null
            ]
            assert s.master_calls == [["000001", "000002", "ZZ9999"]]
            for _ in range(4):  # 같은 코드는 다시 읽지 않는다(없는 코드도 기억한다)
                await s.data("0")
            assert len(s.master_calls) == 1
            s.script = [{"rt_cd": "0", "output2": [{"code": "000001"}, {"code": "000003"}]}]
            s.clock.advance(6)
            await s.data("0")
            assert s.master_calls[-1] == ["000003"]  # 새 코드만 읽는다

    run_with_mp(scenario)


def test_마스터_조회가_실패하면_이름_시장은_null로_계속하고_잠시_뒤_다시_읽는다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            s.script = [{"rt_cd": "0", "output2": [{"code": "000001"}, {"code": "000002", "name": "행의 이름"}]}]
            s.master_error = RuntimeError(f"DB 접속 실패 {HTS}")
            r = await s.results("0")
            assert r.status_code == 200
            d = r.json()["data"]
            assert [(i["name"], i["market"]) for i in d["items"]] == [(None, None), ("행의 이름", None)]
            for _ in range(3):  # 실패 직후에는 요청마다 DB를 치지 않는다
                s.clock.advance(1)
                await s.data("0")
            assert len(s.master_calls) == 1
            s.master_error = None
            s.clock.advance(31)
            s.script = [{"rt_cd": "0", "output2": [{"code": "000001"}, {"code": "000002", "name": "행의 이름"}]}]
            d = await s.data("0")
            assert len(s.master_calls) == 2 and d["items"][0]["name"] == "마스터000001" and d["items"][0]["market"] == "KOSPI"

    run_with_mp(scenario)


def test_마스터_캐시는_최대_5000건이고_1시간_뒤_만료된다() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        local_psearch.reset_psearch_state()
        local_psearch.set_clock(clock)
        calls: list[int] = []

        def loader(wanted: list[str]) -> dict[str, tuple[str, str]]:
            calls.append(len(wanted))
            return {c: (f"n{c}", "KOSPI") for c in wanted}

        local_psearch.set_master_loader(loader)
        try:
            many = [f"{i:06d}" for i in range(6000)]
            out = await local_psearch._enrich(many)
            assert out["000000"] == ("n000000", "KOSPI") and out["005999"] == ("n005999", "KOSPI")
            assert len(local_psearch._master_cache) == 5000 and calls == [6000]
            clock.advance(3599)
            await local_psearch._enrich(["005999"])
            assert calls == [6000]  # 1시간 안: 재사용
            clock.advance(2)
            await local_psearch._enrich(["005999"])
            assert calls == [6000, 1]  # 1시간 뒤: 다시 읽음
            # 시계가 거꾸로 가도(과거 시각 항목) 다시 읽는다
            clock.t -= 7200
            await local_psearch._enrich(["005999"])
            assert calls == [6000, 1, 1]
        finally:
            local_psearch.set_clock(None)
            local_psearch.set_master_loader(None)
            local_psearch.reset_psearch_state()

    asyncio.run(scenario())


# ── 입력 검증 ───────────────────────────────────────────────────────────────────────────────────────
def test_잘못된_seq는_400이고_증권사를_부르지_않는다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            bad = ["", " ", "a b", "12345678901", "한글", "a-b", "0;1", "0\n", "\n0", "a_b", "٣", "0/../1", "%00", "0 ", "<script>", "a" * 11, "０"]
            for seq in bad:
                r = await s.results(seq)
                assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_SEQ" and r.json()["data"] is None, repr(seq)
            r = await s.client.get("/api/v1/local/psearch/results")  # 파라미터 자체가 없음
            assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_SEQ"
            r = await s.client.get("/api/v1/local/psearch/results?seq=0&seq=1")  # 중복 파라미터는 처음 값만(검증은 통과)
            assert r.status_code == 200 and s.result_calls == ["1"]  # 중복 파라미터는 FastAPI가 마지막 값을 쓴다(검증은 그 값에 한다)
            for seq in ("0", "A9", "1234567890", "abcdefghij"):
                assert (await s.results(seq)).status_code == 200, seq

    run_with_mp(scenario)


def test_조건_20개_초과는_오래_안_쓴_것부터_버린다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            for i in range(21):
                assert (await s.results(f"a{i}")).status_code == 200
            assert len(local_psearch._entries) == 20 and "a0" not in local_psearch._entries and "a20" in local_psearch._entries
            await s.data("a1")  # 최근에 쓴 것은 살아남는다
            await s.data("a21")
            assert "a1" in local_psearch._entries and "a2" not in local_psearch._entries and len(local_psearch._entries) == 20
            for i in range(100):  # 계속 새 조건을 보내도 보관은 20개를 넘지 않는다
                await s.results(f"b{i}")
            assert len(local_psearch._entries) == 20

    run_with_mp(scenario)


# ── 설정 누락 ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("hts", ["", "   "])
def test_hts_id가_없으면_두_경로_모두_503_PSEARCH_NOT_CONFIGURED(hts: str) -> None:
    async def scenario(mp) -> None:
        async with PStack(mp, KIS_HTS_ID=hts) as s:
            for r in (await s.conditions(), await s.results("0")):
                assert r.status_code == 503 and "no-store" in r.headers["cache-control"]
                body = r.json()
                assert body["data"] is None and body["error"] == {"code": "PSEARCH_NOT_CONFIGURED", "message": "HTS ID가 설정되지 않았습니다. .env의 KIS_HTS_ID를 확인하세요."}
            assert not s.result_calls and s.titles_calls == 0 and not mock_kis_server.PSEARCH_CALLS

    run_with_mp(scenario)


def test_앱키가_없으면_두_경로_모두_503_LOCAL_INTRADAY_NOT_CONFIGURED() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp, KIS_APP_KEY="", KIS_APP_SECRET="") as s:
            for r in (await s.conditions(), await s.results("0")):
                assert r.status_code == 503 and r.json()["error"]["code"] == "LOCAL_INTRADAY_NOT_CONFIGURED"
                assert "no-store" in r.headers["cache-control"]
            assert not s.result_calls and s.titles_calls == 0

    async def only_secret(mp) -> None:
        async with PStack(mp, KIS_APP_SECRET="") as s:
            assert (await s.results("0")).json()["error"]["code"] == "LOCAL_INTRADAY_NOT_CONFIGURED"

    run_with_mp(scenario)
    run_with_mp(only_secret)


# ── 호출 실패: stale·오류 ────────────────────────────────────────────────────────────────────────────
def test_이전_결과가_없을_때_증권사_실패는_오류_코드로_돌려준다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            s.script = [KisError("RATE_LIMITED", "증권사 호출 한도를 초과했습니다.")]
            r = await s.results("0")
            assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED" and r.json()["data"] is None
            r = await s.results("0")  # 방금 실패: 5초 동안은 증권사를 다시 두드리지 않고 같은 오류
            assert r.status_code == 429 and s.result_calls == ["0"]
            s.clock.advance(5.1)
            s.script = [KisError("UPSTREAM_UNAVAILABLE", f"증권사 서버에 연결하지 못했습니다. {HTS}")]
            r = await s.results("0")
            assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
            no_secret(r.text)
            s.clock.advance(5.1)
            s.script = [KisError("UPSTREAM_BAD_RESPONSE", "증권사 응답을 해석할 수 없습니다.")]
            assert (await s.results("0")).status_code == 502
            s.clock.advance(5.1)
            s.script = [KisError("AUTH_FAILED", "증권사 인증에 실패했습니다(앱키·시크릿을 확인하세요).")]
            assert (await s.results("0")).json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
            s.clock.advance(5.1)
            s.script = [ValueError(f"예상 밖 {HTS}")]
            r = await s.results("0")
            assert r.status_code == 502 and "예상 밖" not in r.text
            s.clock.advance(5.1)
            assert (await s.results("0")).status_code == 200  # 회복

    run_with_mp(scenario)


def test_이전_결과가_있으면_실패해도_stale로_돌려주고_회복하면_해제된다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            ok = await s.data("0")
            s.clock.advance(6)
            s.script = [KisError("RATE_LIMITED", "한도")]
            r = await s.results("0")
            assert r.status_code == 200
            d = r.json()["data"]
            assert d["stale"] is True and ids(d) == ids(ok) and d["fetched_at"] == ok["fetched_at"] and d["age_seconds"] == 6 and d["changes"] == []
            assert [i["entered_at"] for i in d["items"]] == [i["entered_at"] for i in ok["items"]]
            s.clock.advance(3)
            d = await s.data("0")  # 실패 직후 재시도 간격 동안은 증권사를 다시 두드리지 않는다
            assert d["stale"] is True and d["age_seconds"] == 9 and mock_kis_server.PSEARCH_CALLS == {"0": 1} and s.result_calls == ["0", "0"]
            s.clock.advance(3)  # 6초 뒤 다시 시도
            s.script = [KisError("UPSTREAM_UNAVAILABLE", "연결 실패")]
            assert (await s.data("0"))["stale"] is True and s.result_calls == ["0", "0", "0"]
            s.clock.advance(6)
            d = await s.data("0")  # 회복(모의 증권사 호출 2번째)
            assert d["stale"] is False and d["fetched_at"] == s.clock.t and d["age_seconds"] == 0
            assert mock_kis_server.PSEARCH_CALLS == {"0": 2}

    run_with_mp(scenario)


def test_증권사_연결이_실제로_끊기면_이전_결과는_stale_없으면_502() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            await s.data("0")
            s.kill_broker()
            s.clock.advance(6)
            r = await s.results("0")
            d = r.json()["data"]
            assert r.status_code == 200 and d["stale"] is True and d["count"] == 5
            no_secret(r.text)
            r = await s.results("2")  # 이전 결과가 없는 조건
            assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
            no_secret(r.text)
            r = await s.conditions()
            assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
            no_secret(r.text)

    run_with_mp(scenario)


def test_실패는_서로_다른_조건에_번지지_않는다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            await s.data("0")
            s.script = [KisError("RATE_LIMITED", "한도")]
            s.clock.advance(6)
            assert (await s.data("0"))["stale"] is True
            d = await s.data("2")  # 다른 조건은 정상
            assert d["stale"] is False and d["count"] == 100

    run_with_mp(scenario)


# ── 접근 통제 ───────────────────────────────────────────────────────────────────────────────────────
PATHS = ("/api/v1/local/psearch/conditions", "/api/v1/local/psearch/results?seq=0")


def test_접근_통제는_존재를_드러내지_않고_증권사를_부르지_않는다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            for path in PATHS:
                assert (await s.client.get(path, headers={"Host": "stock.example.com"})).status_code == 404, path
                for h in ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded", "X-Real-IP", "Via", "X-Forwarded-Host"):
                    r = await s.client.get(path, headers={h: "1.2.3.4"})
                    assert r.status_code == 404 and r.json()["error"]["code"] == "FEATURE_DISABLED", (path, h)
            assert not s.result_calls and s.titles_calls == 0 and not local_psearch._entries and not mock_kis_server.PSEARCH_CALLS

    async def off(mp) -> None:
        async with PStack(mp, LOCAL_INTRADAY_ENABLED="false") as s:
            for path in PATHS:
                assert (await s.client.get(path)).status_code == 404
            assert not s.result_calls and s.titles_calls == 0

    async def ip_denied(mp) -> None:
        async with PStack(mp, LOCAL_INTRADAY_ALLOWED_IPS="10.99.0.0/16") as s:  # 127.0.0.1은 허용 목록 밖
            for path in PATHS:
                assert (await s.client.get(path)).status_code == 404
            assert not s.result_calls

    run_with_mp(scenario)
    run_with_mp(off)
    run_with_mp(ip_denied)


def test_로그인을_켠_환경에서는_관리자_세션만_통과한다() -> None:
    from services.public_api.auth import service as auth_service

    async def scenario(mp) -> None:
        mp.setattr(local_realtime, "internal_token_enforced", lambda: True)
        mp.setattr(local_realtime, "get_auth_session_factory", lambda: (lambda: types.SimpleNamespace(close=lambda: None)))
        mp.setattr(auth_service, "require_admin", lambda sess, uid, sid: object() if uid == UID else None)
        admin = {"x-auth-user": UID, "x-auth-session": SID}
        member = {"x-auth-user": "33333333-3333-4333-8333-333333333333", "x-auth-session": SID}
        async with PStack(mp) as s:
            for h in ({}, member, {"x-auth-user": "not-uuid", "x-auth-session": SID}):
                for path in PATHS:
                    r = await s.client.get(path, headers=h)
                    assert r.status_code == 403, (path, h)
                no_secret(r.text)
            assert not s.result_calls and s.titles_calls == 0  # 관리자가 아니면 증권사 호출도 캐시 생성도 없다
            assert not local_psearch._entries
            assert (await s.conditions(headers=admin)).status_code == 200
            assert (await s.results("0", headers=admin)).status_code == 200

    run_with_mp(scenario)


def test_두_경로_모두_소유자_확인_의존성을_쓰고_조회_GET만_있다() -> None:
    routes = {r.path: r for r in local_psearch.router.routes}
    assert set(routes) == {"/local/psearch/conditions", "/local/psearch/results"}
    for route in routes.values():
        assert local_realtime.require_owner in [d.call for d in route.dependant.dependencies]  # type: ignore[attr-defined]
        assert route.methods == {"GET"}  # type: ignore[attr-defined]


def test_쓰기_메서드는_허용되지_않는다() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            for path in PATHS:
                for method in ("POST", "PUT", "DELETE", "PATCH"):
                    r = await s.client.request(method, path)
                    assert r.status_code in (404, 405), (method, path, r.status_code)
            assert not s.result_calls and s.titles_calls == 0

    run_with_mp(scenario)


# ── 비밀값 노출 없음 ─────────────────────────────────────────────────────────────────────────────────
def test_응답_로그_오류_어디에도_hts_id와_앱키가_없다(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario(mp) -> None:
        caplog.set_level(logging.DEBUG)  # httpx·httpcore 요청 로그까지 모두 잡는다
        texts: list[str] = []
        async with PStack(mp) as s:
            async def grab(r: httpx.Response) -> None:
                texts.append(r.text + json.dumps(dict(r.headers)))

            await grab(await s.conditions())
            for seq in ("0", "1", "2"):
                await grab(await s.results(seq))
            await grab(await s.results("bad seq"))
            s.script = [KisError("UPSTREAM_ERROR", f"거절 {HTS} {APP_KEY} {APP_SECRET}")]
            s.clock.advance(6)
            await grab(await s.results("0"))
            s.script = [KisError("UPSTREAM_UNAVAILABLE", f"실패 {HTS}"), KisError("RATE_LIMITED", APP_KEY), RuntimeError(HTS + APP_SECRET)]
            for seq in ("7", "8", "9"):
                await grab(await s.results(seq))
            s.script = [RuntimeError(HTS), KisError("UPSTREAM_ERROR", HTS), RuntimeError(APP_KEY)]
            for _ in range(3):
                s.clock.advance(61)
                await grab(await s.conditions())
            s.master_error = RuntimeError(HTS)
            s.clock.advance(6)
            s.script = [{"rt_cd": "0", "output2": [{"code": "000077"}]}]
            await grab(await s.results("0"))
            s.kill_broker()
            s.clock.advance(6)
            await grab(await s.results("0"))
            await grab(await s.results("22"))
        no_secret(*texts)
        logs = "\n".join(f"{rec.name} {rec.getMessage()} {rec.exc_text or ''}" for rec in caplog.records)
        assert any(rec.name.startswith("httpx") for rec in caplog.records), "httpx 요청 로그가 수집되지 않아 시험이 무의미함"
        no_secret(logs)
        assert "user_id=***" in logs

    run_with_mp(scenario)


# ── 응답 헤더 ───────────────────────────────────────────────────────────────────────────────────────
def test_모든_응답은_Cache_Control_no_store() -> None:
    async def scenario(mp) -> None:
        async with PStack(mp) as s:
            checks = [await s.conditions(), await s.results("0"), await s.results("1"), await s.results("2")]
            for r in checks:
                assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
            s.script = [KisError("RATE_LIMITED", "한도")]
            e = await s.results("9")
            assert e.status_code == 429 and "no-store" in e.headers.get("cache-control", "")
            e = await s.results("")
            assert e.status_code == 400 and "no-store" in e.headers.get("cache-control", "")
            e = await s.client.get("/api/v1/local/psearch/results?seq=0", headers={"X-Real-IP": "1.1.1.1"})
            assert e.status_code == 404

    run_with_mp(scenario)
