"""직전 거래일 산정 로직 (REQ-005).

03-system-design.md §3-3(v4, 규칙 F 피드백 루프 — 6단계 DEF-001 대응)의
실행 가능한 pseudocode를 그대로 구현한다.

v4 근본 수정: v3까지는 "오늘 제외" 판단을 개장 시각(`market_open_time`)
기준으로 비교해, 실제로는 장중 내내(개장~마감 사이) "오늘"을 잘못 반환하는
결함(DEF-001)이 있었다. v4는 판단 기준을 **마감 시각**
(`reference.market_calendar.session_close_at`)으로 통일하고, 개장 시각이라는
개념 자체를 이 로직에서 제거했다(`market_hours.py` 삭제, DEC-018).

캘린더 데이터 공백(해당 연도 데이터 미갱신 등)은 절대로 "달력상 전날"로 조용히
대체(fallback)하지 않고 None을 반환해 호출자가 "캘린더 미확인" 상태로
명시적으로 처리하게 한다(§3-3, REQ-005 KPI: 테스트 통과율 100%).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from shared.calendar_service.types import VALID_MARKETS, CalendarLookup, CalendarRow, Market

# 정상적인 KRX/NXT 캘린더라면 연휴가 아무리 길어도(설/추석 대체휴일 포함) 10일을
# 넘지 않는다. 캘린더 데이터가 잘못 적재되어(예: is_trading_day=False가
# 비정상적으로 장기간 이어짐) 무한에 가깝게 역순 탐색하는 것을 막기 위한
# 방어적 상한이다 - §3-3 pseudocode 주석은 "구현체 재량 사항"으로 남겼고,
# 이 상한을 두는 쪽을 택했다(unit-01-note.md 참조). 정상 데이터에서는 발생하지 않는다.
MAX_LOOKBACK_DAYS = 400


class CalendarIntegrityError(RuntimeError):
    """캘린더 데이터는 존재하지만 내용이 비정상적일 때의 공통 베이스.

    "캘린더 데이터 자체가 없음"(None 반환, 424 CALENDAR_NOT_CONFIRMED 대상)과는
    달리, 이 계열의 예외는 데이터가 있으나 신뢰할 수 없는 상태임을 뜻하므로
    호출자(API 레이어 등)는 이를 구분해 5xx로 처리해야 한다(조용한 오답 금지).
    """


class CalendarScanLimitExceeded(CalendarIntegrityError):
    """역순 탐색이 MAX_LOOKBACK_DAYS를 초과했을 때 발생."""


class CalendarDataError(CalendarIntegrityError):
    """거래일(is_trading_day=True) 행인데 session_close_at이 비어 있을 때 발생.

    §3-2 데이터 모델상 거래일에는 마감 시각이 항상 존재해야 한다(휴장일만
    session_close_at이 None). 이 불변조건이 깨지면 마감 여부를 판단할 수 없으므로,
    `None`과 시각을 비교하다 알아보기 힘든 TypeError로 죽는 대신 원인을 명시한다.
    """


def _already_closed(candidate: date, row: CalendarRow, as_of: datetime) -> bool:
    if candidate < as_of.date():
        # candidate가 오늘보다 이전인 과거 날짜라면, 그날의 마감 시각과 무관하게
        # 이미 통째로 지나간 날이므로 항상 "마감됨"으로 취급한다.
        return True
    # candidate가 오늘(as_of.date())인 경우에만 실제로 마감 시각을 비교한다.
    # "개장 시각" 비교는 어디에도 등장하지 않는다(v4, DEF-001 근본 원인 제거).
    if row.session_close_at is None:
        raise CalendarDataError(
            f"{candidate} {row.market} 행은 거래일(is_trading_day=True)인데 "
            "session_close_at이 비어 있습니다. 캘린더 데이터 적재 상태를 확인하세요."
        )
    return as_of.time() >= row.session_close_at


def get_last_trading_day(
    market: Market,
    as_of: datetime,
    calendar: CalendarLookup,
) -> date | None:
    if market not in VALID_MARKETS:
        raise ValueError(f"알 수 없는 거래소 세션 구분: {market!r}")

    candidate = as_of.date()
    scanned_days = 0
    while True:
        row = calendar.get(trade_date=candidate, market=market)
        if row is None:
            return None
        # 단락 평가(short-circuit) 순서를 반드시 지켜야 한다: 휴장일 행은
        # session_close_at이 None일 수 있으므로, is_trading_day가 False일 때
        # _already_closed()가 아예 호출되지 않아야 한다(2차 검증에서 발견,
        # 03-system-design.md §3-3 "구현 시 필수 주의사항" 2번).
        if row.is_trading_day and _already_closed(candidate, row, as_of):
            return candidate
        # 휴장일이거나, 오늘이면서 아직 마감 전이면 하루씩 거슬러 올라간다.
        candidate -= timedelta(days=1)
        scanned_days += 1
        if scanned_days > MAX_LOOKBACK_DAYS:
            raise CalendarScanLimitExceeded(
                f"market={market} as_of={as_of.isoformat()} 기준으로 "
                f"{MAX_LOOKBACK_DAYS}일을 역순 탐색했지만 거래일을 찾지 못했습니다. "
                "캘린더 데이터 적재 상태를 확인하세요."
            )
