#!/usr/bin/env python
"""회원 관리 스크립트 (DEC-067). 회원 가입 화면이 없으므로 회원은 **이 스크립트로만** 추가·변경한다. PC에서 실행한다.

사용법 (프로젝트 루트):
    python scripts/manage_users.py add <아이디> --name "표시 이름"      # 비밀번호는 숨김 입력(두 번)
    python scripts/manage_users.py set-password <아이디>
    python scripts/manage_users.py disable <아이디>  /  enable <아이디>  /  unlock <아이디>
    python scripts/manage_users.py delete <아이디>                      # 확인을 위해 아이디를 다시 입력
    python scripts/manage_users.py list
    python scripts/manage_users.py audit [--limit 20]                   # 최근 로그인 기록
    python scripts/manage_users.py check                                # 계정 권한 점검(운영 반영 전후 확인)

연결: 환경변수 `AUTH_ADMIN_DATABASE_URL`(없으면 `ALEMBIC_DATABASE_URL`). 이 연결은 `auth` 스키마를 쓸 수 있는 소유자/마이그레이터 계정이어야 하며
`api_service`·`batch_worker` 주소는 쓰지 않는다. 운영(Neon)을 바꿀 때는 소유자 직접 접속 주소(풀러 제외)를 이 변수에 넣는다.

비밀번호는 명령줄 인자로 받지 않는다(셸 기록·프로세스 목록에 남는 것을 막기 위해). 자동화·시험용으로 `--password-stdin`(표준입력 한 줄)만 허용한다.
출력에는 비밀번호·해시를 절대 표시하지 않는다. 종료 코드: 0 성공, 1 실패, 2 설정 오류.
"""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from shared.auth.passwords import (  # noqa: E402
    PolicyError,
    hash_password,
    normalize_display_name,
    normalize_username,
)

URL_ENV = "AUTH_ADMIN_DATABASE_URL"
FALLBACK_URL_ENV = "ALEMBIC_DATABASE_URL"


class UserError(RuntimeError):
    """사용자에게 그대로 보여 줄 수 있는 오류(비밀 정보 없음)."""


def _engine() -> Engine:
    url = os.environ.get(URL_ENV, "").strip() or os.environ.get(FALLBACK_URL_ENV, "").strip()
    if not url:
        raise SystemExit(f"[설정 오류] 환경변수 {URL_ENV}(또는 {FALLBACK_URL_ENV})에 소유자/마이그레이터 접속 주소를 넣어 주세요.")
    return create_engine(url, pool_pre_ping=True)


def _read_password(args: argparse.Namespace, username: str) -> str:
    if getattr(args, "password_stdin", False):
        line = sys.stdin.readline()
        return line.rstrip("\r\n")
    first = getpass.getpass("비밀번호(입력은 보이지 않습니다): ")
    second = getpass.getpass("비밀번호 확인: ")
    if first != second:
        raise UserError("두 비밀번호가 다릅니다.")
    return first


def add_user(engine: Engine, username: str, display_name: str, password: str) -> None:
    username = normalize_username(username)
    display_name = normalize_display_name(display_name)
    password_hash = hash_password(password, username=username)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO auth.app_users (username, display_name, password_hash) "
                "VALUES (:u, :d, :h) ON CONFLICT (username) DO NOTHING RETURNING user_id"
            ),
            {"u": username, "d": display_name, "h": password_hash},
        ).first()
    if row is None:
        raise UserError(f"이미 있는 아이디입니다: {username}")


def set_password(engine: Engine, username: str, password: str) -> None:
    username = normalize_username(username)
    password_hash = hash_password(password, username=username)
    with engine.begin() as conn:
        n = conn.execute(
            text(
                "UPDATE auth.app_users SET password_hash = :h, failed_attempts = 0, lockout_level = 0, "
                "locked_until = NULL, updated_at = now() WHERE username = :u"
            ),
            {"h": password_hash, "u": username},
        ).rowcount
    if n == 0:
        raise UserError(f"없는 아이디입니다: {username}")


def _update_flag(engine: Engine, username: str, sql: str) -> None:
    username = normalize_username(username)
    with engine.begin() as conn:
        n = conn.execute(text(sql), {"u": username}).rowcount
    if n == 0:
        raise UserError(f"없는 아이디입니다: {username}")


