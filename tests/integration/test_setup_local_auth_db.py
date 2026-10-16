"""setup_local_auth: 로컬 DB에 auth_service 계정·권한을 만들고 관리자 계정을 만든다(임시 PostgreSQL, 실제 SQL)."""

# ruff: noqa: E501
from __future__ import annotations

import io
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import manage_users as mu  # noqa: E402
from scripts import setup_local_auth as sla  # noqa: E402
from tests.integration.pg_temp_db import TempDb, temp_database  # noqa: E402


def test_계정_권한_준비_후_auth_service로_조회_갱신_가능_그리고_관리자_생성(monkeypatch):
    with temp_database() as tdb:
        # 이 시험 클러스터의 auth_service 비밀번호는 'x' — 같은 값으로 준비해 다른 시험에 영향을 주지 않는다.
        owner = TempDb.render(tdb.migrator_url)
        ok, msg = sla.provision_auth_db(owner, "x")
        assert ok, msg
        ok2, msg2 = sla.provision_auth_db(owner, "x")  # 여러 번 실행해도 안전
        assert ok2, msg2

        auth_url = TempDb.render(tdb.migrator_url.set(username="auth_service", password="x"))
        assert sla.check_auth_db(auth_url)[0]

        # 관리자 계정이 없으면 만든다(비밀번호는 표준입력 한 줄)
        monkeypatch.setattr(sys, "stdin", io.StringIO("LocalPassw0rd!\n"))
        ok3, msg3 = sla.ensure_admin(owner, "jcw1973", "tester", True)
        assert ok3 and "만들었습니다" in msg3, msg3
        ok4, msg4 = sla.ensure_admin(owner, "jcw1973", "tester", True)  # 이미 있으면 아무것도 안 한다
        assert ok4 and "이미 있습니다" in msg4

        # auth_service(API가 쓰는 계정)로 비밀번호 재설정이 된다 = reset_password.ps1 이 쓰는 경로
        eng = create_engine(auth_url)
        try:
            mu.set_password(eng, "jcw1973", "NewLocalPassw0rd!")
            assert mu.verify_stored_password(eng, "jcw1973", "NewLocalPassw0rd!") and not mu.verify_stored_password(eng, "jcw1973", "LocalPassw0rd!")
            with eng.connect() as c:
                assert c.execute(text("SELECT role FROM auth.app_users WHERE username='jcw1973'")).scalar() == "admin"
        finally:
            eng.dispose()


def test_auth_스키마가_없으면_안내하고_실패한다():
    with temp_database() as tdb:
        eng = create_engine(TempDb.render(tdb.migrator_url))
        try:
            with eng.begin() as c:
                c.execute(text("DROP SCHEMA auth CASCADE"))
        finally:
            eng.dispose()
        ok, msg = sla.provision_auth_db(TempDb.render(tdb.migrator_url), "x")
        assert not ok and "start_local_api" in msg
