#!/usr/bin/env python
# ruff: noqa: E501
"""내 PC(로컬) 데이터가 왜 최신 날짜가 아닌지 한 번에 진단한다(읽기 전용, DB 쓰기·증권사·공공데이터 호출 없음).

확인하는 것: ① 화면에 보이는 마지막 발행 거래일과 지금 있어야 할 거래일 ② 그 사이 빠진 거래일마다 배치가 돌았는지·결과(미공개/실패/성공)
③ 마지막 배치 시각 ④ 로그 파일 끝부분 ⑤ (Windows) 작업 스케줄러 등록 상태. 마지막에 **원인 판정과 다음 행동**을 한국어로 출력한다.

사용(프로젝트 루트에서, `.env`의 BATCH_DATABASE_URL을 읽는다):
    py -3.12 scripts\\diagnose_local_data.py
비밀값(DB 비밀번호 등)은 출력하지 않는다. 종료코드: 0 최신 / 1 진단 불가(설정·접속) / 2 지연 있음(원인은 출력 참고)
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
KST = ZoneInfo("Asia/Seoul")
NOT_PUBLISHED_PREFIX = "NOT_PUBLISHED"  # 배치가 "원천에 아직 데이터 없음"으로 남기는 접두(DEC-058)
TASK_NAME = "StockScreenerKR-DailyBatch"


@dataclass(frozen=True)
class Run:
    run_type: str
    status: str
    trade_date: date | None
    started_at: datetime
    error_summary: str | None


def classify_day(day: date, runs: Sequence[Run]) -> tuple[str, str]:
    """빠진 거래일 하나의 상태. (코드, 설명). 코드: NO_RUN / NOT_PUBLISHED / FAILED / PARTIAL / OK_UNPUBLISHED."""
    mine = sorted((r for r in runs if r.trade_date == day), key=lambda r: r.started_at)
    if not mine:
        return "NO_RUN", "이 날짜를 시도한 배치 기록이 없습니다"
    last = mine[-1]
    summary = (last.error_summary or "").strip()
    if last.status == "SUCCESS":
        return "OK_UNPUBLISHED", f"수집은 성공으로 기록됐는데 발행되지 않았습니다({last.run_type}, {last.started_at:%m-%d %H:%M})"
    if summary.startswith(NOT_PUBLISHED_PREFIX):
        return "NOT_PUBLISHED", f"원천(공공데이터)에 아직 데이터가 없었습니다(마지막 시도 {last.started_at:%m-%d %H:%M}, 총 {len(mine)}회)"
    if last.status == "PARTIAL":
        return "PARTIAL", f"일부만 수집됐습니다(마지막 시도 {last.started_at:%m-%d %H:%M}, 총 {len(mine)}회)"
    return "FAILED", f"수집 실패: {summary[:120] or '사유 없음'} (마지막 시도 {last.started_at:%m-%d %H:%M}, 총 {len(mine)}회)"


def verdict(missing: Sequence[date], states: dict[date, tuple[str, str]], last_run_at: datetime | None, now: datetime) -> list[str]:
    """원인 판정과 다음 행동(순수 함수)."""
    if not missing:
        return ["[정상] 발행 일봉이 기대 거래일과 같습니다. 화면이 낡아 보이면 API 서버를 다시 시작하고 새로고침하세요."]
    codes = {states[d][0] for d in missing}
    out: list[str] = []
    if last_run_at is None or (now - last_run_at) > timedelta(days=2):
        age = "배치 기록이 전혀 없습니다" if last_run_at is None else f"마지막 배치가 {last_run_at:%m-%d %H:%M}으로 이틀 넘게 지났습니다"
        out.append(f"[원인 의심 1순위] 배치가 돌지 않고 있습니다 — {age}. 작업 스케줄러 등록·노트북 절전/전원·로그인 상태를 확인하세요.")
        out.append("[바로 할 일] py -3.12 scripts\\run_daily_batch.py  (빠진 날을 오래된 순으로 채웁니다. 이틀 넘은 배치 공백도 최근 10거래일 안이면 복구됩니다)")
        return out
    if codes == {"NOT_PUBLISHED"}:
        out.append("[원인] 공공데이터가 하루(+1영업일) 늦게 공개되는 정상 지연입니다. 배치는 정상이고 원천에 아직 데이터가 없습니다.")
        out.append("[할 일] 없음 — 공개되면 다음 배치(14:30·18:30)가 자동으로 채웁니다. 오늘 날짜로 보고 싶다면 화면에서 \"장중 기준\"을 켜세요(증권사 일봉으로 최대 5거래일 보충).")
    elif "FAILED" in codes or "PARTIAL" in codes:
        bad = [d for d in missing if states[d][0] in ("FAILED", "PARTIAL")]
        out.append(f"[원인] 수집 실패 기록이 있습니다({', '.join(map(str, bad))}). 위 '수집 실패' 줄의 사유가 원인입니다(키·한도·네트워크 등).")
        out.append("[바로 할 일] py -3.12 scripts\\run_daily_batch.py 로 재시도 후, 같은 사유가 반복되면 그 줄을 그대로 알려 주세요.")
    elif "NO_RUN" in codes:
        out.append("[원인] 일부 날짜는 배치가 시도조차 하지 않았습니다. 배치가 해당 시간에 실행되지 못했을 가능성이 큽니다(노트북 꺼짐·절전).")
        out.append("[바로 할 일] py -3.12 scripts\\run_daily_batch.py  (빠진 날을 자동으로 따라잡습니다)")
    else:
        out.append("[원인] 수집은 성공으로 기록됐는데 발행이 늦습니다. 가공(Derivation) 단계 로그를 확인해야 합니다.")
        out.append("[바로 할 일] py -3.12 scripts\\run_daily_batch.py 후에도 같으면 logs\\daily_batch.log 끝부분을 알려 주세요.")
    return out


def calendar_end_warning(last_calendar_date: date | None, today: date, margin_days: int = 45) -> str | None:
    """달력이 곧 끝나거나 이미 끝났으면 안내 문구(없으면 None). 달력이 끝나면 직전 거래일을 계산할 수 없어 화면·배치가 멈춘다."""
    if last_calendar_date is None:
        return "[경고] 휴장일 달력이 DB에 없습니다 → scripts\\fix_local_data.ps1 이 data\\calendar\\*.yaml 을 적재합니다."
    left = (last_calendar_date - today).days
    if left < 0:
        return f"[경고] 휴장일 달력이 {last_calendar_date}에 끝나 이미 지났습니다 → 새 연도 data\\calendar\\<연도>.yaml 을 만들어 적재해야 합니다(없으면 직전 거래일을 계산할 수 없습니다)."
    if left <= margin_days:
        return f"[주의] 휴장일 달력이 {left}일 뒤({last_calendar_date})에 끝납니다 → 다음 연도 data\\calendar\\<연도>.yaml 이 있는지 확인하세요."
    return None


def tail(path: Path, n: int = 12) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]


def scheduler_state() -> str:
    if os.name != "nt":
        return "(Windows가 아니라 작업 스케줄러 상태는 확인하지 않음)"
    try:
        res = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "(schtasks 실행 실패)"
    if res.returncode != 0:
        return f"작업 스케줄러에 '{TASK_NAME}'이(가) 등록돼 있지 않습니다 → scripts\\register_daily_batch_task.ps1 로 등록하세요."
    keep = ("상태", "Status", "마지막 실행 시간", "Last Run Time", "마지막 결과", "Last Result", "다음 실행 시간", "Next Run Time")
    return "\n".join(f"  {ln.strip()}" for ln in res.stdout.splitlines() if ln.strip().startswith(keep))


def load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(now: datetime | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    load_dotenv()
    url = os.environ.get("BATCH_DATABASE_URL")
    if not url:
        print("[진단 불가] .env에 BATCH_DATABASE_URL이 없습니다.")
        return 1
    from sqlalchemy import create_engine, text

    now = (now or datetime.now(KST)).astimezone(KST)
    try:
        engine = create_engine(url)
        with engine.connect() as c:
            published = c.execute(text("SELECT trade_date FROM public_serving.current_published_batch WHERE market = 'KRX'")).scalar()
            rows = c.execute(text("SELECT trade_date, is_trading_day, session_close_at FROM reference.market_calendar WHERE market = 'KRX' AND trade_date BETWEEN :a AND :b ORDER BY trade_date"), {"a": now.date() - timedelta(days=40), "b": now.date()}).all()
            last_calendar = c.execute(text("SELECT max(trade_date) FROM reference.market_calendar WHERE market = 'KRX'")).scalar()
            runs = [Run(r[0], r[1], r[2], r[3], r[4]) for r in c.execute(text("SELECT run_type::text, status::text, trade_date_covered, started_at, error_summary FROM public_serving.batch_run WHERE started_at > now() - interval '30 days' ORDER BY started_at"))]
    except Exception as exc:  # noqa: BLE001 — 접속 문자열(비밀번호)이 메시지에 섞일 수 있어 종류만 보인다
        print(f"[진단 불가] DB를 읽지 못했습니다({type(exc).__name__}). DB가 켜져 있는지, .env의 BATCH_DATABASE_URL이 맞는지 확인하세요.")
        return 1
    # 지금 있어야 할 거래일: 오늘이 거래일이고 마감 뒤면 오늘, 아니면 직전 거래일
    expected = None
    for d, trading, close in reversed(rows):
        if trading and (d < now.date() or (close is not None and now.time() >= close)):
            expected = d
            break
    if expected is None or published is None:
        print(f"[진단 불가] 발행 거래일({published}) 또는 달력(기대 거래일 {expected})을 읽지 못했습니다. 달력은 scripts\\load_calendar.py 로 적재하세요.")
        return 1
    missing = [d for d, trading, _ in rows if trading and published < d <= expected]
    by_day: dict[date, list[Run]] = defaultdict(list)
    for r in runs:
        if r.trade_date:
            by_day[r.trade_date].append(r)
    states = {d: classify_day(d, by_day[d]) for d in missing}
    ingests = [r for r in runs if r.run_type == "ingest"]
    last_run_at = max((r.started_at for r in runs), default=None)
    print(f"지금 {now:%Y-%m-%d %H:%M} (KST)")
    print(f"화면에 쓰이는 발행 거래일: {published}   /   지금 있어야 할 거래일: {expected}   /   뒤처진 거래일: {len(missing)}개")
    for d in missing:
        print(f"  - {d}: {states[d][1]}")
    warn = calendar_end_warning(last_calendar, now.date())
    if warn:
        print(warn)
    print(f"마지막 배치 기록: {last_run_at:%Y-%m-%d %H:%M}" if last_run_at else "마지막 배치 기록: 없음")
    if ingests:
        li = ingests[-1]
        print(f"마지막 수집(ingest): {li.started_at:%m-%d %H:%M} {li.status} 대상일 {li.trade_date}")
    print("작업 스케줄러:\n" + scheduler_state())
    log = tail(REPO_ROOT / "logs" / "daily_batch.log")
    if log:
        print("logs\\daily_batch.log 끝부분:")
        for ln in log:
            print("  " + ln[:200])
    else:
        print("logs\\daily_batch.log: 없음(배치가 한 번도 로그를 남기지 못했거나 위치가 다름)")
    print()
    for line in verdict(missing, states, last_run_at, now):
        print(line)
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