def set_active(engine: Engine, username: str, active: bool) -> None:
    reset = ", failed_attempts = 0, lockout_level = 0, locked_until = NULL" if active else ""
    flag = "true" if active else "false"
    _update_flag(engine, username, f"UPDATE auth.app_users SET is_active = {flag}{reset}, updated_at = now() WHERE username = :u")


def unlock(engine: Engine, username: str) -> None:
    _update_flag(
        engine,
        username,
        "UPDATE auth.app_users SET failed_attempts = 0, lockout_level = 0, locked_until = NULL, updated_at = now() WHERE username = :u",
    )


def delete_user(engine: Engine, username: str) -> None:
    _update_flag(engine, username, "DELETE FROM auth.app_users WHERE username = :u")


def list_users(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT username, display_name, is_active, locked_until, last_login_at, created_at "
                "FROM auth.app_users ORDER BY created_at, username"
            )
        ).mappings()
        return [dict(r) for r in rows]


def purge_audit(engine: Engine, days: int) -> int:
    """`days`일보다 오래된 로그인 기록을 지우고 지운 건수를 돌려준다(보존기간 수동 정리)."""
    if days < 1:
        raise UserError("--days는 1 이상이어야 합니다.")
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM auth.login_audit WHERE occurred_at < now() - make_interval(days => :d)"),
            {"d": days},
        )
        return result.rowcount or 0


def audit_rows(engine: Engine, limit: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT occurred_at, username_attempted, result, client_ip FROM auth.login_audit "
                "ORDER BY occurred_at DESC, audit_id DESC LIMIT :n"
            ),
            {"n": limit},
        ).mappings()
        return [dict(r) for r in rows]


def check_privileges(engine: Engine) -> list[tuple[str, bool, str]]:
    """(점검 항목, 통과 여부, 설명). `auth_service`는 정확히 설계한 권한만, 다른 앱 계정은 `auth` 스키마 접근이 없어야 한다."""
    results: list[tuple[str, bool, str]] = []

    def q(sql: str, **params) -> bool | None:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    role_exists = bool(q("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_service')"))
    results.append(("auth_service 역할 존재", role_exists, "없으면 deploy/render/neon-auth-setup.sql 실행"))
    if role_exists:
        expect = [
            ("auth_service: auth 스키마 USAGE", "SELECT has_schema_privilege('auth_service', 'auth', 'USAGE')", True),
            ("auth_service: app_users SELECT", "SELECT has_table_privilege('auth_service', 'auth.app_users', 'SELECT')", True),
            ("auth_service: app_users INSERT 없음", "SELECT has_table_privilege('auth_service', 'auth.app_users', 'INSERT')", False),
            ("auth_service: app_users DELETE 없음", "SELECT has_table_privilege('auth_service', 'auth.app_users', 'DELETE')", False),
            ("auth_service: 아이디 열 UPDATE 없음", "SELECT has_column_privilege('auth_service', 'auth.app_users', 'username', 'UPDATE')", False),
            ("auth_service: is_active 열 UPDATE 없음", "SELECT has_column_privilege('auth_service', 'auth.app_users', 'is_active', 'UPDATE')", False),
            ("auth_service: failed_attempts 열 UPDATE", "SELECT has_column_privilege('auth_service', 'auth.app_users', 'failed_attempts', 'UPDATE')", True),
            ("auth_service: login_audit INSERT", "SELECT has_table_privilege('auth_service', 'auth.login_audit', 'INSERT')", True),
            ("auth_service: login_audit SELECT 없음", "SELECT has_table_privilege('auth_service', 'auth.login_audit', 'SELECT')", False),
            ("auth_service: public_serving 접근 없음", "SELECT has_schema_privilege('auth_service', 'public_serving', 'USAGE')", False),
        ]
        for label, sql, want in expect:
            got = bool(q(sql))
            results.append((label, got == want, "정상" if got == want else f"기대 {want}, 실제 {got}"))
    for other in ("api_service", "batch_worker"):
        if q("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :r)", r=other):
            got = bool(q("SELECT has_schema_privilege(:r, 'auth', 'USAGE')", r=other))
            results.append((f"{other}: auth 스키마 접근 없음", not got, "정상" if not got else "접근 권한이 있습니다(제거 필요)"))
    return results


