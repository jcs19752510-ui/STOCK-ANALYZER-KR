"""증권사 일봉(주식현재가 일자별) 조회·정규화·모의 서버 시험 — DEC-090 일봉 보충의 입력 경로. 실제 증권사 접속 없음."""

# ruff: noqa: E501
from __future__ import annotations

import sys
import threading
from datetime import date, datetime
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import mock_kis_server  # noqa: E402

from services.public_api.intraday import config as cfg  # noqa: E402
from services.public_api.intraday.kis_client import KisClient, KisError  # noqa: E402
from services.public_api.intraday.normalize import (  # noqa: E402
    DAILY_PRICE_FIELDS,
    normalize_daily_price,
)


def _settings(tmp_path: Path, base: str | None = None):
    env = {cfg.ENABLED_ENV: "true", cfg.APP_KEY_ENV: "mock", cfg.APP_SECRET_ENV: "mock", cfg.TOKEN_CACHE_ENV: str(tmp_path / "tok.json")}
    if base:
        env |= {cfg.BASE_URL_ENV: base, cfg.ALLOW_CUSTOM_BASE_ENV: "true"}
    return cfg.get_settings(env)


def _row(**over):
    f = DAILY_PRICE_FIELDS
    base = {f["date"]: "20261001", f["open"]: "70,000", f["high"]: "71000", f["low"]: "69000", f["close"]: "70500", f["volume"]: "1,234,567"}
    for k, v in over.items():
        base[f[k]] = v
    return base


# ── 클라이언트 ──────────────────────────────────────────────────────────────────────────
def test_client_daily_price_params_headers_and_low_priority(tmp_path):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "0", "output": []})

    client = KisClient(_settings(tmp_path), httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: 1_000_000.0, sleep=lambda s: None)
    client.daily_price("005930")
    req = seen[-1]
    assert req.url.path.endswith("/inquire-daily-price") and req.headers["tr_id"] == "FHKST01010400"
    assert dict(req.url.params) == {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930", "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "1"}
    with pytest.raises(ValueError):
        client.daily_price("")


def test_client_daily_price_error_mapping(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과"})

    client = KisClient(_settings(tmp_path), httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: 1_000_000.0, sleep=lambda s: None)
    with pytest.raises(KisError) as ei:
        client.daily_price("005930")
    assert ei.value.code == "RATE_LIMITED"
    assert "mock" not in str(ei.value)  # 앱키·비밀이 오류 문구에 없다


# ── 정규화 ──────────────────────────────────────────────────────────────────────────────
def test_normalize_parses_sorts_dedups_and_uses_decimal():
    rows = [_row(date="20261002", close="71,000"), _row(), _row(date="20260930", close="69000"), _row(close="99999")]  # 같은 날짜 중복은 처음 값
    bars = normalize_daily_price(rows)
    assert [b.trade_date for b in bars] == [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
    assert bars[1].close == Decimal("70500") and isinstance(bars[1].close, Decimal) and bars[1].volume == 1234567
    assert bars[2].close == Decimal("71000")


@pytest.mark.parametrize(
    "bad",
    [
        {"date": ""}, {"date": "2026-10-01"}, {"date": "20261301"}, {"close": ""}, {"close": "abc"}, {"close": "0"}, {"close": "-5"},
        {"volume": ""}, {"volume": "-1"}, {"open": ""}, {"high": "x"}, {"low": ""}, {"close": "nan"}, {"close": "inf"},
    ],
)
def test_normalize_drops_untrustworthy_rows_instead_of_filling_zero(bad):
    assert normalize_daily_price([_row(**bad)]) == []


def test_normalize_keeps_zero_volume_and_ignores_extra_fields():
    r = _row(volume="0") | {"unknown": "x", "prdy_vrss": "100"}
    assert normalize_daily_price([r])[0].volume == 0
    assert normalize_daily_price([]) == [] and normalize_daily_price([{}]) == []


# ── 모의 서버 끝까지(HTTP) ──────────────────────────────────────────────────────────────
@pytest.fixture
def mock_rest(monkeypatch):
    monkeypatch.setattr(mock_kis_server.Handler, "fixed_now", datetime(2026, 10, 7, 11, 0, tzinfo=mock_kis_server.KST))  # 수요일 장중
    server = ThreadingHTTPServer(("127.0.0.1", 0), mock_kis_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_mock_server_daily_price_end_to_end(mock_rest, tmp_path):
    client = KisClient(_settings(tmp_path, mock_rest), min_interval=0.0)
    bars = normalize_daily_price(client.daily_price("005930")["output"])
    assert len(bars) == 30 and bars[-1].trade_date == date(2026, 10, 7)  # 장중이라 오늘 행(진행 중) 포함
    assert all(d.weekday() < 5 for d in (b.trade_date for b in bars))
    assert all(b.low <= b.close <= b.high or b.low <= b.open for b in bars)
    # 같은 날짜는 항상 같은 값(결정적) — 교차검증 시험이 흔들리지 않는다
    again = normalize_daily_price(client.daily_price("005930")["output"])
    assert bars == again


def test_mock_server_special_codes(mock_rest, tmp_path):
    client = KisClient(_settings(tmp_path, mock_rest), min_interval=0.0)
    assert normalize_daily_price(client.daily_price("000000")["output"]) == []  # 상장 직후·거래정지
    normal = {b.trade_date: b for b in normalize_daily_price(client.daily_price("000010")["output"])}
    doubled = {b.trade_date: b for b in normalize_daily_price(client.daily_price("000019")["output"])}  # 끝자리 9: 수정주가 어긋남 모사
    d = date(2026, 10, 6)
    # 끝자리 9 종목은 종가가 2배로 어긋난다(교차검증이 잡아야 하는 상황). 같은 날짜 값이 정상 종목의 기준과 다름을 확인한다.
    assert doubled[d].close > 0 and doubled[d].close % 20 == 0 and doubled[d].close != normal[d].close


def test_mock_server_before_open_has_no_today_row(monkeypatch, tmp_path):
    monkeypatch.setattr(mock_kis_server.Handler, "fixed_now", datetime(2026, 10, 7, 8, 30, tzinfo=mock_kis_server.KST))
    server = ThreadingHTTPServer(("127.0.0.1", 0), mock_kis_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = KisClient(_settings(tmp_path, f"http://127.0.0.1:{server.server_address[1]}"), min_interval=0.0)
        bars = normalize_daily_price(client.daily_price("005930")["output"])
        assert bars[-1].trade_date == date(2026, 10, 6)
    finally:
        server.shutdown()
        server.server_close()
