# ruff: noqa: E501
"""소유자 전용 투자자 수급(DEC-068) 실제 PostgreSQL 통합 시험: 수집 적재·권한·API 접근 통제."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scripts import collect_investor_flow as cif
from services.public_api.intraday.normalize import normalize_investor_rows
from tests.integration.pattern_api_env import api_client, prepare_database
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

TOKEN = "t" * 48


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _row(d, p=1, f=2, i=3, pa=10, fa=20, ia=30):
    return {
        "stck_bsop_date": d,
        "prsn_ntby_qty": str(p), "frgn_ntby_qty": str(f), "orgn_ntby_qty": str(i),
        "prsn_ntby_tr_pbmn": str(pa), "frgn_ntby_tr_pbmn": str(fa), "orgn_ntby_tr_pbmn": str(ia),
    }


def _upsert(db, code, rows, now=datetime(2026, 10, 5, 21, 0), include_today=False):
    days = cif.usable_days(normalize_investor_rows(rows), now, include_today)
    eng = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(eng) as s:
            n = cif.upsert_days(s, code, days)
            s.commit()
        return n
    finally:
        eng.dispose()


def _stock_code(db) -> str:
    eng = create_engine(TempDb.render(db.migrator_url))
    try:
        with eng.connect() as c:
            return c.execute(text("SELECT stock_code FROM public_serving.stock_master LIMIT 1")).scalar_one()
    finally:
        eng.dispose()


def _env(monkeypatch, owner="owner"):
    monkeypatch.setenv("PUBLIC_API_INTERNAL_TOKEN", TOKEN)
    if owner is None:
        monkeypatch.delenv("PUBLIC_API_OWNER_USERNAME", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_API_OWNER_USERNAME", owner)


def _hdr(username="owner", token=TOKEN):
    h = {}
    if token:
        h["X-Internal-Token"] = token
    if username:
        h["X-Auth-Username"] = username
    return h


def test_collector_filters_today_before_confirmation_and_is_idempotent(db):
    code = _stock_code(db)
    rows = [_row("20261005", p=5), _row("20261002", p=-7), _row("20261001", p=9)]
    # 20:00 이전: 당일(10/05) 제외
    assert _upsert(db, code, rows, now=datetime(2026, 10, 5, 15, 0)) == 2
    # 20:00 이후: 당일 포함, 같은 날짜는 덮어쓰기(중복 없음)
    assert _upsert(db, code, rows, now=datetime(2026, 10, 5, 21, 0)) == 3
    assert _upsert(db, code, rows, now=datetime(2026, 10, 5, 21, 0)) == 3
    eng = create_engine(TempDb.render(db.migrator_url))
    try:
        with eng.connect() as c:
            n = c.execute(text("SELECT count(*) FROM public_serving.investor_flow_daily WHERE stock_code=:c"), {"c": code}).scalar_one()
    finally:
        eng.dispose()
    assert n == 3


def test_collector_handles_missing_values_and_future_dates(db):
    code = _stock_code(db)
    blank = {"stck_bsop_date": "20261001"}  # 값이 모두 없는 행은 버려진다
    future = _row("20261231")
    assert _upsert(db, code, [blank, future], now=datetime(2026, 10, 5, 21, 0)) == 0
    partial = _row("20260930")
    partial["frgn_ntby_qty"] = ""  # 일부 결측은 NULL(0 아님)
    assert _upsert(db, code, [partial]) == 1


def test_api_service_is_select_only(db):
    api = create_engine(TempDb.render(db.api_url))
    try:
        with api.connect() as c:
            assert c.execute(text("SELECT count(*) FROM public_serving.investor_flow_daily")).scalar_one() >= 0
        for sql in (
            "INSERT INTO public_serving.investor_flow_daily(stock_code,trade_date) VALUES ('Z00001','2026-01-01')",
            "DELETE FROM public_serving.investor_flow_daily",
        ):
            with api.connect() as c, pytest.raises(DBAPIError, match="permission denied"):
                c.execute(text(sql))
    finally:
        api.dispose()


def test_owner_gets_rows_newest_first_with_null_kept(db, monkeypatch):
    code = _stock_code(db)
    _env(monkeypatch)
    with api_client(db) as c:
        r = c.get(f"/api/v1/internal/owner/stocks/{code}/investor", headers=_hdr())
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    rows = r.json()["data"]["rows"]
    dates = [x["date"] for x in rows]
    assert dates == sorted(dates, reverse=True) and len(rows) >= 3
    partial = next(x for x in rows if x["date"] == "2026-09-30")
    assert partial["foreign_quantity"] is None and partial["personal_quantity"] == 1


def test_non_owner_missing_token_and_disabled_are_blocked(db, monkeypatch):
    code = _stock_code(db)
    path = f"/api/v1/internal/owner/stocks/{code}/investor"
    _env(monkeypatch)
    with api_client(db) as c:
        assert c.get(path, headers=_hdr(username="kim")).status_code == 403  # 다른 회원
        assert c.get(path, headers=_hdr(username=None)).status_code == 403  # 아이디 없음
        assert c.get(path, headers=_hdr(token=None)).status_code == 401  # 토큰 없음
        assert c.get(path, headers=_hdr(token="x" * 48)).status_code == 401  # 틀린 토큰
        assert c.get(path).status_code == 401  # 헤더 전혀 없음
        assert c.get(path, headers=_hdr(username="OWNER ")).status_code == 200  # 대소문자·공백 정규화
        assert c.get(path, headers=_hdr(username="owner2")).status_code == 403  # 접두 일치 불가
    _env(monkeypatch, owner=None)
    with api_client(db) as c:
        r = c.get(path, headers=_hdr())
    assert r.status_code == 404 and r.json()["error"]["code"] == "FEATURE_DISABLED"


def test_owner_endpoint_input_validation(db, monkeypatch):
    _env(monkeypatch)
    with api_client(db) as c:
        assert c.get("/api/v1/internal/owner/stocks/ZZZZZZ/investor", headers=_hdr()).status_code == 404
        assert c.get("/api/v1/internal/owner/stocks/12;DROP/investor", headers=_hdr()).status_code == 404


def test_public_stock_endpoints_never_expose_investor_data(db, monkeypatch):
    code = _stock_code(db)
    _env(monkeypatch)
    with api_client(db) as c:
        for p in (f"/api/v1/stocks/{code}/metrics", f"/api/v1/stocks/{code}/prices"):
            body = c.get(p).text
            assert "personal_quantity" not in body and "institution" not in body


def test_collector_dry_run_and_missing_config(monkeypatch, capsys):
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    monkeypatch.setenv("BATCH_DATABASE_URL", "postgresql+psycopg://u:SecretPw@127.0.0.1:1/x")
    assert cif.main(["--dry-run"]) == 1
    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    assert cif.main(["--dry-run"]) == 0
    monkeypatch.delenv("BATCH_DATABASE_URL")
    assert cif.main(["--dry-run"]) == 1
    out = capsys.readouterr()
    assert "SecretPw" not in out.out + out.err


def test_collector_db_failure_does_not_leak_connection_string(monkeypatch, capsys):
    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.setenv("BATCH_DATABASE_URL", "postgresql+psycopg://u:SecretPw@127.0.0.1:1/x?connect_timeout=1")


    class FakeKis:
        def __init__(self, *_a, **_k): ...
        def investor(self, _code):
            return {"output": [_row("20260930")]}

    monkeypatch.setattr(cif, "KisClient", FakeKis)
    assert cif.main(["--codes", "005930"]) == 1
    out = capsys.readouterr()
    assert "SecretPw" not in out.out + out.err


def test_collector_aborts_after_consecutive_kis_errors(monkeypatch, capsys):
    from services.public_api.intraday.kis_client import KisError

    calls = []

    class DownKis:
        def __init__(self, *_a, **_k): ...
        def investor(self, code):
            calls.append(code)
            raise KisError("UPSTREAM_UNAVAILABLE", "x")

    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.setenv("BATCH_DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x?connect_timeout=1")
    monkeypatch.setattr(cif, "KisClient", DownKis)
    codes = ",".join(f"{n:06d}" for n in range(100))
    assert cif.main(["--codes", codes]) == 1
    assert len(calls) == cif.MAX_CONSECUTIVE_ERRORS
    assert "연속" in capsys.readouterr().err


def test_dotenv_loader_reads_only_kis_keys_and_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nBATCH_DATABASE_URL=postgresql+psycopg://x:y@localhost:5432/local\n"
        "KIS_APP_KEY=\"key-from-file\"\nKIS_APP_SECRET='secret-from-file'\nOTHER=1\nbroken line\n",
        encoding="utf-8",
    )
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "BATCH_DATABASE_URL", "OTHER"):
        monkeypatch.delenv(k, raising=False)
    assert cif.load_kis_keys_from_dotenv(env) == ["KIS_APP_KEY", "KIS_APP_SECRET"]
    assert os.environ["KIS_APP_KEY"] == "key-from-file" and os.environ["KIS_APP_SECRET"] == "secret-from-file"
    assert "BATCH_DATABASE_URL" not in os.environ and "OTHER" not in os.environ  # 로컬 DB 주소 등은 읽지 않는다
    monkeypatch.setenv("KIS_APP_KEY", "already-set")
    assert cif.load_kis_keys_from_dotenv(env) == []  # 이미 설정된 값은 덮어쓰지 않는다
    assert os.environ["KIS_APP_KEY"] == "already-set"
    assert cif.load_kis_keys_from_dotenv(tmp_path / "missing.env") == []


def test_two_owners_via_comma_list_and_everyone_else_blocked(db, monkeypatch):
    code = _stock_code(db)
    path = f"/api/v1/internal/owner/stocks/{code}/investor"
    _env(monkeypatch, owner=" JCS1973 , jcs1975 ,, ")
    with api_client(db) as c:
        assert c.get(path, headers=_hdr(username="jcs1973")).status_code == 200
        assert c.get(path, headers=_hdr(username="jcs1975")).status_code == 200
        assert c.get(path, headers=_hdr(username="Jcs1975 ")).status_code == 200
        for no in ("jcs1974", "jcs19731975", "jcs197", "jcs1973,jcs1975", ","):
            assert c.get(path, headers=_hdr(username=no)).status_code == 403, no
    _env(monkeypatch, owner=" , ,")  # 빈 항목뿐이면 기능이 꺼진 것으로 본다(아무도 허용하지 않음)
    with api_client(db) as c:
        assert c.get(path, headers=_hdr(username="jcs1973")).status_code == 404
