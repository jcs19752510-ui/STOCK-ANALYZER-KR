#!/usr/bin/env python
"""증권사(KIS) 일봉 보충 캐시 적재 — 소유자 PC 전용 (DEC-097).

발행 일봉(공공데이터, 발행 거래일 P)이 직전 거래일(E)보다 뒤처지면 장중 재계산이 빠진 날(P 초과 ~ E 이하)을 증권사 일봉으로 메운다.
이 스크립트는 그 일봉을 `public_serving.kis_daily_bar`에 미리 적재해 서버를 다시 켜도 종목마다 재조회하지 않게 한다(확정 값 아님).

- P >= E 이면 호출 없이 캐시 정리(trade_date <= P 행 삭제)만 하고 종료한다.
- 아니면 발행 일봉이 P에 있는 종목마다 `KisClient.daily_price` → `normalize_daily_price`로 P 이상 E 이하 행을 upsert한다
  (P 행은 교차검증 기준이라 포함). P..E 필요한 거래일이 이미 모두 캐시에 있는 종목은 건너뛴다(증분).
- 한 종목 실패는 경고만 하고 계속한다(최대 2회 재시도). 마지막에 항상 trade_date <= P 행을 지운다(확정 데이터가 대신함).

사용법:
    py -3.12 scripts/collect_kis_daily_bars.py [--dry-run] [--limit N]

필요: KIS_APP_KEY·KIS_APP_SECRET(환경변수 또는 `.env`), BATCH_DATABASE_URL(환경변수). 값은 출력하지 않는다.
종료코드: 0 정상 / 1 설정·인증·DB 실패 / 2 일부 종목 실패.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, delete, func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts.collect_investor_flow import load_kis_keys_from_dotenv  # noqa: E402
from services.public_api.intraday.config import IntradayConfigError, get_settings  # noqa: E402
from services.public_api.intraday.kis_client import KisClient, KisError  # noqa: E402
from services.public_api.intraday.normalize import normalize_daily_price  # noqa: E402
from shared.calendar_service import get_last_trading_day  # noqa: E402
from shared.calendar_service.sql_repository import SqlCalendarRepository  # noqa: E402
from shared.db_models.public_serving import (  # noqa: E402
    CurrentPublishedBatch,
    DailyPrice,
    KisDailyBar,
)

KST = ZoneInfo("Asia/Seoul")
MARKET = "KRX"
MAX_RETRIES = 2  # 첫 시도 외 재시도 횟수
RETRY_DELAY_SEC = 3.0
COMMIT_EVERY = 100
MAX_CONSECUTIVE_ERRORS = 20


def trading_days_between(calendar, start_exclusive: date, end_inclusive: date) -> list[date]:
    """(start, end] 구간의 거래일(캘린더 기준, 오름차순)."""
    days: list[date] = []
    day = start_exclusive + timedelta(days=1)
    while day <= end_inclusive:
        row = calendar.get(day, MARKET)
        if row is not None and row.is_trading_day:
            days.append(day)
        day += timedelta(days=1)
    return days


def purge_published(session: Session, published: date) -> int:
    """확정 데이터가 대신하는 trade_date <= P 행을 지운다. 지운 행 수."""
    res = session.execute(delete(KisDailyBar).where(KisDailyBar.trade_date <= published))
    return res.rowcount or 0


def codes_published_on(session: Session, published: date) -> list[str]:
    return list(
        session.execute(
            select(DailyPrice.stock_code)
            .where(DailyPrice.trade_date == published)
            .order_by(DailyPrice.stock_code)
        ).scalars()
    )


def cached_dates(session: Session, required: list[date]) -> dict[str, set[date]]:
    out: dict[str, set[date]] = {}
    for code, day in session.execute(
        select(KisDailyBar.stock_code, KisDailyBar.trade_date).where(
            KisDailyBar.trade_date.in_(required)
        )
    ):
        out.setdefault(code, set()).add(day)
    return out


def pending_codes(codes: list[str], cache: dict[str, set[date]], required: list[date]) -> list[str]:
    """필요한 날짜(P 포함)가 캐시에 전부 있는 종목은 뺀다(증분)."""
    need = set(required)
    return [c for c in codes if not need <= cache.get(c, set())]


def upsert_bars(session: Session, code: str, bars: list) -> int:
    for b in bars:
        stmt = pg_insert(KisDailyBar).values(
            stock_code=code,
            trade_date=b.trade_date,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[KisDailyBar.stock_code, KisDailyBar.trade_date],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "fetched_at": func.now(),
                },
            )
        )
    return len(bars)


def fetch_bars(
    client,
    code: str,
    published: date,
    expected: date,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list:
    """일봉 조회(재시도 포함) → P 이상 E 이하 DailyBar. 끝내 실패하면 마지막 예외를 올린다."""
    last: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            body = client.daily_price(code)
            raw = body.get("output") if isinstance(body, dict) else None
            rows = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
            return [b for b in normalize_daily_price(rows) if published <= b.trade_date <= expected]
        except KisError as exc:
            if exc.code == "NOT_CONFIGURED":
                raise
            last = exc
        except Exception as exc:  # 네트워크 등 일시 오류
            last = exc
        if attempt < MAX_RETRIES:
            sleep(RETRY_DELAY_SEC)
    assert last is not None
    raise last


def collect(
    session: Session,
    client,
    codes: list[str],
    published: date,
    expected: date,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, int], list[str]]:
    """대상 종목을 조회·적재한다. (통계, 오류 예) — 연속 실패가 많으면 통계에 aborted=1."""
    stats = {"stocks": len(codes), "skipped": 0, "fetched": 0, "rows": 0, "errors": 0, "aborted": 0}
    samples: list[str] = []
    todo_days = [
        published,
        *trading_days_between(SqlCalendarRepository(session), published, expected),
    ]
    todo = pending_codes(codes, cached_dates(session, todo_days), todo_days)
    stats["skipped"] = len(codes) - len(todo)
    consecutive = 0
    for i, code in enumerate(todo, start=1):
        try:
            bars = fetch_bars(client, code, published, expected, sleep=sleep)
            consecutive = 0
            stats["fetched"] += 1
            stats["rows"] += upsert_bars(session, code, bars)
        except KisError as exc:
            if exc.code == "NOT_CONFIGURED":
                raise
            stats["errors"] += 1
            consecutive += 1
            if len(samples) < 10:
                samples.append(f"{code}: {exc.code}")
        except Exception as exc:
            stats["errors"] += 1
            consecutive += 1
            if len(samples) < 10:
                samples.append(f"{code}: {type(exc).__name__}")
        if consecutive >= MAX_CONSECUTIVE_ERRORS:
            stats["aborted"] = 1
            break
        if i % COMMIT_EVERY == 0:
            session.commit()
            print(f"[진행] {i}/{len(todo)}", flush=True)
    session.commit()
    return stats, samples


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="처리 종목 수 상한(시험용).")
    parser.add_argument(
        "--dry-run", action="store_true", help="대상만 계산해 출력하고 호출·반영 안 함."
    )
    args = parser.parse_args(argv)

    load_kis_keys_from_dotenv(REPO_ROOT / ".env")
    db_url = os.environ.get("BATCH_DATABASE_URL", "").strip()
    if not db_url:
        print("[실패] BATCH_DATABASE_URL 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        return 1

    engine = create_engine(db_url)
    try:
        with Session(engine) as session:
            published_row = session.get(CurrentPublishedBatch, MARKET)
            if published_row is None:
                print("[정보] 발행된 데이터가 없어 할 일이 없습니다.")
                return 0
            published: date = published_row.trade_date
            expected = get_last_trading_day(
                MARKET, datetime.now(KST), SqlCalendarRepository(session)
            )
            if expected is None:
                print("[실패] 휴장일 캘린더로 직전 거래일을 계산할 수 없습니다.", file=sys.stderr)
                return 1
            if published >= expected:
                if args.dry_run:
                    print(
                        f"(--dry-run) 발행일 {published} >= 직전 거래일 {expected}: 정리만 필요합니다."
                    )
                    return 0
                purged = purge_published(session, published)
                session.commit()
                print(
                    f"[완료] 발행일 {published} >= 직전 거래일 {expected}: 보충 불필요. 캐시 정리 {purged}행."
                )
                return 0

            try:
                settings = get_settings()
            except IntradayConfigError as exc:
                print(f"[실패] {exc}", file=sys.stderr)
                return 1
            if not settings.configured:
                print(
                    "[실패] KIS_APP_KEY·KIS_APP_SECRET 환경변수가 설정되지 않았습니다.",
                    file=sys.stderr,
                )
                return 1

            codes = codes_published_on(session, published)
            if args.limit is not None:
                codes = codes[: args.limit]
            print(
                f"[정보] 발행일 {published} → 직전 거래일 {expected}, 대상 종목 {len(codes)}건",
                flush=True,
            )
            if args.dry_run:
                days = [
                    published,
                    *trading_days_between(SqlCalendarRepository(session), published, expected),
                ]
                todo = pending_codes(codes, cached_dates(session, days), days)
                print(
                    f"(--dry-run) 조회 대상 {len(todo)}건(캐시에 이미 있는 {len(codes) - len(todo)}건 제외). 호출/반영은 하지 않았습니다."
                )
                return 0

            stats, samples = collect(session, KisClient(settings), codes, published, expected)
            purged = purge_published(session, published)
            session.commit()
    except KisError as exc:
        print(f"[실패] 증권사 설정 오류: {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:  # 접속 문자열(비밀번호)이 섞이지 않게 종류만 출력.
        print(f"[실패] {type(exc).__name__}: 수집을 중단했습니다.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        f"[완료] 종목 {stats['stocks']}건 / 건너뜀(캐시) {stats['skipped']}건 / 조회 {stats['fetched']}건 / "
        f"적재 행 {stats['rows']}건 / 오류 {stats['errors']}건 / 캐시 정리 {purged}행"
    )
    for sample in samples:
        print(f"  오류 예: {sample}")
    if stats["aborted"]:
        print(
            f"[실패] 연속 {MAX_CONSECUTIVE_ERRORS}건 실패로 중단했습니다(증권사 접속·앱키 확인).",
            file=sys.stderr,
        )
    return 0 if stats["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
