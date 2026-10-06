"""달력 적재 스크립트(`load_calendar.py`) 시험(DEC-093) — 실제 PostgreSQL 임시 DB. 연말에 달력을 못 넣으면 어떻게 되는지까지."""

# ruff: noqa: E501
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scripts import load_calendar as lc
from shared.calendar_service import get_last_trading_day
from shared.calendar_service.sql_repository import SqlCalendarRepository
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

CAL = Path(__file__).resolve().parents[2] / "data" / "calendar"
KST = ZoneInfo("Asia/Seoul")


@pytest.fixture()
def db():
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def test_load_2026_and_2027_then_year_boundary_and_idempotence(db, monkeypatch):
    monkeypatch.setenv("BATCH_DATABASE_URL", TempDb.render(db.batch_url))
    mig = create_engine(TempDb.render(db.migrator_url))
    api = create_engine(TempDb.render(db.api_url))
    try:
        with mig.begin() as c:
            c.execute(text("DELETE FROM reference.market_calendar"))
        # 2026만 적재: 새해에는 직전 거래일을 계산할 수 없다(CALENDAR_NOT_CONFIRMED의 원인)
        assert lc.main([str(CAL / "2026.yaml")]) == 0
        with Session(api) as s:
            assert get_last_trading_day("KRX", datetime(2027, 1, 4, 10, 0, tzinfo=KST), SqlCalendarRepository(s)) is None
        # 2027 적재 후: 12/31 연말휴장·1/1 휴장·주말을 건너뛰어 2026-12-30(수)
        assert lc.main([str(CAL / "2027.yaml")]) == 0
        with Session(api) as s:
            cal = SqlCalendarRepository(s)
            assert get_last_trading_day("KRX", datetime(2027, 1, 4, 10, 0, tzinfo=KST), cal) == date(2026, 12, 30)
            assert get_last_trading_day("KRX", datetime(2027, 1, 4, 16, 0, tzinfo=KST), cal) == date(2027, 1, 4)  # 마감(15:30) 뒤엔 오늘
            assert get_last_trading_day("KRX", datetime(2027, 2, 9, 10, 0, tzinfo=KST), cal) == date(2027, 2, 4)  # 설 연휴(2/5)·주말·대체(2/8) 건너뜀
            assert get_last_trading_day("KRX", datetime(2027, 9, 17, 10, 0, tzinfo=KST), cal) == date(2027, 9, 13)  # 추석 연휴 3일
        # 다시 적재해도 같다(멱등)
        with mig.connect() as c:
            before = c.execute(text("SELECT count(*), count(*) FILTER (WHERE is_trading_day) FROM reference.market_calendar")).one()
        assert lc.main([str(CAL / "2027.yaml")]) == 0
        with mig.connect() as c:
            after = c.execute(text("SELECT count(*), count(*) FILTER (WHERE is_trading_day) FROM reference.market_calendar")).one()
        assert tuple(before) == tuple(after)
        assert before[0] == 1460 and before[1] == 2 * (244 + 247)  # 2026+2027 × (KRX+NXT) 행, 거래일은 연 244·247일씩 두 시장 같음
    finally:
        mig.dispose()
        api.dispose()


def test_load_calendar_fails_loudly_without_db_url_or_with_bad_file(monkeypatch, tmp_path):
    monkeypatch.delenv("BATCH_DATABASE_URL", raising=False)
    assert lc.main([str(CAL / "2027.yaml")]) == 1  # DB 주소 없음
    bad = tmp_path / "bad.yaml"
    bad.write_text("year: 2027\nmarkets: [\n", encoding="utf-8")
    assert lc.main([str(bad), "--dry-run"]) == 1  # 파싱 실패
    assert os.environ.get("BATCH_DATABASE_URL") is None
    assert lc.main([str(CAL / "2027.yaml"), "--dry-run"]) == 0  # 건조 실행은 DB 없이 성공
