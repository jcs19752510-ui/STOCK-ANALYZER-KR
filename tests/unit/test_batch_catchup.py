"""일일 배치 따라잡기·신선도 점검(DEC-047, R5) 단위 테스트(DB·외부 호출 없음)."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from shared.batch_catchup import plan_catchup

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D = date
TRADING = [D(2026, 9, 28), D(2026, 9, 29), D(2026, 9, 30), D(2026, 10, 1), D(2026, 10, 2)]


def test_plan_returns_missing_dates_oldest_first():
    done = [D(2026, 9, 28), D(2026, 10, 1)]
    assert plan_catchup(TRADING, done, target=D(2026, 10, 2)) == [
        D(2026, 9, 29),
        D(2026, 9, 30),
        D(2026, 10, 2),
    ]


def test_plan_empty_when_up_to_date():
    assert plan_catchup(TRADING, TRADING, target=D(2026, 10, 2)) == []


def test_plan_limits_to_recent_n_trading_days_and_ignores_future():
    out = plan_catchup(TRADING, [], target=D(2026, 10, 1), max_days=2)
    assert out == [D(2026, 9, 30), D(2026, 10, 1)]


def test_plan_ignores_holidays_not_in_trading_list():
    # 주말·휴장일은 trading_dates에 없으므로 대상이 되지 않는다.
    trading = [D(2026, 9, 25), D(2026, 9, 28)]
    assert plan_catchup(trading, [D(2026, 9, 25)], target=D(2026, 9, 28)) == [D(2026, 9, 28)]


def test_freshness_lag_counts_trading_days():
    mod = _load("check_data_freshness")
    assert mod.lag_in_trading_days(TRADING, D(2026, 10, 2), D(2026, 10, 2)) == 0
    assert mod.lag_in_trading_days(TRADING, D(2026, 10, 1), D(2026, 10, 2)) == 1
    assert mod.lag_in_trading_days(TRADING, D(2026, 9, 28), D(2026, 10, 2)) == 4
    assert "지연" in mod.build_message(None, D(2026, 10, 2), None)


@pytest.fixture
def batch():
    return _load("run_daily_batch")


def test_catchup_runs_oldest_first_and_stops_on_blocking_failure(batch, monkeypatch):
    calls: list[str] = []

    def fake_run(args):
        calls.append(" ".join(args[-2:]))
        # 09-30 수집이 실패하면(과거 날짜) 그 뒤 날짜로 넘어가지 않고 그 코드로 종료
        return 1 if args[-1] == "2026-09-30" and "run_ingestion" in " ".join(args) else 0

    monkeypatch.setattr(batch, "_run", fake_run)
    rc = batch._run_with_catchup([D(2026, 9, 29), D(2026, 9, 30), D(2026, 10, 1)], D(2026, 10, 1))
    assert rc == 1
    assert calls == [
        "--trade-date 2026-09-29",
        "--trade-date 2026-09-29",
        "--trade-date 2026-09-30",
    ]


def test_target_not_published_yet_returns_retry_code(batch, monkeypatch):
    monkeypatch.setattr(batch, "_run", lambda args: 1 if "run_ingestion" in " ".join(args) else 0)
    assert batch._run_with_catchup([D(2026, 10, 1)], D(2026, 10, 1)) == batch.EXIT_NOT_PUBLISHED


def test_nothing_pending_makes_no_calls(batch, monkeypatch):
    monkeypatch.setattr(batch, "_run", lambda args: pytest.fail("호출되면 안 됨"))
    assert batch._run_with_catchup([], D(2026, 10, 1)) == 0


def test_all_success_runs_ingest_then_derive_per_date(batch, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(batch, "_run", lambda args: seen.append(args[2]) or 0)
    assert batch._run_with_catchup([D(2026, 9, 30), D(2026, 10, 1)], D(2026, 10, 1)) == 0
    assert seen == [
        "services.ingestion_batch.run_ingestion",
        "services.derivation_batch.run_derivation",
        "services.ingestion_batch.run_ingestion",
        "services.derivation_batch.run_derivation",
    ]
