"""HTS 조건검색 연동 확인 도구 시험 — 실제 uvicorn 없이 모의 증권사 REST(`scripts/mock_kis_server.py`)로 정상·0건·100건·변화 감지·오류·마스킹을 검증한다 (DEC-087).

실제 증권사에는 접속하지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from services.public_api.intraday.config import IntradaySettings
from services.public_api.intraday.kis_client import KisClient, KisError

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / rel)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


mock = _load("mock_kis_server", "mock_kis_server.py")
tool = _load("kis_psearch_smoke_test", "kis_psearch_smoke_test.py")

KST = timezone(timedelta(hours=9))
APP_KEY = "APPKEY-SECRET-1234"
APP_SECRET = "APPSECRET-SECRET-5678"
HTS_ID = "myhtsid77"


class Rig:
    def __enter__(self):
        mock.PSEARCH_CALLS.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), mock.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def settings(self, tmp: Path) -> IntradaySettings:
        return IntradaySettings(enabled=True, app_key=APP_KEY, app_secret=APP_SECRET, base_url=self.base, allowed_networks=(), token_cache_path=tmp / "tok.json")

    def client(self, tmp: Path) -> KisClient:
        return KisClient(self.settings(tmp), min_interval=0.0)


class FakeClock:
    """시계·잠깐 자기: 조회 간격 동안의 시간이 실제로 흐르지 않고 즉시 지나가게 한다."""

    def __init__(self, start: datetime) -> None:
        self.t = start.timestamp()

    def __call__(self) -> float:
        self.t += 0.01  # 호출마다 조금 흐른다(응답 시간 측정용)
        return self.t

    def sleep(self, sec: float) -> None:
        self.t += sec


TUE_1000 = datetime(2026, 10, 6, 10, 0, 0, tzinfo=KST)
SUN_1100 = datetime(2026, 10, 4, 11, 0, 0, tzinfo=KST)


def run(rig: Rig, tmp: Path, seqs: list[str], seconds: float = 60, interval: float = 5, start: datetime = TUE_1000, **kw):
    clock = FakeClock(start)
    lines: list[str] = []
    code = tool.run_check(rig.client(tmp), HTS_ID, seqs, seconds, interval, say=lines.append, clock=clock, sleep=clock.sleep, secrets={APP_KEY, APP_SECRET}, **kw)
    return code, "\n".join(lines)


# ── KisClient ────────────────────────────────────────────────────────────
def test_클라이언트가_공식_경로와_tr_id와_파라미터로_호출한다(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "0", "output2": [{"seq": "0"}]})

    settings = IntradaySettings(enabled=True, app_key=APP_KEY, app_secret=APP_SECRET, base_url="https://x.test", allowed_networks=(), token_cache_path=tmp_path / "t.json")
    client = KisClient(settings, httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0)
    client.psearch_titles("abc")
    client.psearch_result("abc", "3")
    t, r = seen[-2], seen[-1]
    assert t.url.path == "/uapi/domestic-stock/v1/quotations/psearch-title" and t.headers["tr_id"] == "HHKST03900300" and dict(t.url.params) == {"user_id": "abc"}
    assert r.url.path == "/uapi/domestic-stock/v1/quotations/psearch-result" and r.headers["tr_id"] == "HHKST03900400" and dict(r.url.params) == {"user_id": "abc", "seq": "3"}
    with pytest.raises(ValueError):
        client.psearch_titles("")
    with pytest.raises(ValueError):
        client.psearch_result("abc", "")


# ── 정상 흐름: 목록 → 반복 조회 → 변화 감지 ──────────────────────────────────
def test_조건_목록과_결과_변화_편입_이탈을_감지하고_정상_종료한다(tmp_path: Path) -> None:
    with Rig() as rig:
        code, out = run(rig, tmp_path, ["0"], seconds=60, interval=5)
    assert code == 0, out
    assert "조건 목록 3건" in out and "모의 변동 조건" in out and "seq=0" in out
    assert "편입" in out and "이탈" in out and "결과가 " in out and "번 바뀜" in out
    assert "응답 필드(5개): code, name, price, chgrate, acml_vol" in out
    assert "응답 시간: 중앙값" in out and "결과 종목 수: 최소 5 · 최대 5" in out
    assert "HTS 조건검색 결과를 API로 받을 수 있고 장중 변화도 확인됐습니다" in out


def test_첫_조건을_기본으로_고른다(tmp_path: Path) -> None:
    with Rig() as rig:
        code, out = run(rig, tmp_path, [], seconds=30, interval=5)
    assert code == 0 and "[seq=0 모의 변동 조건]" in out


def test_list_only는_목록만_보고_끝낸다(tmp_path: Path) -> None:
    with Rig() as rig:
        code, out = run(rig, tmp_path, ["0"], list_only=True)
        assert mock.PSEARCH_CALLS == {}  # 결과 조회를 하지 않았다
    assert code == 0 and "완료(--list-only)" in out


# ── 확인필요·경계 ─────────────────────────────────────────────────────────
def test_결과가_계속_0건이면_확인필요로_안내한다(tmp_path: Path) -> None:
    with Rig() as rig:
        code, out = run(rig, tmp_path, ["1"], seconds=20, interval=5)
    assert "0건" in out and "검색 결과가 없습니다" in out
    assert code == 1  # 결과를 한 번도 받지 못했으므로 실패로 본다(0건 응답 안내는 함께 나온다)
    assert "결과를 한 번도 받지 못했습니다" in out


def test_100건_한도에_닿으면_조건을_좁히라고_안내한다(tmp_path: Path) -> None:
    with Rig() as rig:
        code, out = run(rig, tmp_path, ["2"], seconds=20, interval=5)
    assert code == 2
    assert "100건 한도에 닿았습니다" in out and "결과 종목 수: 최소 100 · 최대 100" in out
    assert "관찰 시간 동안 결과가 바뀌지 않았습니다" in out


def test_장_시간_밖이면_변화를_확인할_수_없다고_안내한다(tmp_path: Path) -> None:
    with Rig() as rig:
        code, out = run(rig, tmp_path, ["2"], seconds=20, interval=5, start=SUN_1100)
    assert code == 2 and "장 시간 밖" in out and "평일 08:00~20:00" in out


def test_조건이_하나도_없으면_서버저장_안내(tmp_path: Path) -> None:
    class Empty:
        def psearch_titles(self, user_id):
            return {"output2": []}

    lines: list[str] = []
    code = tool.run_check(Empty(), HTS_ID, [], 10, 5, say=lines.append)
    assert code == 2 and "서버저장" in "\n".join(lines)


def test_조건_목록_조회가_거절되면_원인_후보를_안내한다(tmp_path: Path) -> None:
    class Denied:
        def psearch_titles(self, user_id):
            raise KisError("UPSTREAM_ERROR", f"증권사가 요청을 거절했습니다. 사용자 {HTS_ID} 없음 {APP_KEY}")

    lines: list[str] = []
    code = tool.run_check(Denied(), HTS_ID, [], 10, 5, say=lines.append, secrets={APP_KEY, APP_SECRET})
    out = "\n".join(lines)
    assert code == 1 and "KIS_HTS_ID" in out and "서버저장" in out
    assert HTS_ID not in out and APP_KEY not in out  # 비밀값은 가려진다


def test_호출_한도_오류는_안내하고_계속_관찰한다(tmp_path: Path) -> None:
    class Limited:
        def __init__(self) -> None:
            self.n = 0

        def psearch_titles(self, user_id):
            return {"output2": [{"seq": "0", "condition_nm": "c", "grp_nm": "g"}]}

        def psearch_result(self, user_id, seq):
            self.n += 1
            if self.n % 2:
                raise KisError("RATE_LIMITED", "한도")
            return {"output2": [{"code": "005930", "name": "삼성전자"}]}

    clock = FakeClock(TUE_1000)
    lines: list[str] = []
    code = tool.run_check(Limited(), HTS_ID, ["0"], 30, 5, say=lines.append, clock=clock, sleep=clock.sleep)
    out = "\n".join(lines)
    assert code == 2 and "RATE_LIMITED" in out and "--interval을 늘려" in out


def test_종목코드_필드_이름이_예상과_달라도_값_모양으로_추정하고_알린다(tmp_path: Path) -> None:
    class Odd:
        def psearch_titles(self, user_id):
            return {"output2": [{"seq": "0", "condition_nm": "c", "grp_nm": "g"}]}

        def psearch_result(self, user_id, seq):
            return {"output2": [{"종목": "005930", "현재가": "70000"}]}

    clock = FakeClock(TUE_1000)
    lines: list[str] = []
    code = tool.run_check(Odd(), HTS_ID, ["0"], 10, 5, say=lines.append, clock=clock, sleep=clock.sleep)
    out = "\n".join(lines)
    assert code == 2 and "필드 이름이 예상" in out and "응답 필드(2개): 종목, 현재가" in out


def test_json_보고서를_저장하고_비밀값은_들어가지_않는다(tmp_path: Path) -> None:
    out_file = tmp_path / "r.json"
    with Rig() as rig:
        code, out = run(rig, tmp_path, ["0"], seconds=30, interval=5, out_path=out_file)
    assert code == 0 and "보고서 저장" in out
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["sequences"]["0"]["fields"] == ["code", "name", "price", "chgrate", "acml_vol"] and data["sequences"]["0"]["changes"]
    assert APP_KEY not in out_file.read_text(encoding="utf-8") and HTS_ID not in out_file.read_text(encoding="utf-8")


def test_출력_어디에도_앱키_시크릿_HTS_ID가_나오지_않는다(tmp_path: Path) -> None:
    with Rig() as rig:
        _, out = run(rig, tmp_path, ["0", "1", "2"], seconds=30, interval=5)
    for secret in (APP_KEY, APP_SECRET, HTS_ID, "mock-token"):
        assert secret not in out


# ── main(): 설정 검증 ─────────────────────────────────────────────────────
def test_main_설정_오류는_종료코드_1(capsys: pytest.CaptureFixture[str]) -> None:
    base = {"KIS_APP_KEY": APP_KEY, "KIS_APP_SECRET": APP_SECRET, "KIS_HTS_ID": HTS_ID}
    assert tool.main(["--seconds", "0"], env=base) == 1
    assert tool.main(["--interval", "0.2"], env=base) == 1
    assert tool.main(["--seq", "a b"], env=base) == 1
    assert tool.main([f"--seq={i}" for i in range(6)], env=base) == 1
    assert tool.main([], env={**base, "KIS_HTS_ID": ""}) == 1  # HTS ID 없음
    assert tool.main([], env={"KIS_HTS_ID": HTS_ID}) == 1  # 앱키 없음
    out = capsys.readouterr().out
    assert "HTS ID가 없습니다" in out and "KIS_APP_KEY" in out
    assert tool.main(["--bogus"], env=base) == 1  # argparse 오류도 1(확인필요 2와 구분)
    assert tool.main(["--help"], env=base) == 0


def test_main이_모의_서버로_끝까지_돈다(tmp_path: Path) -> None:
    with Rig() as rig:
        env = {"KIS_APP_KEY": APP_KEY, "KIS_APP_SECRET": APP_SECRET, "KIS_HTS_ID": HTS_ID, "KIS_BASE_URL": rig.base, "KIS_ALLOW_CUSTOM_BASE_URL": "true", "KIS_TOKEN_CACHE_PATH": str(tmp_path / "tok.json")}
        assert tool.main(["--list-only"], env=env) == 0


def test_업무_거절과_HTTP_장애를_http_status로_구분할_수_있다(tmp_path: Path) -> None:
    mode = {"v": "business"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        if mode["v"] == "business":
            return httpx.Response(200, json={"rt_cd": "1", "msg1": "검색 결과가 없습니다."})
        return httpx.Response(500, json={"rt_cd": "1", "msg1": "서버 오류"})

    settings = IntradaySettings(enabled=True, app_key=APP_KEY, app_secret=APP_SECRET, base_url="https://x.test", allowed_networks=(), token_cache_path=tmp_path / "t.json")
    client = KisClient(settings, httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0)
    with pytest.raises(KisError) as e1:
        client.psearch_result("abc", "0")
    assert e1.value.code == "UPSTREAM_ERROR" and e1.value.http_status == 200
    mode["v"] = "http"
    with pytest.raises(KisError) as e2:
        client.psearch_result("abc", "0")
    assert e2.value.code == "UPSTREAM_ERROR" and e2.value.http_status == 500
