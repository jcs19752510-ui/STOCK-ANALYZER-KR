"""내 PC(로컬 서버)에 운영과 같은 로그인·회원가입을 켜거나 끈다 (DEC-075).

    py -3.12 scripts/setup_local_auth.py          # 켜기 (처음 한 번. 이미 켜져 있으면 값을 그대로 두고 점검만)
    py -3.12 scripts/setup_local_auth.py --off    # 끄기 (예전처럼 로그인 없이 사용)

하는 일
  1) 루트 `.env`(API용)와 `frontend/.env.local`(웹용)에 로그인에 필요한 값을 넣는다. 없는 값만 새로 만들고, 기존 값·주석은 그대로 둔다.
     - 웹↔API 내부 토큰, 웹 세션 서명 값은 이 PC 전용으로 무작위 생성한다(운영과 다른 값이어도 된다).
     - 회원 DB 주소(`PUBLIC_API_AUTH_DATABASE_URL`)는 운영 Neon의 회원 DB(`auth_service` 계정)를 그대로 쓴다. 없으면 한 번 물어본다.
  2) 바꾸기 전 파일을 `*.bak-YYYYmmdd-HHMMSS`로 복사해 둔다.
  3) 회원 DB에 실제로 접속해 `auth.app_users` 조회가 되는지 확인한다(주소·비밀번호는 화면에 출력하지 않는다).

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
    """SQLAlchemy+psycopg 형식으로 맞춘다(Render에 넣은 값과 같은 형태)."""
    url = url.strip().strip('"').strip("'")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("회원 DB 주소는 postgresql://... 형식이어야 합니다.")
    return url


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
    ap.add_argument("--no-check", action="store_true", help="회원 DB 접속 확인을 건너뜀(시험용)")
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

    auth_url = os.environ.get(AUTH_DB_KEY, "").strip() or api_vals.get(AUTH_DB_KEY, "")
    if not auth_url:
        print("운영 회원 DB 주소가 필요합니다(Render > stock-analyzer-api > Environment 의 PUBLIC_API_AUTH_DATABASE_URL 값).")
        auth_url = getpass.getpass("PUBLIC_API_AUTH_DATABASE_URL (입력은 화면에 보이지 않음): ").strip()
    try:
        auth_url = normalize_db_url(auth_url)
    except ValueError as exc:
        print(f"[오류] {exc}")
        return 2

    token = api_vals.get(TOKEN_KEY, "")
    if len(token) < MIN_SECRET:
        token = web_vals.get(TOKEN_KEY, "") if len(web_vals.get(TOKEN_KEY, "")) >= MIN_SECRET else secrets.token_hex(32)
    session_secret = web_vals.get(SECRET_KEY, "")
    if len(session_secret) < MIN_SECRET:
        session_secret = secrets.token_hex(32)

    backup(env_path, stamp)
    backup(web_path, stamp)
    env_path.write_text(
        apply_env(api_text, api_nl, {AUTH_DB_KEY: auth_url, TOKEN_KEY: token, REQUIRE_KEY: "true"}),
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
    if not args.no_check:
        ok, message = check_auth_db(auth_url)
        print(("[확인] " if ok else "[경고] ") + message)
        if not ok:
            return 3
    print("다음: 1) scripts\\start_local_api.ps1 로 API 재기동  2) frontend 에서 npx next dev -p 4000 재기동  3) http://localhost:4000 접속")
    return 0


if __name__ == "__main__":
    sys.exit(main())
