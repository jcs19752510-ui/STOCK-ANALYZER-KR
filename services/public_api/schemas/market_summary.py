from __future__ import annotations

from pydantic import BaseModel


class SectorSummary(BaseModel):
    """`market_summary_daily.top_sectors_by_value` 항목(REQ-004, §3-2). 최대 5개."""

    sector: str
    trading_value_krw: int


class MarketSummaryItem(BaseModel):
    """시장(KOSPI|KOSDAQ|ALL) 1개에 대한 요약 통계(REQ-004, 03-system-design.md §4-2).

    개별 종목 원본 시세 나열이 아니라 상승/하락/보합 종목 수, 총 거래대금,
    업종별 거래대금 상위 등 **가공된 요약 통계**로만 구성한다(§4-3). 원본
    시세 필드는 이 스키마 어디에도 존재하지 않는다.
    """

    market: str
    advancers_count: int
    decliners_count: int
    unchanged_count: int
    top_sectors_by_value: list[SectorSummary]
    total_trading_value_krw: int


class MarketSummaryData(MarketSummaryItem):
    """`GET /api/v1/market-summary` 응답(REQ-004, 03-system-design.md §4-2, DEC-016).

    `market` 생략(기본값 ALL) 또는 `market=ALL` 명시 요청 시 `by_market`에
    KOSPI/KOSDAQ 개별 요약이 함께 담긴다. `market=KOSPI`/`KOSDAQ`를 명시
    요청하면 `by_market`은 `null`이다 — 이 코드베이스의 다른 옵셔널 필드
    (`DataFreshness.session_close_at`/`staleness_note` 등)와 동일하게, 필드
    자체를 생략하지 않고 항상 존재하되 값을 `null`로 표현하는 일관된 계약을
    따른다(설계서 §4-2 예시 JSON의 "필드 없음" 서술을 이 코드베이스 관례에
    맞춰 "null" 표현으로 구현 — `unit-08-note.md` 참조).
    """

    by_market: list[MarketSummaryItem] | None = None
