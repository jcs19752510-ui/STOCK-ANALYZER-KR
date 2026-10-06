"""따라잡기 시도 상한(DEC-092) — "데이터 공개 전" 실패는 세지 않는다. 실제 PostgreSQL 임시 DB."""

# ruff: noqa: E501
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.ingestion_batch import batch_run_repository as brr
from shared import batch_catchup as bc
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

D = {n: date(2026, 10, n) for n in range(1, 10)}


def test_constants_match_ingestion_module():
    assert bc.NOT_PUBLISHED_PREFIX == brr.NOT_PUBLISHED_ERROR_SUMMARY_PREFIX
    assert bc.LEGACY_NOT_PUBLISHED_TEXT == brr.LEGACY_NOT_PUBLISHED_TEXT


@pytest.fixture(scope="module")
def db():
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def put(conn, day: date, status: str, err: str | None, n: int = 1, run_type: str = "ingest") -> None:
    for _ in range(n):
        conn.execute(
            text("INSERT INTO public_serving.batch_run(batch_run_id,run_type,status,trade_date_covered,validation_passed,error_summary) VALUES (:i, CAST(:t AS public_serving.batch_run_type), CAST(:s AS public_serving.batch_run_status), :d, false, :e)"),
            {"i": uuid.uuid4(), "t": run_type, "s": status, "d": day, "e": err},
        )


def test_not_published_failures_do_not_exhaust_a_day_but_real_failures_do(db):
    eng = create_engine(TempDb.render(db.migrator_url))
    with eng.begin() as c:
        c.execute(text("DELETE FROM public_serving.batch_run"))
        put(c, D[2], "FAILED", f"{bc.NOT_PUBLISHED_PREFIX}: 대상 거래일 데이터가 0건 반환되었습니다", n=6)  # 10/2: 공개 전 6회(이번 사례) → 세지 않음
        put(c, D[3], "FAILED", f"{bc.LEGACY_NOT_PUBLISHED_TEXT}(예전 문구)", n=5)  # 접두 도입 전 같은 사유
        put(c, D[4], "FAILED", "API 호출 실패: 키 오류", n=3)  # 진짜 실패 3회 → 상한
        put(c, D[5], "PARTIAL", None, n=3)  # 부분 성공 3회 → 상한
        put(c, D[6], "FAILED", "API 호출 실패: 일시 오류", n=2)
        put(c, D[6], "FAILED", f"{bc.NOT_PUBLISHED_PREFIX}: x", n=5)  # 진짜 2회 + 공개 전 5회 → 진짜만 세어 2회 → 상한 아님
        put(c, D[7], "FAILED", None, n=3)  # 사유 없는 실패도 센다(NULL은 진짜 실패)
    with Session(eng) as s:
        got = set(bc.fetch_exhausted_dates(s, since=D[1], before=D[9]))
    eng.dispose()
    assert got == {D[4], D[5], D[7]}
    assert D[2] not in got and D[3] not in got and D[6] not in got
