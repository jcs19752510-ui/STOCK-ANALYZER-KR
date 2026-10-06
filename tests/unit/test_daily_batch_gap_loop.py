"""일일 배치 루프: 가공이 보류된 날짜(종료코드 3)는 건너뛰고 다음 날짜로 계속한다(DEC-093)."""

from __future__ import annotations

from datetime import date

from scripts import run_daily_batch as rdb

D1, D2, D3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)


def test_blocked_day_is_skipped_and_run_continues(monkeypatch, capsys):
    calls = []
    codes = {D1: 3, D2: 0, D3: 0}
    monkeypatch.setattr(rdb, "_run_one_date", lambda d: calls.append(d) or codes[d])
    rc = rdb._run_with_catchup([D1, D2, D3], D3)
    out = capsys.readouterr()
    assert rc == 0 and calls == [D1, D2, D3]
    assert "가공 보류" in out.err and "2026-10-01" in out.err and "보류된 날짜 있음" in out.out


def test_real_failure_still_stops_and_target_failure_still_waits(monkeypatch):
    monkeypatch.setattr(rdb, "_run_one_date", lambda d: 1 if d == D1 else 0)
    assert rdb._run_with_catchup([D1, D2], D2) == 1  # 더 이전 날짜의 진짜 실패는 중단(기존 동작)
    monkeypatch.setattr(rdb, "_run_one_date", lambda d: 1 if d == D2 else 0)
    assert rdb._run_with_catchup([D1, D2], D2) == rdb.EXIT_NOT_PUBLISHED  # 대상일 실패 = 공개 대기


def test_all_clean_message_unchanged(monkeypatch, capsys):
    monkeypatch.setattr(rdb, "_run_one_date", lambda d: 0)
    assert rdb._run_with_catchup([D1], D1) == 0
    assert "정상 종료" in capsys.readouterr().out
