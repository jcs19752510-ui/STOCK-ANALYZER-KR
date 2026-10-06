"""`scripts/diagnose_local_data.py` 판정 로직 시험(순수 함수) — DB·PC 없이."""

# ruff: noqa: E501
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import diagnose_local_data as dg  # noqa: E402

KST = dg.KST
NOW = datetime(2026, 10, 6, 21, 30, tzinfo=KST)
D1, D2 = date(2026, 10, 2), date(2026, 10, 6)


def run(day, status="FAILED", err=None, at=NOW - timedelta(minutes=10), rtype="ingest"):
    return dg.Run(rtype, status, day, at, err)


def test_classify_each_state():
    assert dg.classify_day(D1, [])[0] == "NO_RUN"
    assert dg.classify_day(D1, [run(D1, err="NOT_PUBLISHED: 0건")])[0] == "NOT_PUBLISHED"
    assert dg.classify_day(D1, [run(D1, err="API 호출 실패(키 오류)")])[0] == "FAILED"
    assert dg.classify_day(D1, [run(D1, status="PARTIAL")])[0] == "PARTIAL"
    assert dg.classify_day(D1, [run(D1, status="SUCCESS")])[0] == "OK_UNPUBLISHED"
    # 마지막 시도가 기준: 실패 뒤 성공이면 성공으로 본다
    assert dg.classify_day(D1, [run(D1, err="x", at=NOW - timedelta(hours=5)), run(D1, status="SUCCESS")])[0] == "OK_UNPUBLISHED"
    assert "총 2회" in dg.classify_day(D1, [run(D1, err="NOT_PUBLISHED", at=NOW - timedelta(hours=5)), run(D1, err="NOT_PUBLISHED")])[1]


def states(*pairs):
    return {d: dg.classify_day(d, r) for d, r in pairs}


def test_verdict_normal_delay_is_not_published():
    st = states((D1, [run(D1, err="NOT_PUBLISHED")]), (D2, [run(D2, err="NOT_PUBLISHED")]))
    out = "\n".join(dg.verdict([D1, D2], st, NOW - timedelta(minutes=10), NOW))
    assert "정상 지연" in out and "장중 기준" in out


def test_verdict_batch_not_running():
    out = "\n".join(dg.verdict([D1, D2], states((D1, []), (D2, [])), NOW - timedelta(days=3), NOW))
    assert "배치가 돌지 않고" in out and "run_daily_batch" in out
    assert "기록이 전혀 없습니다" in "\n".join(dg.verdict([D1], states((D1, [])), None, NOW))


def test_verdict_failed_and_no_run_and_fresh():
    st = states((D1, [run(D1, err="키 오류")]), (D2, []))
    assert "수집 실패" in "\n".join(dg.verdict([D1, D2], st, NOW - timedelta(hours=1), NOW))
    assert "시도조차" in "\n".join(dg.verdict([D2], states((D2, [])), NOW - timedelta(hours=1), NOW))
    assert dg.verdict([], {}, NOW, NOW)[0].startswith("[정상]")


def test_calendar_end_warning():
    today = date(2026, 12, 1)
    assert dg.calendar_end_warning(date(2027, 12, 31), today) is None  # 충분히 남음
    assert "30일 뒤" in dg.calendar_end_warning(date(2026, 12, 31), today)  # 곧 끝남
    assert "이미 지났" in dg.calendar_end_warning(date(2026, 11, 30), today)
    assert "달력이 DB에 없습니다" in dg.calendar_end_warning(None, today)
