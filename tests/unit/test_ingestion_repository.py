"""services/ingestion_batch/repository.py 단위테스트 — 순수 계산 로직만.

`upsert_*`/`apply_dart_valuation`의 DB 반영 부분은 PostgreSQL 전용
`ON CONFLICT` 구문을 쓰므로 SQLite로 대체 검증할 수 없다(test_run_ingestion.py/
test_seed_stock_master.py와 동일한 이유 — 로컬 Docker PostgreSQL로 수동
검증했다, 테스트 결과서 참조). 이 파일은 `compute_per_pbr()`(DB 세션 없이
검증 가능하도록 분리한 PER/PBR 계산 공식)만 다룬다.
"""

from __future__ import annotations

from decimal import Decimal

from services.ingestion_batch.repository import compute_per_pbr

MARKET_CAP = 566_942_110_000_000  # 임의 시가총액(실측 재무제표 규모와 자릿수만 맞춘 예시값)


def test_normal_profit_and_positive_equity():
    per, pbr = compute_per_pbr(
        MARKET_CAP, net_income=Decimal("44260956000000"), equity=Decimal("424313255000000")
    )
    assert per == MARKET_CAP / Decimal("44260956000000")
    assert pbr == MARKET_CAP / Decimal("424313255000000")


def test_negative_net_income_yields_none_per_but_keeps_pbr():
    per, pbr = compute_per_pbr(
        MARKET_CAP, net_income=Decimal("-1000000000"), equity=Decimal("424313255000000")
    )
    assert per is None
    assert pbr is not None


def test_zero_equity_yields_none_pbr():
    per, pbr = compute_per_pbr(MARKET_CAP, net_income=Decimal("1000000000"), equity=Decimal("0"))
    assert per is not None
    assert pbr is None


def test_missing_values_yield_none():
    per, pbr = compute_per_pbr(MARKET_CAP, net_income=None, equity=None)
    assert per is None
    assert pbr is None
