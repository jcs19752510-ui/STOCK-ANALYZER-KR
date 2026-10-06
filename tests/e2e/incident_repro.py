#!/usr/bin/env python
# ruff: noqa: E501
"""2026-10-06 사고 재현: "공개 전" 실패가 쌓여 어떤 날이 영구 포기된 뒤, 데이터가 공개되었을 때 `fix_local_data.ps1`이 그 날을 채우고 화면 날짜를 올리는가 (DEC-092~094).

실제 일일 배치(`run_daily_batch.py`)·가공·발행·진단·달력 적재를 **진짜로**, 모의 공공데이터 서버·임시 PostgreSQL에 대고 돌리고, 사용자가 실행하는 `fix_local_data.ps1`을
PowerShell 7로 그대로 실행한다(Windows 전용 명령만 대역). 시각은 실제 현재 시각, 달력은 저장소의 `data/calendar/*.yaml` 그대로다.

    PWSH=<pwsh 경로> python tests/e2e/incident_repro.py [--old-code]   # --old-code: DEC-092 수정 전 `fetch_exhausted_dates`로 되돌려 같은 시나리오가 실패함을 보인다
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "e2e"))

import ps1_scripts_check as h  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts import load_calendar as lc  # noqa: E402
from scripts.mock_gov_data_server import start_server  # noqa: E402
from services.ingestion_batch.calendar_lookup import SqlCalendarRepository  # noqa: E402
from shared import batch_catchup as bc  # noqa: E402
from shared.calendar_service import get_last_trading_day  # noqa: E402
from tests.integration.pg_temp_db import TempDb, temp_database  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
CATCHUP = 6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-code", action="store_true")
    args = ap.parse_args()
    if not h.PWSH:
        print("[건너뜀] pwsh가 없습니다.")
        return 0
    rec = h.rec
    env_file = REPO / ".env"
    backup = env_file.read_bytes() if env_file.exists() else None
    work = Path(tempfile.mkdtemp(prefix="incident-"))
    server = None
    try:
        with temp_database() as tdb:
            batch_url = TempDb.render(tdb.batch_url)
            os.environ["BATCH_DATABASE_URL"] = batch_url
            server, stats, unpub = start_server()
            base = f"http://127.0.0.1:{server.server_address[1]}/"
            common = {"GOV_DATA_PORTAL_SERVICE_KEY": "mock", "GOV_DATA_PORTAL_BASE_URL": base, "DAILY_BATCH_CATCHUP_DAYS": str(CATCHUP), "PYTHONUTF8": "1"}
            env_file.write_text("BATCH_DATABASE_URL=" + batch_url + "\nPUBLIC_API_DATABASE_URL=" + TempDb.render(tdb.api_url) + "\n" + "".join(f"{k}={v}\n" for k, v in common.items()), encoding="utf-8")
            for y in (2026, 2027):
                assert lc.main([str(REPO / "data" / "calendar" / f"{y}.yaml")]) == 0
            mig = create_engine(TempDb.render(tdb.migrator_url))
            with Session(mig) as s:
                target = get_last_trading_day("KRX", datetime.now(KST), SqlCalendarRepository(s))
                window = sorted(s.execute(text("SELECT trade_date FROM reference.market_calendar WHERE market='KRX' AND is_trading_day AND trade_date <= :t ORDER BY trade_date DESC LIMIT :n"), {"t": target, "n": CATCHUP}).scalars().all())
            x = window[-3]  # 사고의 "10/2"에 해당하는 날(그 뒤 2거래일이 더 있다)
            print(f"[시나리오] 지금 기대 거래일 {target}, 포기됐던 날 X={x}, 창={[str(d) for d in window]}")
            py_env = {**os.environ, **common, "BATCH_DATABASE_URL": batch_url}

            def batch() -> subprocess.CompletedProcess:
                return subprocess.run([sys.executable, str(REPO / "scripts" / "run_daily_batch.py")], cwd=REPO, env=py_env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)

            subprocess.run([sys.executable, str(REPO / "scripts" / "seed_stock_master.py"), "--trade-date", window[0].isoformat()], cwd=REPO, env=py_env, check=True, capture_output=True)
            # 1) X와 그 이후는 아직 공개 전. 스케줄러가 하루 2번씩 며칠 돌린 것처럼 5번 실행
            for d in window[-3:]:
                unpub.add(d.strftime("%Y%m%d"))
            for _ in range(5):
                batch()
            with mig.connect() as c:
                published = c.execute(text("SELECT trade_date FROM public_serving.current_published_batch WHERE market='KRX'")).scalar()
                fails = c.execute(text("SELECT count(*) FROM public_serving.batch_run WHERE trade_date_covered=:d AND status='FAILED' AND run_type='ingest'"), {"d": x}).scalar_one()
            rec("재현 1: 공개 전 5회 실행 후 발행일은 X 직전 거래일에서 멈춤", published == window[-4], f"발행 {published}")
            rec("재현 2: X에 '공개 전' 실패가 3회 이상 쌓임(예전 코드는 여기서 영구 포기)", fails >= 3, f"{fails}회")
            if args.old_code:

                from sqlalchemy import func, select

                from shared.db_models.public_serving import BatchRun

                def old_fetch(session, *, since, before, max_attempts=bc.MAX_ATTEMPTS_PER_PAST_DATE):
                    rows = session.execute(select(BatchRun.trade_date_covered).where(BatchRun.trade_date_covered >= since, BatchRun.trade_date_covered < before, BatchRun.status.in_(("FAILED", "PARTIAL"))).group_by(BatchRun.trade_date_covered).having(func.count() >= max_attempts)).scalars()
                    return [d for d in rows if d is not None]

                with Session(mig) as s:
                    ex = old_fetch(s, since=window[0], before=target)
                rec("(옛 코드) X가 시도 상한으로 영구 제외됨 — 사고 재현", x in ex, str(ex))
            else:
                with Session(mig) as s:
                    ex = bc.fetch_exhausted_dates(s, since=window[0], before=target)
                rec("수정 후: X는 영구 제외되지 않음", x not in ex, str(ex))
            # 2) 공개됨 → 사용자가 실행하는 fix_local_data.ps1
            unpub.clear()
            shim = h.make_shims(work, sys.executable)
            log, state = work / "calls.log", work / "state.txt"
            r = h.run_ps1("fix_local_data.ps1", shim, {"HARNESS_LOG": str(log), "HARNESS_STATE": str(state), "HARNESS_REAL_BATCH": "1", **common})
            out = r.stdout + r.stderr
            with mig.connect() as c:
                published = c.execute(text("SELECT trade_date FROM public_serving.current_published_batch WHERE market='KRX'")).scalar()
                x_rows = c.execute(text("SELECT count(*) FROM raw_internal.raw_ohlcv WHERE trade_date=:d"), {"d": x}).scalar_one()
                derived = {r[0] for r in c.execute(text("SELECT DISTINCT trade_date FROM public_serving.derived_metrics_daily"))}
            print("----- fix_local_data.ps1 출력(발췌) -----")
            for line in out.splitlines():
                if line.startswith(("===", "[", "지금", "화면에", "  - ", "batch exit", "RESULT", "마지막")) :
                    print("  " + line[:170])
            print("-----")
            if args.old_code:
                rec("(옛 코드) fix_local_data로도 X가 채워지지 않음", x_rows == 0 and published != target, f"X 원본 {x_rows}행, 발행 {published}")
            else:
                rec("fix_local_data: 포기됐던 날 X의 원본 시세가 채워짐", x_rows > 0, f"{x_rows}행")
                rec("fix_local_data: 발행일이 기대 거래일까지 올라감(화면 날짜)", published == target, f"발행 {published} / 기대 {target}")
                rec("fix_local_data: 진단(후)이 [정상]이고 종료코드 0", "[정상]" in out.split("diagnosis AFTER")[-1] and r.returncode == 0 and "RESULT: data is up to date" in out, f"rc={r.returncode}")
                rec("fix_local_data: X와 이후 모든 날짜가 가공·발행됨", {d for d in window[-3:]} <= derived, f"가공된 날짜 {len(derived)}개")
                rec("fix_local_data: 가공 보류 경고 없음(구멍 없이 채워짐)", "가공 보류" not in out)
            mig.dispose()
    finally:
        if server is not None:
            server.shutdown()
        if backup is None:
            env_file.unlink(missing_ok=True)
        else:
            env_file.write_bytes(backup)
        shutil.rmtree(work, ignore_errors=True)
    failed = [n for n, ok, _ in h.results if not ok]
    print(f"\n{len(h.results) - len(failed)}/{len(h.results)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
