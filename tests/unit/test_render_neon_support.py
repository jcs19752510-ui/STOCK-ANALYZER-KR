"""Render + Neon 베타 지원 기능 단위 테스트 (DEC-063).

- 시간 제한 환경변수(기본값 불변, 잘못된 값은 ConfigError)
- /api/v1/live (DB 미사용)
- 프록시 진단 미들웨어(처음 N건만 로그)
- run_public_api 기동 거부(REQUIRE_TRUSTED_PROXY)
- 배치 중복 실행 방지 락(가짜 연결 + 선택적 실제 PostgreSQL)
"""

from __future__ import annotations

import logging
import os
import runpy
import sys
from pathlib import Path

import pytest

os.environ.setdefault("PUBLIC_API_DATABASE_URL", "postgresql+psycopg://x:y@localhost/z")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from services.public_api.core import config  # noqa: E402
from services.public_api.middleware import PeerDiagnosticsMiddleware  # noqa: E402
from shared import batch_lock  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 시간 제한 설정
@pytest.mark.parametrize(
    ("fn", "default"),
    [
        (config.get_db_connect_timeout_seconds, 3),
        (config.get_db_statement_timeout_ms, 3000),
        (config.get_request_timeout_seconds, 4.5),
    ],
)
def test_timeout_defaults_unchanged(monkeypatch, fn, default):
    for name in (
        "PUBLIC_API_DB_CONNECT_TIMEOUT_SECONDS",
        "PUBLIC_API_DB_STATEMENT_TIMEOUT_MS",
        "PUBLIC_API_REQUEST_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    assert fn() == default


def test_timeout_env_override(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_DB_CONNECT_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("PUBLIC_API_DB_STATEMENT_TIMEOUT_MS", "8000")
    monkeypatch.setenv("PUBLIC_API_REQUEST_TIMEOUT_SECONDS", "12.5")
    assert config.get_db_connect_timeout_seconds() == 10
    assert config.get_db_statement_timeout_ms() == 8000
    assert config.get_request_timeout_seconds() == 12.5


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PUBLIC_API_DB_CONNECT_TIMEOUT_SECONDS", "abc"),
        ("PUBLIC_API_DB_CONNECT_TIMEOUT_SECONDS", "0"),
        ("PUBLIC_API_DB_CONNECT_TIMEOUT_SECONDS", "31"),
        ("PUBLIC_API_DB_STATEMENT_TIMEOUT_MS", "100"),
        ("PUBLIC_API_REQUEST_TIMEOUT_SECONDS", "-1"),
        ("PUBLIC_API_REQUEST_TIMEOUT_SECONDS", "999"),
    ],
)
def test_timeout_invalid_values_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    getter = {
        "PUBLIC_API_DB_CONNECT_TIMEOUT_SECONDS": config.get_db_connect_timeout_seconds,
        "PUBLIC_API_DB_STATEMENT_TIMEOUT_MS": config.get_db_statement_timeout_ms,
        "PUBLIC_API_REQUEST_TIMEOUT_SECONDS": config.get_request_timeout_seconds,
    }[name]
    with pytest.raises(config.ConfigError):
        getter()


