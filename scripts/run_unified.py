#!/usr/bin/env python
"""웹(Next.js) + API(FastAPI) 통합 서비스 기동·감시 스크립트 (DEC-078).

서비스 1개(컨테이너 1개) 안에서 두 프로세스를 함께 띄운다.

    1) API를 **같은 컨테이너 안에서만** 접속되는 주소(127.0.0.1:UNIFIED_API_PORT)로 기동한다.
       → 외부에는 웹 포트(PORT) 하나만 열린다. 웹 서버가 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`으로 API를 부른다.
    2) API가 `/api/v1/live`에 응답할 때까지 기다린 뒤에 웹을 기동한다(웹이 먼저 뜨고 API가 없는 구간을 만들지 않는다).
    3) 두 프로세스를 감시한다. **하나라도 끝나면 나머지를 종료하고 0이 아닌 코드로 끝난다** → Render가 컨테이너를 다시 띄운다
       (한쪽만 죽은 채 "정상"으로 남는 것을 막는다).
    4) SIGTERM/SIGINT(배포·종료)를 받으면 두 프로세스에 종료를 전달하고 정상 종료(0)한다.

환경변수(모두 선택):
    PORT                      웹이 듣는 공개 포트(Render가 지정). 기본 3000
    UNIFIED_API_PORT          API 내부 포트. 기본 8000
    UNIFIED_API_READY_SECONDS API 준비 대기 한도(초). 기본 90 (넘으면 비정상 종료)
    UNIFIED_WEB_DIR           웹 폴더. 기본 <저장소>/frontend (이미지에서는 /app/frontend)
    UNIFIED_API_CMD / UNIFIED_WEB_CMD   시험용: 기동 명령을 통째로 바꾼다(공백 구분, shlex)
    NODE_OPTIONS              없으면 `--max-old-space-size=256`(무료 서버 512MB 안에서 웹이 메모리를 독점하지 않게)
"""

# ruff: noqa: E501
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = 0.25
STOP_GRACE_SECONDS = 10


def log(message: str) -> None:
    print(f"[unified] {message}", flush=True)


def api_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/live", timeout=2) as response:  # noqa: S310
            return response.status < 500
    except urllib.error.HTTPError as exc:  # 4xx도 "응답함"
        return exc.code < 500
    except Exception:  # noqa: BLE001 - 아직 안 떴다
        return False


def stop(process: subprocess.Popen | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    log(f"{name} 종료 요청")
    process.terminate()
    try:
        process.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        log(f"{name}가 {STOP_GRACE_SECONDS}초 안에 끝나지 않아 강제 종료")
        process.kill()
        process.wait()


def build_commands(api_port: int, web_port: int, web_dir: Path) -> tuple[list[str], list[str]]:
    api_cmd = shlex.split(os.environ["UNIFIED_API_CMD"]) if os.environ.get("UNIFIED_API_CMD") else [sys.executable, "scripts/run_public_api.py"]
    if os.environ.get("UNIFIED_WEB_CMD"):
        web_cmd = shlex.split(os.environ["UNIFIED_WEB_CMD"])
    else:
        # npx/npm 래퍼 없이 Next를 직접 실행한다(래퍼가 메모리를 80MB쯤 더 쓴다).
        web_cmd = ["node", str(web_dir / "node_modules" / "next" / "dist" / "bin" / "next"), "start", "-H", "0.0.0.0", "-p", str(web_port)]
    return api_cmd, web_cmd


def main() -> int:
    api_port = int(os.environ.get("UNIFIED_API_PORT", "8000"))
    web_port = int(os.environ.get("PORT", "3000"))
    ready_seconds = float(os.environ.get("UNIFIED_API_READY_SECONDS", "90"))
    web_dir = Path(os.environ.get("UNIFIED_WEB_DIR", str(REPO_ROOT / "frontend")))
    api_cmd, web_cmd = build_commands(api_port, web_port, web_dir)

    api_env = {**os.environ, "PUBLIC_API_HOST": "127.0.0.1", "PUBLIC_API_PORT": str(api_port)}
    web_env = {**os.environ}
    web_env.setdefault("NODE_OPTIONS", "--max-old-space-size=256")
    web_env.setdefault("NEXT_PUBLIC_API_BASE_URL", f"http://127.0.0.1:{api_port}")

    api: subprocess.Popen | None = None
    web: subprocess.Popen | None = None
    stopping = False

    def on_signal(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        log(f"종료 신호({signal.Signals(signum).name}) 수신")

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    try:
        log(f"API 기동(내부 127.0.0.1:{api_port})")
        api = subprocess.Popen(api_cmd, cwd=REPO_ROOT, env=api_env)  # noqa: S603
        deadline = time.monotonic() + ready_seconds
        while not api_ready(api_port):
            if stopping:
                return 0
            if api.poll() is not None:
                log(f"API가 준비되기 전에 종료됨(코드 {api.returncode})")
                return api.returncode or 1
            if time.monotonic() > deadline:
                log(f"API가 {ready_seconds:.0f}초 안에 준비되지 않음")
                return 1
            time.sleep(POLL_SECONDS)
        log("API 준비 완료 → 웹 기동")
        web = subprocess.Popen(web_cmd, cwd=web_dir if web_dir.exists() else REPO_ROOT, env=web_env)  # noqa: S603

        while not stopping:
            for name, proc in (("API", api), ("웹", web)):
                if proc.poll() is not None:
                    log(f"{name}가 종료됨(코드 {proc.returncode}) → 서비스 전체를 종료해 재시작시킵니다")
                    return proc.returncode or 1
            time.sleep(POLL_SECONDS)
        return 0
    finally:
        stop(web, "웹")
        stop(api, "API")


if __name__ == "__main__":
    sys.exit(main())