def _fmt(value: object) -> str:
    return "-" if value is None else str(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="회원 관리(가입 화면 없음, 관리자가 직접 추가)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="회원 추가")
    a.add_argument("username")
    a.add_argument("--name", required=True, help="화면에 보일 이름")
    a.add_argument("--password-stdin", action="store_true", help="표준입력 한 줄에서 비밀번호를 읽음(자동화용)")
    s = sub.add_parser("set-password", help="비밀번호 재설정(실패 횟수·잠금도 초기화)")
    s.add_argument("username")
    s.add_argument("--password-stdin", action="store_true")
    for name, helptext in (("disable", "로그인 막기"), ("enable", "다시 허용(잠금 초기화)"), ("unlock", "잠금만 풀기")):
        sub.add_parser(name, help=helptext).add_argument("username")
    d = sub.add_parser("delete", help="회원 삭제(되돌릴 수 없음)")
    d.add_argument("username")
    d.add_argument("--yes", action="store_true", help="확인 입력 없이 삭제(자동화용)")
    sub.add_parser("list", help="회원 목록")
    au = sub.add_parser("audit", help="최근 로그인 기록")
    au.add_argument("--limit", type=int, default=20)
    pu = sub.add_parser("purge-audit", help="오래된 로그인 기록 삭제(기본 90일 보존)")
    pu.add_argument("--days", type=int, default=90)
    sub.add_parser("check", help="계정 권한 점검")
    return p


def main(argv: list[str] | None = None, *, engine: Engine | None = None) -> int:
    args = build_parser().parse_args(argv)
    eng = engine if engine is not None else _engine()
    try:
        if args.cmd == "add":
            add_user(eng, args.username, args.name, _read_password(args, args.username))
            print(f"추가했습니다: {normalize_username(args.username)}")
        elif args.cmd == "set-password":
            set_password(eng, args.username, _read_password(args, args.username))
            print(f"비밀번호를 바꿨습니다: {normalize_username(args.username)}")
        elif args.cmd == "disable":
            set_active(eng, args.username, False)
            print(f"로그인을 막았습니다: {normalize_username(args.username)}")
        elif args.cmd == "enable":
            set_active(eng, args.username, True)
            print(f"다시 허용했습니다: {normalize_username(args.username)}")
        elif args.cmd == "unlock":
            unlock(eng, args.username)
            print(f"잠금을 풀었습니다: {normalize_username(args.username)}")
        elif args.cmd == "delete":
            username = normalize_username(args.username)
            if not args.yes:
                typed = input(f"'{username}' 회원을 삭제합니다. 확인을 위해 아이디를 한 번 더 입력하세요: ").strip().lower()
                if typed != username:
                    raise UserError("입력이 달라 삭제하지 않았습니다.")
            delete_user(eng, username)
            print(f"삭제했습니다: {username}")
        elif args.cmd == "list":
            rows = list_users(eng)
            print(f"{'아이디':<20}{'이름':<20}{'상태':<8}{'잠금 해제 시각':<28}{'마지막 로그인':<28}")
            for r in rows:
                print(f"{r['username']:<20}{r['display_name']:<20}{'활성' if r['is_active'] else '비활성':<8}{_fmt(r['locked_until']):<28}{_fmt(r['last_login_at']):<28}")
            print(f"총 {len(rows)}명")
        elif args.cmd == "audit":
            for r in audit_rows(eng, max(1, min(args.limit, 500))):
                print(f"{_fmt(r['occurred_at'])}  {_fmt(r['username_attempted']):<20}{r['result']:<9}{_fmt(r['client_ip'])}")
        elif args.cmd == "purge-audit":
            print(f"{args.days}일보다 오래된 기록 {purge_audit(eng, args.days)}건을 삭제했습니다.")
        elif args.cmd == "check":
            results = check_privileges(eng)
            for label, ok, note in results:
                print(f"{'OK  ' if ok else 'FAIL'}  {label}  {'' if ok and note == '정상' else note}")
            return 0 if all(ok for _, ok, _ in results) else 1
    except PolicyError as exc:
        for m in exc.messages:
            print(f"[규칙 위반] {m}", file=sys.stderr)
        return 1
    except UserError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        # 접속 문자열(비밀번호 포함 가능)이 메시지에 섞이지 않도록 원인 종류만 보여 준다.
        print(f"[DB 오류] {type(exc).__name__}: auth 스키마 접근 권한·마이그레이션 0015 적용 여부를 확인하세요.", file=sys.stderr)
        return 1
    finally:
        if engine is None:
            eng.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
