#!/usr/bin/env python
"""로그인 기능 종단간(E2E) 시험 환경 (DEC-067): 임시 PostgreSQL + 실제 API(내부 토큰 강제) + 실제 웹 서버(로그인 켬) + 브라우저 시험.

pytest가 자동으로 모으지 않는다(파일명이 test_로 시작하지 않음). 직접 실행한다:
    source <PG 접속 환경변수>   # TEST_PG_ADMIN_PSQL, ALEMBIC/BATCH/PUBLIC_API_DATABASE_URL, PUBLIC_API_AUTH_DATABASE_URL
    python tests/e2e/login_stack.py            # 웹 빌드(로그인용 공개 변수) → 서버 3개 기동 → 브라우저 시험 → 정리
    python tests/e2e/login_stack.py --no-build # 이미 같은 설정으로 빌드해 두었을 때
    python tests/e2e/login_stack.py --unified  # 통합 서비스(DEC-078): API+웹을 scripts/run_unified.py 하나로 띄운 구성으로 같은 시험

임시 DB에 시험 데이터(픽스처 종목 + 배치 발행)와 회원 5명을 만든 뒤 API(포트 4321)와 웹(포트 4322)을 띄우고
`frontend/scripts/qa/login-e2e.mjs`를 실행한다. 종료 시 서버를 끄고 임시 DB를 지운다. 개발 DB에는 아무것도 쓰지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from scripts import manage_users as mu  # noqa: E402
from tests.integration.pattern_api_env import prepare_database  # noqa: E402
from tests.integration.pg_temp_db import TempDb, temp_database  # noqa: E402

API_PORT, WEB_PORT, BAD_WEB_PORT = 4321, 4322, 4323  # BAD_WEB: 내부 토큰이 API와 다른 웹(운영에서 실제로 겪은 설정 오류) 재현용
GOOD_PW = "Tr0ub4dor&3-horse-staple"
OTHER_PW = "Correct-Horse-Battery-9!"
LOG_DIR = Path(os.environ.get("E2E_LOG_DIR", "/tmp/claude-0/e2e-logs"))


def wait_http(url: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310
                if r.status < 500:
                    return
        except urllib.error.HTTPError as exc:  # 3xx/4xx도 "응답함"으로 본다
            if exc.code < 500:
                return
            last = str(exc)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"{url} 응답 없음: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--unified", action="store_true", help="API+웹을 scripts/run_unified.py 한 프로세스로 띄운다(운영 통합 서비스와 같은 구성)")
    parser.add_argument("--only", default="", help="브라우저 시험에서 이름에 이 문자열이 든 장면만(디버깅용)")
    args = parser.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for port in (API_PORT, WEB_PORT, BAD_WEB_PORT):
        probe = subprocess.run(["bash", "-c", f"exec 3<>/dev/tcp/127.0.0.1/{port}"], capture_output=True)
        if probe.returncode == 0:
            print(f"[e2e] 포트 {port}를 이미 다른 프로세스가 쓰고 있습니다. 먼저 종료하세요.", file=sys.stderr)
            return 2

    token = secrets.token_urlsafe(48)
    session_secret = secrets.token_urlsafe(48)
    web_env = {
        "AUTH_REQUIRED": "true",
        "SESSION_SECRET": session_secret,
        "PUBLIC_API_INTERNAL_TOKEN": token,
        "NEXT_PUBLIC_API_BASE_URL": f"http://127.0.0.1:{API_PORT}",
        "NEXT_PUBLIC_BROWSER_API_BASE_URL": "same-origin",
        "NEXT_PUBLIC_AUTH_ENABLED": "true",
        "FRONTEND_TRUSTED_PROXY_HOPS": "0",
    }
    procs: list[subprocess.Popen] = []
    code = 1
    try:
        if not args.no_build:
            print("[e2e] 웹 빌드(로그인용 공개 변수) …", flush=True)
            subprocess.run(["npm", "run", "build"], cwd=REPO / "frontend", env={**os.environ, **web_env}, check=True,
                           stdout=(LOG_DIR / "web-build.log").open("w"), stderr=subprocess.STDOUT)
        with temp_database() as tdb:
            prepare_database(tdb)
            admin = create_engine(TempDb.render(tdb.migrator_url))
            # 권한은 DB 기준(DEC-074): kim만 관리자, 나머지는 일반. wait는 가입 신청 후 승인 대기 중인 계정.
            users = [("kim", "김철수", GOOD_PW, "admin"), ("lee", "이영희", OTHER_PW, "user"), ("off", "퇴사자", GOOD_PW, "user"),
                     ("evil", "<script>window.__xss=1</script>", GOOD_PW, "user"), ("lock", "잠금시험", GOOD_PW, "user"), ("park", "박민수", OTHER_PW, "user"),
                     ("wait", "대기자", OTHER_PW, "user")]
            for username, name, pw, role in users:
                mu.add_user(admin, username, name, pw, role)
            mu.set_active(admin, "off", False)
            with admin.begin() as conn:
                conn.execute(text("UPDATE auth.app_users SET is_active = false, approved_at = NULL WHERE username = 'wait'"))
            with admin.begin() as conn:  # 소유자 전용 투자자 수급 시험 값(T00001)
                conn.execute(text(
                    "INSERT INTO public_serving.investor_flow_daily (stock_code, trade_date, personal_quantity, foreign_quantity, institution_quantity,"
                    " personal_amount_million, foreign_amount_million, institution_amount_million) VALUES"
                    " ('T00001', '2026-09-30', -1234, 567, 890, -100, 50, 60), ('T00001', '2026-10-01', 4321, NULL, -765, 400, NULL, -70)"))
            admin.dispose()

            api_url = make_url(os.environ["PUBLIC_API_DATABASE_URL"]).set(database=tdb.name)
            auth_url = make_url(os.environ["PUBLIC_API_AUTH_DATABASE_URL"]).set(database=tdb.name)
            api_env = {
                **os.environ,
                "PUBLIC_API_DATABASE_URL": TempDb.render(api_url),
                "PUBLIC_API_AUTH_DATABASE_URL": TempDb.render(auth_url),
                "PUBLIC_API_INTERNAL_TOKEN": token,
                "PUBLIC_API_REQUIRE_INTERNAL_TOKEN": "true",
                "PUBLIC_API_HOST": "127.0.0.1",
                "PUBLIC_API_PORT": str(API_PORT),
                "PUBLIC_API_CORS_ALLOWED_ORIGINS": f"http://localhost:{WEB_PORT}",
                "PUBLIC_API_SIGNUP_PER_10MIN": "30",
                "PUBLIC_API_SIGNUP_GLOBAL_PER_HOUR": "500",
                "PUBLIC_API_LOGIN_RATE_PER_MINUTE": "40",
                "PUBLIC_API_LOGIN_GLOBAL_PER_MINUTE": "3000",
                "PYTHONPATH": str(REPO),
            }
            # 자식 프로세스까지 한꺼번에 끌 수 있게 새 프로세스 그룹으로 띄운다(npx가 만든 next-server가 남아 포트를 붙잡는 것을 막는다).
            web_run_env = {**os.environ, **web_env, "AUTH_COOKIE_INSECURE": os.environ.get("E2E_COOKIE_INSECURE", "")}
            if args.unified:
                # 운영 컨테이너와 같다: 한 진입점이 API(내부 포트)를 먼저 띄운 뒤 웹을 띄운다. 웹은 node 로 next 를 직접 실행(npx 없음).
                unified_env = {**web_run_env, **api_env, "PORT": str(WEB_PORT), "UNIFIED_API_PORT": str(API_PORT), "UNIFIED_WEB_DIR": str(REPO / "frontend")}
                procs.append(subprocess.Popen([sys.executable, "scripts/run_unified.py"], cwd=REPO, env=unified_env, start_new_session=True,
                                              stdout=(LOG_DIR / "unified.log").open("w"), stderr=subprocess.STDOUT))
            else:
                procs.append(subprocess.Popen([sys.executable, "scripts/run_public_api.py"], cwd=REPO, env=api_env, start_new_session=True,
                                              stdout=(LOG_DIR / "api.log").open("w"), stderr=subprocess.STDOUT))
                procs.append(subprocess.Popen(["npx", "next", "start", "-H", "127.0.0.1", "-p", str(WEB_PORT)], cwd=REPO / "frontend", start_new_session=True,
                                              env=web_run_env, stdout=(LOG_DIR / "web.log").open("w"), stderr=subprocess.STDOUT))
            wait_http(f"http://127.0.0.1:{API_PORT}/api/v1/live")
            wait_http(f"http://127.0.0.1:{WEB_PORT}/login")
            bad_env = {**os.environ, **web_env, "PUBLIC_API_INTERNAL_TOKEN": "x" * 48, "AUTH_COOKIE_INSECURE": os.environ.get("E2E_COOKIE_INSECURE", "")}
            procs.append(subprocess.Popen(["npx", "next", "start", "-H", "127.0.0.1", "-p", str(BAD_WEB_PORT)], cwd=REPO / "frontend", start_new_session=True, env=bad_env,
                                          stdout=(LOG_DIR / "web-bad.log").open("w"), stderr=subprocess.STDOUT))
            wait_http(f"http://127.0.0.1:{BAD_WEB_PORT}/login")
            print("[e2e] 서버 준비 완료, 브라우저 시험 시작", flush=True)

            admin_psql = os.environ["TEST_PG_ADMIN_PSQL"]
            env = {
                **os.environ,
                "QA_BASE": f"http://localhost:{WEB_PORT}",
                "QA_API": f"http://127.0.0.1:{API_PORT}",
                "QA_BAD_BASE": f"http://localhost:{BAD_WEB_PORT}",
                "QA_TOKEN": token,
                "QA_SESSION_SECRET": session_secret,
                "QA_PW": GOOD_PW,
                "QA_PW2": OTHER_PW,
                "QA_ADMIN_PSQL": f"{admin_psql} -d {tdb.name}",
                "QA_COOKIE_INSECURE": os.environ.get("E2E_COOKIE_INSECURE", ""),
                "QA_ONLY": args.only,
                "QA_OUT": os.environ.get("QA_OUT", "/home/user/STOCK-ANALYZER-KR/docs/qa/2026-10-05"),
            }
            code = subprocess.run(["node", "scripts/qa/login-e2e.mjs"], cwd=REPO / "frontend", env=env).returncode
    finally:
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
    print(f"[e2e] 종료 코드 {code} (로그: {LOG_DIR})", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
