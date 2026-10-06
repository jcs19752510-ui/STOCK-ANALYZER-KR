"""장중 재계산 종단 시험용 공용 환경 — 실제 uvicorn 서버 + 모의 증권사 REST(HTTP) + 임시 PostgreSQL.

`test_live_screen_stack_db.py`(pytest)와 `tests/e2e/live_screen_stack.py`(브라우저 종단)가 함께 쓴다. 개발 DB·실제 증권사에는 접속하지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import functools
import threading
import time
from datetime import datetime
from http.server import ThreadingHTTPServer

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import scripts.mock_kis_server as mock_kis_server
from services.public_api.api import local_intraday, local_market, local_screen
from services.public_api.db.session import get_db
from services.public_api.realtime.market import PollerConfig
from tests.integration.pattern_fixtures import build_stocks
from tests.integration.pg_temp_db import TempDb

CODES = sorted(build_stocks())
KST = mock_kis_server.KST


def align_published_closes_with_mock(tdb: TempDb) -> None:
    """증권사(모의)와 발행 일봉이 같은 종가를 갖도록 맞춘다(교차검증을 통과시키는 전제 — 실제 응답과의 일치는 사용자 PC에서 확인).

    9/30 종가를 모의 서버 값으로 바꾸고, 그 비율만큼 **전체 이력을 같은 비율로 키워** 가격 단절(±31%) 없이 이어지게 한다(발행 지표는 비율이라 불변).
    """
    eng = create_engine(TempDb.render(tdb.migrator_url))
    mock_rows = {c: {r["stck_bsop_date"]: r for r in mock_kis_server.daily_price_rows(c, datetime(2026, 10, 2, 10, 0, tzinfo=KST))} for c in CODES}
    with eng.begin() as conn:
        for c in CODES:
            target = mock_rows[c]["20260930"]
            cur = conn.execute(text("SELECT close FROM public_serving.daily_prices WHERE stock_code=:s AND trade_date='2026-09-30'"), {"s": c}).scalar_one()
            k = float(target["stck_clpr"]) / float(cur)
            conn.execute(text("UPDATE public_serving.daily_prices SET open=round(open*:k), high=round(high*:k), low=round(low*:k), close=round(close*:k) WHERE stock_code=:s"), {"k": k, "s": c})
            conn.execute(text("UPDATE public_serving.daily_prices SET close=:c WHERE stock_code=:s AND trade_date='2026-09-30'"), {"c": target["stck_clpr"], "s": c})
    eng.dispose()


class FullStack:
    def __init__(self, db: TempDb, mp: pytest.MonkeyPatch, now: datetime, *, port: int = 0, cors_ok: bool = True) -> None:
        self.db, self.mp, self.now, self.port = db, mp, now, port

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
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
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
