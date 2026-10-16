"""내 PC(로컬 서버)에 운영과 같은 로그인·회원가입을 켜거나 끈다 (DEC-075).

    py -3.12 scripts/setup_local_auth.py          # 켜기 (처음 한 번. 이미 켜져 있으면 값을 그대로 두고 점검만)
    py -3.12 scripts/setup_local_auth.py --off    # 끄기 (예전처럼 로그인 없이 사용)

하는 일
  1) 루트 `.env`(API용)와 `frontend/.env.local`(웹용)에 로그인에 필요한 값을 넣는다. 없는 값만 새로 만들고, 기존 값·주석은 그대로 둔다.
     - 웹↔API 내부 토큰, 웹 세션 서명 값은 이 PC 전용으로 무작위 생성한다(운영과 다른 값이어도 된다).
     - 회원 DB는 **이 컴퓨터의 로컬 DB**(`ALEMBIC_DATABASE_URL`, localhost)다. 그 DB에 `auth_service` 계정과 권한을 만들고
       (`deploy/local/auth-service-setup.sql`의 GRANT), `PUBLIC_API_AUTH_DATABASE_URL`을 그 계정 주소로 넣는다.
       `.env`에 localhost가 아닌 `AUTH_ADMIN_DATABASE_URL`(예전 원격 DB 주소)이 있으면 지운다.
     - 관리자 계정이 하나도 없으면 만든다(아이디·이름·비밀번호를 물어봄. 기본 아이디 jcw1973).
  2) 바꾸기 전 파일을 `*.bak-YYYYmmdd-HHMMSS`로 복사해 둔다.
  3) 회원 DB에 실제로 접속해 `auth.app_users` 조회가 되는지 확인한다(주소·비밀번호는 화면에 출력하지 않는다).
  전제: Docker DB가 켜져 있고, `scripts\\start_local_api.ps1`을 한 번 실행해 DB 마이그레이션(auth 스키마)이 적용돼 있어야 한다.
  옵션: --admin-id 아이디 / --admin-name 이름 / --admin-password-stdin(표준입력 한 줄) / --no-admin(관리자 만들기 건너뜀)

끝난 뒤: API를 `scripts\\start_local_api.ps1`로 다시 띄우고, 웹을 `npx next dev -p 4000`으로 다시 띄운다(환경값은 기동 때 읽는다).
"""
# ruff: noqa: E501  (한글 설명 문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path

AUTH_DB_KEY = "PUBLIC_API_AUTH_DATABASE_URL"
OWNER_KEY = "ALEMBIC_DATABASE_URL"  # 로컬 DB 소유자 주소(마이그레이션용)
ADMIN_URL_KEY = "AUTH_ADMIN_DATABASE_URL"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "", None}
GRANTS_FILE = Path(__file__).resolve().parent.parent / "deploy" / "local" / "auth-service-setup.sql"
TOKEN_KEY = "PUBLIC_API_INTERNAL_TOKEN"
REQUIRE_KEY = "PUBLIC_API_REQUIRE_INTERNAL_TOKEN"
SECRET_KEY = "SESSION_SECRET"
MIN_SECRET = 32

_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_text(path: Path) -> tuple[str, str]:
    """(내용, 줄바꿈). 윈도우 메모장이 붙인 BOM은 읽을 때 버린다."""
    if not path.exists():
        return "", "\n"
    raw = path.read_bytes().decode("utf-8-sig")  # read_text는 줄바꿈을 바꿔 버리므로 바이트로 읽는다
    return raw, ("\r\n" if "\r\n" in raw else "\n")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and not line.lstrip().startswith("#"):
            values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return values


def apply_env(text: str, newline: str, updates: dict[str, str | None]) -> str:
    """기존 줄은 값만 바꾸고, 없는 키는 끝에 붙인다. None이면 그 줄을 지운다. 그 밖의 줄(주석 포함)은 그대로."""
    out: list[str] = []
    done: set[str] = set()
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and not line.lstrip().startswith("#") and m.group(1) in updates:
            key = m.group(1)
            done.add(key)
            if updates[key] is not None:
                out.append(f"{key}={updates[key]}")
            continue
        out.append(line)
    pending = [(k, v) for k, v in updates.items() if k not in done and v is not None]
    if pending and out and out[-1].strip():
        out.append("")
    out.extend(f"{k}={v}" for k, v in pending)
    return newline.join(out) + newline


