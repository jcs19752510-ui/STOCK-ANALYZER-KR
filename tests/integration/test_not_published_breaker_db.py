"""데이터 미공개(0건) 실행이 서킷브레이커 연속 실패에 섞이지 않는지(DEC-058). 임시 DB."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.ingestion_batch import run_ingestion
from services.ingestion_batch.batch_run_repository import (
    LEGACY_NOT_PUBLISHED_TEXT,
    NOT_PUBLISHED_ERROR_SUMMARY_PREFIX,
    recent_ingest_statuses,
)
from services.ingestion_batch.circuit_breaker import evaluate
from services.ingestion_batch.gov_data_client import FetchResult
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

REAL_FAILURE = "API 호출 실패: 연결 실패"


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


@pytest.fixture()
def clean(db: TempDb):
    eng = create_engine(TempDb.render(db.migrator_url))
    with eng.begin() as c:
        c.execute(text("DELETE FROM public_serving.batch_run"))
    yield eng
    eng.dispose()


def _seed(eng, rows: list[tuple[str, str | None]]):
    """(status, error_summary) 목록을 오래된 순으로 적재한다."""
    base = datetime(2026, 10, 1, 7, 0).astimezone()
    with eng.begin() as c:
        for i, (st, summary) in enumerate(rows):
            c.execute(
                text(
                    "INSERT INTO public_serving.batch_run"
                    "(batch_run_id,run_type,started_at,finished_at,status,validation_passed,error_summary)"
                    " VALUES (:id,'ingest',:t,:t,:s,false,:e)"
                ),
                {"id": uuid.uuid4(), "t": base + timedelta(hours=i), "s": st, "e": summary},
            )


def _view(db: TempDb, limit: int = 3):
    eng = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(eng) as s:
            statuses = recent_ingest_statuses(s, limit)
        return statuses, evaluate(statuses, threshold=3)
    finally:
        eng.dispose()


NP = f"{NOT_PUBLISHED_ERROR_SUMMARY_PREFIX}: 대상 거래일 데이터가 0건 반환되었습니다(...)"
LEGACY = f"{LEGACY_NOT_PUBLISHED_TEXT}(공공데이터포털 +1영업일 지연 ...)"


def test_weekend_not_published_runs_do_not_open_the_breaker(db, clean):
    _seed(clean, [("SUCCESS", None)] + [("FAILED", NP)] * 4)  # 금요일 성공 → 토·일 미공개 4회
    statuses, breaker = _view(db)
    assert statuses == ["SUCCESS"]  # 미공개 행은 집계에서 빠진다
    assert breaker.is_open is False and breaker.consecutive_failures == 0


def test_legacy_rows_without_prefix_are_excluded_by_message(db, clean):
    _seed(clean, [("SUCCESS", None)] + [("FAILED", LEGACY)] * 3)
    statuses, breaker = _view(db)
    assert statuses == ["SUCCESS"] and breaker.is_open is False


def test_real_failures_still_open_the_breaker_even_between_not_published_rows(db, clean):
    _seed(
        clean,
        [("FAILED", REAL_FAILURE), ("FAILED", NP), ("FAILED", REAL_FAILURE), ("FAILED", NP),
         ("FAILED", REAL_FAILURE)],
    )  # fmt: skip
    statuses, breaker = _view(db)
    assert statuses == ["FAILED", "FAILED", "FAILED"]  # 진짜 실패 3건만 센다
    assert breaker.is_open is True and breaker.consecutive_failures == 3


def test_run_once_records_not_published_with_prefix_and_failed_status(db, clean):
    class EmptyApi:
        """대상 거래일이 아직 공개되지 않아 0건을 돌려주는 가짜 클라이언트."""

        def fetch_ohlcv(self, trade_date, *, page_no, num_of_rows):
            return FetchResult(records=[], total_count=0)

    eng = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(eng) as s:
            status, covered, summary = run_ingestion.run_once(
                s, EmptyApi(), trade_date_override=date(2026, 10, 2)
            )
            s.commit()
    finally:
        eng.dispose()
    assert status == "FAILED" and covered == date(2026, 10, 2)  # 재시도 대상으로 FAILED 기록
    assert summary is not None and summary.startswith(NOT_PUBLISHED_ERROR_SUMMARY_PREFIX)
    statuses, breaker = _view(db)
    assert statuses == [] and breaker.is_open is False
    for _ in range(3):
        eng = create_engine(TempDb.render(db.batch_url))
        try:
            with Session(eng) as s:
                run_ingestion.run_once(s, EmptyApi(), trade_date_override=date(2026, 10, 2))
                s.commit()
        finally:
            eng.dispose()
    # 3번 더 반복해도 경보가 켜지지 않는다
    assert _view(db)[1].is_open is False
