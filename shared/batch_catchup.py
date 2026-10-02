"""일일 배치 따라잡기(catch-up) 계획 (DEC-047, R5).

스케줄러가 며칠 실패하거나 PC가 꺼져 있어도, 다음 실행이 "마지막 정상 가공일 이후의 빠진 거래일"을
오래된 날짜부터 순서대로 채우도록 대상 날짜를 정한다. 날짜 계산은 순수 함수(`plan_catchup`)로 분리해
DB 없이 테스트하고, DB 조회는 얇은 함수 둘로 둔다. 오래된 날짜부터 처리하므로 마지막에 처리한 날짜가
가장 최신이라 `current_published_batch` 포인터가 뒤로 가지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db_models.public_serving import BatchRun
from shared.db_models.reference import MarketCalendar

DEFAULT_CATCHUP_TRADING_DAYS = 10


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
