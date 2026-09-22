#!/usr/bin/env python
"""Ingestion Batch 실행 CLI (REQ-011).

03-system-design.md §1-2: "공공데이터포털 API를 호출해 원본 OHLCV를
raw_internal.raw_ohlcv에 적재한다. 이 컴포넌트만 외부 데이터 소스와
통신한다." §2-1: 호스팅 플랫폼의 Scheduled Job 또는 cron 컨테이너가 하루
1~2회 이 스크립트를 실행하는 것을 전제로 설계했다.

사용법:
    python -m services.ingestion_batch.run_ingestion
    python -m services.ingestion_batch.run_ingestion --trade-date 2026-09-11
    python -m services.ingestion_batch.run_ingestion --dry-run

MVP는 KRX 정규장 세션만 다룬다(DEC-010 — NXT 데이터 커버리지 미확인).

+1영업일 지연 처리(REQ-011)에 대한 설계 노트(unit-02-note.md §2 참조):
설계서(§2-2)는 "하루 1~2회 배치 호출"이라고만 되어 있고, 공공데이터포털이
실제로 기준일자 데이터를 정확히 언제(영업일+1 오후 몇 시) 배포하는지는 이
프로젝트가 조사한 2차 출처(01-trend-analysis.md)에서도 "확인 필요"로 남아
있다. 이 스크립트는 정확한 배포 시각을 하드코딩해 추측하는 대신, API가
실제로 반환하는 결과(0건이면 "아직 배포되지 않음")를 근거로 판단한다 —
운영자가 cron 실행 시각을 잘못 잡아도 조용히 빈 데이터를 성공으로 기록하지
않고 명시적으로 FAILED 처리한다(REQ-005/012 전반의 "명시적 실패" 원칙과 동일).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.ingestion_batch.batch_run_repository import (  # noqa: E402
    finish_run,
    recent_ingest_statuses,
    start_run,
)
from services.ingestion_batch.calendar_lookup import SqlCalendarRepository  # noqa: E402
from services.ingestion_batch.circuit_breaker import (  # noqa: E402
    evaluate as evaluate_circuit_breaker,
)
from services.ingestion_batch.core.config import ConfigError, get_settings  # noqa: E402
from services.ingestion_batch.gov_data_client import (  # noqa: E402
    FetchResult,
    FundamentalsFetchResult,
    GovDataApiError,
    GovDataClientError,
    GovDataPortalClient,
)
from services.ingestion_batch.repository import upsert_fundamentals, upsert_ohlcv  # noqa: E402
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day  # noqa: E402
from shared.calendar_service.types import CalendarLookup  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
INGEST_MARKET = "KRX"  # MVP 범위: KRX 정규장만 (DEC-010)
CIRCUIT_BREAKER_THRESHOLD = 3

# 2026-09-22 실 서비스키로 최초 실행해 발견한 결함: 전 종목이 약 2,867건인데
# 기본 num_of_rows=1000 한 페이지만 가져오고 페이지네이션을 전혀 하지 않아
# 65% 가까이 누락된 채 PARTIAL로 끝났다(unit-02-note.md §3이 "실 데이터
# 규모를 몰라 배선을 보류"라고 명시했던 그 갭). scripts/seed_stock_master.py의
# 페이지네이션 패턴(PAGE_SIZE/MAX_PAGES)을 그대로 따른다.
PAGE_SIZE = 1000
MAX_PAGES = 10


class IngestionRunError(RuntimeError):
    """이번 실행이 실패했음을 나타낸다(배치 프로세스 자체는 계속 정상 종료 흐름을 탄다)."""


def _fetch_all_ohlcv(client: GovDataPortalClient, trade_date: date) -> FetchResult:
    records = []
    page_no = 1
    total_count = 0
    while True:
        result = client.fetch_ohlcv(trade_date, page_no=page_no, num_of_rows=PAGE_SIZE)
        total_count = result.total_count
        records.extend(result.records)
        if len(records) >= total_count:
            break
        if page_no >= MAX_PAGES:
            raise IngestionRunError(
                f"OHLCV 페이지 상한({MAX_PAGES})에 도달했지만 아직 totalCount"
                f"({total_count})에 도달하지 못했습니다(현재까지 {len(records)}건). "
                "PAGE_SIZE/MAX_PAGES 조정이 필요합니다."
            )
        page_no += 1
    return FetchResult(records=records, total_count=total_count)


def _fetch_all_fundamentals(
    client: GovDataPortalClient, trade_date: date
) -> FundamentalsFetchResult:
    records = []
    page_no = 1
    total_count = 0
    while True:
        result = client.fetch_fundamentals(trade_date, page_no=page_no, num_of_rows=PAGE_SIZE)
        total_count = result.total_count
        records.extend(result.records)
        if len(records) >= total_count:
            break
        if page_no >= MAX_PAGES:
            raise IngestionRunError(
                f"재무지표 페이지 상한({MAX_PAGES})에 도달했지만 아직 totalCount"
                f"({total_count})에 도달하지 못했습니다(현재까지 {len(records)}건). "
                "PAGE_SIZE/MAX_PAGES 조정이 필요합니다."
            )
        page_no += 1
    return FundamentalsFetchResult(records=records, total_count=total_count)


def resolve_target_trade_date(calendar: CalendarLookup, *, override: date | None) -> date:
    if override is not None:
        return override

    now = datetime.now(KST)
    trade_date = get_last_trading_day(INGEST_MARKET, now, calendar)
    if trade_date is None:
        raise IngestionRunError(
            "휴장일 캘린더가 아직 갱신되지 않아 대상 거래일을 계산할 수 없습니다. "
            "scripts/load_calendar.py로 캘린더를 먼저 적재하세요."
        )
    return trade_date


def run_once(
    session: Session,
    client: GovDataPortalClient,
    *,
    trade_date_override: date | None,
) -> tuple[str, date | None, str | None]:
    """한 번의 배치 실행을 수행하고 (status, trade_date_covered, error_summary)를 반환한다.

    실행 결과와 무관하게(캘린더 미확인 실패 포함) 항상 batch_run 행을 정확히 1개
    기록한다 — 서킷브레이커(circuit_breaker.py)가 연속 실패를 판단하려면 실패한
    시도도 빠짐없이 기록되어야 하기 때문이다(§5-4).
    """
    batch_run_id = start_run(session)
    session.flush()

    try:
        target_date = resolve_target_trade_date(
            SqlCalendarRepository(session), override=trade_date_override
        )
    except (IngestionRunError, CalendarIntegrityError) as exc:
        finish_run(
            session,
            batch_run_id,
            status="FAILED",
            trade_date_covered=None,
            validation_passed=False,
            error_summary=str(exc),
        )
        return "FAILED", None, str(exc)

    try:
        result = _fetch_all_ohlcv(client, target_date)
    except (GovDataApiError, GovDataClientError, IngestionRunError) as exc:
        error_summary = f"API 호출 실패: {exc}"
        finish_run(
            session,
            batch_run_id,
            status="FAILED",
            trade_date_covered=target_date,
            validation_passed=False,
            error_summary=error_summary,
        )
        return "FAILED", target_date, error_summary

    if not result.records:
        error_summary = (
            "대상 거래일 데이터가 0건 반환되었습니다(공공데이터포털 +1영업일 지연 특성상 "
            "아직 배포되지 않았을 가능성 — 배치 실행 시각을 확인하세요)."
        )
        finish_run(
            session,
            batch_run_id,
            status="FAILED",
            trade_date_covered=target_date,
            validation_passed=False,
            error_summary=error_summary,
        )
        return "FAILED", target_date, error_summary

    affected = upsert_ohlcv(
        session, result.records, market=INGEST_MARKET, source_batch_id=batch_run_id
    )
    validation_passed = affected == result.total_count
    status = "SUCCESS" if validation_passed else "PARTIAL"
    error_summary = (
        None
        if validation_passed
        else f"수신 {affected}건 / API totalCount {result.total_count}건 — 일부 누락 가능성"
    )

    # 재무지표(시가총액) 수집은 OHLCV와 같은 오퍼레이션을 재호출해 별도로
    # 처리한다(§0 docstring — 새 외부 API 추가 없음, fetch_stock_master_snapshot과
    # 동일 패턴). PER/PBR은 이 오퍼레이션이 제공하지 않아 항상 None으로
    # 적재된다(gov_data_client.py DEF-005 정정 참조). 이 단계 실패는 OHLCV
    # 성공 여부(핵심 시세/스크리닝 기능)를 함께 FAILED로 끌어내리지 않는다 —
    # 재무지표는 raw_fundamentals가 애초에 전 컬럼 nullable로 설계된 "있으면
    # 쓰고 없어도 되는" 보조 데이터이기 때문이다(모델 docstring 참조).
    try:
        fundamentals_result = _fetch_all_fundamentals(client, target_date)
        upsert_fundamentals(
            session, fundamentals_result.records, source_batch_id=batch_run_id
        )
    except (GovDataApiError, GovDataClientError, IngestionRunError) as exc:
        fundamentals_warning = f"재무지표(raw_fundamentals) 수집 실패(OHLCV는 정상 반영됨): {exc}"
        error_summary = (
            f"{error_summary}; {fundamentals_warning}" if error_summary else fundamentals_warning
        )

    finish_run(
        session,
        batch_run_id,
        status=status,
        trade_date_covered=target_date,
        validation_passed=validation_passed,
        error_summary=error_summary,
    )
    return status, target_date, error_summary


def _record_failed_run(
    session: Session, *, trade_date_covered: date | None, error_summary: str
) -> None:
    batch_run_id = start_run(session)
    session.flush()
    finish_run(
        session,
        batch_run_id,
        status="FAILED",
        trade_date_covered=trade_date_covered,
        validation_passed=False,
        error_summary=error_summary,
    )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trade-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="수동 지정 대상 거래일(YYYY-MM-DD). 생략 시 캘린더로 자동 계산.",
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
        print("  BATCH_DATABASE_URL: 설정됨")
        print(f"  GOV_DATA_PORTAL_BASE_URL: {settings.gov_data_portal_base_url}")
        print(
            f"  GOV_DATA_PORTAL_SERVICE_KEY: "
            f"{'설정됨' if settings.gov_data_portal_service_key else '미설정(dry-run이라 허용)'}"
        )
        return 0

    engine = create_engine(settings.database_url)
    with (
        Session(engine) as session,
        GovDataPortalClient(
            base_url=settings.gov_data_portal_base_url,
            service_key=settings.gov_data_portal_service_key,  # type: ignore[arg-type]
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
        ) as client,
    ):
        try:
            status, trade_date_covered, error_summary = run_once(
                session, client, trade_date_override=args.trade_date
            )
            session.commit()
        except Exception as exc:  # DB/네트워크 계층의 예기치 못한 예외도 명시적으로 기록
            session.rollback()
            _record_failed_run(
                session,
                trade_date_covered=args.trade_date,
                error_summary=f"예기치 못한 오류: {exc}",
            )
            session.commit()
            print(f"[실패] {exc}", file=sys.stderr)
            return 1

        breaker = evaluate_circuit_breaker(
            recent_ingest_statuses(session, CIRCUIT_BREAKER_THRESHOLD),
            threshold=CIRCUIT_BREAKER_THRESHOLD,
        )
        if breaker.is_open:
            print(
                f"[고위험 알림] Ingestion Batch가 {breaker.consecutive_failures}일 연속 "
                "실패했습니다. 운영자 수동 개입이 필요합니다(§5-4).",
                file=sys.stderr,
            )

        if status == "FAILED":
            print(f"[실패] trade_date={trade_date_covered} {error_summary}", file=sys.stderr)
            return 1

        print(f"[완료] status={status} trade_date={trade_date_covered}")
        if error_summary:
            print(f"  경고: {error_summary}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
