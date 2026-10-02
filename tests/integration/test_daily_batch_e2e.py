"""일일 배치 스케줄링 종단 시험(DEC-047, R5): 실제 PostgreSQL + 모의 공공데이터 서버 + 실제 `run_daily_batch.py` 실행.

검증: ① 빠진 거래일을 오래된 순으로 따라잡는다 ② 대상일이 아직 미배포면 종료코드 2로 끝나고 다음 실행이 복구한다
③ 이미 최신이면 공공데이터를 전혀 호출하지 않는다 ④ 반복 실패한 과거 날짜는 시도 상한 후 멈춘다 ⑤ 신선도 점검이 지연을
감지하고 웹훅 알림을 보낸다. 시간은 실제 현재 시각을 쓰므로 기대값은 같은 캘린더 로직으로 계산한다.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scripts.mock_gov_data_server import start_server
from services.ingestion_batch.calendar_lookup import SqlCalendarRepository
from shared.calendar_service import get_last_trading_day
from tests.integration.pattern_api_env import seed_calendar
from tests.integration.pg_temp_db import REPO_ROOT, TempDb, TempDbUnavailable, temp_database

KST = ZoneInfo("Asia/Seoul")
CATCHUP_DAYS = 6


@pytest.fixture()
def env():
    try:
        with temp_database() as db:
            mig = create_engine(TempDb.render(db.migrator_url))
            today = datetime.now(KST).date()
            seed_calendar(mig, start=today - timedelta(days=60), end=today + timedelta(days=10))
            server, stats, unpublished = start_server()
            base = f"http://127.0.0.1:{server.server_address[1]}/"
            try:
                yield {"db": db, "mig": mig, "base": base, "stats": stats, "unpub": unpublished}
            finally:
                server.shutdown()
                mig.dispose()
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _target_and_window(mig) -> tuple[date, list[date]]:
    with Session(mig) as s:
        target = get_last_trading_day("KRX", datetime.now(KST), SqlCalendarRepository(s))
        rows = s.execute(
            text(
                "SELECT trade_date FROM reference.market_calendar WHERE market='KRX' "
                "AND is_trading_day AND trade_date <= :t ORDER BY trade_date DESC LIMIT :n"
            ),
            {"t": target, "n": CATCHUP_DAYS},
        ).scalars().all()
    return target, sorted(rows)


def _run(script: str, env, *args: str, extra: dict | None = None) -> subprocess.CompletedProcess:
    e = {
        **os.environ,
        "BATCH_DATABASE_URL": TempDb.render(env["db"].batch_url),
        "GOV_DATA_PORTAL_SERVICE_KEY": "mock",
        "GOV_DATA_PORTAL_BASE_URL": env["base"],
        "DAILY_BATCH_CATCHUP_DAYS": str(CATCHUP_DAYS),
        "PYTHONUTF8": "1",
        **(extra or {}),
    }
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=REPO_ROOT, env=e, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300,
    )  # fmt: skip


def _seed_master(env, day: date) -> None:
    """종목 마스터를 미리 채운다. 실제 운영에서는 이전 실행들이 이미 만들어 둔 상태다."""
    r = _run("seed_stock_master.py", env, "--trade-date", day.isoformat())
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]


def _scalar(mig, sql: str, **p):
    with mig.connect() as c:
        return c.execute(text(sql), p).scalar_one()


def _published(mig):
    return _scalar(mig, "SELECT trade_date FROM public_serving.current_published_batch WHERE market='KRX'")


def test_first_run_catches_up_window_oldest_first_and_publishes_latest(env):
    target, window = _target_and_window(env["mig"])
    r = _run("run_daily_batch.py", env)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    ingested = _scalar(env["mig"], "SELECT count(DISTINCT trade_date) FROM raw_internal.raw_ohlcv")
    assert ingested == len(window)
    assert _published(env["mig"]) == target
    # 오래된 날짜부터 처리: ingest 실행 이력의 시작 시각 순서 == 거래일 오름차순
    order = [
        row[0]
        for row in env["mig"].connect().execute(
            text(
                "SELECT trade_date_covered FROM public_serving.batch_run "
                "WHERE run_type='ingest' ORDER BY started_at"
            )
        )
    ]
    assert order == sorted(order) and set(order) == set(window)
    assert "처리 대상 거래일(오래된 순)" in r.stdout


def test_up_to_date_run_makes_no_external_calls(env):
    # 처음 수집하는 가장 오래된 날짜는 직전 이력이 없어 가공이 부분 성공(PARTIAL)으로 끝나 계속 "미완료"로 남는다.
    # 실제 운영처럼 이력이 있는 상태를 만들려고 첫 실행만 한 거래일 더 넓게 되짚는다.
    assert _run("run_daily_batch.py", env, extra={"DAILY_BATCH_CATCHUP_DAYS": str(CATCHUP_DAYS + 1)}).returncode == 0
    before = dict(env["stats"])
    r = _run("run_daily_batch.py", env)
    assert r.returncode == 0 and "할 일이 없습니다" in r.stdout
    assert "seed_stock_master" not in r.stdout  # 종목 마스터 갱신도 건너뛴다
    assert dict(env["stats"]) == before  # 공공데이터 호출 0건 증가


def test_unpublished_latest_exits_2_then_recovers_next_run(env):
    target, window = _target_and_window(env["mig"])
    _seed_master(env, window[0])
    env["unpub"].add(target.strftime("%Y%m%d"))
    r = _run("run_daily_batch.py", env)
    assert r.returncode == 2, r.stdout[-600:] + r.stderr[-600:]
    assert "아직 배포되지 않았을" in r.stderr
    earlier = [d for d in window if d != target]
    assert _scalar(env["mig"], "SELECT count(DISTINCT trade_date) FROM raw_internal.raw_ohlcv") == len(earlier)
    assert _published(env["mig"]) == earlier[-1]  # 직전 거래일까지는 정상 발행
    # 신선도: 허용 지연(1거래일) 이내라 정상
    assert _run("check_data_freshness.py", env).returncode == 0

    env["unpub"].clear()  # 공개됨
    r2 = _run("run_daily_batch.py", env)
    assert r2.returncode == 0, r2.stdout[-600:] + r2.stderr[-600:]
    assert _published(env["mig"]) == target
    assert _run("check_data_freshness.py", env, "--max-lag", "0").returncode == 0


def test_past_date_that_keeps_failing_stops_after_attempt_cap(env):
    target, window = _target_and_window(env["mig"])
    bad = window[1]  # 과거(대상 아님) 거래일 하나가 영구 0건
    _seed_master(env, window[0])
    env["unpub"].add(bad.strftime("%Y%m%d"))
    for _ in range(3):
        _run("run_daily_batch.py", env)
    calls_before = env["stats"][bad.strftime("%Y%m%d")]
    assert calls_before > 0
    r = _run("run_daily_batch.py", env)
    assert env["stats"][bad.strftime("%Y%m%d")] == calls_before  # 상한(3회) 후에는 더 호출하지 않는다
    assert "더 이상 재시도하지 않는 거래일" in r.stderr and bad.isoformat() in r.stderr


class _Capture(BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        type(self).bodies.append(json.loads(self.rfile.read(n) or b"{}"))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_freshness_check_alerts_webhook_when_stale_and_respects_no_notify(env):
    assert _run("run_daily_batch.py", env).returncode == 0
    target, window = _target_and_window(env["mig"])
    stale = window[0]  # 대상보다 (CATCHUP_DAYS-1)거래일 이전으로 포인터를 되돌린다
    with env["mig"].begin() as c:
        c.execute(
            text("UPDATE public_serving.current_published_batch SET trade_date=:d WHERE market='KRX'"),
            {"d": stale},
        )
    _Capture.bodies = []
    hook = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=hook.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{hook.server_address[1]}/hook"
    try:
        r = _run("check_data_freshness.py", env, extra={"DATA_FRESHNESS_WEBHOOK_URL": url})
        assert r.returncode == 1 and "데이터 지연" in r.stderr
        assert len(_Capture.bodies) == 1 and "데이터 지연" in _Capture.bodies[0]["text"]
        assert stale.isoformat() in _Capture.bodies[0]["text"]
        quiet = _run("check_data_freshness.py", env, "--no-notify", extra={"DATA_FRESHNESS_WEBHOOK_URL": url})
        assert quiet.returncode == 1 and len(_Capture.bodies) == 1  # 알림 억제
        # 웹훅이 죽어 있어도 점검 결과(종료코드 1)는 그대로, 경고만 남긴다
        hook.shutdown()
        dead = _run("check_data_freshness.py", env, extra={"DATA_FRESHNESS_WEBHOOK_URL": url})
        assert dead.returncode == 1 and "웹훅 알림 전송 실패" in dead.stderr
    finally:
        hook.server_close()
