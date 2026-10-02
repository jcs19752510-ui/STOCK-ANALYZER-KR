"""`scripts/enrich_earnings.py` 단위 테스트 (UNIT-23) — 대상 사업연도 결정."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.enrich_earnings import resolve_bsns_year

KST = ZoneInfo("Asia/Seoul")


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 2, tzinfo=KST), "2025"),
        (datetime(2026, 4, 5, tzinfo=KST), "2025"),  # 기한+여유 경계 당일부터 직전 연도
        (datetime(2026, 4, 4, tzinfo=KST), "2024"),  # 직전 연도 사업보고서가 아직 이를 수 있음
        (datetime(2026, 1, 1, tzinfo=KST), "2024"),
        (datetime(2026, 12, 31, tzinfo=KST), "2025"),
    ],
)
def test_resolve_bsns_year_boundaries(now, expected):
    assert resolve_bsns_year(now) == expected
