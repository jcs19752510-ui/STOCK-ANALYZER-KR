"""scripts/setup_local_auth.py — 로컬 서버 로그인 켜기/끄기 설정 파일 갱신 (DEC-075)."""

# ruff: noqa: E501
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import setup_local_auth as sla  # noqa: E402

OWNER_URL = "postgresql://migrator:pw%21x@localhost:5432/stock_screener"


def _run(tmp_path: Path, *extra: str, monkeypatch: pytest.MonkeyPatch, owner: str | None = None) -> int:
    """`owner`가 있으면 환경변수로 로컬 DB 소유자 주소를 준다(없으면 .env 의 값을 쓴다). DB 준비·관리자 만들기는 건너뛴다(--no-db)."""
    monkeypatch.delenv(sla.OWNER_KEY, raising=False)
    monkeypatch.delenv(sla.AUTH_DB_KEY, raising=False)
    if owner is not None:
        monkeypatch.setenv(sla.OWNER_KEY, owner)
    return sla.main(["--root", str(tmp_path), "--no-db", *extra])


def _read(path: Path) -> dict[str, str]:
    return sla.parse_env(path.read_text(encoding="utf-8"))


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "frontend").mkdir()
    # 윈도우(CRLF + BOM) 기존 파일, 로컬 전용 설정과 주석이 들어 있다.
    (tmp_path / ".env").write_bytes(
        "﻿# 로컬 DB\r\nPUBLIC_API_DATABASE_URL=postgresql+psycopg://api_service:x@localhost:5432/stock_screener\r\nALEMBIC_DATABASE_URL=postgresql+psycopg://migrator:pw%21x@localhost:5432/stock_screener\r\nLOCAL_INTRADAY_ENABLED=true\r\nKIS_APP_KEY=abc\r\n".encode()
    )
    (tmp_path / "frontend" / ".env.local").write_text(
        "NEXT_PUBLIC_API_BASE_URL=http://localhost:4001\nNEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true\n", encoding="utf-8"
    )
    return tmp_path


