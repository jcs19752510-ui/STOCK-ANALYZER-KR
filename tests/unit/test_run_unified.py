"""scripts/run_unified.py — 웹+API 통합 서비스 기동·감시 (DEC-078). 가짜 API/웹 프로세스로 시작 순서·종료 전파·환경값을 확인한다."""

# ruff: noqa: E501
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import run_unified as ru  # noqa: E402

FAKE_API = textwrap.dedent(
    """
    import http.server, json, os, sys, time
    out = os.environ["T_OUT"]
    open(out + "/api.pid", "w").write(str(os.getpid()))
    open(out + "/api.env", "w").write(json.dumps({k: os.environ.get(k) for k in ("PUBLIC_API_HOST", "PUBLIC_API_PORT")}))
    delay = float(os.environ.get("T_API_DELAY", "0"))
    die_after = float(os.environ.get("T_API_DIE_AFTER", "-1"))
    exit_code = int(os.environ.get("T_API_EXIT", "0"))
    if os.environ.get("T_API_EXIT_EARLY"):
        sys.exit(exit_code)
    time.sleep(delay)
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", int(os.environ["PUBLIC_API_PORT"])), H)
    open(out + "/api.listening", "w").write(str(time.time()))
    if die_after >= 0:
        srv.timeout = die_after
        srv.handle_request(); sys.exit(exit_code or 9)
    srv.serve_forever()
    """
)
FAKE_WEB = textwrap.dedent(
    """
    import json, os, sys, time
    out = os.environ["T_OUT"]
    open(out + "/web.pid", "w").write(str(os.getpid()))
    open(out + "/web.started", "w").write(str(time.time()))
    open(out + "/web.env", "w").write(json.dumps({k: os.environ.get(k) for k in ("NODE_OPTIONS", "NEXT_PUBLIC_API_BASE_URL", "PORT")}))
    die_after = float(os.environ.get("T_WEB_DIE_AFTER", "-1"))
    if die_after >= 0:
        time.sleep(die_after); sys.exit(int(os.environ.get("T_WEB_EXIT", "3")))
    while True: time.sleep(0.2)
    """
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def alive(pid_file: Path) -> bool:
    if not pid_file.exists():
        return False
    try:
        os.kill(int(pid_file.read_text()), 0)
        return True
    except OSError:
        return False


def wait_for(path: Path, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture()
def stack(tmp_path: Path):
    (tmp_path / "fake_api.py").write_text(FAKE_API)
    (tmp_path / "fake_web.py").write_text(FAKE_WEB)
    api_port = free_port()

    def start(**extra: str) -> subprocess.Popen:
        base = {k: v for k, v in os.environ.items() if k not in ("NODE_OPTIONS", "NEXT_PUBLIC_API_BASE_URL")}
        env = {
            **base,
            "UNIFIED_API_CMD": f"{sys.executable} {tmp_path / 'fake_api.py'}",
            "UNIFIED_WEB_CMD": f"{sys.executable} {tmp_path / 'fake_web.py'}",
            "UNIFIED_API_PORT": str(api_port),
            "PORT": str(free_port()),
            "UNIFIED_WEB_DIR": str(tmp_path),
            "T_OUT": str(tmp_path),
            **extra,
        }
        return subprocess.Popen([sys.executable, str(REPO / "scripts" / "run_unified.py")], env=env, cwd=REPO)

    procs: list[subprocess.Popen] = []

    def tracked(**extra: str) -> subprocess.Popen:
        p = start(**extra)
        procs.append(p)
        return p

    yield tmp_path, api_port, tracked
    for p in procs:
        if p.poll() is None:
            p.kill()
            p.wait()
    for name in ("api.pid", "web.pid"):
        f = tmp_path / name
        if f.exists():
            try:
                os.kill(int(f.read_text()), signal.SIGKILL)
            except OSError:
                pass


def test_API가_준비된_뒤에_웹이_시작된다(stack) -> None:
    out, _, tracked = stack
    p = tracked(T_API_DELAY="1.5")
    assert wait_for(out / "web.started")
    assert float((out / "web.started").read_text()) >= float((out / "api.listening").read_text())  # 웹은 API가 응답한 뒤에 시작
    assert p.poll() is None


def test_API는_내부주소로_웹에는_내부_API주소와_메모리_제한이_들어간다(stack) -> None:
    out, api_port, tracked = stack
    tracked()
    assert wait_for(out / "web.started")
    api_env = json.loads((out / "api.env").read_text())
    web_env = json.loads((out / "web.env").read_text())
    assert api_env == {"PUBLIC_API_HOST": "127.0.0.1", "PUBLIC_API_PORT": str(api_port)}
    assert web_env["NEXT_PUBLIC_API_BASE_URL"] == f"http://127.0.0.1:{api_port}"
    assert web_env["NODE_OPTIONS"] == "--max-old-space-size=256"


def test_이미_설정된_NODE_OPTIONS와_API주소는_덮어쓰지_않는다(stack) -> None:
    out, _, tracked = stack
    tracked(NODE_OPTIONS="--max-old-space-size=300", NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:9999")
    assert wait_for(out / "web.started")
    web_env = json.loads((out / "web.env").read_text())
    assert web_env["NODE_OPTIONS"] == "--max-old-space-size=300" and web_env["NEXT_PUBLIC_API_BASE_URL"] == "http://127.0.0.1:9999"


def test_종료_신호를_받으면_둘_다_끄고_정상_종료(stack) -> None:
    out, _, tracked = stack
    p = tracked()
    assert wait_for(out / "web.started")
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=20) == 0
    time.sleep(0.3)
    assert not alive(out / "api.pid") and not alive(out / "web.pid")


def test_API가_죽으면_웹도_끄고_비정상_종료(stack) -> None:
    out, _, tracked = stack
    p = tracked(T_API_DIE_AFTER="1.0", T_API_EXIT="7")
    assert wait_for(out / "web.started")
    assert p.wait(timeout=30) == 7  # 죽은 쪽의 종료 코드를 그대로 전달 → Render가 다시 띄운다
    time.sleep(0.3)
    assert not alive(out / "web.pid")


def test_웹이_죽으면_API도_끄고_비정상_종료(stack) -> None:
    out, _, tracked = stack
    p = tracked(T_WEB_DIE_AFTER="0.5", T_WEB_EXIT="3")
    assert p.wait(timeout=30) == 3
    time.sleep(0.3)
    assert not alive(out / "api.pid")


def test_API가_준비되지_않으면_웹을_띄우지_않고_실패(stack) -> None:
    out, _, tracked = stack
    p = tracked(T_API_DELAY="30", UNIFIED_API_READY_SECONDS="2")
    assert p.wait(timeout=20) == 1
    assert not (out / "web.started").exists()
    time.sleep(0.3)
    assert not alive(out / "api.pid")


def test_API가_시작하자마자_죽으면_그_코드로_실패하고_웹은_뜨지_않는다(stack) -> None:
    out, _, tracked = stack
    p = tracked(T_API_EXIT_EARLY="1", T_API_EXIT="5")
    assert p.wait(timeout=20) == 5
    assert not (out / "web.started").exists()


def test_기본_기동_명령은_npx_없이_next를_직접_실행하고_공개_포트에_붙는다() -> None:
    api_cmd, web_cmd = ru.build_commands(8000, 3000, Path("/app/frontend"))
    assert api_cmd[1:] == ["scripts/run_public_api.py"]
    assert web_cmd[0] == "node" and web_cmd[1].endswith("node_modules/next/dist/bin/next")
    assert web_cmd[2:] == ["start", "-H", "0.0.0.0", "-p", "3000"]
