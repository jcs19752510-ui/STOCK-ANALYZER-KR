"""상장시장 구분(KOSPI/KOSDAQ) 공용 타입 (03-system-design.md §3-1-1).

거래소 세션 구분(KRX/NXT, `shared.calendar_service.types.Market`)과는 다른
축이다. 04단계 Q1이 지적한 `market` 필드 의미 중복(설계서 §0-1)을 코드
레벨에서도 재발시키지 않기 위해, 상장시장 구분은 반드시 이 모듈의 타입만
사용하고 거래소 세션 타입과 혼용하지 않는다.

`stock_master`(UNIT-03), 향후 `derived_metrics_daily`/`market_summary_daily`
(UNIT-06~08)가 모두 이 축을 공유하므로 한 곳에서 정의해 재사용한다.
"""

from __future__ import annotations

from typing import Literal

ListedMarket = Literal["KOSPI", "KOSDAQ"]
VALID_LISTED_MARKETS: tuple[ListedMarket, ...] = ("KOSPI", "KOSDAQ")

# API 파라미터(GET /stocks?market=, GET /screen?market= 등)는 전체 조회를 위한
# ALL도 허용한다(생략 시 기본값, 03-system-design.md §4-2).
ListedMarketFilter = Literal["KOSPI", "KOSDAQ", "ALL"]
VALID_LISTED_MARKET_FILTERS: tuple[ListedMarketFilter, ...] = ("KOSPI", "KOSDAQ", "ALL")

__all__ = [
    "VALID_LISTED_MARKETS",
    "VALID_LISTED_MARKET_FILTERS",
    "ListedMarket",
    "ListedMarketFilter",
]
