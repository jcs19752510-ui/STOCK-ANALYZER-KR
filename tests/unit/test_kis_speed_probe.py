"""kis_speed_probe(DEC-102): 모의 증권사(응답 지연 + 초당 호출 한도)로 측정·권장 로직을 확인한다. 실제 KIS 응답은 아니다."""

# ruff: noqa: E501
from __future__ import annotations

import importlib.util
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts import mock_kis_server as mock
from services.public_api.intraday.config import IntradaySettings
from services.public_api.intraday.kis_client import KisClient

_spec = importlib.util.spec_from_file_location("kis_speed_probe", Path(__file__).resolve().parents[2] / "scripts" / "kis_speed_probe.py")
probe_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe_mod)


def make_server(latency: float, limit_per_sec: int | None):
    hits: list[float] = []
    lock = threading.Lock()

    class H(mock.Handler):
        def do_GET(self) -> None:  # noqa: N802
            time.sleep(latency)
            if limit_per_sec is not None:
                now = time.monotonic()
                with lock:
                    hits.append(now)
                    recent = [t for t in hits if now - t <= 1.0]
                    over = len(recent) > limit_per_sec
                if over:
                    self._send(200, {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."})
                    return
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(tmp_path, latency, limit, **kw):
    server = make_server(latency, limit)
    settings = IntradaySettings(enabled=True, app_key="k", app_secret="s", base_url=f"http://127.0.0.1:{server.server_address[1]}", allowed_networks=(), token_cache_path=tmp_path / "t.json")
    lines: list[str] = []
    try:
        rc = probe_mod.probe(lambda interval: KisClient(settings, min_interval=interval), calls=20, concurrency=4, latency_n=3, gap=0.05, out=lines.append, **kw)
    finally:
        server.shutdown()
    return rc, "\n".join(lines)


@pytest.fixture(autouse=True)
def _no_rest(monkeypatch):
    monkeypatch.setattr(probe_mod, "STEP_REST", 0.0)


def test_unlimited_server_recommends_safe_cap_and_prints_env_lines(tmp_path):
    rc, text = run(tmp_path, 0.15, None)
    assert rc == 0
    assert "KIS_MARKET_MIN_INTERVAL=0.1\n" in text + "\n"  # 기본은 0.1초보다 빠르게 권장하지 않는다
    assert "KIS_MARKET_CONCURRENCY=" in text and "중앙값" in text
    assert "app" not in text.lower() or "appkey" not in text.lower()  # 비밀값 문구 없음


def test_aggressive_allows_fastest_step(tmp_path):
    rc, text = run(tmp_path, 0.05, None, aggressive=True)
    assert rc == 0 and "KIS_MARKET_MIN_INTERVAL=0.06" in text


def test_stops_climbing_at_the_rate_limit(tmp_path):
    rc, text = run(tmp_path, 0.02, 11)  # 초당 11건 한도: 8·10건/초는 통과, 12.5건/초에서 한도 신호
    assert rc == 0
    assert "더 빠른 단계는 시험하지 않는다" in text and "한도 신호" in text
    assert "간격 0.06초" not in text  # 한도 신호 뒤 단계는 시험하지 않았다
    assert "KIS_MARKET_MIN_INTERVAL=0.1\n" in text + "\n"


def test_too_low_limit_recommends_slow_and_serial(tmp_path):
    rc, text = run(tmp_path, 0.02, 3)  # 초당 3건 한도: 모든 단계 실패
    assert rc == 0 and "통과한 단계가 없습니다" in text


def test_recommend_and_percentile_helpers():
    ok = {"errors": []}
    bad = {"errors": ["RATE_LIMITED"]}
    assert probe_mod.recommend([{"interval": 0.125, **ok}, {"interval": 0.08, **ok}], aggressive=False) == 0.125
    assert probe_mod.recommend([{"interval": 0.125, **ok}, {"interval": 0.08, **ok}], aggressive=True) == 0.08
    assert probe_mod.recommend([{"interval": 0.125, **bad}], aggressive=True) is None
    assert probe_mod.recommend([{"interval": 0.125, **ok}, {"interval": 0.1, **ok, "limited": True}], aggressive=True) == 0.125  # 오류는 없지만 호출률 저하
    assert probe_mod.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
