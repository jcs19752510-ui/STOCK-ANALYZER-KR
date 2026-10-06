"""빠진 날 방어(DEC-093) — 직전 거래일 원본 시세가 이력 한가운데 비어 있으면 그날 가공을 보류한다. 실제 PostgreSQL 임시 DB."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.derivation_batch import run_derivation as rd
from services.derivation_batch.run_derivation import (
    GAP_BLOCKED_PREFIX,
    find_missing_previous_day,
    run_once,
)
from services.public_api.db.calendar_repository import SqlCalendarRepository
from shared import batch_catchup as bc
from tests.integration.pattern_api_env import prepare_database
from tests.integration.pattern_fixtures import TARGET_DATE, trading_dates
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database


@pytest.fixture()
def db():
    try:
        with temp_database() as tdb:
            prepare_database(tdb)  # 130거래일, 기준일 2026-09-30 가공·발행까지
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _add_day(mig, day: date, like: date) -> None:
    """`like` 날짜의 원본 시세를 `day`로 복사해 하루를 더 만든다(가격 그대로)."""
    with mig.begin() as c:
        c.execute(text("INSERT INTO raw_internal.raw_ohlcv(stock_code,trade_date,market,open,high,low,close,volume,trading_value,ingested_at,source_batch_id) SELECT stock_code,:d,market,open,high,low,close,volume,trading_value,now(),source_batch_id FROM raw_internal.raw_ohlcv WHERE trade_date=:l"), {"d": day, "l": like})
        c.execute(text("INSERT INTO raw_internal.raw_fundamentals(stock_code,trade_date,per,pbr,market_cap,ingested_at,source_batch_id) SELECT stock_code,:d,per,pbr,market_cap,now(),source_batch_id FROM raw_internal.raw_fundamentals WHERE trade_date=:l"), {"d": day, "l": like})


def test_hole_in_history_blocks_next_day_and_other_cases_do_not(db):
    mig = create_engine(TempDb.render(db.migrator_url))
    batch = create_engine(TempDb.render(db.batch_url))
    try:
        d1 = _next_weekday(TARGET_DATE)  # 10/1
        d2 = _next_weekday(d1)  # 10/2
        d3 = _next_weekday(d2)  # 10/5(달력은 평일=거래일 단순 모델)
        _add_day(mig, d1, TARGET_DATE)
        _add_day(mig, d3, TARGET_DATE)  # d2는 일부러 비움 → d3 가공 시 직전 거래일(d2)이 구멍
        with Session(batch) as s:
            cal = SqlCalendarRepository(s)
            assert find_missing_previous_day(s, cal, d1) is None  # 직전(9/30)이 있다
            assert find_missing_previous_day(s, cal, d2) is None  # 직전(d1)이 있다
            assert find_missing_previous_day(s, cal, d3) == d2  # 직전(d2)이 비어 있고 그 앞 이력은 있다 → 구멍
            # 이력이 시작되기 전(첫 날)이면 막지 않는다
            first = trading_dates()[-1]
            assert find_missing_previous_day(s, cal, first) is None
        # 구멍이 있는 날 가공은 보류(FAILED, GAP_BLOCKED) — 발행 포인터는 그대로
        with Session(batch) as s:
            status, covered, err = run_once(s, trade_date_override=d3)
            s.commit()
            assert status == "FAILED" and covered == d3 and (err or "").startswith(GAP_BLOCKED_PREFIX) and str(d2) in err
            pointer = s.execute(text("SELECT trade_date FROM public_serving.current_published_batch WHERE market='KRX'")).scalar_one()
            assert pointer == TARGET_DATE
        # 구멍 아닌 날은 정상 가공
        with Session(batch) as s:
            status, covered, _ = run_once(s, trade_date_override=d1)
            s.commit()
            assert status == "SUCCESS" and covered == d1
        # 구멍을 메우면 d3도 정상, 또는 --allow-gap으로 강제 가능
        with Session(batch) as s:
            status, _, _ = run_once(s, trade_date_override=d3, allow_gap=True)
            s.commit()
            assert status in ("SUCCESS", "PARTIAL")
        _add_day(mig, d2, TARGET_DATE)
        with Session(batch) as s:
            assert find_missing_previous_day(s, SqlCalendarRepository(s), d3) is None
    finally:
        mig.dispose()
        batch.dispose()


def test_gap_blocked_failures_are_not_counted_toward_attempt_cap(db):
    """가공 보류 기록이 몇 번 쌓여도 그 날짜를 영구 포기하지 않는다(구멍이 메워지면 다시 가공해야 하므로)."""
    d = date(2026, 10, 5)
    mig = create_engine(TempDb.render(db.migrator_url))
    with mig.begin() as c:
        for _ in range(6):
            c.execute(text("INSERT INTO public_serving.batch_run(batch_run_id,run_type,status,trade_date_covered,validation_passed,error_summary) VALUES (gen_random_uuid(),'derive','FAILED',:d,false,:e)"), {"d": d, "e": f"{GAP_BLOCKED_PREFIX}: x"})
    with Session(mig) as s:
        assert d not in bc.fetch_exhausted_dates(s, since=date(2026, 10, 1), before=date(2026, 10, 9))
    mig.dispose()
    assert bc.GAP_BLOCKED_PREFIX == rd.GAP_BLOCKED_PREFIX


def test_cli_exit_code_for_gap_blocked_is_3():
    from scripts import run_daily_batch as rdb

    assert rdb.EXIT_GAP_BLOCKED == rd.EXIT_GAP_BLOCKED == 3


def test_partial_hole_when_previous_day_has_too_few_stocks(db):
    """직전 거래일에 일부 종목만 있으면(수집이 중간에 끊김) 그다음 날 가공을 보류한다. 절반 이상 있으면 막지 않는다."""
    mig = create_engine(TempDb.render(db.migrator_url))
    batch = create_engine(TempDb.render(db.batch_url))
    try:
        d1 = _next_weekday(TARGET_DATE)
        d2 = _next_weekday(d1)
        _add_day(mig, d1, TARGET_DATE)
        total = 0
        with mig.connect() as c:
            total = c.execute(text("SELECT count(*) FROM raw_internal.raw_ohlcv WHERE trade_date=:d"), {"d": d1}).scalar_one()
        assert total >= 8
        with Session(batch) as s:
            assert find_missing_previous_day(s, SqlCalendarRepository(s), d2) is None  # d1 전체 있음
        keep = total // 2  # 정확히 절반 → 경계: 50% 미만이 아니므로 막지 않는다
        with mig.begin() as c:
            c.execute(text("DELETE FROM raw_internal.raw_ohlcv WHERE trade_date=:d AND stock_code NOT IN (SELECT stock_code FROM raw_internal.raw_ohlcv WHERE trade_date=:d ORDER BY stock_code LIMIT :k)"), {"d": d1, "k": keep})
        with Session(batch) as s:
            assert find_missing_previous_day(s, SqlCalendarRepository(s), d2) is None
        with mig.begin() as c:  # 절반 미만(30%)으로 더 지움
            c.execute(text("DELETE FROM raw_internal.raw_ohlcv WHERE trade_date=:d AND stock_code NOT IN (SELECT stock_code FROM raw_internal.raw_ohlcv WHERE trade_date=:d ORDER BY stock_code LIMIT :k)"), {"d": d1, "k": max(1, int(total * 0.3))})
        with Session(batch) as s:
            assert find_missing_previous_day(s, SqlCalendarRepository(s), d2) == d1
            status, _, err = run_once(s, trade_date_override=d2)
            s.commit()
            assert status == "FAILED" and (err or "").startswith(GAP_BLOCKED_PREFIX) and str(d1) in err
    finally:
        mig.dispose()
        batch.dispose()
