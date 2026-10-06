"""`scripts/kis_daily_price_smoke_test.py` 시험 — 모의 서버·가짜 클라이언트만 쓴다(실제 증권사 접속 없음)."""

# ruff: noqa: E501
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import kis_daily_price_smoke_test as smoke  # noqa: E402

from services.public_api.intraday import config as cfg  # noqa: E402
from services.public_api.intraday.kis_client import KisError  # noqa: E402

ENV = {cfg.ENABLED_ENV: "true", cfg.APP_KEY_ENV: "SECRETKEY123", cfg.APP_SECRET_ENV: "SECRETVAL456"}
NOW = datetime(2026, 10, 7, 11, 0, tzinfo=smoke.KST)


class FakeClient:
    def __init__(self, rows_by_code=None, fail=()):
        self.rows_by_code, self.fail, self.calls = rows_by_code or {}, set(fail), []

    def daily_price(self, code):
        self.calls.append(code)
        if code in self.fail:
            raise KisError("UPSTREAM_ERROR", "거절")
        return {"output": self.rows_by_code.get(code, [])}


def row(d: str, close: int):
    return {"stck_bsop_date": d, "stck_oprc": str(close), "stck_hgpr": str(close), "stck_lwpr": str(close), "stck_clpr": str(close), "acml_vol": "10"}


def test_all_match_exit_0_and_marks_today_partial(capsys):
    client = FakeClient({"005930": [row("20261007", 100), row("20261006", 99), row("20261005", 98)]})
    pub = {"005930": {date(2026, 10, 6): Decimal(99), date(2026, 10, 5): Decimal(98)}}
    code, report = smoke.run(client, ["005930"], db_loader=lambda c: pub, now=NOW, sleep=lambda s: None)
    out = capsys.readouterr().out
    assert code == 0 and report["codes"]["005930"]["today_partial"] is True and report["codes"]["005930"]["same_close"] == 2
    assert "오늘 진행 봉 포함" in out and "비교 2/2" in out


def test_close_mismatch_is_exit_2(capsys):
    client = FakeClient({"005930": [row("20261006", 99)]})
    code, _ = smoke.run(client, ["005930"], db_loader=lambda c: {"005930": {date(2026, 10, 6): Decimal(50)}}, now=NOW, sleep=lambda s: None)
    assert code == 2 and "비교 0/1" in capsys.readouterr().out


def test_empty_response_and_missing_db_are_exit_2_and_all_fail_is_1():
    assert smoke.run(FakeClient({"005930": []}), ["005930"], db_loader=None, now=NOW, sleep=lambda s: None)[0] == 2
    assert smoke.run(FakeClient(fail={"005930", "000660"}), ["005930", "000660"], db_loader=None, now=NOW, sleep=lambda s: None)[0] == 1
    mixed = smoke.run(FakeClient({"000660": [row("20261006", 1)]}, fail={"005930"}), ["005930", "000660"], db_loader=None, now=NOW, sleep=lambda s: None)[0]
    assert mixed == 2


def test_db_error_does_not_leak_message_and_continues(capsys):
    def boom(codes):
        raise RuntimeError("postgresql://user:SECRETPASS@host/db")

    client = FakeClient({"005930": [row("20261006", 1)]})
    code, _ = smoke.run(client, ["005930"], db_loader=boom, now=NOW, sleep=lambda s: None)
    out = capsys.readouterr().out
    assert code == 2 and "SECRETPASS" not in out and "RuntimeError" in out


def test_missing_expected_field_flags_check_needed(capsys):
    bad = [{"stck_bsop_date": "20261006", "stck_clpr": "1", "acml_vol": "1"}]
    code, report = smoke.run(FakeClient({"005930": bad}), ["005930"], db_loader=None, now=NOW, sleep=lambda s: None)
    assert code == 2 and "stck_oprc" in report["fields_missing"] and "기대한 필드가 없습니다" in capsys.readouterr().out


def test_main_validates_args_masks_secrets_and_writes_report(tmp_path, capsys):
    client = FakeClient({"005930": [row("20261006", 99)]})
    out_file = tmp_path / "r.json"
    rc = smoke.main(["--code", "005930", "--no-db", "--out", str(out_file)], env=ENV, client_factory=lambda s: client)
    text = capsys.readouterr().out
    assert rc == 2 and json.loads(out_file.read_text(encoding="utf-8"))["codes"]["005930"]["usable"] == 1
    assert "SECRETKEY123" not in text and "SECRETVAL456" not in text
    assert smoke.main(["--code", "abc"], env=ENV, client_factory=lambda s: client) == 1
    assert smoke.main(["--code", "005930"] * 31, env=ENV, client_factory=lambda s: client) == 1
    assert smoke.main(["--no-db"], env={cfg.ENABLED_ENV: "true"}, client_factory=lambda s: client) == 1  # 앱키 없음
    assert smoke.main(["--bogus"], env=ENV) == 1
