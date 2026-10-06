"""실시간 스모크 테스트 도구 시험 — 모의 증권사 웹소켓 서버로 정상·장 밖·접속키 오류·값 이상·마스킹을 검증한다 (DEC-084).

실제 증권사에는 접속하지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from services.public_api.intraday.config import IntradaySettings
from services.public_api.realtime import protocol as p

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / rel)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


mock = _load("mock_kis_ws_server", "mock_kis_ws_server.py")
smoke = _load("kis_ws_smoke_test", "kis_ws_smoke_test.py")

KST = timezone(timedelta(hours=9))
TUE_0930 = datetime(2026, 10, 6, 9, 30, 4, tzinfo=KST)  # 화요일 장중
SUN_1100 = datetime(2026, 10, 4, 11, 0, 0, tzinfo=KST)  # 일요일
APP_KEY = "APPKEY-SECRET-1234"
APP_SECRET = "APPSECRET-SECRET-5678"


def settings(port: int) -> IntradaySettings:
    return IntradaySettings(
        enabled=True, app_key=APP_KEY, app_secret=APP_SECRET, base_url="http://mock", allowed_networks=(),
        token_cache_path=Path("unused"), ws_url=f"ws://127.0.0.1:{port}",
    )


def approval_http(key: str = "mock-approval", status: int = 200, body: dict | None = None, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(json.loads(request.content))
        return httpx.Response(status, json=body if body is not None else ({"approval_key": key} if status == 200 else {"error": "x"}))

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def until(pred, timeout: float = 5.0) -> None:
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("조건이 시간 안에 충족되지 않았습니다")
        await asyncio.sleep(0.01)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


async def check(server, *, http=None, now=TUE_0930, feeder=None, seconds: float = 0.8, code: str = "005930", secrets_in_out: bool = True):
    """모의 서버를 띄우고 점검을 실행한다. (종료 코드, 출력 줄 목록, 승인 요청 기록)"""
    port = await server.start()
    lines: list[str] = []
    calls: list = []
    task = asyncio.create_task(feeder(server)) if feeder else None
    try:
        rc = await smoke.run_check(
            settings(port), code, seconds, now_fn=lambda: now,
            http_factory=http or approval_http(calls=calls), out=lines.append,
        )
    finally:
        if task:
            await task
        await server.stop()
    return rc, lines, calls


async def feed_normal(server, *, count: int = 3, book_asc: bool = True, acml_values: list[int] | None = None) -> None:
    await until(lambda: len(server.subscriptions) == 2)
    acml = acml_values or [1000 + 100 * i for i in range(count)]
    for i, a in enumerate(acml):
        await server.emit(p.TR_TRADE, mock.trade_values("005930", f"09300{1 + i}", 70500, 30, a, prev_close=70000))
        book = mock.book_values("005930", f"09300{1 + i}", 70500, seed=i)
        if not book_asc:  # 매도 호가 순서를 뒤집는다
            prices = [book[f"askp{k}"] for k in range(1, 11)]
            for k, price in enumerate(reversed(prices), start=1):
                book[f"askp{k}"] = price
        await server.emit(p.TR_BOOK, book)
        await asyncio.sleep(0.02)


def text(lines: list[str]) -> str:
    return "\n".join(lines)


def test_정상이면_종료코드_0과_요약을_출력한다() -> None:
    async def scenario() -> None:
        server = mock.MockKisWsServer(ping_interval=0.1)
        rc, lines, calls = await check(server, feeder=feed_normal)
        out = text(lines)
        assert rc == 0, out
        assert "[OK] 접속키 발급" in out and "[OK] 웹소켓 접속" in out
        assert "체결 3건, 호가 3건" in out
        assert "PINGPONG" in out and "첫 체결까지" in out
        assert "PC 시계 차이" in out and "현재가 예시: 70,500원" in out and "호가 1단계 예시" in out
        assert "[OK] 값 검증" in out and "[실패]" not in out and "[확인필요]" not in out
        assert calls == [{"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": APP_SECRET}]
        # 체결·호가를 모두 구독했고 PINGPONG이 한 번 이상 왔다
        assert {r["tr_id"] for r in server.received} == {p.TR_TRADE, p.TR_BOOK}
        assert "PINGPONG 0회" not in out

    run(scenario())


def test_장_시간_밖이고_체결이_없으면_확인필요_종료코드_2() -> None:
    async def scenario() -> None:
        rc, lines, _ = await check(mock.MockKisWsServer(), now=SUN_1100, seconds=0.4)
        out = text(lines)
        assert rc == 2, out
        assert "장 시간 밖" in out and "[확인필요]" in out and "체결 0건" in out
        assert "[실패]" not in out

    run(scenario())


def test_장중인데_체결이_없고_구독_응답은_있으면_확인필요() -> None:
    async def scenario() -> None:
        rc, lines, _ = await check(mock.MockKisWsServer(), seconds=0.4)
        out = text(lines)
        assert rc == 2, out
        assert "휴장일" in out and "[실패]" not in out

    run(scenario())


def test_장중인데_아무것도_못_받으면_실패() -> None:
    async def scenario() -> None:
        server = mock.MockKisWsServer()
        server.ignore_subscribe = True
        rc, lines, _ = await check(server, seconds=0.4)
        assert rc == 1, text(lines)
        assert "아무것도 받지 못했습니다" in text(lines)

    run(scenario())


def test_접속키_발급이_거절되면_증권사_메시지를_보여주고_실패() -> None:
    async def scenario() -> None:
        body = {"error_code": "EGW00103", "error_description": f"유효하지 않은 AppKey입니다 {APP_KEY}"}
        rc, lines, _ = await check(mock.MockKisWsServer(), http=approval_http(status=403, body=body))
        out = text(lines)
        assert rc == 1
        assert "[실패] 접속키 발급" in out and "EGW00103" in out and "HTTP 403" in out
        assert APP_KEY not in out  # 증권사가 앱키를 되돌려 써도 가려진다

    run(scenario())


def test_웹소켓이_접속키를_거부하면_실패() -> None:
    async def scenario() -> None:
        # 발급은 되었지만 증권사 웹소켓은 다른 키만 인정하는 상황 → OPSP0011
        server = mock.MockKisWsServer(approval_key="other-key")
        rc, lines, _ = await check(server, seconds=0.5)
        out = text(lines)
        assert rc == 1, out
        assert "접속키 오류" in out and "OPSP0011" in out
        assert "mock-approval" not in out

    run(scenario())


def test_접속_실패는_실패로_보고하고_비밀값을_가린다() -> None:
    async def scenario() -> None:
        lines: list[str] = []

        def bad_connect(*a, **k):
            raise OSError(f"boom {APP_SECRET} mock-approval")

        rc = await smoke.run_check(settings(1), "005930", 0.3, now_fn=lambda: TUE_0930, http_factory=approval_http(), connect=bad_connect, out=lines.append)
        out = text(lines)
        assert rc == 1 and "[실패] 웹소켓 접속" in out
        assert APP_SECRET not in out and "mock-approval" not in out and "***" in out

    run(scenario())


def test_호가_순서가_뒤바뀌면_값_이상으로_실패() -> None:
    async def scenario() -> None:
        async def feeder(server):
            await feed_normal(server, count=2, book_asc=False)

        rc, lines, _ = await check(mock.MockKisWsServer(), feeder=feeder)
        out = text(lines)
        assert rc == 1, out
        assert "값 이상" in out and "오름차순" in out and "[OK] 값 검증" not in out

    run(scenario())


def test_누적_거래량이_줄어들면_값_이상으로_실패() -> None:
    async def scenario() -> None:
        async def feeder(server):
            await feed_normal(server, acml_values=[1000, 1200, 1100])

        rc, lines, _ = await check(mock.MockKisWsServer(), feeder=feeder)
        out = text(lines)
        assert rc == 1, out
        assert "누적 거래량이 줄어듦" in out and "1,200 → 1,100" in out

    run(scenario())


def test_PC_시계가_크게_어긋나면_확인필요() -> None:
    async def scenario() -> None:
        late = datetime(2026, 10, 6, 9, 40, 0, tzinfo=KST)  # 체결보다 10분 뒤
        rc, lines, _ = await check(mock.MockKisWsServer(), feeder=feed_normal, now=late)
        out = text(lines)
        assert rc == 2, out
        assert "시간 동기화" in out and "[실패]" not in out

    run(scenario())


def test_전체_출력에_앱키_시크릿_접속키가_없다() -> None:
    async def scenario() -> None:
        server = mock.MockKisWsServer(ping_interval=0.1)
        rc, lines, _ = await check(server, feeder=feed_normal)
        out = text(lines)
        assert rc == 0
        for secret in (APP_KEY, APP_SECRET, "mock-approval"):
            assert secret not in out

    run(scenario())


def test_mask는_긴_값부터_가린다() -> None:
    assert smoke.mask("a KEYKEY b KEY", {"KEY", "KEYKEY"}) == "a *** b ***"
    assert smoke.mask("plain", {""}) == "plain"


def test_check_book_순서와_총잔량_검증() -> None:
    good = p.parse_book(mock.book_values("005930", "093000", 70500))
    assert good is not None and smoke.check_book(good) == []
    bad_bid = mock.book_values("005930", "093000", 70500)
    bad_bid["bidp3"], bad_bid["bidp2"] = bad_bid["bidp2"], bad_bid["bidp3"]
    book = p.parse_book(bad_bid)
    assert book is not None and any("내림차순" in x for x in smoke.check_book(book))
    neg = mock.book_values("005930", "093000", 70500)
    neg["total_askp_rsqn"] = -5
    book = p.parse_book(neg)
    assert book is not None and any("총잔량" in x for x in smoke.check_book(book))


def test_장_시간_판정과_시계_차이() -> None:
    assert smoke.in_market_hours(datetime(2026, 10, 6, 8, 0, tzinfo=KST))
    assert smoke.in_market_hours(datetime(2026, 10, 6, 19, 59, tzinfo=KST))
    assert not smoke.in_market_hours(datetime(2026, 10, 6, 7, 59, tzinfo=KST))
    assert not smoke.in_market_hours(datetime(2026, 10, 6, 20, 0, tzinfo=KST))
    assert not smoke.in_market_hours(datetime(2026, 10, 3, 10, 0, tzinfo=KST))  # 토요일
    assert smoke.in_market_hours(datetime(2026, 10, 6, 0, 30, tzinfo=UTC))  # UTC 00:30 = KST 09:30
    assert smoke.clock_diff_seconds(datetime(2026, 10, 6, 9, 30, 4, tzinfo=KST), "09:30:01") == 3
    assert smoke.clock_diff_seconds(datetime(2026, 10, 6, 0, 0, 1, tzinfo=KST), "23:59:59") == 2  # 자정 경계


def test_main_인수와_설정_오류는_종료코드_1(capsys: pytest.CaptureFixture[str]) -> None:
    env = {"KIS_APP_KEY": APP_KEY, "KIS_APP_SECRET": APP_SECRET}
    assert smoke.main(["--seconds", "121"], env) == 1
    assert smoke.main(["--seconds", "0"], env) == 1
    assert smoke.main(["--code", "12"], env) == 1
    assert smoke.main(["--bogus"], env) == 1  # argparse 오류도 1(2는 확인필요 전용)
    assert smoke.main([], {}) == 1  # 앱키 없음
    # 기본 주소가 아닌 KIS_WS_URL은 허용 스위치 없이는 거부된다
    assert smoke.main([], {**env, "KIS_WS_URL": "ws://127.0.0.1:1"}) == 1
    out = capsys.readouterr().out
    assert "[설정 오류]" in out and APP_KEY not in out and APP_SECRET not in out


def test_main_모의_서버_전체_경로(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """main → get_settings → run_check까지(접속키 발급은 가짜 전송으로 대체)."""
    async def scenario() -> int:
        server = mock.MockKisWsServer()
        port = await server.start()
        real_client = httpx.AsyncClient
        monkeypatch.setattr(smoke.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"approval_key": "mock-approval"}))))
        env = {
            "KIS_APP_KEY": APP_KEY, "KIS_APP_SECRET": APP_SECRET, "KIS_BASE_URL": "http://mock",
            "KIS_WS_URL": f"ws://127.0.0.1:{port}", "KIS_ALLOW_CUSTOM_BASE_URL": "true",
        }
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, lambda: smoke.main(["--seconds", "0.3"], env))
        finally:
            await server.stop()

    rc = run(scenario())
    out = capsys.readouterr().out
    assert rc == 2  # 모의 서버는 체결을 보내지 않으므로 장 시간 안·밖 모두 확인필요
    assert "[OK] 접속키 발급" in out and "[OK] 웹소켓 접속" in out and "사용자 지정 주소" in out
    assert APP_KEY not in out and APP_SECRET not in out