def backup(path: Path, stamp: str) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{stamp}"))


def normalize_db_url(url: str) -> str:
    """SQLAlchemy+psycopg 형식으로 맞춘다."""
    url = url.strip().strip('"').strip("'")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("DB 주소는 postgresql://... 형식이어야 합니다.")
    return url


def is_local_url(url: str) -> bool:
    from sqlalchemy.engine import make_url

    try:
        return make_url(url).host in LOCAL_HOSTS
    except Exception:  # noqa: BLE001
        return False


def grant_statements() -> list[str]:
    """`auth-service-setup.sql`에서 GRANT 문만 뽑는다(psql 전용 줄 `SELECT format ... \\gexec`는 제외)."""
    stmts: list[str] = []
    cur = ""
    for line in GRANTS_FILE.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("--") or t.upper().startswith(("SELECT FORMAT", "WHERE NOT EXISTS")):
            continue
        cur += " " + t
        if t.endswith(";"):
            if cur.strip().upper().startswith("GRANT"):
                stmts.append(cur.strip())
            cur = ""
    return stmts


def _short_error(exc: BaseException) -> str:
    import re

    first = (str(exc).strip().splitlines() or [""])[0]
    return re.sub(r"://[^@\s]*@", "://***@", first)[:200]


def provision_auth_db(owner_url: str, password: str) -> tuple[bool, str]:
    """로컬 DB에 `auth_service` 계정을 만들고(있으면 비밀번호만 갱신) 권한을 준다. 여러 번 실행해도 안전."""
    try:
        import psycopg  # type: ignore
        from psycopg import sql  # type: ignore
    except ImportError:
        return False, "psycopg가 없습니다(py -3.12 로 실행하세요)"
    dsn = owner_url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(dsn, connect_timeout=10, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth'")
            if cur.fetchone() is None:
                return False, "auth 스키마가 없습니다. 먼저 scripts\\start_local_api.ps1 로 API를 한 번 시작해 DB 마이그레이션을 적용한 뒤 다시 실행하세요."
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'auth_service'")
            exists = cur.fetchone() is not None
            cur.execute(
                sql.SQL("{} ROLE auth_service LOGIN PASSWORD {}{}").format(
                    sql.SQL("ALTER" if exists else "CREATE"),
                    sql.Literal(password),
                    sql.SQL("" if exists else " NOSUPERUSER NOCREATEDB NOCREATEROLE"),
                )
            )
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO auth_service").format(sql.Identifier(conn.info.dbname)))
            for stmt in grant_statements():
                cur.execute(stmt)
        return True, "회원 DB 계정(auth_service)과 권한을 준비했습니다"
    except Exception as exc:  # noqa: BLE001 — 접속 정보가 메시지에 섞이지 않도록 종류와 지운 첫 줄만 보인다
        return False, f"로컬 DB 준비 실패({type(exc).__name__}: {_short_error(exc)}) — Docker DB가 켜져 있는지, .env의 {OWNER_KEY}를 확인하세요"


def ensure_admin(owner_url: str, admin_id: str | None, admin_name: str | None, password_stdin: bool) -> tuple[bool, str]:
    """활성 관리자가 하나도 없으면 만든다. 이미 있으면 아무것도 하지 않는다."""
    from sqlalchemy import create_engine, text

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import manage_users as mu

    eng = create_engine(owner_url)
    try:
        with eng.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM auth.app_users WHERE role = 'admin' AND is_active")).scalar() or 0
        if count:
            return True, f"관리자 계정이 이미 있습니다({count}명). 비밀번호를 잊었으면 scripts\\reset_password.ps1"
        username = (admin_id or "").strip() or input("관리자 아이디 [jcw1973]: ").strip() or "jcw1973"
        name = (admin_name or "").strip() or input(f"표시 이름 [{username}]: ").strip() or username
        if password_stdin:
            pw = sys.stdin.readline().rstrip("\r\n").lstrip("\ufeff")
        else:
            pw = getpass.getpass("관리자 비밀번호(8자 이상, 입력은 보이지 않음): ")
            if pw != getpass.getpass("비밀번호 확인: "):
                return False, "두 비밀번호가 다릅니다. 다시 실행하세요."
        mu.add_user(eng, username, name, pw, "admin")
        return True, f"관리자 계정을 만들었습니다: {username}"
    except (mu.UserError, mu.PolicyError) as exc:
        return False, f"관리자 계정을 만들지 못했습니다: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"관리자 확인 실패({type(exc).__name__}: {_short_error(exc)})"
    finally:
        eng.dispose()


def check_auth_db(url: str) -> tuple[bool, str]:
    try:
        import psycopg  # type: ignore
    except ImportError:
        return False, "psycopg가 없어 접속 확인을 건너뜀(py -3.12 로 실행하세요)"
    dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(dsn, connect_timeout=20) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM auth.app_users")
            (count,) = cur.fetchone()
        return True, f"회원 DB 접속 확인(회원 {count}명)"
    except Exception as exc:  # 접속 정보가 메시지에 섞이지 않도록 종류만 보인다
        return False, f"회원 DB 접속 실패({type(exc).__name__}) — 주소·비밀번호를 확인하세요"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--off", action="store_true", help="로컬 로그인을 끈다")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="저장소 루트(시험용)")
    ap.add_argument("--api-base", default="http://localhost:4001", help="웹이 부를 로컬 API 주소")
    ap.add_argument("--no-db", "--no-check", dest="no_db", action="store_true", help="DB 준비·접속 확인·관리자 만들기를 건너뜀(시험용)")
    ap.add_argument("--no-admin", action="store_true", help="관리자 계정 만들기를 건너뜀")
    ap.add_argument("--admin-id", default=None, help="만들 관리자 아이디(기본: 물어봄, 기본값 jcw1973)")
    ap.add_argument("--admin-name", default=None, help="관리자 표시 이름")
    ap.add_argument("--admin-password-stdin", action="store_true", help="관리자 비밀번호를 표준입력 한 줄에서 읽음(자동화·시험용)")
    args = ap.parse_args(argv)

    root = Path(args.root)
    env_path = root / ".env"
    web_path = root / "frontend" / ".env.local"
    api_text, api_nl = read_text(env_path)
    web_text, web_nl = read_text(web_path)
    api_vals, web_vals = parse_env(api_text), parse_env(web_text)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if args.off:
        backup(env_path, stamp)
        backup(web_path, stamp)
        env_path.write_text(apply_env(api_text, api_nl, {REQUIRE_KEY: "false"}), encoding="utf-8", newline="")
        web_path.parent.mkdir(parents=True, exist_ok=True)
        web_path.write_text(
            apply_env(
                web_text,
                web_nl,
                {
                    "AUTH_REQUIRED": None,
                    "NEXT_PUBLIC_AUTH_ENABLED": None,
                    "NEXT_PUBLIC_BROWSER_API_BASE_URL": None,
                    "AUTH_COOKIE_INSECURE": None,
                },
            ),
            encoding="utf-8",
            newline="",
        )
        print("로컬 로그인을 껐습니다. API와 웹을 다시 띄우세요. (다시 켜기: py -3.12 scripts/setup_local_auth.py)")
        return 0

    owner_url = os.environ.get(OWNER_KEY, "").strip() or api_vals.get(OWNER_KEY, "")
    if not owner_url:
        print(f"[오류] .env 에 {OWNER_KEY}(이 컴퓨터 로컬 DB의 소유자 주소)가 필요합니다. .env.example 을 참고하세요.")
        return 2
    try:
        owner_url = normalize_db_url(owner_url)
    except ValueError as exc:
        print(f"[오류] {exc}")
        return 2
    if not is_local_url(owner_url):
        print(f"[오류] {OWNER_KEY} 가 localhost 가 아닙니다. 로그인 회원 DB는 이 컴퓨터의 로컬 DB만 사용합니다.")
        return 2

    from sqlalchemy.engine import make_url

    existing = os.environ.get(AUTH_DB_KEY, "").strip() or api_vals.get(AUTH_DB_KEY, "")
    reuse_password = None
    if existing:
        try:
            old = make_url(normalize_db_url(existing))
            if old.host in LOCAL_HOSTS and old.username == "auth_service" and old.password:
                reuse_password = old.password  # 이미 로컬 주소면 비밀번호를 그대로 둔다(다시 실행해도 값이 바뀌지 않음)
        except (ValueError, Exception):  # noqa: BLE001
            reuse_password = None
    auth_password = reuse_password or secrets.token_hex(16)
    auth_url = make_url(owner_url).set(username="auth_service", password=auth_password).render_as_string(hide_password=False)

    if not args.no_db:
        ok, message = provision_auth_db(owner_url, auth_password)
        print(("[완료] " if ok else "[오류] ") + message)
        if not ok:
            return 3  # 설정 파일은 아직 건드리지 않았다

    updates: dict[str, str | None] = {AUTH_DB_KEY: auth_url}
    old_admin_url = api_vals.get(ADMIN_URL_KEY, "")
    removed_remote = False
    if old_admin_url and not is_local_url(old_admin_url):
        updates[ADMIN_URL_KEY] = None  # 예전 원격 DB 주소는 지운다(비밀번호 재설정 등이 엉뚱한 DB를 보지 않게)
        removed_remote = True

    token = api_vals.get(TOKEN_KEY, "")
    if len(token) < MIN_SECRET:
        token = web_vals.get(TOKEN_KEY, "") if len(web_vals.get(TOKEN_KEY, "")) >= MIN_SECRET else secrets.token_hex(32)
    session_secret = web_vals.get(SECRET_KEY, "")
    if len(session_secret) < MIN_SECRET:
        session_secret = secrets.token_hex(32)

    backup(env_path, stamp)
    backup(web_path, stamp)
    env_path.write_text(
        apply_env(api_text, api_nl, {**updates, TOKEN_KEY: token, REQUIRE_KEY: "true"}),
        encoding="utf-8",
        newline="",
    )
    web_path.parent.mkdir(parents=True, exist_ok=True)
    web_path.write_text(
        apply_env(
            web_text,
            web_nl,
            {
                "AUTH_REQUIRED": "true",
                SECRET_KEY: session_secret,
                TOKEN_KEY: token,
                "NEXT_PUBLIC_API_BASE_URL": args.api_base,
                "NEXT_PUBLIC_BROWSER_API_BASE_URL": "same-origin",
                "NEXT_PUBLIC_AUTH_ENABLED": "true",
                "AUTH_COOKIE_INSECURE": "true",  # 로컬은 http라서 쿠키의 Secure 표시를 쓰지 않는다
            },
        ),
        encoding="utf-8",
        newline="",
    )
    print(f"[완료] {env_path.name}, frontend/{web_path.name} 에 로그인 설정을 넣었습니다. (이전 파일은 .bak-{stamp} 로 보관)")
    if removed_remote:
        print(f"[정리] .env 의 localhost 가 아닌 {ADMIN_URL_KEY} 를 지웠습니다(회원 DB는 이제 로컬 DB입니다).")
    if not args.no_db:
        ok, message = check_auth_db(auth_url)
        print(("[확인] " if ok else "[경고] ") + message)
        if not ok:
            return 3
        if not args.no_admin:
            ok, message = ensure_admin(owner_url, args.admin_id, args.admin_name, args.admin_password_stdin)
            print(("[확인] " if ok else "[경고] ") + message)
            if not ok:
                return 3
    print("다음: 1) scripts\\start_local_api.ps1 로 API 재기동  2) frontend 에서 npx next dev -p 4000 재기동  3) http://localhost:4000 접속")
    return 0


if __name__ == "__main__":
    sys.exit(main())
