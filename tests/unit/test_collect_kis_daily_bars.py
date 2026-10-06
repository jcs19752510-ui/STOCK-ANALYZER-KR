# ruff: noqa: E501
"""증권사 일봉 캐시 수집 스크립트(DEC-097): 순수 함수·재시도·종료코드 단위 시험(가짜 클라이언트만 사용)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from scripts import collect_kis_daily_bars as ckb
from services.public_api.intraday.kis_client import KisError

P, D1, D2 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)


def _row(day: date, close: int = 100) -> dict:
    # 일자별 시세 응답 행(normalize_daily_price가 읽는 키)
    f = ckb.normalize_daily_price.__globals__["DAILY_PRICE_FIELDS"]
    return {
        f["date"]: day.strftime("%Y%m%d"),
        f["open"]: str(close),
        f["high"]: str(close + 1),
        f["low"]: str(close - 1),
        f["close"]: str(close),
        f["volume"]: "1000",
    }


class FakeClient:
    def __init__(self, bodies=None, fail_times=0, exc=None):
        self.bodies = bodies or {}
        self.fail_times = fail_times
        self.exc = exc or RuntimeError("boom")
        self.calls = []

    def daily_price(self, code):
        self.calls.append(code)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.exc
        return self.bodies.get(code, {"output": []})


class FakeCalendar:
    def __init__(self, trading):
        self.trading = set(trading)

    def get(self, day, market):
        return SimpleNamespace(is_trading_day=day in self.trading)


def test_trading_days_between_excludes_start_and_non_trading_days():
    cal = FakeCalendar([P, D1, D2])
    assert ckb.trading_days_between(cal, P, D2) == [D1, D2]  # 10/3~10/4 주말은 거래일 아님
    assert ckb.trading_days_between(cal, D2, D2) == []


def test_pending_codes_skips_fully_cached_only():
    required = [P, D1, D2]
    cache = {"A": {P, D1, D2}, "B": {P, D1}, "C": set()}
    assert ckb.pending_codes(["A", "B", "C", "D"], cache, required) == ["B", "C", "D"]


def test_fetch_bars_filters_range_and_normalizes():
    body = {
        "output": [
            _row(date(2026, 9, 30)),
            _row(P),
            _row(D1),
            _row(D2),
            _row(date(2026, 10, 6)),
            "junk",
        ]
    }
    bars = ckb.fetch_bars(FakeClient({"X": body}), "X", P, D2, sleep=lambda s: None)
    assert [b.trade_date for b in bars] == [P, D1, D2]


def test_fetch_bars_retries_twice_then_succeeds():
    client = FakeClient({"X": {"output": [_row(P)]}}, fail_times=2)
    sleeps: list[float] = []
    bars = ckb.fetch_bars(client, "X", P, D2, sleep=sleeps.append)
    assert len(client.calls) == 3 and len(sleeps) == 2 and len(bars) == 1


def test_fetch_bars_gives_up_after_two_retries():
    client = FakeClient(fail_times=99, exc=KisError("RATE", "x"))
    with pytest.raises(KisError):
        ckb.fetch_bars(client, "X", P, D2, sleep=lambda s: None)
    assert len(client.calls) == 3


def test_fetch_bars_not_configured_is_not_retried():
    client = FakeClient(fail_times=99, exc=KisError("NOT_CONFIGURED", "x"))
    with pytest.raises(KisError):
        ckb.fetch_bars(client, "X", P, D2, sleep=lambda s: None)
    assert len(client.calls) == 1


def test_main_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("BATCH_DATABASE_URL", raising=False)
    monkeypatch.setattr(ckb, "load_kis_keys_from_dotenv", lambda p: [])
    assert ckb.main([]) == 1
    assert "BATCH_DATABASE_URL" in capsys.readouterr().err
