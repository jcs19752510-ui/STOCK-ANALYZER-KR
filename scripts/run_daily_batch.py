#!/usr/bin/env python
"""일일 배치(Ingestion → Derivation) 오케스트레이션 스크립트.

03-system-design.md §2-1: "호스팅 플랫폼의 Scheduled Job 또는 cron 컨테이너가
하루 1~2회 이 스크립트를 실행하는 것을 전제로 설계했다"는 문장은
`run_ingestion`/`run_derivation` **개별** CLI를 가리킨다 — 이 프로젝트는
호스팅 플랫폼이 아직 미확정(.env.example 참조)이라, 어떤 스케줄러
기술(Windows 작업 스케줄러 / cron / 컨테이너 오케스트레이터의 CronJob)을
쓰든 **이 스크립트 하나만** 호출하면 되도록 두 CLI를 순서대로(수집 성공 시에만
가공) 실행하는 얇은 드라이버로 만들었다. 스케줄러 자체(트리거 시각/재시도
정책)는 실행 환경이 정해지는 대로 그 환경의 스케줄러 설정으로 관리한다 —
이 스크립트 안에 스케줄링 로직(sleep 루프 등)을 넣지 않는다(1회 실행하고
종료, 상주 프로세스 아님).

두 CLI 모두 `--trade-date`를 생략하면 휴장일 캘린더로 "직전 거래일"을 각자
동일한 로직(`shared.calendar_service.get_last_trading_day`)으로 계산하므로,
아무 날짜에 실행해도(주말/공휴일 포함) 항상 같은 날짜를 가리켜 안전하게
매일 실행할 수 있다(멱등 upsert).

**(2026-09-22 추가)** `scripts/seed_stock_master.py`도 Ingestion 앞에 매일
같이 실행한다 — 신규 상장 종목이 다음날 바로 검색에 잡히게 하기 위함이다
(예전엔 이 스크립트가 "1회성 초기 시드"로만 설계돼 매번 수동 실행이
필요했다). `upsert_stock_master`가 기존 종목의 `is_active`를 건드리지
않도록 이미 고쳐뒀기 때문에(DEF-007 수정), 매일 재실행해도 수동으로
상장폐지 처리해둔 종목이 되돌아가지 않는다. 이 단계가 실패해도(예: 일시적
네트워크 오류) 그날의 시세 수집(핵심 기능)까지 막지는 않는다 — 경고만
남기고 계속 진행한다.

사용법:
    python scripts/run_daily_batch.py
    python scripts/run_daily_batch.py --dry-run   # 수집만 --dry-run으로 검증, 가공 스킵
    python scripts/run_daily_batch.py --no-catchup  # 따라잡기 없이 직전 거래일만(기존 동작)
    python scripts/run_daily_batch.py --no-lock     # 중복 실행 방지 락을 쓰지 않음(DEC-063)

**(2026-10-02, DEC-047) 따라잡기·재시도 설계**: 매 실행이 최근 N(기본 10,
`DAILY_BATCH_CATCHUP_DAYS`) 거래일 중 가공이 끝나지 않은 날짜를 오래된 순으로 채운다
(며칠 실패·PC 꺼짐 후에도 스스로 복구).
이미 최신이면 API를 호출하지 않고 종료하므로 하루 여러 번 실행해도 안전하다. 대상 거래일 데이터가
아직 배포 전이면 종료코드 2(`EXIT_NOT_PUBLISHED`)로 끝나 스케줄러의 다음 실행이 다시 시도한다.

로그는 stdout/stderr로만 내보낸다 — 파일 로그가 필요하면 스케줄러(Windows
작업 스케줄러의 "출력을 파일로" 옵션, cron의 `>> logfile.log` 리다이렉트)가
책임진다(이 스크립트가 로그 파일 경로/로테이션을 자체 관리하지 않음).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# 따라잡기에서 한 번에 되짚는 최대 거래일 수(공공데이터 호출 한도 보호). DEC-047.
EXIT_NOT_PUBLISHED = 2  # 대상 거래일 데이터가 아직 배포되지 않음 → 스케줄러가 나중에 다시 실행


def _run(args: list[str]) -> int:
    print(f"[{datetime.now(KST):%Y-%m-%d %H:%M:%S} KST] $ {' '.join(args)}", flush=True)
    result = subprocess.run(args, check=False)
    return result.returncode


def _pending_dates() -> tuple[list[date], date] | None:
    """(빠진 거래일 오름차순, 대상 거래일). DB·캘린더를 못 읽으면 None(단일 실행 폴백)."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from services.ingestion_batch.calendar_lookup import SqlCalendarRepository
        from shared.batch_catchup import (
            DEFAULT_CATCHUP_TRADING_DAYS,
            fetch_derived_dates,
            fetch_exhausted_dates,
            fetch_trading_dates,
            plan_catchup,
        )
        from shared.calendar_service import get_last_trading_day

        url = os.environ.get("BATCH_DATABASE_URL")
        if not url:
            return None
        max_days = int(os.environ.get("DAILY_BATCH_CATCHUP_DAYS", DEFAULT_CATCHUP_TRADING_DAYS))
        with Session(create_engine(url)) as session:
            target = get_last_trading_day("KRX", datetime.now(KST), SqlCalendarRepository(session))
            if target is None:
                return None
            trading = fetch_trading_dates(session, market="KRX", target=target, max_days=max_days)
            since = target - timedelta(days=max_days * 3 + 10)
            done = fetch_derived_dates(session, since=since)
            exhausted = [
                d
                for d in fetch_exhausted_dates(session, since=since, before=target)
                if d not in set(done)
            ]
        if exhausted:
            print(
                "[경고] 반복 실패·부분 성공으로 더 이상 재시도하지 않는 거래일: "
                + ", ".join(d.isoformat() for d in sorted(exhausted))
                + " — 필요하면 `--trade-date`로 수동 처리하세요.",
                file=sys.stderr,
            )
        return plan_catchup(trading, [*done, *exhausted], target=target, max_days=max_days), target
    except Exception as exc:  # 계획 단계 실패가 배치 자체를 막지 않게 한다(기존 동작으로 폴백)
        print(f"[경고] 따라잡기 계획 실패, 단일 실행으로 진행: {exc}", file=sys.stderr)
        return None


