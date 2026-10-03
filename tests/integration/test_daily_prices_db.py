"""공개용 일봉 테이블 `public_serving.daily_prices` 통합 임시 DB 테스트 (UNIT-19, DEC-041).

종목 상세 차트(C안)용 원값 노출은 `raw_internal`의 권한을 풀지 않고, 공개용 복사본 테이블로만 한다.
임시 DB에 실제 마이그레이션(0012)·실제 역할 권한을 적용해 검증한다. 개발 DB에는 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from services.derivation_batch.run_derivation import run_once
from tests.integration.pattern_api_env import prepare_database
from tests.integration.pattern_fixtures import TARGET_DATE
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, run_alembic, temp_database

COLUMNS = {
    "stock_code": "character varying",
    "trade_date": "date",
    "open": "numeric",
    "high": "numeric",
    "low": "numeric",
    "close": "numeric",
    "volume": "bigint",
    "trading_value": "bigint",
}


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)  # 시드 → 배치(발행)까지. 0012 적용 후라 daily_prices도 채워진다.
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _scalar(engine, sql: str, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar_one()


@pytest.fixture()
def mig(db):
    eng = create_engine(TempDb.render(db.migrator_url))
    yield eng
    eng.dispose()


@pytest.fixture()
def api(db):
    eng = create_engine(TempDb.render(db.api_url))
    yield eng
    eng.dispose()


def test_u19_01_table_has_expected_columns_and_primary_key(mig):
    with mig.connect() as c:
        cols = dict(
            c.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns"
                    " WHERE table_schema='public_serving' AND table_name='daily_prices'"
                )
            ).all()
        )
        pk = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT a.attname FROM pg_index i JOIN pg_attribute a"
                    " ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey)"
                    " WHERE i.indrelid='public_serving.daily_prices'::regclass AND i.indisprimary"
                    " ORDER BY a.attnum"
                )
            ).all()
        ]
    assert COLUMNS.items() <= cols.items()
    assert pk == ["stock_code", "trade_date"]


def test_u19_02_api_service_is_select_only_and_still_cannot_read_raw(api):
    assert _scalar(api, "SELECT count(*) FROM public_serving.daily_prices") > 0
    for sql in (
        "INSERT INTO public_serving.daily_prices(stock_code,trade_date,open,high,low,close,"
        "volume,trading_value) VALUES ('Z00001','2026-01-02',1,1,1,1,1,1)",
        "UPDATE public_serving.daily_prices SET close = 1",
        "DELETE FROM public_serving.daily_prices",
    ):
        with api.connect() as c, pytest.raises(DBAPIError, match="permission denied"):
            c.execute(text(sql))
    # 2차 방어 유지: 원본 테이블은 여전히 읽을 수 없다
    with api.connect() as c, pytest.raises(DBAPIError, match="permission denied"):
        c.execute(text("SELECT 1 FROM raw_internal.raw_ohlcv LIMIT 1"))


def test_u19_03_batch_copies_krx_ohlcv_exactly(mig):
    raw = _scalar(
        mig,
        "SELECT count(*) FROM raw_internal.raw_ohlcv WHERE market='KRX' AND trade_date<=:d",
        d=TARGET_DATE,
    )
    pub = _scalar(mig, "SELECT count(*) FROM public_serving.daily_prices")
    assert pub == raw > 0
    mismatches = _scalar(
        mig,
        "SELECT count(*) FROM raw_internal.raw_ohlcv r JOIN public_serving.daily_prices p"
        " USING (stock_code, trade_date) WHERE r.market='KRX' AND (r.open<>p.open OR"
        " r.high<>p.high OR r.low<>p.low OR r.close<>p.close OR r.volume<>p.volume OR"
        " r.trading_value<>p.trading_value)",
    )
    assert mismatches == 0


def test_u19_04_rerun_is_idempotent_and_propagates_corrections(db, mig):
    before = _scalar(mig, "SELECT count(*) FROM public_serving.daily_prices")
    code = _scalar(mig, "SELECT min(stock_code) FROM public_serving.daily_prices")
    with mig.begin() as c:  # 원본 정정(상류 데이터가 고쳐진 상황)
        c.execute(
            text(
                "UPDATE raw_internal.raw_ohlcv SET close = close + 7 WHERE stock_code=:c"
                " AND trade_date=:d AND market='KRX'"
            ),
            {"c": code, "d": TARGET_DATE},
        )
        raw_close = c.execute(
            text(
                "SELECT close FROM raw_internal.raw_ohlcv WHERE stock_code=:c AND trade_date=:d"
                " AND market='KRX'"
            ),
            {"c": code, "d": TARGET_DATE},
        ).scalar_one()
    batch = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(batch) as s:
            status = run_once(s, trade_date_override=TARGET_DATE)[0]
            s.commit()
    finally:
        batch.dispose()
    assert status == "SUCCESS"
    assert _scalar(mig, "SELECT count(*) FROM public_serving.daily_prices") == before  # 중복 없음
    pub_close = _scalar(
        mig,
        "SELECT close FROM public_serving.daily_prices WHERE stock_code=:c AND trade_date=:d",
        c=code,
        d=TARGET_DATE,
    )
    assert Decimal(pub_close) == Decimal(raw_close)  # 정정 반영


def test_u19_05_nxt_rows_and_rows_outside_retention_are_not_copied(db, mig):
    code = _scalar(mig, "SELECT min(stock_code) FROM public_serving.daily_prices")
    old = TARGET_DATE - timedelta(days=500)  # 보존 기간(400일) 밖
    batch_id = _scalar(mig, "SELECT batch_run_id FROM public_serving.batch_run LIMIT 1")
    with mig.begin() as c:
        c.execute(
            text(
                "INSERT INTO raw_internal.raw_ohlcv(stock_code,trade_date,market,open,high,low,"
                "close,volume,trading_value,source_batch_id)"
                " VALUES (:c,:d1,'KRX',1,1,1,1,1,1,:b), (:c,:d2,'NXT',1,1,1,1,1,1,:b)"
            ),
            {"c": code, "d1": old, "d2": TARGET_DATE, "b": batch_id},
        )
    batch = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(batch) as s:
            run_once(s, trade_date_override=TARGET_DATE)
            s.commit()
    finally:
        batch.dispose()
    assert (
        _scalar(mig, "SELECT count(*) FROM public_serving.daily_prices WHERE trade_date=:d", d=old)
        == 0
    )
    # NXT 행은 같은 (종목, 일자)의 KRX 값을 덮어쓰지 않는다(PK에 시장이 없으므로 KRX만 복사)
    krx_close = _scalar(
        mig,
        "SELECT close FROM raw_internal.raw_ohlcv WHERE stock_code=:c AND trade_date=:d"
        " AND market='KRX'",
        c=code,
        d=TARGET_DATE,
    )
    pub_close = _scalar(
        mig,
        "SELECT close FROM public_serving.daily_prices WHERE stock_code=:c AND trade_date=:d",
        c=code,
        d=TARGET_DATE,
    )
    assert Decimal(pub_close) == Decimal(krx_close)


def test_u19_06_migration_is_reversible_and_leaves_other_tables_alone(db, mig):
    other_before = _scalar(mig, "SELECT count(*) FROM public_serving.derived_metrics_daily")
    down = run_alembic(db, "downgrade", "0011")
    assert down.returncode == 0, down.stderr[-400:]
    assert _scalar(mig, "SELECT to_regclass('public_serving.daily_prices') IS NULL")  # 테이블 제거
    assert _scalar(mig, "SELECT count(*) FROM public_serving.derived_metrics_daily") == other_before
    up = run_alembic(db, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-400:]
    assert _scalar(mig, "SELECT to_regclass('public_serving.daily_prices') IS NOT NULL")
    prepare_database(db)  # 다음 테스트를 위해 시드·배치(발행)를 다시 수행해 테이블을 채운다


# ── UNIT-20: 실제 API(읽기 전용 api_service 세션) ────────────────────────────────────────
def test_u20_api_returns_real_prices_equal_to_raw_ohlcv(db, mig):
    from tests.integration.pattern_api_env import api_client

    code = _scalar(mig, "SELECT min(stock_code) FROM public_serving.daily_prices")
    with mig.connect() as c:
        raw = c.execute(
            text(
                "SELECT trade_date, open, high, low, close, volume FROM raw_internal.raw_ohlcv"
                " WHERE stock_code=:c AND market='KRX' ORDER BY trade_date DESC LIMIT 60"
            ),
            {"c": code},
        ).all()
    raw.reverse()
    with api_client(db) as client:
        resp = client.get(f"/api/v1/stocks/{code}/prices", params={"days": 60})
        missing = client.get("/api/v1/stocks/ZZZZZZ/prices")
    assert resp.status_code == 200, resp.text
    prices = resp.json()["data"]["prices"]
    assert len(prices) == len(raw) == 60
    for got, want in zip(prices, raw, strict=True):
        assert got["trade_date"] == want[0].isoformat()
        assert (got["open"], got["high"], got["low"], got["close"]) == tuple(
            float(v) for v in want[1:5]
        )
        assert got["volume"] == want[5]
    assert prices[0]["change"] is None and prices[1]["change"] is not None
    assert missing.status_code == 404


def test_u22_quotes_endpoint_on_real_db_matches_last_two_closes(db, mig):
    from tests.integration.pattern_api_env import api_client

    codes = [
        r[0]
        for r in mig.connect().execute(
            text("SELECT DISTINCT stock_code FROM public_serving.daily_prices ORDER BY 1 LIMIT 3")
        )
    ]
    with mig.connect() as c:
        want = {
            code: c.execute(
                text(
                    "SELECT close FROM public_serving.daily_prices WHERE stock_code=:c"
                    " ORDER BY trade_date DESC LIMIT 2"
                ),
                {"c": code},
            ).all()
            for code in codes
        }
    with api_client(db) as client:
        resp = client.get("/api/v1/stocks/quotes", params={"codes": ",".join(codes + ["ZZZZZZ"])})
    assert resp.status_code == 200, resp.text
    quotes = resp.json()["data"]["quotes"]
    assert [q["stock_code"] for q in quotes] == codes  # 없는 종목은 생략, 요청 순서 유지
    for q in quotes:
        last, prev = (float(v[0]) for v in want[q["stock_code"]])
        assert q["close"] == last and q["change"] == pytest.approx(last - prev)
