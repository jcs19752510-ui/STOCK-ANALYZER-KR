#!/usr/bin/env python
"""DART 연간 실적(매출액·영업이익·당기순이익) 수집 — 종목 상세 실적 탭용 (DEC-041, UNIT-23).

종목마다 DART `단일회사 전체 재무제표`(사업보고서, 11011)를 **1회** 호출하면 당기·전기·전전기
3개 연도가 함께 오므로, 한 종목당 최근 3개 연도 실적이 `public_serving.corp_earnings`에 쌓인다
(연결(CFS) 우선, 없으면 개별(OFS)). 찾지 못한 항목은 NULL(0으로 채우지 않는다). 금융회사처럼 표준
매출 계정이 없는 업종은 매출이 NULL로 남는다.

재수집 시점: 사업보고서는 사업연도 종료 후 90일 이내 제출(법정). 매년 4월 5일경 이후 1회
실행하면 된다(`resolve_bsns_year`가 오늘 날짜로 대상 연도를 고른다). 같은 (종목, 연도)는
멱등 upsert로 덮어쓴다.

사용법:
    py -3.12 scripts/enrich_earnings.py --limit 20      # 검증용 소규모 실행
    py -3.12 scripts/enrich_earnings.py                  # 전 종목(DART 호출 약 3,000회)
    py -3.12 scripts/enrich_earnings.py --dry-run

DART_API_KEY·BATCH_DATABASE_URL(환경변수) 필요. 종목 단위 오류는 건너뛰고 요약에 집계하며,
키 미설정·DB 접속 실패 같은 전체 오류는 0이 아닌 종료 코드로 실패한다. 200종목마다
커밋하므로 중단돼도 그 시점까지는 남고 재실행해도 안전하다. 인증키는 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.ingestion_batch.core.config import ConfigError, get_settings  # noqa: E402
from services.ingestion_batch.dart_client import (  # noqa: E402
    DartApiError,
    DartClient,
    DartClientError,
)
from services.ingestion_batch.repository import upsert_annual_earnings  # noqa: E402
from shared.db_models.public_serving import StockMaster  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
COMMIT_EVERY = 200
ANNUAL_REPORT_DEADLINE = (4, 5)  # 사업보고서 법정 기한(3/31) + 지각 제출 여유


def resolve_bsns_year(today: datetime) -> str:
    """오늘 기준 가장 최근에 제출됐을 사업보고서의 사업연도(4/5 이전이면 재작년)."""
    if (today.month, today.day) >= ANNUAL_REPORT_DEADLINE:
        return str(today.year - 1)
    return str(today.year - 2)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bsns-year", default=None, help="대상 사업연도(YYYY). 생략 시 자동.")
    parser.add_argument("--limit", type=int, default=None, help="처리 종목 수 상한(검증용).")
    parser.add_argument("--dry-run", action="store_true", help="설정만 확인하고 호출·반영 안 함.")
    args = parser.parse_args(argv)

    try:
        settings = get_settings(require_service_key=False, require_dart_key=not args.dry_run)
    except ConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    bsns_year = args.bsns_year or resolve_bsns_year(datetime.now(KST))
    if args.dry_run:
        print(
            f"(--dry-run) 설정 확인 완료. 대상 사업연도={bsns_year}. 호출/반영은 하지 않았습니다."
        )
        return 0
    print(f"[정보] 대상 사업연도={bsns_year}(당기·전기·전전기 3개 연도 수집)")

    stats = {
        "active_stocks": 0,
        "skipped_no_corp_code": 0,
        "stocks_with_earnings": 0,
        "year_rows_upserted": 0,
        "skipped_no_report": 0,
        "errors": 0,
    }
    error_samples: list[str] = []
    engine = create_engine(settings.database_url)
    try:
        with (
            Session(engine) as session,
            DartClient(
                api_key=settings.dart_api_key,  # type: ignore[arg-type]
                timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.max_retries,
            ) as client,
        ):
            codes = (
                session.execute(
                    select(StockMaster.stock_code)
                    .where(StockMaster.is_active.is_(True))
                    .order_by(StockMaster.stock_code)
                )
                .scalars()
                .all()
            )
            if args.limit is not None:
                codes = codes[: args.limit]
            stats["active_stocks"] = len(codes)
            corp_map = client.fetch_corp_code_map()
            print(f"[정보] 활성 종목 {len(codes)}건, DART 고유번호 {len(corp_map)}건", flush=True)

            for i, stock_code in enumerate(codes, start=1):
                corp_code = corp_map.get(stock_code)
                if not corp_code:
                    stats["skipped_no_corp_code"] += 1
                    continue
                try:
                    records = client.fetch_annual_earnings(
                        corp_code, bsns_year=bsns_year, fs_div="CFS"
                    )
                    if not records:
                        records = client.fetch_annual_earnings(
                            corp_code, bsns_year=bsns_year, fs_div="OFS"
                        )
                    if records:
                        stats["year_rows_upserted"] += upsert_annual_earnings(
                            session, stock_code, records
                        )
                        stats["stocks_with_earnings"] += 1
                    else:
                        stats["skipped_no_report"] += 1
                except (DartApiError, DartClientError) as exc:
                    stats["errors"] += 1
                    if len(error_samples) < 10:
                        error_samples.append(f"{stock_code}: {exc}")
                if i % COMMIT_EVERY == 0:
                    session.commit()
                    print(f"[진행] {i}/{len(codes)}건 처리, 커밋 완료", flush=True)
            session.commit()
    except Exception as exc:  # DB/네트워크 계층의 예기치 못한 오류도 명시적으로 알린다
        print(f"[실패] 예기치 못한 오류: {exc}", file=sys.stderr)
        return 1

    print("[완료] 결과 요약:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    for line in error_samples:
        print(f"    - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
