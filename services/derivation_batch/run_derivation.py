#!/usr/bin/env python
"""Derivation Batch 실행 CLI (REQ-002).

03-system-design.md §1-2: "Derivation Batch — raw_internal을 읽어 등락률
순위·이동평균 괴리율·거래량 이상치 스코어(REQ-002)... 를 계산해
public_serving에 쓴다. 이 컴포넌트가 유일하게 raw→public 경계를 넘나드는
지점". MVP는 Ingestion Batch와 동일하게 KRX 정규장 세션만 다룬다(DEC-010).

사용법:
    python -m services.derivation_batch.run_derivation
    python -m services.derivation_batch.run_derivation --trade-date 2026-09-11
    python -m services.derivation_batch.run_derivation --dry-run

**검증 규칙(§5-4 "결측치 과다" 기준을 이 유닛이 구체적 수치로 확정)**:
당일 처리된 종목 중 `return_pct`가 null인 비율이 5%를 초과하면
`validation_passed=False`로 기록하고 `current_published_batch` 포인터를
갱신하지 않는다(§3-2/§5-3 — 이전 정상 데이터가 계속 서빙됨). 신규 상장
종목 결측(전일 종가 없음)은 정상적인 개별 결측이지만, **최초 1회 배치처럼
전종목이 "전일 데이터 없음" 상태이면 이 임계치를 넘어 의도적으로
발행을 보류한다** — 이는 결함이 아니라 "명시적 실패 원칙"(REQ-005/012와
동일한 원칙)의 자연스러운 결과다(`unit-06-note.md` §2/§3 참조).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.derivation_batch.batch_run_repository import finish_run, start_run  # noqa: E402
from services.derivation_batch.compute import (  # noqa: E402
    MarketSummaryInput,
    compute_ma_gap_pct,
    compute_market_summary,
    compute_return_pct,
    compute_volume_anomaly_score,
    rank_percentile,
)
from services.derivation_batch.core.config import ConfigError, get_settings  # noqa: E402
from services.derivation_batch.repository import (  # noqa: E402
    VOLUME_BASELINE_WINDOW,
    ActiveStock,
    DerivedMetricsInput,
    FundamentalsRow,
    MarketSummaryUpsertInput,
    OhlcvPoint,
    fetch_active_stocks,
    fetch_fundamentals_map,
    fetch_ohlcv_window,
    fetch_sector_map,
    fetch_trading_values,
    publish_current_batch,
    upsert_derived_metrics,
    upsert_market_summary,
)
from shared.calendar_service import (  # noqa: E402
    CalendarIntegrityError,
    SqlCalendarRepository,
    get_last_trading_day,
)
from shared.calendar_service.types import CalendarLookup  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
DERIVATION_MARKET = "KRX"  # raw_ohlcv 거래소 세션 구분(§3-1-1). MVP 범위: KRX만(DEC-010)
MAX_MISSING_RETURN_PCT_RATIO = 0.05  # §5-4 "결측 비율 임계치(예: 5%)"를 이 유닛이 확정한 수치


class DerivationRunError(RuntimeError):
    """이번 실행이 실패했음을 나타낸다(프로세스 자체는 정상 종료 흐름을 탄다)."""


def resolve_target_trade_date(calendar: CalendarLookup, *, override: date | None) -> date:
    if override is not None:
        return override
    now = datetime.now(KST)
    trade_date = get_last_trading_day(DERIVATION_MARKET, now, calendar)
    if trade_date is None:
        raise DerivationRunError(
            "휴장일 캘린더가 아직 갱신되지 않아 대상 거래일을 계산할 수 없습니다. "
            "scripts/load_calendar.py로 캘린더를 먼저 적재하세요."
        )
    return trade_date


@dataclass(frozen=True)
class StockDayMetrics:
    stock_code: str
    market: str
    return_pct: Decimal | None
    ma5_gap_pct: Decimal | None
    ma20_gap_pct: Decimal | None
    volume_anomaly_score: Decimal | None
    per_raw: Decimal | None
    pbr_raw: Decimal | None
    market_cap_raw_krw: int | None
    # REQ-003 `GET /screen?volume_min=` 필터 전용(unit-07-note.md §2 참조).
    # API 응답에는 절대 노출하지 않는다 — per_raw/pbr_raw와 동일한 원칙.
    volume_raw: int | None = None


def compute_stock_day_metrics(
    stock: ActiveStock,
    window: list[OhlcvPoint],
    fundamentals: FundamentalsRow | None,
    *,
    target_date: date,
) -> StockDayMetrics | None:
    """`window`는 `target_date` 이하 최신순(내림차순) 원본 시세다.

    `window[0]`이 `target_date`가 아니면(당일 휴장/거래정지 등으로 그날
    시세 자체가 없음) 이 종목은 이번 배치 결과에서 완전히 제외한다 —
    "결측치는 null"(§3-2) 원칙은 개별 지표 값에 대한 것이고, 그날 아예
    거래된 적이 없는 종목까지 빈 행으로 만들지는 않는다(`unit-06-note.md`
    §2 참조).
    """
    if not window or window[0].trade_date != target_date:
        return None

    closes = [point.close for point in window]
    today_close = closes[0]
    prev_close = closes[1] if len(closes) >= 2 else None
    return_pct = compute_return_pct(today_close, prev_close)

    ma5_gap_pct = compute_ma_gap_pct(closes, window=5)
    ma20_gap_pct = compute_ma_gap_pct(closes, window=20)

    baseline_volumes = [p.volume for p in window[1 : 1 + VOLUME_BASELINE_WINDOW]]
    volume_anomaly_score = compute_volume_anomaly_score(
        window[0].volume, baseline_volumes, window=VOLUME_BASELINE_WINDOW
    )

    return StockDayMetrics(
        stock_code=stock.stock_code,
        market=stock.market,
        return_pct=return_pct,
        ma5_gap_pct=ma5_gap_pct,
        ma20_gap_pct=ma20_gap_pct,
        volume_anomaly_score=volume_anomaly_score,
        per_raw=fundamentals.per if fundamentals else None,
        pbr_raw=fundamentals.pbr if fundamentals else None,
        market_cap_raw_krw=fundamentals.market_cap if fundamentals else None,
        volume_raw=window[0].volume,
    )


def build_derivation_inputs(
    rows: list[StockDayMetrics], *, target_date: date
) -> list[DerivedMetricsInput]:
    """개별 종목 지표 + 코스피/코스닥 통합 전체 종목 기준 백분위(§3-2)를 합쳐 반환."""
    return_ranks = rank_percentile(
        [(r.stock_code, r.return_pct) for r in rows if r.return_pct is not None],
        descending=True,
    )
    per_percentiles = rank_percentile(
        [(r.stock_code, r.per_raw) for r in rows if r.per_raw is not None],
        descending=False,
    )
    pbr_percentiles = rank_percentile(
        [(r.stock_code, r.pbr_raw) for r in rows if r.pbr_raw is not None],
        descending=False,
    )
    market_cap_percentiles = rank_percentile(
        [
            (r.stock_code, Decimal(r.market_cap_raw_krw))
            for r in rows
            if r.market_cap_raw_krw is not None
        ],
        descending=True,
    )

    return [
        DerivedMetricsInput(
            stock_code=r.stock_code,
            market=r.market,
            trade_date=target_date,
            return_pct=r.return_pct,
            return_rank_pct=return_ranks.get(r.stock_code),
            ma5_gap_pct=r.ma5_gap_pct,
            ma20_gap_pct=r.ma20_gap_pct,
            volume_anomaly_score=r.volume_anomaly_score,
            per_raw=r.per_raw,
            pbr_raw=r.pbr_raw,
            market_cap_raw_krw=r.market_cap_raw_krw,
            volume_raw=r.volume_raw,
            per_percentile=per_percentiles.get(r.stock_code),
            pbr_percentile=pbr_percentiles.get(r.stock_code),
            market_cap_percentile=market_cap_percentiles.get(r.stock_code),
        )
        for r in rows
    ]


def build_market_summary_inputs(
    rows: list[StockDayMetrics],
    *,
    trading_value_by_code: dict[str, int],
    sector_by_code: dict[str, str | None],
    target_date: date,
) -> list[MarketSummaryUpsertInput]:
    """REQ-004 `market_summary_daily` KOSPI/KOSDAQ/ALL 3행을 만든다(§3-2, DEC-016).

    `ALL`은 KOSPI/KOSDAQ 결과를 사후 합산하지 않고, `rows`(그날 거래된 전
    종목) 전체를 `compute_market_summary()`에 직접 넘겨 재집계한다 —
    업종 상위 리스트처럼 부분 상위 N의 합으로 전체 상위 N을 복원할 수 없는
    값이 있기 때문이다.
    """

    def to_summary_inputs(subset: list[StockDayMetrics]) -> list[MarketSummaryInput]:
        result: list[MarketSummaryInput] = []
        for r in subset:
            trading_value = trading_value_by_code.get(r.stock_code)
            if trading_value is None:
                # day_metrics에 포함된 종목(그날 원본 시세 존재)인데 같은
                # 날짜의 거래대금 레코드가 없는 것은 데이터 정합성 이상이다
                # — 0으로 조용히 대체하지 않고 이 종목을 시장 요약 집계에서
                # 제외한다(§3-2 결측치 처리의 명시적 실패 원칙과 동일한 정신).
                continue
            result.append(
                MarketSummaryInput(
                    return_pct=r.return_pct,
                    trading_value_krw=trading_value,
                    sector=sector_by_code.get(r.stock_code),
                )
            )
        return result

    market_subsets: list[tuple[str, list[StockDayMetrics]]] = [
        ("KOSPI", [r for r in rows if r.market == "KOSPI"]),
        ("KOSDAQ", [r for r in rows if r.market == "KOSDAQ"]),
        ("ALL", rows),
    ]

    inputs: list[MarketSummaryUpsertInput] = []
    for market_label, subset in market_subsets:
        result = compute_market_summary(to_summary_inputs(subset))
        inputs.append(
            MarketSummaryUpsertInput(
                trade_date=target_date,
                market=market_label,
                advancers_count=result.advancers_count,
                decliners_count=result.decliners_count,
                unchanged_count=result.unchanged_count,
                top_sectors_by_value=[
                    {"sector": s.sector, "trading_value_krw": s.trading_value_krw}
                    for s in result.top_sectors_by_value
                ],
                total_trading_value_krw=result.total_trading_value_krw,
            )
        )
    return inputs


def _validation_passed(rows: list[StockDayMetrics]) -> tuple[bool, int]:
    missing = sum(1 for r in rows if r.return_pct is None)
    if not rows:
        return False, missing
    return (missing / len(rows)) <= MAX_MISSING_RETURN_PCT_RATIO, missing


def run_once(
    session: Session,
    *,
    trade_date_override: date | None,
) -> tuple[str, date | None, str | None]:
    """한 번의 배치 실행을 수행하고 (status, trade_date_covered, error_summary)를 반환한다.

    실행 결과와 무관하게 항상 batch_run 행을 정확히 1개 기록한다(run_ingestion.py와
    동일한 원칙 — §5-4 감사 추적성).
    """
    batch_run_id = start_run(session)
    session.flush()

    try:
        target_date = resolve_target_trade_date(
            SqlCalendarRepository(session), override=trade_date_override
        )
    except (DerivationRunError, CalendarIntegrityError) as exc:
        finish_run(
            session,
            batch_run_id,
            status="FAILED",
            trade_date_covered=None,
            validation_passed=False,
            error_summary=str(exc),
        )
        return "FAILED", None, str(exc)

    active_stocks = fetch_active_stocks(session)
    if not active_stocks:
        error_summary = (
            "활성 종목(public_serving.stock_master)이 없습니다. "
            "scripts/seed_stock_master.py를 먼저 실행하세요."
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

    fundamentals_map = fetch_fundamentals_map(session, target_date)

    day_metrics: list[StockDayMetrics] = []
    for stock in active_stocks:
        window = fetch_ohlcv_window(
            session, stock.stock_code, market=DERIVATION_MARKET, upto_date=target_date
        )
        computed = compute_stock_day_metrics(
            stock, window, fundamentals_map.get(stock.stock_code), target_date=target_date
        )
        if computed is not None:
            day_metrics.append(computed)

    if not day_metrics:
        error_summary = (
            "대상 거래일의 원본 시세 데이터(raw_internal.raw_ohlcv)가 하나도 없습니다 "
            "(Ingestion Batch 미실행이거나 아직 그 날짜 데이터가 적재되지 않았을 수 있음)."
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

    derivation_inputs = build_derivation_inputs(day_metrics, target_date=target_date)
    upsert_derived_metrics(session, derivation_inputs, batch_run_id=batch_run_id)

    # REQ-004 — derived_metrics_daily와 같은 배치 실행 안에서 시장 동향 요약도
    # 함께 산출한다(03-system-design.md §1-2 "Derivation Batch... 시장 요약
    # 통계(REQ-004)를 계산해 public_serving에 쓴다"). day_metrics는 이미
    # "그날 실제로 거래된 종목"만 담고 있으므로 별도 필터링이 불필요하다.
    trading_value_by_code = fetch_trading_values(
        session, market=DERIVATION_MARKET, trade_date=target_date
    )
    sector_by_code = fetch_sector_map(session)
    market_summary_inputs = build_market_summary_inputs(
        day_metrics,
        trading_value_by_code=trading_value_by_code,
        sector_by_code=sector_by_code,
        target_date=target_date,
    )
    upsert_market_summary(session, market_summary_inputs, batch_run_id=batch_run_id)

    validation_passed, missing_count = _validation_passed(day_metrics)
    status = "SUCCESS" if validation_passed else "PARTIAL"
    error_summary = None
    if not validation_passed:
        error_summary = (
            f"등락률(return_pct) 결측 비율이 임계치({MAX_MISSING_RETURN_PCT_RATIO:.0%})를 "
            f"초과했습니다({missing_count}/{len(day_metrics)}건). derived_metrics_daily에는 "
            "기록했으나 current_published_batch 포인터는 갱신하지 않았습니다(§3-2/§5-3 — "
            "이전 정상 데이터가 계속 서빙됨)."
        )

    finish_run(
        session,
        batch_run_id,
        status=status,
        trade_date_covered=target_date,
        validation_passed=validation_passed,
        error_summary=error_summary,
    )

    if validation_passed:
        publish_current_batch(
            session, market=DERIVATION_MARKET, trade_date=target_date, batch_run_id=batch_run_id
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
        help="설정만 검증하고 실제 DB 반영은 하지 않는다.",
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("(--dry-run) 설정 확인 완료. 실제 DB 반영은 하지 않았습니다.")
        print("  BATCH_DATABASE_URL: 설정됨")
        return 0

    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        try:
            status, trade_date_covered, error_summary = run_once(
                session, trade_date_override=args.trade_date
            )
            session.commit()
        except Exception as exc:  # DB 계층의 예기치 못한 예외도 명시적으로 기록
            session.rollback()
            _record_failed_run(
                session,
                trade_date_covered=args.trade_date,
                error_summary=f"예기치 못한 오류: {exc}",
            )
            session.commit()
            print(f"[실패] {exc}", file=sys.stderr)
            return 1

        if status == "FAILED":
            print(f"[실패] trade_date={trade_date_covered} {error_summary}", file=sys.stderr)
            return 1

        print(f"[완료] status={status} trade_date={trade_date_covered}")
        if error_summary:
            print(f"  경고: {error_summary}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
