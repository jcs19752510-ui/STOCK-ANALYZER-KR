#!/usr/bin/env python
"""데이터 신선도 점검 (03-system-design.md §7-2, DEC-047).

`current_published_batch`의 거래일이 기대 거래일보다 `--max-lag`거래일을 넘게 뒤처졌는지 확인한다.
공공데이터가 +1영업일에 배포되므로 기본 허용 지연은 1거래일이다. 지연이면 종료코드 1과 함께
`DATA_FRESHNESS_WEBHOOK_URL`(Slack/Discord 호환 `{"text": ...}`)이 설정돼 있으면 알림을 보낸다.
읽기 전용(DB 쓰기 없음)이라 하루 몇 번을 실행해도 안전하다.

사용법: python scripts/check_data_freshness.py [--max-lag 1] [--no-notify]
환경변수: BATCH_DATABASE_URL(필수), DATA_FRESHNESS_WEBHOOK_URL(선택)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

KST = ZoneInfo("Asia/Seoul")


def lag_in_trading_days(trading_dates: list[date], published: date, expected: date) -> int:
    """기대 거래일과 발행 거래일 사이의 거래일 수(같으면 0). 순수 함수."""
    return sum(1 for d in trading_dates if published < d <= expected)


def build_message(published: date | None, expected: date, lag: int | None) -> str:
    if published is None:
        return f"[데이터 지연] 발행된 배치가 없습니다(기대 거래일 {expected})."
    return f"[데이터 지연] 최신 발행 {published} / 기대 {expected} — {lag}거래일 지연."


def _notify(url: str, text: str) -> None:
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10):  # noqa: S310 (운영자가 지정한 https 웹훅)
        pass


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-lag", type=int, default=1, help="허용 지연(거래일). 기본 1")
    parser.add_argument("--no-notify", action="store_true", help="웹훅 알림을 보내지 않는다")
    args = parser.parse_args(argv)

    url = os.environ.get("BATCH_DATABASE_URL")
    if not url:
        print("[실패] 환경변수 BATCH_DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 1

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from services.ingestion_batch.calendar_lookup import SqlCalendarRepository
    from shared.batch_catchup import fetch_trading_dates
    from shared.calendar_service import get_last_trading_day
    from shared.db_models.public_serving import CurrentPublishedBatch

    with Session(create_engine(url)) as session:
        expected = get_last_trading_day("KRX", datetime.now(KST), SqlCalendarRepository(session))
        if expected is None:
            print("[실패] 캘린더 미갱신으로 기대 거래일을 계산할 수 없습니다.", file=sys.stderr)
            return 1
        published = session.execute(
            select(CurrentPublishedBatch.trade_date).where(CurrentPublishedBatch.market == "KRX")
        ).scalar_one_or_none()
        if published is None:
            lag = None
        else:
            dates = fetch_trading_dates(session, market="KRX", target=expected, max_days=30)
            lag = lag_in_trading_days(dates, published, expected)

    if published is not None and lag is not None and lag <= args.max_lag:
        print(f"[정상] 발행 {published} / 기대 {expected} (지연 {lag}, 허용 {args.max_lag}).")
        return 0

    message = build_message(published, expected, lag)
    print(message, file=sys.stderr)
    webhook = os.environ.get("DATA_FRESHNESS_WEBHOOK_URL", "").strip()
    if webhook and not args.no_notify:
        try:
            _notify(webhook, message)
        except Exception as exc:  # 알림 실패가 점검 결과(종료코드)를 바꾸지 않는다
            print(f"[경고] 웹훅 알림 전송 실패: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
