# ruff: noqa: E501
"""일일 배치 따라잡기(catch-up) 계획 (DEC-047, R5).

스케줄러가 며칠 실패하거나 PC가 꺼져 있어도, 다음 실행이 "마지막 정상 가공일 이후의 빠진 거래일"을
오래된 날짜부터 순서대로 채우도록 대상 날짜를 정한다. 날짜 계산은 순수 함수(`plan_catchup`)로 분리해
DB 없이 테스트하고, DB 조회는 얇은 함수 둘로 둔다. 오래된 날짜부터 처리하므로 마지막에 처리한 날짜가
가장 최신이라 `current_published_batch` 포인터가 뒤로 가지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.db_models.public_serving import BatchRun
from shared.db_models.reference import MarketCalendar

DEFAULT_CATCHUP_TRADING_DAYS = 10
# 같은 (과거) 거래일이 이만큼 실패·부분 성공으로 끝나면 더는 다시 시도하지 않는다
# (운영자에게 경고만 남김). 이력이 없어 가공이 항상 PARTIAL로 끝나는 날짜나,
# 캘린더는 거래일인데 API가 영구히 0건을 주는 날짜 때문에 매 실행마다 같은 호출을
# 반복하는 것을 막는다. 대상(최신) 거래일에는 적용하지 않는다(공개 지연으로
# 정상적으로 반복될 수 있음).
MAX_ATTEMPTS_PER_PAST_DATE = 3
# "공공데이터가 아직 공개 전(0건)"으로 끝난 시도는 시도 횟수에 세지 않는다(DEC-092).
# 공공데이터는 +1영업일(휴일이 끼면 그 이상) 뒤에 공개되므로 그날 14:30·18:30과
# 주말·휴일 실행이 모두 "공개 전" 실패로 쌓이는 것이 정상이다. 이를 세면 정작 공개된 날에는
# 이미 상한(3회)을 넘어 영구히 건너뛰게 된다(2026-10-02 사례).
# 값은 `services/ingestion_batch/batch_run_repository.py`와 같아야 하며 같은지 시험이 확인한다
# (shared는 services를 가져올 수 없어 복사해 둔다).
NOT_PUBLISHED_PREFIX = "NOT_PUBLISHED"
LEGACY_NOT_PUBLISHED_TEXT = "대상 거래일 데이터가 0건 반환되었습니다"
# 직전 거래일 구멍 때문에 가공을 보류한 시도(DEC-093)도 세지 않는다 — 구멍이 메워지면 그 날짜를 다시 가공해야 한다.
GAP_BLOCKED_PREFIX = "GAP_BLOCKED"


def plan_catchup(
    trading_dates: Iterable[date],
    done_dates: Iterable[date],
    *,
    target: date,
    max_days: int = DEFAULT_CATCHUP_TRADING_DAYS,
) -> list[date]:
    """`target` 이하 최근 `max_days`개 거래일 중 가공이 끝나지 않은 날짜를 오름차순으로 반환한다."""
    done = set(done_dates)
    recent = sorted({d for d in trading_dates if d <= target})[-max(max_days, 1) :]
    return [d for d in recent if d not in done]


def fetch_trading_dates(
    session: Session, *, market: str, target: date, max_days: int
) -> list[date]:
    # 주말·연휴를 감안해 달력일 여유를 두고 조회한 뒤 plan_catchup이 거래일 개수로 자른다.
    since = target - timedelta(days=max_days * 3 + 10)
    rows = session.execute(
        select(MarketCalendar.trade_date).where(
            MarketCalendar.market == market,
            MarketCalendar.is_trading_day.is_(True),
            MarketCalendar.trade_date >= since,
            MarketCalendar.trade_date <= target,
        )
    ).scalars()
    return list(rows)


def fetch_derived_dates(session: Session, *, since: date) -> list[date]:
    """가공(derive)이 검증까지 통과한 거래일. 검증 실패(PARTIAL) 날짜는 다시 시도 대상이다."""
    rows = session.execute(
        select(BatchRun.trade_date_covered)
        .where(
            BatchRun.run_type == "derive",
            BatchRun.status == "SUCCESS",
            BatchRun.validation_passed.is_(True),
            BatchRun.trade_date_covered >= since,
        )
        .distinct()
    ).scalars()
    return [d for d in rows if d is not None]


def fetch_exhausted_dates(
    session: Session, *, since: date, before: date, max_attempts: int = MAX_ATTEMPTS_PER_PAST_DATE
) -> list[date]:
    """`since` 이상 `before` 미만 거래일 중 실패·부분 성공이 `max_attempts`회 이상 쌓인 날짜.

    "데이터 공개 전(0건)" 실패는 세지 않는다(DEC-092). 진짜 오류와 PARTIAL만 센다.
    """
    summary = BatchRun.error_summary
    not_waiting = or_(
        summary.is_(None),
        summary.not_like(f"{NOT_PUBLISHED_PREFIX}%")
        & summary.not_like(f"{LEGACY_NOT_PUBLISHED_TEXT}%")
        & summary.not_like(f"{GAP_BLOCKED_PREFIX}%"),
    )
    rows = session.execute(
        select(BatchRun.trade_date_covered)
        .where(
            BatchRun.trade_date_covered >= since,
            BatchRun.trade_date_covered < before,
            BatchRun.status.in_(("FAILED", "PARTIAL")),
            not_waiting,
        )
        .group_by(BatchRun.trade_date_covered)
        .having(func.count() >= max_attempts)
    ).scalars()
    return [d for d in rows if d is not None]