def test_켜기_필요한_값을_넣고_기존_로컬_설정은_그대로(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(repo, monkeypatch=monkeypatch) == 0
    api, web = _read(repo / ".env"), _read(repo / "frontend" / ".env.local")
    # API 쪽
    assert api[sla.AUTH_DB_KEY].startswith("postgresql+psycopg://auth_service:")
    assert api[sla.REQUIRE_KEY] == "true"
    assert len(api[sla.TOKEN_KEY]) >= 32
    # 기존 로컬 값은 보존
    assert api["PUBLIC_API_DATABASE_URL"].endswith("/stock_screener")
    assert api["LOCAL_INTRADAY_ENABLED"] == "true" and api["KIS_APP_KEY"] == "abc"
    assert "# 로컬 DB" in (repo / ".env").read_text(encoding="utf-8")
    # 웹 쪽: API와 같은 토큰, 로그인 켬, 같은 오리진 호출, http 쿠키
    assert web[sla.TOKEN_KEY] == api[sla.TOKEN_KEY]
    assert web["AUTH_REQUIRED"] == "true" and web["NEXT_PUBLIC_AUTH_ENABLED"] == "true"
    assert web["NEXT_PUBLIC_BROWSER_API_BASE_URL"] == "same-origin"
    assert web["AUTH_COOKIE_INSECURE"] == "true"
    assert len(web[sla.SECRET_KEY]) >= 32 and web[sla.SECRET_KEY] != web[sla.TOKEN_KEY]
    assert web["NEXT_PUBLIC_API_BASE_URL"] == "http://localhost:4001"
    assert web["NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED"] == "true"  # 로컬 전용 기능 스위치 보존


def test_윈도우_줄바꿈과_BOM_처리(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(repo, monkeypatch=monkeypatch) == 0
    raw = (repo / ".env").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # BOM 제거
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")  # 기존 CRLF 유지
    assert sla.parse_env(raw.decode("utf-8"))["PUBLIC_API_DATABASE_URL"]  # 첫 줄 BOM 때문에 키가 깨지지 않음


def test_다시_실행해도_값이_바뀌지_않는다(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(repo, monkeypatch=monkeypatch)
    first = (_read(repo / ".env"), _read(repo / "frontend" / ".env.local"))
    assert _run(repo, monkeypatch=monkeypatch) == 0  # 주소는 .env에서 다시 읽는다
    assert first == (_read(repo / ".env"), _read(repo / "frontend" / ".env.local"))
    assert len(list(repo.glob(".env.bak-*"))) >= 1  # 바꾸기 전 파일 보관


def test_파일이_없어도_새로_만든다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(tmp_path, monkeypatch=monkeypatch, owner=OWNER_URL) == 0
    assert _read(tmp_path / ".env")[sla.REQUIRE_KEY] == "true"
    assert _read(tmp_path / "frontend" / ".env.local")["AUTH_REQUIRED"] == "true"


def test_끄기는_로그인_설정만_걷어내고_나머지는_보존(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(repo, monkeypatch=monkeypatch)
    assert sla.main(["--root", str(repo), "--off"]) == 0
    api, web = _read(repo / ".env"), _read(repo / "frontend" / ".env.local")
    assert api[sla.REQUIRE_KEY] == "false"
    for key in ("AUTH_REQUIRED", "NEXT_PUBLIC_AUTH_ENABLED", "NEXT_PUBLIC_BROWSER_API_BASE_URL", "AUTH_COOKIE_INSECURE"):
        assert key not in web
    assert web["NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED"] == "true" and web["NEXT_PUBLIC_API_BASE_URL"] == "http://localhost:4001"
    assert api["LOCAL_INTRADAY_ENABLED"] == "true"


def test_끈_뒤_다시_켜면_같은_토큰을_재사용(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(repo, monkeypatch=monkeypatch)
    token = _read(repo / ".env")[sla.TOKEN_KEY]
    sla.main(["--root", str(repo), "--off"])
    assert _run(repo, monkeypatch=monkeypatch) == 0
    assert _read(repo / ".env")[sla.TOKEN_KEY] == token


@pytest.mark.parametrize("raw,expected", [
    ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
    ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ('"postgresql+psycopg://u:p@h/db"', "postgresql+psycopg://u:p@h/db"),
])
def test_주소_형식_정규화(raw: str, expected: str) -> None:
    assert sla.normalize_db_url(raw) == expected


def test_잘못된_주소는_거부하고_파일을_건드리지_않는다(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = (repo / ".env").read_bytes()
    assert _run(repo, monkeypatch=monkeypatch, owner="mysql://x") == 2
    assert (repo / ".env").read_bytes() == before
    assert not (repo / "frontend" / ".env.local").read_text(encoding="utf-8").count("AUTH_REQUIRED")


def test_화면_출력에_비밀값이_없다(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _run(repo, monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    api = _read(repo / ".env")
    assert api[sla.TOKEN_KEY] not in out and "pw%21x" not in out and "pw!x" not in out and api[sla.AUTH_DB_KEY] not in out and _read(repo / "frontend" / ".env.local")[sla.SECRET_KEY] not in out


def test_로컬이_아닌_DB_주소는_거부하고_파일을_건드리지_않는다(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = (repo / ".env").read_bytes()
    assert _run(repo, monkeypatch=monkeypatch, owner="postgresql://o:p@ep-abc.example.com:5432/db") == 2
    assert (repo / ".env").read_bytes() == before


def test_원격_AUTH_ADMIN_주소는_지우고_로컬_것은_둔다(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = repo / ".env"
    env.write_text(env.read_text(encoding="utf-8").replace("\r\n", "\n") + "AUTH_ADMIN_DATABASE_URL=postgresql+psycopg://o:p@ep-abc.example.com:5432/db\n", encoding="utf-8")
    assert _run(repo, monkeypatch=monkeypatch) == 0
    assert sla.ADMIN_URL_KEY not in _read(env)
    env.write_text(env.read_text(encoding="utf-8") + "AUTH_ADMIN_DATABASE_URL=postgresql+psycopg://o:p@localhost:5432/db\n", encoding="utf-8")
    assert _run(repo, monkeypatch=monkeypatch) == 0
    assert _read(env)[sla.ADMIN_URL_KEY].endswith("@localhost:5432/db")


def test_예전_로컬_회원_DB_비밀번호는_재사용(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(repo, monkeypatch=monkeypatch)
    url = _read(repo / ".env")[sla.AUTH_DB_KEY]
    assert url.startswith("postgresql+psycopg://auth_service:") and "@localhost:5432/stock_screener" in url
    assert _run(repo, monkeypatch=monkeypatch) == 0 and _read(repo / ".env")[sla.AUTH_DB_KEY] == url


def test_예전_원격_회원_DB_주소는_새_로컬_주소로_바뀐다(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = repo / ".env"
    env.write_text(env.read_text(encoding="utf-8").replace("\r\n", "\n") + "PUBLIC_API_AUTH_DATABASE_URL=postgresql+psycopg://auth_service:old@ep-abc.example.com:5432/remotedb\n", encoding="utf-8")
    assert _run(repo, monkeypatch=monkeypatch) == 0
    url = _read(env)[sla.AUTH_DB_KEY]
    assert "ep-abc" not in url and "@localhost:5432/stock_screener" in url and ":old@" not in url


def test_GRANT_문은_SQL_파일에서_12개를_뽑고_psql_전용_줄은_제외한다() -> None:
    stmts = sla.grant_statements()
    assert len(stmts) == 12 and all(s.upper().startswith("GRANT") and s.endswith(";") for s in stmts)
    assert not any("gexec" in s or "format(" in s for s in stmts)
    assert any("UPDATE (password_hash" in s for s in stmts) and any("auth.user_sessions" in s for s in stmts)