def _run_one_date(trade_date: date | None) -> int:
    """Ingestion → Derivation 1회. `trade_date`가 None이면 각 CLI가 직전 거래일을 계산한다."""
    extra = ["--trade-date", trade_date.isoformat()] if trade_date else []
    ingest_rc = _run([sys.executable, "-m", "services.ingestion_batch.run_ingestion", *extra])
    if ingest_rc != 0:
        print(f"[실패] Ingestion 종료코드 {ingest_rc} — Derivation 건너뜀.", file=sys.stderr)
        return ingest_rc
    derive_rc = _run([sys.executable, "-m", "services.derivation_batch.run_derivation", *extra])
    if derive_rc != 0:
        print(f"[실패] Derivation Batch 종료코드 {derive_rc}.", file=sys.stderr)
    return derive_rc


def _run_with_catchup(pending: list[date], target: date) -> int:
    if not pending:
        print(f"[완료] 대상 거래일 {target} 까지 가공이 이미 끝나 있어 할 일이 없습니다.")
        return 0
    print(f"[정보] 처리 대상 거래일(오래된 순): {', '.join(d.isoformat() for d in pending)}")
    for trade_date in pending:
        rc = _run_one_date(trade_date)
        if rc != 0:
            if trade_date == target:
                print(
                    f"[대기] {target} 데이터가 아직 배포되지 않았을 수 있습니다. "
                    f"스케줄러가 나중에 다시 실행하도록 종료코드 {EXIT_NOT_PUBLISHED}로 끝냅니다.",
                    file=sys.stderr,
                )
                return EXIT_NOT_PUBLISHED
            return rc  # 더 이전 날짜가 막히면 건너뛰지 않고 중단(다음 실행이 이어서 처리)
    print(f"[완료] {datetime.now(KST):%Y-%m-%d %H:%M:%S} KST 일일 배치 정상 종료.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """중복 실행 방지 락(DEC-063)을 잡고 배치를 실행한다. 다른 실행이 있으면 양보(종료코드 0)."""
    argv = sys.argv[1:] if argv is None else argv
    if "--dry-run" in argv or "--no-lock" in argv:
        return _main_locked(argv)

    from shared.batch_lock import LockState, daily_batch_lock

    with daily_batch_lock(os.environ.get("BATCH_DATABASE_URL")) as state:
        if state is LockState.HELD:
            print(
                "[정보] 다른 일일 배치가 이미 실행 중이라 이번 실행은 건너뜁니다"
                "(PC와 GitHub Actions 중복 방지). 정상 종료합니다."
            )
            return 0
        return _main_locked(argv)


def _main_locked(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv

    planned = None
    if not dry_run and "--no-catchup" not in argv:
        planned = _pending_dates()
        if planned is not None and not planned[0]:
            # 이미 최신이면 종목 마스터 갱신까지 건너뛰어 공공데이터를 전혀
            # 호출하지 않고 끝낸다(하루 여러 번 실행해도 안전).
            return _run_with_catchup(*planned)

    seed_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "seed_stock_master.py")]
    if dry_run:
        seed_cmd.append("--dry-run")
    seed_rc = _run(seed_cmd)
    if seed_rc != 0:
        print(
            f"[경고] 종목 마스터(신규 상장 반영) 갱신이 종료코드 {seed_rc}로 실패했습니다 — "
            "그날의 시세 수집은 계속 진행합니다(핵심 기능 아님).",
            file=sys.stderr,
        )

    if planned is not None:
        return _run_with_catchup(*planned)

    ingest_cmd = [sys.executable, "-m", "services.ingestion_batch.run_ingestion"]
    if dry_run:
        ingest_cmd.append("--dry-run")

    ingest_rc = _run(ingest_cmd)
    if ingest_rc != 0:
        print(
            f"[실패] Ingestion Batch가 종료코드 {ingest_rc}로 실패해 "
            "Derivation Batch를 실행하지 않습니다.",
            file=sys.stderr,
        )
        return ingest_rc

    if dry_run:
        print("(--dry-run) Ingestion만 점검하고 Derivation은 건너뜁니다.")
        return 0

    derive_cmd = [sys.executable, "-m", "services.derivation_batch.run_derivation"]
    derive_rc = _run(derive_cmd)
    if derive_rc != 0:
        print(f"[실패] Derivation Batch가 종료코드 {derive_rc}로 실패했습니다.", file=sys.stderr)
        return derive_rc

    print(f"[완료] {datetime.now(KST):%Y-%m-%d %H:%M:%S} KST 일일 배치 정상 종료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
