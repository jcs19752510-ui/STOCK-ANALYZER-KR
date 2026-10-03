"""API 통합 테스트 환경 헬퍼 — 임시 DB + 실제 FastAPI 앱 (UNIT-16, 05-test-plan §7·§8·§9).

임시 DB(`pg_temp_db`)에 픽스처(T00001~T00010)를 적재하고 배치를 실행해 발행까지 마친 뒤,
`get_db` 의존성을 **읽기 전용 `api_service` 계정**의 세션으로 바꿔 실제 앱을 `TestClient`로 호출한다
(실제 SQL·실제 권한·실제 미들웨어). 개발 DB에는 아무것도 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.derivation_batch.run_derivation import run_once
from services.public_api.db.session import get_db
from services.public_api.main import app
from services.public_api.rate_limit import reset_rate_limit_state
from tests.integration.pattern_fixtures import TARGET_DATE, seed_fixture
from tests.integration.pg_temp_db import TempDb


def seed_calendar(engine, *, start: date = date(2026, 8, 1), end: date = date(2026, 12, 31)):
    """KRX 캘린더(평일=거래일, 마감 15:30). 휴장일은 모른다 — 평일 단순 모델."""
    rows = []
    d = start
    while d <= end:
        trading = d.weekday() < 5
        rows.append(
            {
                "d": d,
                "t": trading,
                "close": time(15, 30) if trading else None,
                "h": None if trading else "휴장",
            }
        )
        d += timedelta(days=1)
    with engine.begin() as c:
        c.execute(text("DELETE FROM reference.market_calendar"))
        c.execute(
            text(
                "INSERT INTO reference.market_calendar"
                "(trade_date,market,is_trading_day,session_close_at,holiday_name,source)"
                " VALUES (:d,'KRX',:t,:close,:h,'test')"
            ),
            rows,
        )


def wipe(engine) -> None:
    with engine.begin() as c:
        for t in (
            "public_serving.current_published_batch",
            "public_serving.market_summary_daily",
            "public_serving.derived_metrics_daily",
            "raw_internal.raw_fundamentals",
            "raw_internal.raw_ohlcv",
            "public_serving.stock_master",
            "public_serving.batch_run",
        ):
            c.execute(text(f"DELETE FROM {t}"))


def prepare_database(db: TempDb, *, stocks=None, derive: bool = True) -> None:
    """픽스처 시드 → 캘린더 → 배치 실행(발행)까지."""
    mig = create_engine(TempDb.render(db.migrator_url))
    batch = create_engine(TempDb.render(db.batch_url))
    try:
        wipe(mig)
        seed_calendar(mig)
        seed_fixture(mig, stocks=stocks)
        if derive:
            with Session(batch) as s:
                status = run_once(s, trade_date_override=TARGET_DATE)[0]
                s.commit()
            assert status == "SUCCESS", status
    finally:
        mig.dispose()
        batch.dispose()


@contextmanager
def api_client(db: TempDb) -> Iterator[TestClient]:
    """`api_service` 세션으로 DB를 바꾼 실제 앱 클라이언트."""
    engine = create_engine(TempDb.render(db.api_url))

    def _override_db():
        session = Session(engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    reset_rate_limit_state()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        reset_rate_limit_state()
        engine.dispose()
