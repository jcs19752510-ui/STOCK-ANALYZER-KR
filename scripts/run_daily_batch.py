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

로그는 stdout/stderr로만 내보낸다 — 파일 로그가 필요하면 스케줄러(Windows
작업 스케줄러의 "출력을 파일로" 옵션, cron의 `>> logfile.log` 리다이렉트)가
책임진다(이 스크립트가 로그 파일 경로/로테이션을 자체 관리하지 않음).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> int:
    print(f"[{datetime.now(KST):%Y-%m-%d %H:%M:%S} KST] $ {' '.join(args)}", flush=True)
    result = subprocess.run(args, check=False)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv

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
