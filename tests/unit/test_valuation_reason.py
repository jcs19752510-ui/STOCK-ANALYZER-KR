"""PER/PBR 산정 불가 사유 판정(DEC-057) 단위 테스트. DB 없음."""

from __future__ import annotations

from decimal import Decimal

from services.derivation_batch.run_derivation import valuation_unavailable_reason


def test_value_present_has_no_reason():
    assert valuation_unavailable_reason(Decimal("12.3"), Decimal("100")) is None
    assert valuation_unavailable_reason(Decimal("12.3"), None) is None


def test_non_positive_denominator_is_loss():
    assert valuation_unavailable_reason(None, Decimal("-5")) == "LOSS"
    assert valuation_unavailable_reason(None, Decimal("0")) == "LOSS"


def test_missing_financials_or_market_cap_is_no_data():
    assert valuation_unavailable_reason(None, None) == "NO_DATA"  # 재무 원문 없음
    # 분모는 양수인데 값이 없는 경우(시가총액 없음)
    assert valuation_unavailable_reason(None, Decimal("100")) == "NO_DATA"
