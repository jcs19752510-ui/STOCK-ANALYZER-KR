#!/usr/bin/env python
"""장중 기준 스크리닝 브라우저 종단 시험 (DEC-089·090) — 실제 웹(`next dev`) + 실제 API(스레드) + 모의 증권사(HTTP) + 임시 PostgreSQL.

    source /tmp/claude-0/pgenv.sh
    python tests/e2e/live_screen_stack.py            # 개발 서버(로컬 모드 켬)로 화면 시험
    python tests/e2e/live_screen_stack.py --prod     # 운영 빌드(로컬 모드 끔): 전환·요청 0건 확인

시각은 2026-10-02(금) 10:00 KST로 고정한다(발행 일봉 9/30이 직전 거래일 10/1보다 1거래일 뒤처진 장중 — 일봉 보충 경로까지 탄다).
개발 DB·실제 증권사에는 접속하지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
API_PORT, WEB_PORT = 4341, 4342
os.environ["PUBLIC_API_CORS_ALLOWED_ORIGINS"] = f"http://localhost:{WEB_PORT}"  # main 가져오기 전에 설정(CORS는 가져올 때 읽는다)
os.environ["PUBLIC_API_RATE_LIMIT_PER_MINUTE"] = "100000"  # 시험용(운영 한도 아님): 브라우저 시험이 429로 흔들리지 않게
LOG_DIR = Path(os.environ.get("E2E_LOG_DIR", "/tmp/claude-0/e2e-logs"))

import pytest  # noqa: E402

from tests.e2e.login_stack import wait_http  # noqa: E402
from tests.integration.live_screen_env import (  # noqa: E402
    KST,
    FullStack,
    align_published_closes_with_mock,
)
from tests.integration.pattern_api_env import prepare_database  # noqa: E402
from tests.integration.pg_temp_db import temp_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true", help="운영 빌드(로컬 모드 끔)로 시험")
    parser.add_argument("--scenario", default="all")
    args = parser.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    web = None
    code = 1
    mp = pytest.MonkeyPatch()
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            align_published_closes_with_mock(tdb)
            with FullStack(tdb, mp, datetime(2026, 10, 2, 10, 0, tzinfo=KST), port=API_PORT):
                web_env = {**os.environ, "NEXT_PUBLIC_API_BASE_URL": f"http://127.0.0.1:{API_PORT}", "FRONTEND_TRUSTED_PROXY_HOPS": "0",
                           "NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED": "true"}
                if not args.prod:
                    web_env["NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED"] = "true"
                else:
                    web_env.pop("NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED", None)
                    subprocess.run(["npm", "run", "build"], cwd=REPO / "frontend", env=web_env, check=True,
                                   stdout=(LOG_DIR / "live-web-build.log").open("w"), stderr=subprocess.STDOUT)
                cmd = ["npx", "next", "start" if args.prod else "dev", "-H", "127.0.0.1", "-p", str(WEB_PORT)]
                web = subprocess.Popen(cmd, cwd=REPO / "frontend", env=web_env, start_new_session=True,
                                       stdout=(LOG_DIR / "live-web.log").open("w"), stderr=subprocess.STDOUT)
                wait_http(f"http://127.0.0.1:{WEB_PORT}/screener", timeout=120)
                print("[live-e2e] 서버 준비 완료, 브라우저 시험 시작", flush=True)
                env = {**os.environ, "QA_BASE": f"http://localhost:{WEB_PORT}", "QA_API": f"http://127.0.0.1:{API_PORT}",
                       "QA_PHASE": "prod" if args.prod else "dev", "QA_SCENARIO": args.scenario}
                code = subprocess.run(["node", "scripts/qa/live-screen-e2e.mjs"], cwd=REPO / "frontend", env=env).returncode
    finally:
        if web is not None and web.poll() is None:
            os.killpg(web.pid, signal.SIGTERM)
            try:
                web.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(web.pid, signal.SIGKILL)
        mp.undo()
    print(f"[live-e2e] 종료 코드 {code} (로그: {LOG_DIR})", flush=True)
    return code


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    print(f"[live-e2e] 소요 {time.time() - t0:.0f}초")
    raise SystemExit(rc)
