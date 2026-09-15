#!/usr/bin/env python
"""종목 마스터(`public_serving.stock_master`) 시드 스크립트 (REQ-001).

03-system-design.md §3-5: "초기 시드 데이터: `stock_master`(상장 종목 목록)...
는 배포 전 1회성 시드 스크립트로 적재한다." 다만 이 문서는 시드 데이터의
실제 출처를 명시하지 않았다(코디네이터 지시로 조사한 결과, `docs/harness/
units/unit-03-note.md` §0 참조). 이 스크립트는 새로운 외부 API를 조사해
도입하는 대신, REQ-011이 이미 채택하고 UNIT-02가 연동한 공공데이터포털
"금융위원회_주식시세정보"(`getStockPriceInfo`) 응답에 함께 내려오는
종목명(`itmsNm`)/시장구분(`mrktCtg`) 필드를 재사용한다 —
03-system-design.md §1-2 "Ingestion Batch만 외부 데이터 소스와 통신한다"
원칙에 따라, 실제 HTTP 호출은 이번에도 `GovDataPortalClient`를 통해서만
이뤄진다(`services/ingestion_batch/gov_data_client.py`).

사용법:
    python scripts/seed_stock_master.py --trade-date 2026-09-11
    python scripts/seed_stock_master.py --trade-date 2026-09-11 --dry-run
    python scripts/seed_stock_master.py   # 생략 시 캘린더로 직전 거래일(KRX) 자동 계산

DB 접속 정보는 `BATCH_DATABASE_URL`(batch_worker 역할 — `public_serving` 쓰기
권한, §3-1), 서비스키는 `GOV_DATA_PORTAL_SERVICE_KEY` 환경변수로 받는다
(`services/ingestion_batch/core/config.py` 재사용, 별도 설정 모듈을 새로
만들지 않는다).

이 스크립트는 1회성 시드 목적이라 `public_serving.batch_run`에 실행 이력을
남기지 않는다 — `batch_run_type` ENUM은 'ingest'/'derive'만 허용하며, 이
성격의 작업을 위한 새 값 추가는 이번 유닛 범위를 벗어난 스키마 변경이라
하지 않았다(unit-03-note.md 참조).

명시적 실패 원칙: 캘린더 미확인, API 오류, 응답 0건, DB 반영 실패 등 어떤
단계에서든 조용히 넘어가지 않고 0이 아닌 종료 코드와 에러 메시지를 남긴다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, func  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.ingestion_batch.calendar_lookup import SqlCalendarRepository  # noqa: E402
from services.ingestion_batch.core.config import ConfigError, get_settings  # noqa: E402
from services.ingestion_batch.gov_data_client import (  # noqa: E402
    GovDataApiError,
    GovDataClientError,
    GovDataPortalClient,
    StockMasterSnapshotRecord,
)
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day  # noqa: E402
from shared.calendar_service.types import CalendarLookup  # noqa: E402
from shared.db_models.public_serving import StockMaster  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
# 직전 거래일 계산용 거래소 세션 구분(§3-1-1) — 상장시장 구분과는 무관하다.
# run_ingestion.py(DEC-010)와 동일하게 MVP는 KRX 정규장 기준으로 판단한다.
CALENDAR_MARKET = "KRX"
PAGE_SIZE = 1000
# 코스피+코스닥 약 2,500종목(03-system-design.md §2-1) 규모에서 넉넉한 안전
# 상한 — API가 totalCount를 계속 과대 보고하는 등 이상 상황에서 무한루프에
# 빠지지 않도록 방어한다.
MAX_PAGES = 10


class SeedStockMasterError(RuntimeError):
    pass


def resolve_target_trade_date(calendar: CalendarLookup, *, override: date | None) -> date:
    if override is not None:
        return override
    now = datetime.now(KST)
    trade_date = get_last_trading_day(CALENDAR_MARKET, now, calendar)
    if trade_date is None:
        raise SeedStockMasterError(
            "휴장일 캘린더가 아직 갱신되지 않아 대상 거래일을 계산할 수 없습니다. "
            "scripts/load_calendar.py로 캘린더를 먼저 적재하거나 --trade-date를 지정하세요."
        )
    return trade_date


def fetch_all_records(
    client: GovDataPortalClient, trade_date: date
) -> list[StockMasterSnapshotRecord]:
    """API의 totalCount 기준으로 필요한 만큼 페이지를 반복 호출해 전 종목을 수집한다.

    run_ingestion.py는 실 데이터 규모를 확인하지 못해 페이지네이션 배선을
    보류했지만(unit-02-note.md §3), 이 스크립트는 전 종목 목록이 반드시
    필요하므로 처음부터 배선한다.
    """
    records: list[StockMasterSnapshotRecord] = []
    page_no = 1
    total_count = 0
    while True:
        result = client.fetch_stock_master_snapshot(
            trade_date, page_no=page_no, num_of_rows=PAGE_SIZE
        )
        total_count = result.total_count
        records.extend(result.records)
        if page_no >= MAX_PAGES:
            raise SeedStockMasterError(
                f"페이지 상한({MAX_PAGES})에 도달했지만 아직 totalCount({total_count})에 "
                f"도달하지 못했습니다(현재까지 조회 {page_no * PAGE_SIZE}건). "
                "PAGE_SIZE/MAX_PAGES 조정이 필요합니다."
            )
        if page_no * PAGE_SIZE >= total_count:
            break
        page_no += 1
    return records


def upsert_stock_master(session: Session, records: list[StockMasterSnapshotRecord]) -> int:
    """(stock_code) 충돌 시 name/market/is_active/updated_at만 갱신한다.

    sector/listing_date는 이 데이터 소스에서 얻을 수 없어(unit-03-note.md §0
    참조) SET 절에서 제외한다 — 향후 별도 출처로 채워질 값을 이 스크립트
    재실행이 덮어쓰지 않도록 하기 위함이다. 응답에 없는(=상장폐지 가능성이
    있는) 기존 종목의 `is_active`를 자동으로 false로 전환하지는 않는다(REQ-001
    요구사항에 상장폐지 자동 감지가 명시되어 있지 않음 — unit-03-note.md
    "수동으로 확인이 필요한 부분" 참조).
    """
    affected = 0
    for record in records:
        stmt = pg_insert(StockMaster).values(
            stock_code=record.stock_code,
            name=record.name,
            market=record.market,
            is_active=True,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[StockMaster.stock_code],
            set_={
                "name": stmt.excluded.name,
                "market": stmt.excluded.market,
                "is_active": True,
                # DEF-004(unit-01-test.md) 재발 방지: 내용이 갱신될 때
                # updated_at도 함께 갱신한다. Core upsert 경로에서는 모델
                # 컬럼의 onupdate가 트리거되지 않으므로 set_에 명시해야 한다.
                "updated_at": func.now(),
            },
        )
        session.execute(stmt)
        affected += 1
    return affected


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trade-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="시드에 사용할 거래일(YYYY-MM-DD). 생략 시 캘린더로 자동 계산.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="설정만 검증하고 실제 API 호출/DB 반영은 하지 않는다.",
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings(require_service_key=not args.dry_run)
    except ConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("(--dry-run) 설정 확인 완료. 실제 API 호출/DB 반영은 하지 않았습니다.")
        print(f"  GOV_DATA_PORTAL_BASE_URL: {settings.gov_data_portal_base_url}")
        print(
            f"  GOV_DATA_PORTAL_SERVICE_KEY: "
            f"{'설정됨' if settings.gov_data_portal_service_key else '미설정(dry-run이라 허용)'}"
        )
        return 0

    trade_date: date | None = None
    engine = create_engine(settings.database_url)
    try:
        with (
            Session(engine) as session,
            GovDataPortalClient(
                base_url=settings.gov_data_portal_base_url,
                service_key=settings.gov_data_portal_service_key,  # type: ignore[arg-type]
                timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.max_retries,
            ) as client,
        ):
            trade_date = resolve_target_trade_date(
                SqlCalendarRepository(session), override=args.trade_date
            )
            records = fetch_all_records(client, trade_date)
            if not records:
                print(
                    "[실패] 조회 결과가 0건입니다(대상 거래일 데이터 미배포 가능성 — "
                    "+1영업일 지연, unit-02-note.md §2 참조). --trade-date로 다른 "
                    "거래일을 지정해 보세요.",
                    file=sys.stderr,
                )
                return 1
            affected = upsert_stock_master(session, records)
            session.commit()
    except (
        SeedStockMasterError,
        CalendarIntegrityError,
        GovDataApiError,
        GovDataClientError,
    ) as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # DB/네트워크 계층의 예기치 못한 예외도 명시적으로 알린다
        print(f"[실패] 예기치 못한 오류: {exc}", file=sys.stderr)
        return 1

    print(
        f"[완료] trade_date={trade_date} {affected}건을 "
        "public_serving.stock_master에 반영했습니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
