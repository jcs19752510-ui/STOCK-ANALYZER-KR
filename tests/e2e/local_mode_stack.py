#!/usr/bin/env python
"""로컬 서버(내 PC)에 로그인을 적용한 구성의 종단간(E2E) 시험 (DEC-075).

내 PC 사용 방식을 그대로 흉내 낸다:
  1) 로컬용 `.env` / `frontend/.env.local`(로컬 DB·모의 증권사 설정이 이미 있는 상태)을 임시 폴더에 만들고
  2) `scripts/setup_local_auth.py`를 실제로 실행해 로그인 설정을 넣고(회원 DB 접속 확인 포함)
  3) `scripts/start_local_api.ps1`이 읽는 키 목록만 골라 API 환경을 만들고, `.env.local` 전체로 웹 환경을 만든 뒤
  4) 실제 API + 실제 웹 + 모의 KIS 서버를 띄우고 브라우저로 확인한다.

    source /tmp/claude-0/pgenv.sh
    python tests/e2e/local_mode_stack.py --mode on    # 로그인 켠 로컬(운영과 같은 동작) + 로컬 전용 기능(호가·체결·분봉)
    python tests/e2e/local_mode_stack.py --mode off   # setup_local_auth.py --off 로 끈 로컬(예전 방식 그대로)

개발 DB에는 아무것도 쓰지 않는다(임시 DB를 만들고 지운다).
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from scripts import manage_users as mu  # noqa: E402
from scripts import setup_local_auth as sla  # noqa: E402
from tests.e2e.login_stack import wait_http  # noqa: E402
from tests.integration.pattern_api_env import prepare_database  # noqa: E402
from tests.integration.pg_temp_db import TempDb, temp_database  # noqa: E402

API_PORT, WEB_PORT, KIS_PORT, WS_PORT = 4331, 4332, 4333, 4334
GOOD_PW = "Tr0ub4dor&3-horse-staple"
OTHER_PW = "Correct-Horse-Battery-9!"
LOG_DIR = Path(os.environ.get("E2E_LOG_DIR", "/tmp/claude-0/e2e-logs"))


def start_script_keys() -> list[str]:
    """`start_local_api.ps1`이 .env에서 읽어 API 환경에 올리는 키 목록(실제 파일에서 읽는다 — 목록에서 빠지면 이 시험이 실패한다)."""
    text = (REPO / "scripts" / "start_local_api.ps1").read_text(encoding="utf-8")
    block = text.split("$keys = @(", 1)[1].split(")", 1)[0]
    return re.findall(r'"([A-Z0-9_]+)"', block)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("on", "off"), default="on")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--dev", action="store_true", help="웹을 개발 서버(next dev)로 띄운다(사용자 PC와 같은 방식). 빌드는 건너뛰고 QA_SCRIPT 환경변수의 스크립트를 실행")
    args = parser.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for port in (API_PORT, WEB_PORT, KIS_PORT, WS_PORT):
        probe = subprocess.run(["bash", "-c", f"exec 3<>/dev/tcp/127.0.0.1/{port}"], capture_output=True)
        if probe.returncode == 0:
            print(f"[local-e2e] 포트 {port}를 이미 다른 프로세스가 쓰고 있습니다.", file=sys.stderr)
            return 2

    procs: list[subprocess.Popen] = []
    code = 1
    fake_root = Path(tempfile.mkdtemp(prefix="local-pc-"))
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            admin = create_engine(TempDb.render(tdb.migrator_url))
            mu.add_user(admin, "kim", "김철수", GOOD_PW, "admin")
            mu.add_user(admin, "lee", "이영희", OTHER_PW, "user")
            admin.dispose()
            api_db = TempDb.render(make_url(os.environ["PUBLIC_API_DATABASE_URL"]).set(database=tdb.name))
            auth_db = TempDb.render(make_url(os.environ["PUBLIC_API_AUTH_DATABASE_URL"]).set(database=tdb.name))
            web_origin = f"http://localhost:{WEB_PORT}"

            # --- 1) "내 PC"의 기존 로컬 설정(로그인 도입 전 상태)
            (fake_root / "frontend").mkdir()
            (fake_root / ".env").write_text(
                f"PUBLIC_API_DATABASE_URL={api_db}\nPUBLIC_API_CORS_ALLOWED_ORIGINS={web_origin}\n"
                "LOCAL_INTRADAY_ENABLED=true\nKIS_APP_KEY=mock\nKIS_APP_SECRET=mock\nUNRELATED_LOCAL_KEY=keep-me\n",
                encoding="utf-8",
            )
            (fake_root / "frontend" / ".env.local").write_text(
                "NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true\nNEXT_PUBLIC_PRICE_EXPOSURE_ENABLED=true\n", encoding="utf-8"
            )

            # --- 2) 로그인 설정 스크립트를 실제로 실행(회원 DB 접속 확인 포함). 끄기 모드는 켠 뒤 --off 까지 실행.
            setup_env = {**os.environ, sla.AUTH_DB_KEY: auth_db}
            base = [sys.executable, str(REPO / "scripts" / "setup_local_auth.py"), "--root", str(fake_root), "--api-base", f"http://127.0.0.1:{API_PORT}"]
            res = subprocess.run(base, env=setup_env, capture_output=True, text=True)
            print(res.stdout.strip())
            if res.returncode != 0:
                print(res.stderr, file=sys.stderr)
                return 10
            if args.mode == "off":
                res = subprocess.run([*base, "--off"], env=setup_env, capture_output=True, text=True)
                print(res.stdout.strip())
                if res.returncode != 0:
                    return 11

            # --- 3) 스크립트가 만든 파일에서 API/웹 환경을 만든다(start_local_api.ps1 의 키 목록 / next 가 읽는 .env.local 전체)
            dotenv = sla.parse_env((fake_root / ".env").read_text(encoding="utf-8"))
            api_keys = start_script_keys()
            api_env = {
                **os.environ,
                **{k: dotenv[k] for k in api_keys if k in dotenv},
                "PUBLIC_API_HOST": "127.0.0.1",
                "PUBLIC_API_PORT": str(API_PORT),
                "KIS_BASE_URL": f"http://127.0.0.1:{KIS_PORT}",
                "KIS_ALLOW_CUSTOM_BASE_URL": "true",
                "KIS_WS_URL": f"ws://127.0.0.1:{WS_PORT}",
                "KIS_HTS_ID": "e2e-hts-id-xyz",  # 증권사 조건검색(DEC-088) — 응답·로그에 나오면 안 되는 값(종단 시험이 확인)
                "KIS_PSEARCH_CACHE_SECONDS": "2",
                "KIS_TOKEN_CACHE_PATH": str(fake_root / "kis-token.json"),
                "PYTHONPATH": str(REPO),
            }
            if args.mode == "off":
                api_env.pop("PUBLIC_API_AUTH_DATABASE_URL", None)  # 로컬 로그인을 끈 PC와 같은 상태(회원 DB 설정이 없어도 정상 동작해야 함)
            web_vals = sla.parse_env((fake_root / "frontend" / ".env.local").read_text(encoding="utf-8"))
            web_env = {**os.environ, **web_vals, "FRONTEND_TRUSTED_PROXY_HOPS": "0"}
            if args.mode == "on":
                assert api_env["PUBLIC_API_REQUIRE_INTERNAL_TOKEN"] == "true" and web_env["AUTH_REQUIRED"] == "true"
                assert api_env["PUBLIC_API_INTERNAL_TOKEN"] == web_env["PUBLIC_API_INTERNAL_TOKEN"], "웹/API 토큰이 다릅니다"
            assert api_env.get("LOCAL_INTRADAY_ENABLED") == "true" and web_env["NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED"] == "true", "로컬 전용 설정이 사라졌습니다"
            assert dotenv.get("UNRELATED_LOCAL_KEY") == "keep-me", "기존 로컬 값이 사라졌습니다"
            web_env["NEXT_PUBLIC_API_BASE_URL"] = f"http://127.0.0.1:{API_PORT}"

            if not args.no_build and not args.dev:
                print(f"[local-e2e] 웹 빌드({args.mode}) …", flush=True)
                subprocess.run(["npm", "run", "build"], cwd=REPO / "frontend", env=web_env, check=True,
                               stdout=(LOG_DIR / "local-web-build.log").open("w"), stderr=subprocess.STDOUT)

            procs.append(subprocess.Popen([sys.executable, "scripts/mock_kis_server.py", "--port", str(KIS_PORT)], cwd=REPO, start_new_session=True, env={**os.environ, "MOCK_PSEARCH_CODE_PREFIX": "T"},
                                          stdout=(LOG_DIR / "local-kis.log").open("w"), stderr=subprocess.STDOUT))
            procs.append(subprocess.Popen([sys.executable, "scripts/mock_kis_ws_server.py", "--port", str(WS_PORT)], cwd=REPO, start_new_session=True,
                                          stdout=(LOG_DIR / "local-ws.log").open("w"), stderr=subprocess.STDOUT))
            procs.append(subprocess.Popen([sys.executable, "scripts/run_public_api.py"], cwd=REPO, env=api_env, start_new_session=True,
                                          stdout=(LOG_DIR / "local-api.log").open("w"), stderr=subprocess.STDOUT))
            procs.append(subprocess.Popen(["npx", "next", "dev" if args.dev else "start", "-H", "127.0.0.1", "-p", str(WEB_PORT)], cwd=REPO / "frontend", env=web_env, start_new_session=True,
                                          stdout=(LOG_DIR / "local-web.log").open("w"), stderr=subprocess.STDOUT))
            wait_http(f"http://127.0.0.1:{API_PORT}/api/v1/live")
            wait_http(f"http://127.0.0.1:{WEB_PORT}/login", timeout=180 if args.dev else 90)
            print("[local-e2e] 서버 준비 완료, 브라우저 시험 시작", flush=True)

            env = {
                **os.environ,
                "QA_BASE": web_origin,
                "QA_API": f"http://127.0.0.1:{API_PORT}",
                "QA_MODE": args.mode,
                "QA_TOKEN": api_env.get("PUBLIC_API_INTERNAL_TOKEN", ""),
                "QA_PW": GOOD_PW,
                "QA_PW2": OTHER_PW,
                "QA_OUT": os.environ.get("QA_OUT", str(REPO / "docs" / "qa" / "2026-10-05")),
            }
            code = subprocess.run(["node", os.environ.get("QA_SCRIPT", "scripts/qa/local-login-e2e.mjs")], cwd=REPO / "frontend", env=env).returncode
    finally:
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        shutil.rmtree(fake_root, ignore_errors=True)
    print(f"[local-e2e] 종료 코드 {code} (로그: {LOG_DIR})", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