def test_blank_env_uses_default(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_REQUEST_TIMEOUT_SECONDS", "  ")
    assert config.get_request_timeout_seconds() == 4.5


# ---------------------------------------------------------------- /api/v1/live
def test_live_endpoint_does_not_touch_db():
    # DB 의존성을 "호출되면 실패"로 바꿔 /live가 DB를 쓰지 않음을 증명한다.
    from services.public_api.db.session import get_db
    from services.public_api.main import app

    def boom():
        raise AssertionError("/live must not use the database")

    app.dependency_overrides[get_db] = boom
    try:
        r = TestClient(app).get("/api/v1/live")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 200
    assert r.json()["data"] == {"status": "ok"}


# ---------------------------------------------------------------- 프록시 진단
def test_peer_diagnostics_logs_only_first_n(caplog):
    PeerDiagnosticsMiddleware._logged = 0
    app = FastAPI()
    app.add_middleware(PeerDiagnosticsMiddleware)

    @app.get("/x")
    def x():
        return {"ok": True}

    @app.get("/api/v1/live")
    def live():
        return {"ok": True}

    client = TestClient(app)
    with caplog.at_level(logging.WARNING):
        for _ in range(PeerDiagnosticsMiddleware.MAX_LOGGED + 5):
            assert client.get("/x", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 200
        client.get("/api/v1/live")
    msgs = [r.getMessage() for r in caplog.records if "PEER-DIAG" in r.getMessage()]
    assert len(msgs) == PeerDiagnosticsMiddleware.MAX_LOGGED
    assert "x-forwarded-for='1.2.3.4'" in msgs[0]
    assert all("/api/v1/live" not in m for m in msgs)  # 헬스체크는 기록하지 않음
    PeerDiagnosticsMiddleware._logged = 0


# ---------------------------------------------------------------- 기동 거부
def _run_public_api(monkeypatch, env: dict[str, str]):
    for k in ("PUBLIC_API_TRUSTED_PROXY_IPS", "PUBLIC_API_REQUIRE_TRUSTED_PROXY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    started = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: started.update(kw))
    monkeypatch.setattr(sys, "argv", ["run_public_api.py"])
    try:
        runpy.run_path(str(REPO / "scripts" / "run_public_api.py"), run_name="__main__")
    except SystemExit as exc:
        return exc.code, started
    return None, started


def test_require_trusted_proxy_blocks_startup_when_empty(monkeypatch, capsys):
    code, started = _run_public_api(monkeypatch, {"PUBLIC_API_REQUIRE_TRUSTED_PROXY": "true"})
    assert code == 1
    assert started == {}
    assert "기동 거부" in capsys.readouterr().err


def test_require_trusted_proxy_allows_when_set(monkeypatch):
    code, started = _run_public_api(
        monkeypatch,
        {
            "PUBLIC_API_REQUIRE_TRUSTED_PROXY": "true",
            "PUBLIC_API_TRUSTED_PROXY_IPS": "10.0.0.0/8",
        },
    )
    assert code in (None, 0)
    assert started.get("proxy_headers") is True


def test_default_startup_unchanged_without_flags(monkeypatch):
    code, started = _run_public_api(monkeypatch, {})
    assert code in (None, 0)
    assert started.get("proxy_headers") is False


# ---------------------------------------------------------------- 배치 락 (가짜 연결)
class _FakeResult:
    def __init__(self, value):
        self._v = value

    def scalar(self):
        return self._v


class _FakeConn:
    def __init__(self, got: bool):
        self.got = got
        self.calls: list[str] = []
        self.closed = False

    def execution_options(self, **_):
        return self

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        return _FakeResult(self.got if "try_advisory" in sql else True)

    def close(self):
        self.closed = True


def _patch_engine(monkeypatch, conn: _FakeConn):
    import sqlalchemy

    class _Engine:
        def connect(self):
            return conn

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: _Engine())


def test_lock_acquired_then_unlocked(monkeypatch):
    conn = _FakeConn(got=True)
    _patch_engine(monkeypatch, conn)
    with batch_lock.daily_batch_lock("postgresql://x") as st:
        assert st is batch_lock.LockState.ACQUIRED
    assert any("pg_advisory_unlock" in c for c in conn.calls)
    assert conn.closed


def test_lock_held_by_other(monkeypatch):
    conn = _FakeConn(got=False)
    _patch_engine(monkeypatch, conn)
    with batch_lock.daily_batch_lock("postgresql://x") as st:
        assert st is batch_lock.LockState.HELD
    assert not any("pg_advisory_unlock" in c for c in conn.calls)
    assert conn.closed


def test_lock_unavailable_when_no_url():
    with batch_lock.daily_batch_lock(None) as st:
        assert st is batch_lock.LockState.UNAVAILABLE


def test_lock_unavailable_on_connection_error(monkeypatch, capsys):
    import sqlalchemy

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(sqlalchemy, "create_engine", boom)
    with batch_lock.daily_batch_lock("postgresql://x") as st:
        assert st is batch_lock.LockState.UNAVAILABLE
    assert "계속 진행" in capsys.readouterr().err


def _load_batch_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_daily_batch", REPO / "scripts/run_daily_batch.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_main_skips_when_lock_held(monkeypatch, capsys):
    mod = _load_batch_module()
    called = []
    monkeypatch.setattr(mod, "_main_locked", lambda argv: called.append(argv) or 0)
    _patch_engine(monkeypatch, _FakeConn(got=False))
    monkeypatch.setenv("BATCH_DATABASE_URL", "postgresql://x")
    assert mod.main([]) == 0
    assert called == []
    assert "건너뜁니다" in capsys.readouterr().out


def test_main_runs_when_lock_acquired_or_unavailable(monkeypatch):
    mod = _load_batch_module()
    monkeypatch.setattr(mod, "_main_locked", lambda argv: 7)
    _patch_engine(monkeypatch, _FakeConn(got=True))
    monkeypatch.setenv("BATCH_DATABASE_URL", "postgresql://x")
    assert mod.main([]) == 7
    monkeypatch.delenv("BATCH_DATABASE_URL")
    assert mod.main([]) == 7  # URL 없음 → 락 없이 진행


def test_main_dry_run_and_no_lock_bypass_lock(monkeypatch):
    mod = _load_batch_module()
    monkeypatch.setattr(mod, "_main_locked", lambda argv: 5)
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: pytest.fail("no lock"))
    monkeypatch.setenv("BATCH_DATABASE_URL", "postgresql://x")
    assert mod.main(["--dry-run"]) == 5
    assert mod.main(["--no-lock"]) == 5


# ---------------------------------------------------------------- 실제 PostgreSQL (선택)
@pytest.mark.skipif(
    not os.environ.get("BATCH_LOCK_TEST_DB_URL"), reason="BATCH_LOCK_TEST_DB_URL 미설정"
)
def test_real_postgres_mutual_exclusion():
    url = os.environ["BATCH_LOCK_TEST_DB_URL"]
    with batch_lock.daily_batch_lock(url) as first:
        assert first is batch_lock.LockState.ACQUIRED
        with batch_lock.daily_batch_lock(url) as second:
            assert second is batch_lock.LockState.HELD
    with batch_lock.daily_batch_lock(url) as third:  # 해제 후 다시 잡을 수 있다
        assert third is batch_lock.LockState.ACQUIRED
