#!/usr/bin/env python
"""투자자별 일별 순매수 수집 — 소유자 전용 표시용 (DEC-068).

소유자 PC에서만 실행한다. 본인 증권사(한국투자증권) 앱키로 종목별 `주식현재가 투자자`를 조회해
`public_serving.investor_flow_daily`에 적재한다(같은 종목·날짜는 멱등 upsert). 앱키는 PC 환경변수에만
있고 서버(Render)에는 넣지 않는다. 적재된 값은 API가 **소유자 계정에게만** 내려준다.

사용법:
    py -3.12 scripts/collect_investor_flow.py --codes 005930,000660   # 검증용
    py -3.12 scripts/collect_investor_flow.py --limit 20
    py -3.12 scripts/collect_investor_flow.py                         # 전 종목(호출 약 2,800회, 수 분)
    py -3.12 scripts/collect_investor_flow.py --dry-run

필요: KIS_APP_KEY, KIS_APP_SECRET, BATCH_DATABASE_URL(환경변수). 값은 출력하지 않는다.
당일 행은 확정 전일 수 있어 KST 20:00 이전에는 적재하지 않는다(`--include-today`로 강제). 확정 시각 자체는
증권사 문서로 확인하지 못했다. 종목 단위 오류는 건너뛰고 요약에 집계하며, 키 누락·DB 접속 실패는 종료 코드 1이다.
100종목마다 커밋하므로 중단돼도 그 시점까지는 남고 재실행해도 안전하다.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.public_api.intraday.config import IntradayConfigError, get_settings  # noqa: E402
from services.public_api.intraday.kis_client import KisClient, KisError  # noqa: E402
from services.public_api.intraday.normalize import normalize_investor_rows  # noqa: E402
from shared.db_models.public_serving import InvestorFlowDaily, StockMaster  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
COMMIT_EVERY = 100
MAX_CONSECUTIVE_ERRORS = 20  # 연속 실패가 이어지면 전체 장애로 보고 중단(2,800회 헛호출 방지)
TODAY_CONFIRM_HOUR = 20  # 이 시각(KST) 이전에는 당일 행을 적재하지 않는다


def extract_rows(body: dict) -> list:
    raw = body.get("output")
    rows = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    return normalize_investor_rows(rows)


def usable_days(days: list, now: datetime, include_today: bool) -> list:
    """미래 날짜는 버리고, 확정 전일 수 있는 당일 행은 제외한다."""
    today: date = now.date()
    keep_today = include_today or now.hour >= TODAY_CONFIRM_HOUR
    return [d for d in days if d.date < today or (d.date == today and keep_today)]


def upsert_days(session: Session, code: str, days: list) -> int:
    for d in days:
        stmt = pg_insert(InvestorFlowDaily).values(
            stock_code=code,
            trade_date=d.date,
            personal_quantity=d.personal_quantity,
            foreign_quantity=d.foreign_quantity,
            institution_quantity=d.institution_quantity,
            personal_amount_million=d.personal_amount_million,
            foreign_amount_million=d.foreign_amount_million,
            institution_amount_million=d.institution_amount_million,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[InvestorFlowDaily.stock_code, InvestorFlowDaily.trade_date],
                set_={
                    "personal_quantity": stmt.excluded.personal_quantity,
                    "foreign_quantity": stmt.excluded.foreign_quantity,
                    "institution_quantity": stmt.excluded.institution_quantity,
                    "personal_amount_million": stmt.excluded.personal_amount_million,
                    "foreign_amount_million": stmt.excluded.foreign_amount_million,
                    "institution_amount_million": stmt.excluded.institution_amount_million,
                    "updated_at": func.now(),
                },
            )
        )
    return len(days)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codes", default=None, help="쉼표로 구분한 종목코드(생략 시 활성 전 종목).")
    parser.add_argument("--limit", type=int, default=None, help="처리 종목 수 상한(검증용).")
    parser.add_argument("--include-today", action="store_true", help="당일 행도 적재(확정 전 값일 수 있음).")
    parser.add_argument("--dry-run", action="store_true", help="설정만 확인하고 호출·반영 안 함.")
    args = parser.parse_args(argv)

    db_url = os.environ.get("BATCH_DATABASE_URL", "").strip()
    try:
        settings = get_settings()
    except IntradayConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1
    if not settings.configured:
        print("[실패] KIS_APP_KEY·KIS_APP_SECRET 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        return 1
    if not db_url:
        print("[실패] BATCH_DATABASE_URL 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        return 1
    if args.dry_run:
        print("(--dry-run) 설정 확인 완료. 호출/반영은 하지 않았습니다.")
        return 0

    consecutive_errors = 0
    stats = {"stocks": 0, "stocks_with_rows": 0, "rows_upserted": 0, "errors": 0}
    error_samples: list[str] = []
    engine = create_engine(db_url)
    try:
        client = KisClient(settings)
        with Session(engine) as session:
            if args.codes:
                codes = [c.strip() for c in args.codes.split(",") if c.strip()]
            else:
                codes = list(
                    session.execute(
                        select(StockMaster.stock_code)
                        .where(StockMaster.is_active.is_(True))
                        .order_by(StockMaster.stock_code)
                    ).scalars()
                )
            if args.limit is not None:
                codes = codes[: args.limit]
            stats["stocks"] = len(codes)
            print(f"[정보] 대상 종목 {len(codes)}건", flush=True)
            now = datetime.now(KST)
            for i, code in enumerate(codes, start=1):
                try:
                    days = usable_days(extract_rows(client.investor(code)), now, args.include_today)
                    consecutive_errors = 0
                    if days:
                        stats["rows_upserted"] += upsert_days(session, code, days)
                        stats["stocks_with_rows"] += 1
                except KisError as exc:
                    stats["errors"] += 1
                    consecutive_errors += 1
                    if len(error_samples) < 10:
                        error_samples.append(f"{code}: {exc.code}")
                    if exc.code == "NOT_CONFIGURED":
                        raise
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        print(f"[실패] 연속 {consecutive_errors}건 실패로 중단합니다(증권사 접속·앱키 확인).", file=sys.stderr)
                        session.commit()
                        return 1
                if i % COMMIT_EVERY == 0:
                    session.commit()
                    print(f"[진행] {i}/{len(codes)}", flush=True)
            session.commit()
    except KisError as exc:
        print(f"[실패] 증권사 설정 오류: {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:  # DB 접속 실패 등. 접속 문자열(비밀번호)이 섞이지 않게 종류만 출력.
        print(f"[실패] {type(exc).__name__}: 수집을 중단했습니다.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        f"[완료] 종목 {stats['stocks']}건 / 값이 있는 종목 {stats['stocks_with_rows']}건 / "
        f"적재 행 {stats['rows_upserted']}건 / 오류 {stats['errors']}건"
    )
    for sample in error_samples:
        print(f"  오류 예: {sample}")
    return 0 if stats["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
