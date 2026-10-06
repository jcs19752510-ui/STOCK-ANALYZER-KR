#!/usr/bin/env python
"""본인 전용 실시간 스트림의 웹 서버 대행(BFF) 종단간 시험 (DEC-084).

로그인을 켠 로컬 구성(운영과 같은 로그인) 전체를 띄우고 HTTP로 확인한다:
  임시 PostgreSQL(회원) + 모의 증권사 REST·웹소켓 + 실제 API + 실제 웹(`next start`).
  1) 비로그인 401, 일반 회원 403, 관리자 200(`text/event-stream`), 잘못된 종목코드·꺼진 빌드 404
  2) 스냅샷 → 체결·호가·시세 이벤트가 **끊김 없이 나눠서(버퍼링 없이)** 도착
  3) 화면(연결)을 닫으면 서버가 증권사 구독을 해지
  4) 관리자 권한 회수·로그아웃 뒤 이어진 스트림이 `end`로 끝나고 새 연결은 거부
  5) 동시 종목 한도 초과 429가 JSON 그대로 전달

    source /tmp/claude-0/pgenv.sh
    python tests/e2e/local_realtime_stack.py [--no-build]
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import httpx  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from scripts import manage_users as mu  # noqa: E402
from tests.e2e.login_stack import wait_http  # noqa: E402
from tests.integration.pattern_api_env import prepare_database  # noqa: E402
from tests.integration.pg_temp_db import TempDb, temp_database  # noqa: E402

API_PORT, WEB_PORT, KIS_PORT, WS_PORT, WEB_OFF_PORT = 4351, 4352, 4353, 4354, 4355
ADMIN_PW = "Tr0ub4dor&3-horse-staple"
USER_PW = "Correct-Horse-Battery-9!"
LOG_DIR = Path(os.environ.get("E2E_LOG_DIR", "/tmp/claude-0/e2e-logs"))
RECHECK = "2"  # 권한 재확인 간격(초, 시험용)

results: list[bool] = []


def rec(name: str, ok: bool, note: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {note}", flush=True)


class Sse:
    """SSE 응답을 이어서 읽으며 이벤트 도착 시각을 기록한다."""

    def __init__(self, resp: httpx.Response) -> None:
        self.resp = resp
        self._it = resp.aiter_text().__aiter__()
        self._buf = ""
        self.events: list[tuple[float, str, dict]] = []

    async def until(self, want: set[str], timeout: float = 15.0, min_count: dict[str, int] | None = None) -> None:
        min_count = min_count or {}

        async def read() -> None:
            while True:
                while "\n\n" in self._buf:
                    block, self._buf = self._buf.split("\n\n", 1)
                    name, data = None, None
                    for line in block.splitlines():
                        if line.startswith("event:"):
                            name = line[6:].strip()
                        elif line.startswith("data:"):
                            data = json.loads(line[5:].strip())
                    if name and data is not None:
                        self.events.append((time.monotonic(), name, data))
                names = [n for _, n, _ in self.events]
                if want <= set(names) and all(names.count(k) >= v for k, v in min_count.items()):
                    return
                self._buf += await self._it.__anext__()

        await asyncio.wait_for(read(), timeout)

    def of(self, name: str) -> list[dict]:
        return [d for _, n, d in self.events if n == name]


async def login(base: str, username: str, password: str) -> httpx.AsyncClient:
    c = httpx.AsyncClient(base_url=base, timeout=30, follow_redirects=False, headers={"Origin": base})  # 쓰기 요청은 같은 출처만 받는다
    r = await c.post("/auth/login", json={"username": username, "password": password, "next": "/", "remember": False})
    assert r.status_code == 200, f"{username} 로그인 실패 {r.status_code}"
    return c


async def scenarios(web: str, web_off: str, engine) -> None:
    path = "/api/v1/local/stocks/005930/stream"
    anon = httpx.AsyncClient(base_url=web, timeout=15)
    r = await anon.get(path)
    rec("비로그인 스트림 → 401", r.status_code == 401, str(r.status_code))
    r = await anon.get("/api/v1/local/realtime/status")
    rec("비로그인 연결 상태 → 401", r.status_code == 401, str(r.status_code))

    lee = await login(web, "lee", USER_PW)
    r = await lee.get(path)
    rec("일반 회원 스트림 → 403(권한 없음)", r.status_code == 403, str(r.status_code))
    r = await lee.get("/api/v1/local/realtime/status")
    rec("일반 회원 연결 상태 → 403", r.status_code == 403, str(r.status_code))

    kim = await login(web, "kim", ADMIN_PW)
    r = await kim.get("/api/v1/local/stocks/ABC/stream")
    rec("잘못된 종목코드 → 404", r.status_code == 404, str(r.status_code))
    off = await login(web_off, "kim", ADMIN_PW)
    r = await off.get(path)
    rec("실시간 기능이 꺼진 웹(로컬 빌드 변수 없음) → 404", r.status_code == 404, str(r.status_code))

    # 관리자 스트림: 스냅샷 + 실시간 이벤트가 끊김 없이 도착
    async with kim.stream("GET", path, timeout=None) as resp:
        rec("관리자 스트림 200 + text/event-stream", resp.status_code == 200 and resp.headers.get("content-type", "").startswith("text/event-stream"), f"{resp.status_code} {resp.headers.get('content-type')}")
        rec("응답 헤더: 캐시 금지, 압축(모아 보내기) 없음", "no-store" in resp.headers.get("cache-control", "") and "content-encoding" not in resp.headers, f"{resp.headers.get('cache-control')} / {resp.headers.get('content-encoding')}")
        sse = Sse(resp)
        t0 = time.monotonic()
        await sse.until({"snapshot"})
        first_latency = time.monotonic() - t0
        snap = sse.of("snapshot")[0]
        rec("스냅샷: 종목·시작 값·1분봉·체결", snap["code"] == "005930" and snap["seeded"] is True and len(snap["bars"]) > 0 and len(snap["ticks"]) > 0, f"bars={len(snap['bars'])} ticks={len(snap['ticks'])}")
        rec("첫 스냅샷 지연 15초 이내", first_latency < 15, f"{first_latency:.2f}s")
        await sse.until({"tick", "quote", "book", "bar"}, timeout=20, min_count={"tick": 6})
        ticks = [t for t, n, _ in sse.events if n == "tick"]
        gaps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
        rec("체결 이벤트가 나눠서 도착(웹 서버가 모아서 보내지 않음)", len(ticks) >= 6 and max(ticks) - min(ticks) >= 1.0 and sum(1 for g in gaps if g > 0.1) >= 2, f"틱 {len(ticks)}건, 간격 최대 {max(gaps):.2f}s")
        q = sse.of("quote")[-1]
        rec("시세 이벤트에 현재가·등락·누적거래량", q["price"] > 0 and q["acml_volume"] is not None, str(q["price"]))
        st = (await kim.get("/api/v1/local/realtime/status")).json()["data"]
        rec("연결 상태(관리자): 구독 종목 005930, 연결됨", st["codes"] == ["005930"] and st["state"] == "connected", json.dumps(st, ensure_ascii=False)[:120])
    # 연결을 닫음 → 유예(1초) 뒤 증권사 구독 해지
    deadline = time.monotonic() + 15
    codes: list[str] = ["?"]
    while time.monotonic() < deadline:
        codes = (await kim.get("/api/v1/local/realtime/status")).json()["data"]["codes"]
        if not codes:
            break
        await asyncio.sleep(0.5)
    rec("화면을 닫으면 증권사 구독이 해지된다", codes == [], str(codes))

    # 권한 회수: 이어진 스트림이 end 로 끝난다(재확인 간격 2초)
    kim2 = await login(web, "kim", ADMIN_PW)
    async with kim2.stream("GET", path, timeout=None) as resp:
        sse = Sse(resp)
        await sse.until({"snapshot"})
        mu.set_role(engine, "kim", "user")  # 관리자 권한 회수
        await sse.until({"end"}, timeout=15)
        rec("권한 회수 뒤 스트림이 end(forbidden)로 끝난다", sse.of("end")[-1] == {"reason": "forbidden"})
    r = await kim2.get(path)
    rec("권한 회수 뒤 새 연결은 403", r.status_code == 403, str(r.status_code))
    mu.set_role(engine, "kim", "admin")

    # 로그아웃 뒤에는 새 연결 401
    kim3 = await login(web, "kim", ADMIN_PW)
    await kim3.post("/auth/logout")
    r = await kim3.get(path)
    rec("로그아웃 뒤 새 연결은 401", r.status_code == 401, str(r.status_code))

    # 동시 종목 한도: 20개 열고 21번째는 429(JSON 그대로 전달)
    kim4 = await login(web, "kim", ADMIN_PW)
    opened = []
    try:
        for i in range(20):
            cm = kim4.stream("GET", f"/api/v1/local/stocks/{900000 + i}/stream", timeout=None)
            resp = await cm.__aenter__()
            opened.append((cm, resp))
            assert resp.status_code == 200, (i, resp.status_code)
        over = await kim4.get("/api/v1/local/stocks/999999/stream")
        err = over.json().get("error", {}) if over.headers.get("content-type", "").startswith("application/json") else {}
        rec("21번째 종목은 429 REALTIME_CAPACITY(JSON)", over.status_code == 429 and err.get("code") == "REALTIME_CAPACITY", f"{over.status_code} {err.get('code')}")
    finally:
        for cm, _ in opened:
            await cm.__aexit__(None, None, None)
    for c in (anon, lee, kim, off, kim2, kim3, kim4):
        await c.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    procs: list[subprocess.Popen] = []
    tmp_token = Path(tempfile.mkdtemp(prefix="rt-e2e-"))
    code = 1
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            admin_engine = create_engine(TempDb.render(tdb.migrator_url))
            mu.add_user(admin_engine, "kim", "김철수", ADMIN_PW, "admin")
            mu.add_user(admin_engine, "lee", "이영희", USER_PW, "user")
            mu.add_user(admin_engine, "park", "박관리", ADMIN_PW, "admin")  # 마지막 활성 관리자는 강등할 수 없으므로 두 번째 관리자를 둔다
            api_db = TempDb.render(make_url(os.environ["PUBLIC_API_DATABASE_URL"]).set(database=tdb.name))
            auth_db = TempDb.render(make_url(os.environ["PUBLIC_API_AUTH_DATABASE_URL"]).set(database=tdb.name))
            token = secrets.token_hex(32)
            web_origin = f"http://127.0.0.1:{WEB_PORT}"
            api_env = {
                **os.environ, "PYTHONPATH": str(REPO), "PUBLIC_API_HOST": "127.0.0.1", "PUBLIC_API_PORT": str(API_PORT),
                "PUBLIC_API_DATABASE_URL": api_db, "PUBLIC_API_AUTH_DATABASE_URL": auth_db,
                "PUBLIC_API_INTERNAL_TOKEN": token, "PUBLIC_API_REQUIRE_INTERNAL_TOKEN": "true",
                "PUBLIC_API_CORS_ALLOWED_ORIGINS": web_origin,
                "LOCAL_INTRADAY_ENABLED": "true", "KIS_APP_KEY": "mock", "KIS_APP_SECRET": "mock", "KIS_ALLOW_CUSTOM_BASE_URL": "true",
                "KIS_BASE_URL": f"http://127.0.0.1:{KIS_PORT}", "KIS_WS_URL": f"ws://127.0.0.1:{WS_PORT}",
                "KIS_TOKEN_CACHE_PATH": str(tmp_token / "kis-token.json"),
                "KIS_REALTIME_GRACE_SECONDS": "1", "KIS_REALTIME_RECHECK_SECONDS": RECHECK,
            }
            web_env = {
                **os.environ, "AUTH_REQUIRED": "true", "SESSION_SECRET": secrets.token_hex(32), "PUBLIC_API_INTERNAL_TOKEN": token,
                "NEXT_PUBLIC_AUTH_ENABLED": "true", "NEXT_PUBLIC_BROWSER_API_BASE_URL": "same-origin",
                "NEXT_PUBLIC_API_BASE_URL": f"http://127.0.0.1:{API_PORT}", "AUTH_COOKIE_INSECURE": "true",
                "NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED": "true", "NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED": "true", "FRONTEND_TRUSTED_PROXY_HOPS": "0",
            }
            if not args.no_build:
                print("[rt-e2e] 웹 빌드 …", flush=True)
                subprocess.run(["npm", "run", "build"], cwd=REPO / "frontend", env=web_env, check=True, stdout=(LOG_DIR / "rt-web-build.log").open("w"), stderr=subprocess.STDOUT)
            def spawn(cmd: list[str], env: dict, log: str, cwd: Path = REPO) -> None:
                procs.append(subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True, stdout=(LOG_DIR / log).open("w"), stderr=subprocess.STDOUT))

            spawn([sys.executable, "scripts/mock_kis_server.py", "--port", str(KIS_PORT)], os.environ, "rt-kis.log")
            spawn([sys.executable, "scripts/mock_kis_ws_server.py", "--port", str(WS_PORT)], os.environ, "rt-ws.log")
            spawn([sys.executable, "scripts/run_public_api.py"], api_env, "rt-api.log")
            spawn(["npx", "next", "start", "-H", "127.0.0.1", "-p", str(WEB_PORT)], web_env, "rt-web.log", REPO / "frontend")
            off_env = {k: v for k, v in web_env.items() if k != "NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED"}  # 같은 빌드, 실행 환경에서만 로컬 모드 변수 제거
            spawn(["npx", "next", "start", "-H", "127.0.0.1", "-p", str(WEB_OFF_PORT)], off_env, "rt-web-off.log", REPO / "frontend")
            wait_http(f"http://127.0.0.1:{API_PORT}/api/v1/live")
            wait_http(f"http://127.0.0.1:{WEB_PORT}/login")
            wait_http(f"http://127.0.0.1:{WEB_OFF_PORT}/login")
            print("[rt-e2e] 서버 준비 완료", flush=True)
            asyncio.run(asyncio.wait_for(scenarios(web_origin, f"http://127.0.0.1:{WEB_OFF_PORT}", admin_engine), 240))
            admin_engine.dispose()
            code = 0 if all(results) else 1
    finally:
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        shutil.rmtree(tmp_token, ignore_errors=True)
    print(f"\n합계 {len(results)}건, 통과 {sum(results)}, 실패 {len(results) - sum(results)}  (로그: {LOG_DIR})", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
