"""장중 재계산 종단 시험(DEC-089·090) — 실제 uvicorn 서버 + 모의 증권사 REST(HTTP) + 실제 시세 폴러·일봉 보충 + 임시 PostgreSQL.

`test_live_screen_db.py`가 가짜 주입으로 계산 정확성을 보는 것과 달리, 여기서는 **진짜 부품이 이어지는지**를 본다:
`/local/screen` → 서비스 → (모의 증권사로) 일봉 보충·전 종목 시세 순환 → 가상 테이블 쿼리 → 응답, 그리고 우선 순환·프로세스 종료 정리.
개발 DB·실제 증권사에는 접속하지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import functools
import threading
import time
import types
from datetime import datetime
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import scripts.mock_kis_server as mock_kis_server
from services.public_api.api import local_intraday, local_market, local_screen
from services.public_api.api.local_realtime import require_owner
from services.public_api.db.session import get_db
from services.public_api.realtime.market import PollerConfig
from tests.integration.pattern_api_env import prepare_database
from tests.integration.pattern_fixtures import build_stocks
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

CODES = sorted(build_stocks())
KST = mock_kis_server.KST


@pytest.fixture(scope="module")
def db():
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            # 증권사(모의)와 발행 일봉이 같은 종가를 갖도록 9/30 종가를 모의 서버 값으로 맞춘다(교차검증을 통과시키는 전제 — 실제 응답과의 일치는 사용자 PC에서 확인).
            eng = create_engine(TempDb.render(tdb.migrator_url))
            mock_rows = {c: {r["stck_bsop_date"]: r for r in mock_kis_server.daily_price_rows(c, datetime(2026, 10, 2, 10, 0, tzinfo=KST))} for c in CODES}
            with eng.begin() as conn:
                for c in CODES:
                    r = mock_rows[c]["20260930"]
                    conn.execute(text("UPDATE public_serving.daily_prices SET open=:o, high=:h, low=:l, close=:c WHERE stock_code=:s AND trade_date='2026-09-30'"),
                                 {"o": r["stck_oprc"], "h": r["stck_hgpr"], "l": r["stck_lwpr"], "c": r["stck_clpr"], "s": c})
            eng.dispose()
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


class FullStack:
    def __init__(self, db: TempDb, mp: pytest.MonkeyPatch, now: datetime) -> None:
        self.db, self.mp, self.now = db, mp, now

    def __enter__(self) -> FullStack:
        mock_kis_server.Handler.fixed_now = self.now
        self.rest = ThreadingHTTPServer(("127.0.0.1", 0), mock_kis_server.Handler)
        threading.Thread(target=self.rest.serve_forever, daemon=True).start()
        env = {
            "LOCAL_INTRADAY_ENABLED": "true", "KIS_APP_KEY": "mock", "KIS_APP_SECRET": "mock", "KIS_ALLOW_CUSTOM_BASE_URL": "true",
            "KIS_BASE_URL": f"http://127.0.0.1:{self.rest.server_address[1]}", "KIS_TOKEN_CACHE_PATH": "/tmp/claude-0/live-screen-test-token.json",
            "LIVE_SCREEN_MIN_INTERVAL": "0",
        }
        for k, v in env.items():
            self.mp.setenv(k, v)
        local_intraday.reset_intraday_service()
        local_market.reset_market_runtime()
        local_screen.reset_live_screen()
        local_market.set_universe_loader(lambda: list(CODES))
        fast = PollerConfig(cycle_pause=0.05, off_hours_cycle_interval=0.05, min_interval=0.01, priority_interval=0.1)
        self.mp.setattr(local_market, "MarketRuntime", functools.partial(local_market.MarketRuntime, config=fast, is_market_open=lambda _n: True))
        self.mp.setattr(local_intraday, "KisClient", functools.partial(local_intraday.KisClient, min_interval=0.01))
        self.engine = create_engine(TempDb.render(self.db.api_url))
        self.mp.setattr(local_screen, "get_session_factory", lambda: sessionmaker(bind=self.engine, autoflush=False))
        local_screen.set_now_provider(lambda: self.now)
        from services.public_api.main import app

        def _db():
            s = Session(self.engine)
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = _db
        self.app = app
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        self.url = f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}"
        self.http = httpx.Client(base_url=self.url, timeout=15)
        return self

    def __exit__(self, *exc) -> None:
        self.http.close()
        self.server.should_exit = True
        self.thread.join(10)
        self.rest.shutdown()
        self.app.dependency_overrides.clear()
        local_screen.set_now_provider(None)
        local_screen.reset_live_screen()
        local_market.set_universe_loader(None)
        local_market.reset_market_runtime()
        local_intraday.reset_intraday_service()
        self.engine.dispose()
        mock_kis_server.Handler.fixed_now = None

    def get_until(self, path: str, params=None, *, want=(200,), timeout=20.0) -> httpx.Response:
        deadline = time.time() + timeout
        while True:
            r = self.http.get(path, params=params)
            if r.status_code in want or time.time() > deadline:
                return r
            time.sleep(0.1)


def test_full_stack_gap_fill_then_live_and_priority_and_shutdown(db, monkeypatch):
    """P=9/30, 오늘=금 10/2 10:00 → E=10/1(1거래일 뒤처짐). 실제 서버가 모의 증권사에서 일봉을 채우고 시세를 모아 재계산 결과를 낸다."""
    app_mod = __import__("services.public_api.main", fromlist=["app"])
    with FullStack(db, monkeypatch, datetime(2026, 10, 2, 10, 0, tzinfo=KST)) as st:
        first = st.http.get("/api/v1/local/screen")
        assert first.status_code in (503, 200)
        if first.status_code == 503:
            assert first.json()["error"]["code"] in ("LIVE_BASE_FILLING", "LIVE_QUOTES_NOT_READY")
        r = st.get_until("/api/v1/local/screen", {"page_size": 200})
        assert r.status_code == 200, r.text
        body = r.json()
        live = body["meta"]["live"]
        bf = live["base_fill"]
        assert bf["state"] == "ready" and bf["gap_days"] == 1 and bf["filled"] == 10 and bf["excluded"] == 0 and bf["mismatched"] == 0 and bf["pending"] == 0
        assert live["basis_trade_date"] == "2026-09-30" and live["expected_trade_date"] == "2026-10-01" and live["today"] == "2026-10-02"
        assert live["quotes_covered"] == 10 and live["quotes_total"] == 10 and live["return_rank_policy"] == "live"
        items = body["data"]["items"]
        assert len(items) == 10 and {i["basis"] for i in items} == {"live"}
        assert "mock-token" not in r.text and "fetched_at" not in r.text
        # 우선 순환: 보이는 종목이 등록되고 폴러가 우선 호출을 했다
        status = st.http.get("/api/v1/local/market/status").json()["data"]
        deadline = time.time() + 5
        while status["poller"]["priority_calls_total"] == 0 and time.time() < deadline:
            time.sleep(0.1)
            st.http.get("/api/v1/local/screen", {"page_size": 200})  # TTL 갱신
            status = st.http.get("/api/v1/local/market/status").json()["data"]
        assert status["poller"]["priority_calls_total"] > 0 and status["poller"]["priority_codes"] == 10
        # 패턴 화면도 같은 서비스·스냅샷 위에서 동작한다
        p = st.get_until("/api/v1/local/screen/pattern", {"required": "c1", "page_size": 200}, want=(200, 424))
        assert p.status_code in (200, 424)
        if p.status_code == 200:
            assert all(i["basis"] in ("live", "daily") for i in p.json()["data"]["items"])
        # 시세 화면에 priority=1 옵션
        q = st.http.get("/api/v1/local/market/quotes", params={"codes": "T00001,T00002", "priority": 1})
        assert q.status_code == 200 and {x["code"] for x in q.json()["data"]["quotes"]} <= {"T00001", "T00002"}
    assert app_mod.app.dependency_overrides == {}
    assert local_screen._service is None  # 종료 처리로 일봉 보충 작업이 정리됨


def test_full_stack_closed_market_returns_daily_without_quotes(db, monkeypatch):
    """장 마감 뒤(E=오늘=P): 보충·시세 없이도 발행 값 그대로 응답한다."""
    with FullStack(db, monkeypatch, datetime(2026, 9, 30, 17, 0, tzinfo=KST)) as st:
        r = st.get_until("/api/v1/local/screen", {"page_size": 200})
        assert r.status_code == 200, r.text
        assert {i["basis"] for i in r.json()["data"]["items"]} == {"daily"} and r.json()["meta"]["live"]["base_fill"]["state"] == "none"


def test_full_stack_broker_mismatch_excludes_stock_and_reports(db, monkeypatch):
    """증권사 일봉의 발행일 종가가 다르면(끝자리 9 종목이 2배 가격) 그 종목은 결과에서 빠지고 meta에 수로 나온다."""
    eng = create_engine(TempDb.render(db.migrator_url))
    try:
        with eng.begin() as conn:  # T00009 → 코드 끝자리 9: 모의 서버가 2배 가격을 돌려준다(원래 9/30 종가는 끝자리 규칙 없이 맞춰져 있었음)
            conn.execute(text("UPDATE public_serving.daily_prices SET close = close + 1 WHERE stock_code='T00009' AND trade_date='2026-09-30'"))
        with FullStack(db, monkeypatch, datetime(2026, 10, 2, 10, 0, tzinfo=KST)) as st:
            r = st.get_until("/api/v1/local/screen", {"page_size": 200})
            assert r.status_code == 200, r.text
            bf = r.json()["meta"]["live"]["base_fill"]
            assert bf["mismatched"] == 1 and bf["excluded"] == 1 and bf["filled"] == 9
            assert "T00009" not in {i["stock_code"] for i in r.json()["data"]["items"]}
    finally:
        with eng.begin() as conn:
            r9 = {r["stck_bsop_date"]: r for r in mock_kis_server.daily_price_rows("T00009", datetime(2026, 10, 2, 10, 0, tzinfo=KST))}["20260930"]
            conn.execute(text("UPDATE public_serving.daily_prices SET close=:c WHERE stock_code='T00009' AND trade_date='2026-09-30'"), {"c": Decimal(r9["stck_clpr"])})
        eng.dispose()
