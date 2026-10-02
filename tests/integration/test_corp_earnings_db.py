"""연간 실적 테이블 `public_serving.corp_earnings` + API 통합 임시 DB 테스트 (UNIT-23, DEC-041)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from services.ingestion_batch.dart_client import AnnualEarningsRecord
from services.ingestion_batch.repository import upsert_annual_earnings
from tests.integration.pattern_api_env import api_client, prepare_database
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, run_alembic, temp_database


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _rec(year, revenue, op, net, fs="CFS"):
    return AnnualEarningsRecord(
        fiscal_year=year,
        fs_div=fs,
        revenue=None if revenue is None else Decimal(revenue),
        operating_income=None if op is None else Decimal(op),
        net_income=None if net is None else Decimal(net),
    )


def _batch_upsert(db, code, records):
    eng = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(eng) as s:
            n = upsert_annual_earnings(s, code, records)
            s.commit()
        return n
    finally:
        eng.dispose()


def _count(db, code):
    eng = create_engine(TempDb.render(db.migrator_url))
    try:
        with eng.connect() as c:
            return c.execute(
                text("SELECT count(*) FROM public_serving.corp_earnings WHERE stock_code=:c"),
                {"c": code},
            ).scalar_one()
    finally:
        eng.dispose()


def test_u23_01_upsert_is_idempotent_and_overwrites_corrections(db):
    code = "T00001"
    recs = [_rec(2023, 100, 10, 5), _rec(2024, 200, -20, 15), _rec(2025, 300, 30, 25)]
    assert _batch_upsert(db, code, recs) == 3
    assert _batch_upsert(db, code, recs) == 3
    assert _count(db, code) == 3  # 중복 없음
    _batch_upsert(db, code, [_rec(2025, 310, 31, 26, fs="OFS")])  # 정정 공시
    eng = create_engine(TempDb.render(db.migrator_url))
    try:
        with eng.connect() as c:
            row = c.execute(
                text(
                    "SELECT revenue, fs_div FROM public_serving.corp_earnings"
                    " WHERE stock_code=:c AND fiscal_year=2025"
                ),
                {"c": code},
            ).one()
    finally:
        eng.dispose()
    assert row[0] == Decimal(310) and row[1] == "OFS"


def test_u23_02_api_returns_ascending_years_with_nulls_and_404(db):
    _batch_upsert(
        db, "T00002", [_rec(2025, None, None, 7), _rec(2023, 1, 2, 3), _rec(2024, 4, -5, 6)]
    )
    with api_client(db) as c:
        ok = c.get("/api/v1/stocks/T00002/earnings")
        none = c.get("/api/v1/stocks/T00003/earnings")  # 종목은 있으나 실적 없음
        missing = c.get("/api/v1/stocks/ZZZZZZ/earnings")
    years = ok.json()["data"]["earnings"]
    assert [y["fiscal_year"] for y in years] == [2023, 2024, 2025]
    assert years[1]["operating_income"] == -5.0  # 적자는 음수 그대로
    assert years[2]["revenue"] is None and years[2]["operating_income"] is None  # 0이 아닌 null
    assert none.status_code == 200 and none.json()["data"]["earnings"] == []
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "STOCK_NOT_FOUND"
    assert set(years[0]) == {"fiscal_year", "fs_div", "revenue", "operating_income", "net_income"}
    assert not ({"score", "rank", "grade", "rating"} & set(years[0]))  # 해석·서열 필드 없음


def test_u23_03_api_service_is_select_only(db):
    api = create_engine(TempDb.render(db.api_url))
    try:
        with api.connect() as c:
            assert (
                c.execute(text("SELECT count(*) FROM public_serving.corp_earnings")).scalar_one()
                >= 0
            )
        for sql in (
            "INSERT INTO public_serving.corp_earnings(stock_code,fiscal_year,fs_div)"
            " VALUES ('Z00001',2025,'CFS')",
            "DELETE FROM public_serving.corp_earnings",
        ):
            with api.connect() as c, pytest.raises(DBAPIError, match="permission denied"):
                c.execute(text(sql))
    finally:
        api.dispose()


def test_u23_04_check_constraint_and_reversible_migration(db):
    mig = create_engine(TempDb.render(db.migrator_url))
    try:
        with mig.connect() as c, pytest.raises(DBAPIError, match="ck_corp_earnings_fs_div"):
            c.execute(
                text(
                    "INSERT INTO public_serving.corp_earnings(stock_code,fiscal_year,fs_div)"
                    " VALUES ('T00001',1999,'XXX')"
                )
            )
        down = run_alembic(db, "downgrade", "0012")
        assert down.returncode == 0, down.stderr[-400:]
        with mig.connect() as c:
            assert c.execute(
                text("SELECT to_regclass('public_serving.corp_earnings') IS NULL")
            ).scalar_one()
            assert c.execute(
                text("SELECT to_regclass('public_serving.daily_prices') IS NOT NULL")
            ).scalar_one()
        up = run_alembic(db, "upgrade", "head")
        assert up.returncode == 0, up.stderr[-400:]
    finally:
        mig.dispose()
