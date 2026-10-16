"""manage_users의 DB 오류 상세(원인 첫 줄)는 보여 주되 접속 문자열·비밀번호는 지운다."""

# ruff: noqa: E501
from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

_spec = importlib.util.spec_from_file_location("manage_users_mod", Path(__file__).resolve().parents[2] / "scripts" / "manage_users.py")
mu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mu)


def test_detail_shows_reason_and_hides_password_and_url():
    eng = create_engine("postgresql+psycopg://dbowner:S3cretPw!@db.example.com:5432/appdb")
    orig = Exception('connection to server at "db.example.com" (1.2.3.4), port 5432 failed: FATAL: password authentication failed for user "dbowner" S3cretPw!\nsecond line')
    exc = OperationalError("SELECT 1", {}, orig)
    d = mu._safe_detail(exc, eng)
    assert "password authentication failed" in d and "S3cretPw" not in d and "second line" not in d


def test_detail_redacts_embedded_url_and_survives_missing_engine():
    exc = OperationalError("x", {}, Exception("could not connect postgresql://u:pw123@host/db refused"))
    d = mu._safe_detail(exc, None)
    assert "pw123" not in d and "://***@" in d
    assert mu._safe_detail(RuntimeError(""), None) == ""
