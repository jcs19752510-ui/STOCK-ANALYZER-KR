"""PER/PBR 산정 불가 사유(DEC-057) 임시 DB 통합 테스트: 파생 컬럼 → API 노출까지."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.derivation_batch.run_derivation import run_once
from tests.integration.pattern_api_env import api_client, prepare_database
from tests.integration.pattern_fixtures import TARGET_DATE
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _exec(url, sql, **params):
    eng = create_engine(TempDb.render(url))
    try:
        with eng.begin() as c:
            return c.execute(text(sql), params)
    finally:
        eng.dispose()


def _rederive(db: TempDb) -> None:
    eng = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(eng) as s:
            assert run_once(s, trade_date_override=TARGET_DATE)[0] == "SUCCESS"
            s.commit()
    finally:
        eng.dispose()


def test_reasons_are_derived_and_exposed_without_raw_values(db):
    # T00001: 적자(순이익 음수) / T00002: 자본잠식 / T00003: 재무 원문 없음 / T00004: 정상(값 있음)
    _exec(db.migrator_url, "DELETE FROM raw_internal.raw_corp_financials")
    for code, ni, eq in (("T00001", -100, 500), ("T00002", 100, -10), ("T00004", 100, 500)):
        _exec(
            db.migrator_url,
            "INSERT INTO raw_internal.raw_corp_financials"
            "(stock_code, corp_code, bsns_year, reprt_code, fs_div, net_income, equity)"
            " VALUES (:c, '00000000', '2025', '11011', 'CFS', :ni, :eq)",
            c=code,
            ni=ni,
            eq=eq,
        )
    _exec(
        db.migrator_url,
        "UPDATE raw_internal.raw_fundamentals SET per=NULL, pbr=NULL"
        " WHERE stock_code IN ('T00001','T00002','T00003')",
    )
    _exec(
        db.migrator_url,
        "UPDATE raw_internal.raw_fundamentals SET per=10, pbr=1 WHERE stock_code='T00004'",
    )
    _rederive(db)
    with api_client(db) as c:
        loss = c.get("/api/v1/stocks/T00001/metrics").json()["data"]
        impaired = c.get("/api/v1/stocks/T00002/metrics").json()["data"]
        nodata = c.get("/api/v1/stocks/T00003/metrics").json()["data"]
        ok = c.get("/api/v1/stocks/T00004/metrics").json()["data"]
    assert (loss["per_unavailable_reason"], loss["pbr_unavailable_reason"]) == ("LOSS", "NO_DATA")
    assert (impaired["per_unavailable_reason"], impaired["pbr_unavailable_reason"]) == (
        "NO_DATA",
        "LOSS",
    )
    assert (nodata["per_unavailable_reason"], nodata["pbr_unavailable_reason"]) == (
        "NO_DATA",
        "NO_DATA",
    )
    assert ok["per_unavailable_reason"] is None and ok["pbr_unavailable_reason"] is None
    assert ok["per_percentile"] is not None
    # 원시 재무 값·원시 PER/PBR은 응답에 없다(§4-3 화이트리스트)
    assert not ({"per_raw", "pbr_raw", "net_income", "equity"} & set(ok))


def test_check_constraint_rejects_unknown_reason_and_api_role_is_read_only(db):
    with pytest.raises(Exception, match="per_unavailable_reason"):
        _exec(
            db.migrator_url,
            "UPDATE public_serving.derived_metrics_daily SET per_unavailable_reason='MAYBE'"
            " WHERE stock_code='T00001'",
        )
    with pytest.raises(Exception, match="permission denied"):
        _exec(
            db.api_url,
            "UPDATE public_serving.derived_metrics_daily SET per_unavailable_reason='LOSS'",
        )
