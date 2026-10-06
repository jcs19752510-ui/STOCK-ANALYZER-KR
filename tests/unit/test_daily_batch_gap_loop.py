"""일일 배치 루프: 가공이 보류된 날짜(종료코드 3)는 건너뛰고 다음 날짜로 계속한다(DEC-093)."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import date

import pytest

from scripts import run_daily_batch as rdb

D1, D2, D3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)


@pytest.fixture(autouse=True)
def _no_kis_step(monkeypatch):
    """기본은 증권사 일봉 캐시 단계를 끈다(개발 PC 환경변수가 시험에 새지 않게)."""
    monkeypatch.delenv("LOCAL_INTRADAY_ENABLED", raising=False)


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


# ── 증권사 일봉 캐시 부가 단계(DEC-097) ───────────────────────────────────────────────
def _kis_env(monkeypatch, *, key="k", secret="s", enabled="true"):
    for name, val in (
        ("KIS_APP_KEY", key),
        ("KIS_APP_SECRET", secret),
        ("LOCAL_INTRADAY_ENABLED", enabled),
    ):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)


def test_kis_step_runs_only_when_keys_and_flag_present(monkeypatch):
    ran = []
    monkeypatch.setattr(rdb, "_run", lambda args: ran.append(args) or 0)
    _kis_env(monkeypatch, enabled="false")
    rdb._run_kis_daily_bars()
    _kis_env(monkeypatch, key=None)
    rdb._run_kis_daily_bars()
    _kis_env(monkeypatch, secret="")
    rdb._run_kis_daily_bars()
    assert ran == []
    _kis_env(monkeypatch)
    rdb._run_kis_daily_bars()
    assert len(ran) == 1 and ran[0][1].endswith("collect_kis_daily_bars.py")


def test_kis_step_failure_does_not_change_exit_code(monkeypatch, capsys):
    _kis_env(monkeypatch)
    monkeypatch.setattr(rdb, "_run_one_date", lambda d: 3 if d == D1 else 0)
    monkeypatch.setattr(rdb, "_run", lambda args: 2)
    assert (
        rdb._run_with_catchup([D1, D2], D2) == 0
    )  # 보류된 날짜가 있어도 부가 단계 실행, 코드 불변
    assert "증권사 일봉 캐시 단계가 종료코드 2" in capsys.readouterr().err
    monkeypatch.setattr(rdb, "_run", lambda args: (_ for _ in ()).throw(OSError("x")))
    assert rdb._run_with_catchup([D1], D1) == 0


def test_kis_step_runs_on_up_to_date_path_and_not_after_real_failure(monkeypatch):
    _kis_env(monkeypatch)
    calls = []
    monkeypatch.setattr(rdb, "_run_kis_daily_bars", lambda: calls.append(1))
    assert rdb._run_with_catchup([], D1) == 0 and calls == [1]  # 이미 최신 → 캐시 정리 경로
    monkeypatch.setattr(rdb, "_run_one_date", lambda d: 1)
    assert rdb._run_with_catchup([D1, D2], D2) == 1 and calls == [1]  # 실패 종료에서는 실행 안 함
