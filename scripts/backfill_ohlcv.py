#!/usr/bin/env python
"""과거 일봉(OHLCV) 백필 스크립트 (REQ-031, 02-system-design.md §7).

패턴 스크리닝 지표(REQ-030)는 종목당 최소 80거래일의 일봉이 필요한데 현재 보유분은
대부분 25거래일이다. 이 스크립트는 `reference.market_calendar`의 KRX 거래일을 최신 →
과거 순으로 순회하며 공공데이터포털 시세를 받아 `raw_internal.raw_ohlcv`에 upsert한다.

사용법:
    py -3.12 scripts/backfill_ohlcv.py --dry-run                       # 계획·예상 호출 수만 출력
    py -3.12 scripts/backfill_ohlcv.py --days 130 --sleep 0.3          # 최근 130거래일
    py -3.12 scripts/backfill_ohlcv.py --from 2026-03-23 --to 2026-10-01 --max-calls 400

DB 접속은 `BATCH_DATABASE_URL`(batch_worker), 서비스키는 `GOV_DATA_PORTAL_SERVICE_KEY`
환경변수(`services/ingestion_batch/core/config.py` 재사용)로 받는다. **서비스키는 로그·예외
메시지·`batch_run.error_summary` 어디에도 남기지 않는다**(출력 경로 전부 `mask_secrets` 통과).

재사용(수정하지 않음): `run_ingestion._fetch_all_ohlcv`(페이지네이션), `repository.upsert_ohlcv`,
`GovDataPortalClient`. `run_ingestion.run_once()`는 재무지표·PER/PBR까지 처리하고 날짜마다
`batch_run`을 남기므로 쓰지 않는다(설계서 §7).

`batch_run` 정책(설계서 D-8): 실행 1회당 `run_type='ingest'` 1행을 남기고 `error_summary`가
`BACKFILL`로 시작한다. 서킷브레이커(`recent_ingest_statuses`)는 이 접두 행을 집계에서 제외한다
(`batch_run_repository.BACKFILL_ERROR_SUMMARY_PREFIX`) — 백필이 일일 수집의 연속 실패 판단을
오염시키지 않도록 하기 위함이다. 비정상 종료로 남은 행도 "BACKFILL(진행 중)" 표식으로 제외된다.

멱등·재개: upsert이며 날짜 단위로 커밋한다. 이미 행이 충분한 날짜(활성 종목 수의 90% 이상)는
건너뛰므로 중단 후 재실행하면 남은 날짜만 처리한다. 임시 파일·임시 DB를 만들지 않는다(규칙 K).
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, quote_plus
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.ingestion_batch import run_ingestion  # noqa: E402
from services.ingestion_batch.batch_run_repository import (  # noqa: E402
    BACKFILL_ERROR_SUMMARY_PREFIX,
    finish_run,
    start_run,
)
from services.ingestion_batch.calendar_lookup import SqlCalendarRepository  # noqa: E402
from services.ingestion_batch.core.config import ConfigError, get_settings  # noqa: E402
from services.ingestion_batch.gov_data_client import (  # noqa: E402
    GovDataApiError,
    GovDataClientError,
    GovDataPortalClient,
    RawOhlcvRecord,
)
from services.ingestion_batch.models import RawOhlcv  # noqa: E402
from services.ingestion_batch.repository import upsert_ohlcv  # noqa: E402
from shared.calendar_service import CalendarIntegrityError, get_last_trading_day  # noqa: E402
from shared.db_models.public_serving import BatchRun, StockMaster  # noqa: E402
from shared.db_models.reference import MarketCalendar  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
INGEST_MARKET = "KRX"  # MVP 범위: KRX 정규장만 (DEC-010)
DEFAULT_DAYS = 130  # 목표 이력(기획서 REQ-031: 최소 80, 목표 130거래일)
SUFFICIENT_RATIO = 0.9  # 날짜별 적재 종목 수가 활성 종목의 이 비율 이상이면 "충분"
COVERAGE_MIN_ROWS = 80  # 완료 검증: 이 일수 이상 보유한 종목 비율(설계서 §7)
DEFAULT_SLEEP_SECONDS = 0.3
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5
IN_PROGRESS_SUMMARY = f"{BACKFILL_ERROR_SUMMARY_PREFIX}(진행 중)"
_SERVICE_KEY_PARAM = re.compile(r"(?i)(service_?key=)[^&\s'\"]+")


class BackfillError(RuntimeError):
    """백필 계획·인자·전제 조건 오류(조용히 넘어가지 않고 중단한다)."""


class CallBudgetExceeded(BackfillError):
    """`--max-calls` 상한에 도달했다(실패가 아니라 깨끗한 중단 신호)."""


# ── 비밀 마스킹 ─────────────────────────────────────────────────────────────────
def mask_secrets(message: str, service_key: str | None) -> str:
    """메시지에서 서비스키(원문·URL 인코딩 형태)와 `serviceKey=` 쿼리 값을 가린다."""
    masked = _SERVICE_KEY_PARAM.sub(r"\1***", message)
    if service_key:
        for variant in {service_key, quote(service_key, safe=""), quote_plus(service_key)}:
            masked = masked.replace(variant, "***")
    return masked


# ── 대상 날짜 선택·건너뜀 판정·호출 수 추정 (순수 함수) ──────────────────────────
def choose_target_dates(
    trading_days: list[date],
    *,
    days: int | None,
    date_from: date | None,
    date_to: date | None,
    last_closed_day: date,
) -> list[date]:
    """KRX 거래일 목록에서 백필 대상을 최신순으로 고른다.

    `--from`이 없으면 `--to`(기본: 마지막 마감 거래일) 이전 최근 `days`(기본 130)개,
    있으면 `[from, to]` 구간의 모든 거래일. 마감되지 않은 날짜(`to > last_closed_day`)는
    API가 0건을 돌려줄 것이 확실하므로 요청 자체를 거부한다.
    """
    if days is not None and date_from is not None:
        raise BackfillError("--days와 --from은 동시에 지정할 수 없습니다.")
    end = date_to or last_closed_day
    if end > last_closed_day:
        raise BackfillError(
            f"--to({end})가 마지막 마감 거래일({last_closed_day})보다 늦습니다. "
            "아직 마감되지 않은 날짜는 수집할 수 없습니다."
        )
    candidates = sorted(
        {d for d in trading_days if d <= end and (date_from is None or d >= date_from)},
        reverse=True,
    )
    if date_from is None:
        candidates = candidates[: (days if days is not None else DEFAULT_DAYS)]
    if not candidates:
        raise BackfillError("대상 거래일이 0건입니다(캘린더 적재 범위·--from/--to를 확인하세요).")
    return candidates


def split_existing(
    dates: list[date],
    row_counts: dict[date, int],
    active_count: int,
    *,
    ratio: float = SUFFICIENT_RATIO,
) -> tuple[list[date], list[date]]:
    """(수집 대상, 이미 충분해 건너뛸 날짜)로 나눈다. 입력 순서를 보존한다."""
    if active_count <= 0:
        raise BackfillError(
            "활성 종목(stock_master)이 0건이라 날짜별 충분 여부를 판단할 수 없습니다. "
            "scripts/seed_stock_master.py를 먼저 실행하세요."
        )
    threshold = math.ceil(round(ratio * active_count, 6))
    to_fetch: list[date] = []
    skipped: list[date] = []
    for d in dates:
        (skipped if row_counts.get(d, 0) >= threshold else to_fetch).append(d)
    return to_fetch, skipped


def pages_per_date(expected_rows: int, *, page_size: int | None = None) -> int:
    size = page_size if page_size is not None else run_ingestion.PAGE_SIZE
    return max(1, math.ceil(expected_rows / size))


def estimate_calls(n_dates: int, pages: int) -> int:
    return n_dates * pages


# ── 호출 간격·상한 ──────────────────────────────────────────────────────────────
class ThrottledClient:
    """`fetch_ohlcv` 호출 수를 세고, 호출 사이에 간격을 두며, 상한 초과 호출은 외부로 보내지 않는다.

    `run_ingestion._fetch_all_ohlcv(client, date)`가 `client.fetch_ohlcv(...)`만 호출하므로
    이 대역을 그대로 넘겨 기존 페이지네이션을 수정 없이 재사용한다. 세는 단위는 논리적
    페이지 요청이며, `GovDataPortalClient`가 내부에서 재시도하는 HTTP 요청은 포함하지 않는다.
    """

    def __init__(
        self,
        inner,
        *,
        sleep_seconds: float,
        max_calls: int | None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._inner = inner
        self._sleep_seconds = sleep_seconds
        self._max_calls = max_calls
        self._sleep = sleep
        self.calls = 0

    def fetch_ohlcv(self, trade_date: date, *, page_no: int = 1, num_of_rows: int = 1000):
        if self._max_calls is not None and self.calls >= self._max_calls:
            raise CallBudgetExceeded(f"--max-calls({self._max_calls}) 상한에 도달했습니다.")
        if self.calls > 0 and self._sleep_seconds > 0:
            self._sleep(self._sleep_seconds)
        self.calls += 1
        return self._inner.fetch_ohlcv(trade_date, page_no=page_no, num_of_rows=num_of_rows)


# ── 실행 결과 ───────────────────────────────────────────────────────────────────
@dataclass
class BackfillReport:
    fetched: dict[date, int] = field(default_factory=dict)  # 날짜 → 적재 행 수
    skipped: list[date] = field(default_factory=list)  # 이미 충분
    empty_dates: list[date] = field(default_factory=list)  # 거래일인데 0건(경고)
    failed: dict[date, str] = field(default_factory=dict)  # 날짜 → (마스킹된) 사유
    remaining: list[date] = field(default_factory=list)  # 중단으로 처리하지 못한 날짜
    stopped_reason: str | None = None  # MAX_CALLS | API_ERROR | CONSECUTIVE_FAILURES | UNEXPECTED
    calls: int = 0


_HARD_STOPS = {"API_ERROR", "CONSECUTIVE_FAILURES", "UNEXPECTED"}


def run_backfill(
    dates: list[date],
    *,
    throttled: ThrottledClient,
    persist_day: Callable[[date, list[RawOhlcvRecord]], int],
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    log: Callable[[str], None] = print,
    mask: Callable[[str], str] = lambda s: s,
) -> BackfillReport:
    """날짜를 순서대로 수집·저장한다(최신 → 과거). 날짜 하나는 전 페이지를 받은 뒤에만 저장한다.

    실패 정책: 게이트웨이/API 오류(키 오류·한도 초과 등)는 같은 결과가 반복되므로 즉시 중단,
    재시도 소진 등 날짜 단위 실패는 기록 후 다음 날짜로 진행하되 연속 N회면 중단, 저장 단계의
    예기치 못한 예외(DB 등)는 즉시 중단한다. `--max-calls` 도달 시 미완료 날짜는 저장하지
    않고 남은 날짜로 보고한다.
    """
    report = BackfillReport()
    consecutive = 0
    for i, d in enumerate(dates):
        try:
            result = run_ingestion._fetch_all_ohlcv(throttled, d)
        except CallBudgetExceeded:
            report.stopped_reason = "MAX_CALLS"
            report.remaining = list(dates[i:])
            break
        except GovDataApiError as exc:
            report.failed[d] = mask(str(exc))
            report.stopped_reason = "API_ERROR"
            report.remaining = list(dates[i + 1 :])
            log(f"[실패] {d} API 오류로 중단합니다: {report.failed[d]}")
            break
        except (GovDataClientError, run_ingestion.IngestionRunError) as exc:
            report.failed[d] = mask(str(exc))
            consecutive += 1
            log(f"[실패] {d} 수집 실패: {report.failed[d]}")
            if consecutive >= max_consecutive_failures:
                report.stopped_reason = "CONSECUTIVE_FAILURES"
                report.remaining = list(dates[i + 1 :])
                break
            continue

        if not result.records:
            report.empty_dates.append(d)
            consecutive = 0
            log(
                f"[경고] {d} 캘린더상 거래일인데 0건이 반환되었습니다"
                "(공공데이터포털 +1영업일 지연 가능성)."
            )
            continue

        try:
            report.fetched[d] = persist_day(d, result.records)
        except Exception as exc:  # DB 등 저장 단계의 예기치 못한 오류 — 일관 상태로 중단
            report.failed[d] = mask(f"{type(exc).__name__}: {exc}")
            report.stopped_reason = "UNEXPECTED"
            report.remaining = list(dates[i + 1 :])
            log(f"[실패] {d} 저장 중 오류로 중단합니다: {report.failed[d]}")
            break
        consecutive = 0
        log(f"[진행] {d} {report.fetched[d]}행 저장 (누적 호출 {throttled.calls}회)")

    report.calls = throttled.calls
    return report


def derive_status(report: BackfillReport) -> tuple[str, bool]:
    """(batch_run.status, validation_passed).

    전부 완료=SUCCESS, 일부만 완료=PARTIAL, 무성과=FAILED.
    """
    if report.failed or report.stopped_reason in _HARD_STOPS:
        return ("PARTIAL" if report.fetched else "FAILED", False)
    if report.stopped_reason == "MAX_CALLS":
        return ("PARTIAL", True)
    if report.empty_dates and not report.fetched:
        return ("FAILED", False)  # 수집 대상이 전부 0건 — 아무것도 적재되지 않았다
    return ("SUCCESS", True)


def exit_code_for(report: BackfillReport) -> int:
    status, _ = derive_status(report)
    if status == "SUCCESS":
        return 0
    if status == "PARTIAL" and report.stopped_reason == "MAX_CALLS" and not report.failed:
        return 0  # 호출 상한 도달은 의도된 깨끗한 중단
    return 1


def _fmt_dates(dates: list[date], limit: int = 20) -> str:
    shown = ", ".join(d.isoformat() for d in dates[:limit])
    return shown + (f" 외 {len(dates) - limit}일" if len(dates) > limit else "")


def build_summary(report: BackfillReport) -> str:
    """`batch_run.error_summary`용 요약. 반드시 `BACKFILL`로 시작한다(서킷브레이커 제외 표식)."""
    parts = [
        f"{BACKFILL_ERROR_SUMMARY_PREFIX}: 수집 {len(report.fetched)}일/"
        f"{sum(report.fetched.values())}행, 호출 {report.calls}회, 건너뜀 {len(report.skipped)}일"
    ]
    if report.empty_dates:
        parts.append(
            f"거래일 0건(경고) {len(report.empty_dates)}일: {_fmt_dates(report.empty_dates, 5)}"
        )
    if report.failed:
        items = list(report.failed.items())[:5]
        parts.append(
            f"실패 {len(report.failed)}일: "
            + "; ".join(f"{d} {msg[:120]}" for d, msg in items)
        )
    if report.remaining:
        parts.append(f"남은 {len(report.remaining)}일: {_fmt_dates(report.remaining, 5)}")
    if report.stopped_reason:
        parts.append(f"중단 사유: {report.stopped_reason}")
    return " | ".join(parts)


# ── DB 조회 (읽기 전용) ─────────────────────────────────────────────────────────
def load_trading_days(session: Session, *, upto: date) -> list[date]:
    stmt = (
        select(MarketCalendar.trade_date)
        .where(MarketCalendar.market == INGEST_MARKET)
        .where(MarketCalendar.is_trading_day.is_(True))
        .where(MarketCalendar.trade_date <= upto)
    )
    return sorted(session.execute(stmt).scalars().all(), reverse=True)


def load_row_counts(session: Session, dates: list[date]) -> dict[date, int]:
    if not dates:
        return {}
    stmt = (
        select(RawOhlcv.trade_date, func.count())
        .where(RawOhlcv.market == INGEST_MARKET)
        .where(RawOhlcv.trade_date.in_(dates))
        .group_by(RawOhlcv.trade_date)
    )
    return {d: n for d, n in session.execute(stmt).all()}


def count_active_stocks(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(StockMaster).where(StockMaster.is_active.is_(True))
    ).scalar_one()


def max_daily_rows(session: Session) -> int:
    return (
        session.execute(
            text(
                "SELECT coalesce(max(n), 0) FROM ("
                " SELECT count(*) AS n FROM raw_internal.raw_ohlcv GROUP BY trade_date) t"
            )
        ).scalar_one()
        or 0
    )


def coverage_counts(session: Session, *, min_rows: int = COVERAGE_MIN_ROWS) -> tuple[int, int]:
    """(min_rows 이상 보유한 종목 수, 전체 종목 수) — 설계서 §7 완료 검증 쿼리."""
    row = session.execute(
        text(
            "SELECT count(*) FILTER (WHERE n >= :m), count(*) FROM ("
            " SELECT stock_code, count(*) AS n FROM raw_internal.raw_ohlcv GROUP BY stock_code) t"
        ),
        {"m": min_rows},
    ).one()
    return int(row[0]), int(row[1])


# ── 계획 ────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Plan:
    dates: list[date]
    to_fetch: list[date]
    skipped: list[date]
    pages: int
    active_count: int


def build_plan(session: Session, args: argparse.Namespace) -> Plan:
    try:
        last_closed = get_last_trading_day(
            INGEST_MARKET, datetime.now(KST), SqlCalendarRepository(session)
        )
    except CalendarIntegrityError as exc:
        raise BackfillError(f"캘린더 데이터가 비정상입니다: {exc}") from exc
    if last_closed is None:
        raise BackfillError(
            "휴장일 캘린더가 아직 갱신되지 않아 대상 거래일을 계산할 수 없습니다. "
            "scripts/load_calendar.py로 캘린더를 먼저 적재하세요."
        )
    dates = choose_target_dates(
        load_trading_days(session, upto=last_closed),
        days=args.days,
        date_from=args.date_from,
        date_to=args.date_to,
        last_closed_day=last_closed,
    )
    active_count = count_active_stocks(session)
    to_fetch, skipped = split_existing(dates, load_row_counts(session, dates), active_count)
    pages = pages_per_date(max(active_count, max_daily_rows(session)))
    return Plan(
        dates=dates, to_fetch=to_fetch, skipped=skipped, pages=pages, active_count=active_count
    )


def render_dry_run(plan: Plan, args: argparse.Namespace, coverage: tuple[int, int]) -> str:
    calls = estimate_calls(len(plan.to_fetch), plan.pages)
    lines = [
        "(--dry-run) 외부 API 호출·DB 쓰기 없이 계획만 출력합니다.",
        f"대상 거래일 {len(plan.dates)}개: {plan.dates[-1]} ~ {plan.dates[0]}",
        f"  이미 충분(활성 {plan.active_count}종목의 {int(SUFFICIENT_RATIO * 100)}% 이상)해 "
        f"건너뜀: {len(plan.skipped)}개",
        f"  수집 대상: {len(plan.to_fetch)}개",
        f"예상 호출 수: {calls}회 (수집 대상 {len(plan.to_fetch)}일 × 일당 {plan.pages}페이지, "
        "재시도 제외)",
        f"최소 소요 시간: 호출 간격 {args.sleep}초 기준 약 {int(calls * args.sleep)}초 "
        "+ API 응답 시간(별도)",
    ]
    if args.max_calls is not None:
        if calls <= args.max_calls:
            lines.append(f"--max-calls {args.max_calls}: 예상 호출 수가 한도 이내입니다.")
        else:
            can_days = args.max_calls // plan.pages
            lines.append(
                f"--max-calls {args.max_calls}: 한도 초과 — 약 {can_days}일 처리 후 중단되고 "
                f"{max(0, len(plan.to_fetch) - can_days)}일이 남습니다(재실행으로 이어서 처리)."
            )
    ready, total = coverage
    ratio = f"{ready / total * 100:.1f}%" if total else "해당 없음"
    lines.append(f"현재 {COVERAGE_MIN_ROWS}일 이상 보유 종목: {ready}/{total} ({ratio})")
    lines.append("외부 호출 0회, DB 쓰기 0건.")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────────
def _date_arg(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--days", type=int, default=None, help=f"최근 N거래일(기본 {DEFAULT_DAYS})."
    )
    parser.add_argument(
        "--from", dest="date_from", type=_date_arg, default=None, help="시작일 YYYY-MM-DD"
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        type=_date_arg,
        default=None,
        help="종료일 YYYY-MM-DD(기본: 마지막 마감 거래일)",
    )
    parser.add_argument(
        "--sleep", type=float, default=DEFAULT_SLEEP_SECONDS, help="호출 간 최소 간격(초)"
    )
    parser.add_argument(
        "--max-calls", type=int, default=None, help="이번 실행의 호출 수 상한(일일 한도 보호)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="호출·쓰기 없이 계획과 예상 호출 수만 출력"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.days is not None and args.days < 1:
        parser.error("--days는 1 이상이어야 합니다.")
    if args.sleep < 0:
        parser.error("--sleep은 0 이상이어야 합니다.")
    if args.max_calls is not None and args.max_calls < 1:
        parser.error("--max-calls는 1 이상이어야 합니다.")

    try:
        settings = get_settings(require_service_key=not args.dry_run)
    except ConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    key = settings.gov_data_portal_service_key

    def emit(message: str) -> None:
        print(mask_secrets(message, key))

    def emit_err(message: str) -> None:
        print(mask_secrets(message, key), file=sys.stderr)

    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            try:
                plan = build_plan(session, args)
            except BackfillError as exc:
                emit_err(f"[실패] {exc}")
                return 1

            if args.dry_run:
                emit(render_dry_run(plan, args, coverage_counts(session)))
                return 0

            emit(
                f"대상 거래일 {len(plan.dates)}개 중 수집 {len(plan.to_fetch)}개, "
                f"건너뜀 {len(plan.skipped)}개(이미 충분). 예상 호출 "
                f"{estimate_calls(len(plan.to_fetch), plan.pages)}회."
            )
            if plan.skipped:
                emit(f"  건너뜀: {_fmt_dates(plan.skipped)}")
            if not plan.to_fetch:
                emit("[완료] 수집할 날짜가 없습니다(모두 충분).")
                return 0
            return _execute(session, settings, plan, args, emit, emit_err)
    finally:
        engine.dispose()


def _execute(session, settings, plan: Plan, args, emit, emit_err) -> int:
    key = settings.gov_data_portal_service_key
    batch_run_id = start_run(session)
    session.get(BatchRun, batch_run_id).error_summary = IN_PROGRESS_SUMMARY  # 비정상 종료 시 표식
    session.commit()

    def persist_day(trade_date: date, records: list[RawOhlcvRecord]) -> int:
        try:
            affected = upsert_ohlcv(
                session, records, market=INGEST_MARKET, source_batch_id=batch_run_id
            )
            session.commit()  # 날짜 단위 커밋 — 중단 후 재개 가능
            return affected
        except Exception:
            session.rollback()  # 해당 날짜는 전부 롤백(부분 적재 없음)
            raise

    report = BackfillReport()
    try:
        with GovDataPortalClient(
            base_url=settings.gov_data_portal_base_url,
            service_key=key,  # type: ignore[arg-type]
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
        ) as client:
            throttled = ThrottledClient(
                client, sleep_seconds=args.sleep, max_calls=args.max_calls
            )
            report = run_backfill(
                plan.to_fetch,
                throttled=throttled,
                persist_day=persist_day,
                log=emit,
                mask=lambda s: mask_secrets(s, key),
            )
        report.skipped = list(plan.skipped)
    except BaseException as exc:  # Ctrl-C 등 강제 중단도 상태를 정리한다(규칙 K)
        session.rollback()
        finish_run(
            session,
            batch_run_id,
            status="FAILED",
            trade_date_covered=None,
            validation_passed=False,
            error_summary=mask_secrets(
                f"{BACKFILL_ERROR_SUMMARY_PREFIX}(중단): {type(exc).__name__}: {exc}", key
            )[:1000],
        )
        session.commit()
        raise

    status, validation_passed = derive_status(report)
    finish_run(
        session,
        batch_run_id,
        status=status,
        trade_date_covered=max(report.fetched) if report.fetched else None,
        validation_passed=validation_passed,
        error_summary=build_summary(report),
    )
    session.commit()

    ready, total = coverage_counts(session)
    emit(
        f"[{'완료' if status == 'SUCCESS' else '종료'}] status={status} "
        f"수집 {len(report.fetched)}일/{sum(report.fetched.values())}행, 호출 {report.calls}회"
    )
    if report.empty_dates:
        emit(
            f"  경고: 거래일인데 0건 {len(report.empty_dates)}일: {_fmt_dates(report.empty_dates)}"
        )
    if report.failed:
        emit_err(f"  실패 {len(report.failed)}일: {_fmt_dates(list(report.failed))}")
    if report.remaining:
        emit(
            f"  남은 날짜 {len(report.remaining)}일({report.stopped_reason}): "
            f"{_fmt_dates(report.remaining)} — 같은 명령을 다시 실행하면 이어서 처리합니다."
        )
    ratio = f"{ready / total * 100:.1f}%" if total else "해당 없음"
    emit(f"  {COVERAGE_MIN_ROWS}일 이상 보유 종목: {ready}/{total} ({ratio})")
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
