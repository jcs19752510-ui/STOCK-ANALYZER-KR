#!/usr/bin/env python
# ruff: noqa: E501
"""Windows PowerShell 스크립트를 **실제로 실행**해 보는 시험(DEC-094). Linux에 PowerShell(pwsh)을 내려받아 쓰고, Windows 전용 명령(작업 스케줄러·포트·프로세스)만
기록하는 대역(`tests/e2e/ps1/stubs.ps1`)으로 바꾼다. 파이썬 쪽(진단·달력 적재)은 진짜로, 임시 PostgreSQL에 대고 돈다.

    PWSH=/path/to/pwsh python tests/e2e/ps1_scripts_check.py

검증: 구문(전체 .ps1) / fix_local_data.ps1(출력이 사라지지 않음·달력 적재·스케줄러 3개 등록·두 번째 실행은 등록 안 함·종료코드) /
register_daily_batch_task.ps1(3개 작업의 시각·실행 인자) / restart_local.ps1(정상·웹 응답 없음). pwsh가 없으면 건너뛴다(종료코드 0, 통과로 세지 않음).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from sqlalchemy import create_engine, text  # noqa: E402

from tests.integration.pattern_api_env import prepare_database  # noqa: E402
from tests.integration.pg_temp_db import TempDb, temp_database  # noqa: E402

PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
results: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + note if note else ''}")


def make_shims(root: Path, python: str) -> Path:
    """cmd·py·docker·powershell 대역 실행 파일(Windows 명령을 Linux에서 흉내)."""
    b = root / "bin"
    b.mkdir()
    (b / "docker").write_text('#!/bin/bash\n[ "$1" = exec ] && echo "/var/run/postgresql:5432 - accepting connections"\nexit 0\n')
    (b / "py").write_text(
        f'#!/bin/bash\nshift\nargs=("${{@//\\\\//}}")\n'
        'case "${args[0]}" in\n  scripts/run_daily_batch.py) if [ "$HARNESS_REAL_BATCH" != 1 ]; then echo "[대기] 2026-10-06 데이터가 아직 배포되지 않았을 수 있습니다(대역: 실제 배치는 incident_repro.py가 확인)"; exit 2; fi;;\nesac\n'
        f'exec {python} "${{args[@]}}"\n'
    )
    (b / "cmd").write_text('#!/bin/bash\n[ "$1" = "/c" ] && shift\nline="$*"\nline="${line//chcp 65001 >nul & /}"\nline="${line//\\\\//}"\nexec bash -c "$line"\n')
    (b / "powershell").write_text(
        '#!/bin/bash\nfile=""\nwhile [ $# -gt 0 ]; do [ "$1" = "-File" ] && { file="$2"; shift; }; shift; done\n'
        f'exec {PWSH} -NoProfile -Command ". {REPO}/tests/e2e/ps1/stubs.ps1; & \'$file\'"\n'
    )
    for f in b.iterdir():
        f.chmod(0o755)
    return b


def run_ps1(script: str, shim: Path, env_extra: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "PYTHONPATH": str(REPO), **env_extra}
    cmd = f". {REPO}/tests/e2e/ps1/stubs.ps1; & '{REPO}/scripts/{script}' {' '.join(args)}; exit $LASTEXITCODE"
    return subprocess.run([PWSH, "-NoProfile", "-Command", cmd], capture_output=True, text=True, env=env, cwd=REPO, timeout=300)


def main() -> int:
    if not PWSH:
        print("[건너뜀] pwsh(PowerShell 7)가 없어 이 시험을 실행하지 않았습니다(통과로 세지 않음).")
        return 0
    # 1) 구문
    for f in sorted((REPO / "scripts").glob("*.ps1")):
        out = subprocess.run([PWSH, "-NoProfile", "-Command", f"$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('{f}',[ref]$t,[ref]$e);$e.Count"], capture_output=True, text=True)
        rec(f"구문 {f.name}", out.stdout.strip() == "0", out.stderr.strip()[:120])
    env_file = REPO / ".env"
    backup = env_file.read_bytes() if env_file.exists() else None
    work = Path(tempfile.mkdtemp(prefix="ps1check-"))
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            batch_url = TempDb.render(tdb.batch_url)
            env_file.write_text(f"BATCH_DATABASE_URL={batch_url}\nPUBLIC_API_DATABASE_URL={TempDb.render(tdb.api_url)}\nGOV_DATA_PORTAL_SERVICE_KEY=dummy\n", encoding="utf-8")
            shim = make_shims(work, sys.executable)
            log, state = work / "calls.log", work / "state.txt"
            base = {"HARNESS_LOG": str(log), "HARNESS_STATE": str(state)}

            # 2) fix_local_data.ps1 — 첫 실행(스케줄러 미등록 상태)
            r = run_ps1("fix_local_data.ps1", shim, base)
            out = r.stdout + r.stderr
            if os.environ.get("PS1_DEBUG"):
                print("-----\n" + out[:6000] + "\n-----")
            rec("fix_local_data: 단계 제목 5개가 모두 출력", all(t in out for t in ("[1/5] DB container", "[2/5] diagnosis BEFORE", "[3/5] catch-up batch", "[4/5] diagnosis AFTER", "[5/5] scheduled task")), out[:80].replace("\n", " "))
            rec("fix_local_data: 진단 출력이 사라지지 않고 두 번 보임(이전 버그 회귀)", out.count("화면에 쓰이는 발행 거래일") == 2, f"{out.count('화면에 쓰이는 발행 거래일')}번")
            rec("fix_local_data: 배치 종료코드가 숫자 하나로 표시(출력 섞임 버그 회귀)", re.search(r"batch exit code: 2\s+\(0 = ok", out) is not None)
            rec("fix_local_data: 배치 전에 DB 마이그레이션(alembic upgrade head) 단계 실행", "[migrate] alembic upgrade head" in out and out.index("[migrate]") < out.index("[3/5] catch-up batch"))
            rec("fix_local_data: 달력 2026·2027 적재 단계 실행", "[calendar] load 2026.yaml" in out and "[calendar] load 2027.yaml" in out)
            eng = create_engine(TempDb.render(tdb.migrator_url))
            with eng.connect() as c:
                last = c.execute(text("SELECT max(trade_date) FROM reference.market_calendar WHERE market='KRX'")).scalar()
            eng.dispose()
            rec("fix_local_data: DB 달력이 2027-12-31까지 적재됨", str(last) == "2027-12-31", str(last))
            calls = log.read_text(encoding="utf-8") if log.exists() else ""
            regs = re.findall(r"REGISTER (\S+) at=(\S+) args=(.*)", calls)
            rec("fix_local_data: 스케줄러 3개 등록(이름·시각·실행 인자)", sorted(n for n, _, _ in regs) == ["StockScreenerKR-DailyBatch", "StockScreenerKR-FreshnessCheck", "StockScreenerKR-InvestorFlow"] and {n: t for n, t, _ in regs}["StockScreenerKR-InvestorFlow"] == "20:10" and {n: t for n, t, _ in regs}["StockScreenerKR-DailyBatch"] == "14:30,18:30" and {n: t for n, t, _ in regs}["StockScreenerKR-FreshnessCheck"] == "09:10", "; ".join(f"{n}@{t}" for n, t, _ in regs))
            flow_args = [a for n, _, a in regs if n.endswith("InvestorFlow")]
            rec("fix_local_data: 수급 작업이 collect_investor_flow.py와 investor_flow.log를 가리킴", bool(flow_args) and "collect_investor_flow.py" in flow_args[0] and "investor_flow.log" in flow_args[0], flow_args[0][:90] if flow_args else "")
            rec("fix_local_data: 종료코드 = 진단 후 지연 있음(2), RESULT 문구 출력", r.returncode == 2 and "RESULT: still behind" in out, f"rc={r.returncode}")
            rec("fix_local_data: 로그 파일에 같은 내용 저장", (REPO / "logs" / "fix_local_data.log").exists() and "diagnosis AFTER" in (REPO / "logs" / "fix_local_data.log").read_text(encoding="utf-8", errors="replace"))

            # 두 번째 실행 — 이미 등록됨 → 다시 등록하지 않음
            before = len(regs)
            r2 = run_ps1("fix_local_data.ps1", shim, base)
            regs2 = re.findall(r"REGISTER (\S+)", log.read_text(encoding="utf-8"))
            rec("fix_local_data: 두 번째 실행은 스케줄러를 다시 등록하지 않음", len(regs2) == before and "Scheduled task exists" in (r2.stdout + r2.stderr))

            # 3) register_daily_batch_task.ps1 -Remove
            r3 = run_ps1("register_daily_batch_task.ps1", shim, base, "-Remove")
            rec("register -Remove: 작업 3개 삭제 호출", log.read_text(encoding="utf-8").count("UNREGISTER") == 3 and r3.returncode == 0)

            # 3-2) run_daily_batch.ps1 래퍼(스케줄러가 실제로 부르는 파일): .env 주입·로그 머리/꼬리·종료코드
            logf = REPO / "logs" / "wrapper_check.log"
            logf.unlink(missing_ok=True)
            r6 = run_ps1("run_daily_batch.ps1", shim, base, "-Script", "scripts\\diagnose_local_data.py", "-LogName", "wrapper_check.log")
            wl = logf.read_text(encoding="utf-8", errors="replace") if logf.exists() else ""
            rec("run_daily_batch.ps1 래퍼: 로그에 시작·끝 표시와 실행 결과(.env의 DB 주소를 읽어 진단 출력) 기록", "run start" in wl and "run end (exit=2)" in wl and "화면에 쓰이는 발행 거래일" in wl, f"rc={r6.returncode}")
            logf.unlink(missing_ok=True)

            # 4) restart_local.ps1
            log.write_text("", encoding="utf-8")
            r4 = run_ps1("restart_local.ps1", shim, {**base, "HARNESS_PORTS_BUSY": "1"}, "-NoBrowser")
            c4 = log.read_text(encoding="utf-8")
            rec("restart_local: 옛 프로세스 종료(4001·4000) 후 API·웹을 새 창으로 시작", c4.count("STOP-PROCESS") == 2 and "start_local_api.ps1" in c4 and "next dev -p 4000" in c4 and r4.returncode == 0, f"rc={r4.returncode}")
            rec("restart_local: 두 서비스 응답 확인(4001 /api/v1/live, 4000 /login)", "GET http://127.0.0.1:4001/api/v1/live" in c4 and "GET http://localhost:4000/login" in c4)
            log.write_text("", encoding="utf-8")
            r5 = run_ps1("restart_local.ps1", shim, {**base, "HARNESS_WEB_DOWN": "1"}, "-NoBrowser")
            rec("restart_local: 응답이 없으면 원인 안내를 출력하고 종료코드 1", r5.returncode == 1 and "did not answer" in (r5.stdout + r5.stderr), f"rc={r5.returncode}")
    finally:
        if backup is None:
            env_file.unlink(missing_ok=True)
        else:
            env_file.write_bytes(backup)
        shutil.rmtree(work, ignore_errors=True)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
