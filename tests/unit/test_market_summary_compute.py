"""`compute_market_summary()`/`build_market_summary_inputs()` 단위테스트 (REQ-004).

`unit-08-note.md` §9가 6단계에 위임한 경계 조건(전 종목 결측, 동일 거래대금
동률, 6개 이상 업종 존재 시 상위 5개 절단, DEC-016 ALL 직접 재집계)을 5단계의
자체 보고를 신뢰하지 않고 이 단계가 직접 픽스처로 검증한다.
"""

from datetime import date
from decimal import Decimal

from services.derivation_batch.compute import (
    MarketSummaryInput,
    compute_market_summary,
)
from services.derivation_batch.run_derivation import (
    StockDayMetrics,
    build_market_summary_inputs,
)

# --- compute_market_summary() 순수 함수 경계 조건 (AC-1) ---


def test_return_pct_none_excluded_from_all_three_buckets():
    rows = [
        MarketSummaryInput(return_pct=None, trading_value_krw=100, sector="반도체"),
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=100, sector="반도체"),
        MarketSummaryInput(return_pct=Decimal("-1"), trading_value_krw=100, sector="반도체"),
        MarketSummaryInput(return_pct=Decimal("0"), trading_value_krw=100, sector="반도체"),
    ]
    result = compute_market_summary(rows)
    assert result.advancers_count == 1
    assert result.decliners_count == 1
    assert result.unchanged_count == 1
    # None 종목은 상승/하락/보합 어디에도 없어야 한다(합계가 전체 4건이 아니라 3건).
    assert result.advancers_count + result.decliners_count + result.unchanged_count == 3


def test_all_return_pct_none_yields_zero_counts_but_total_value_still_summed():
    rows = [
        MarketSummaryInput(return_pct=None, trading_value_krw=100, sector=None),
        MarketSummaryInput(return_pct=None, trading_value_krw=200, sector=None),
    ]
    result = compute_market_summary(rows)
    assert result.advancers_count == 0
    assert result.decliners_count == 0
    assert result.unchanged_count == 0
    assert result.total_trading_value_krw == 300  # 등락률 결측과 무관하게 거래대금은 합산


def test_sector_none_excluded_from_top_sectors_but_included_in_total_value():
    rows = [
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=1000, sector=None),
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=500, sector="반도체"),
    ]
    result = compute_market_summary(rows)
    assert result.total_trading_value_krw == 1500
    assert len(result.top_sectors_by_value) == 1
    assert result.top_sectors_by_value[0].sector == "반도체"
    assert result.top_sectors_by_value[0].trading_value_krw == 500


def test_all_sector_none_returns_empty_top_sectors_list():
    """§8-2 항목8 — sector 출처 미확정으로 전종목 sector=None인 현재 상태.
    빈 배열을 반환해야 하며 존재하지 않는 업종을 지어내지 않는다."""
    rows = [
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=1000, sector=None),
        MarketSummaryInput(return_pct=Decimal("-1"), trading_value_krw=500, sector=None),
    ]
    result = compute_market_summary(rows)
    assert result.top_sectors_by_value == []


def test_top_sectors_truncated_to_5_and_sorted_descending():
    rows = [
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=v, sector=f"업종{v}")
        for v in [100, 600, 200, 500, 300, 400]  # 6개 업종
    ]
    result = compute_market_summary(rows, top_n=5)
    assert len(result.top_sectors_by_value) == 5  # 6개 중 5개만
    values = [s.trading_value_krw for s in result.top_sectors_by_value]
    assert values == sorted(values, reverse=True)
    assert values == [600, 500, 400, 300, 200]
    # 최하위(100)는 절단되어 포함되지 않아야 한다.
    assert "업종100" not in [s.sector for s in result.top_sectors_by_value]


def test_top_sectors_tie_value_both_included_when_within_top_n():
    rows = [
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=100, sector="A"),
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=100, sector="B"),
    ]
    result = compute_market_summary(rows, top_n=5)
    sectors = {s.sector for s in result.top_sectors_by_value}
    assert sectors == {"A", "B"}  # 동률이어도 둘 다 포함(절단 경계에 걸리지 않는 한)


def test_sector_totals_aggregate_across_multiple_stocks_same_sector():
    rows = [
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=100, sector="반도체"),
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=200, sector="반도체"),
        MarketSummaryInput(return_pct=Decimal("1"), trading_value_krw=50, sector="화학"),
    ]
    result = compute_market_summary(rows)
    by_sector = {s.sector: s.trading_value_krw for s in result.top_sectors_by_value}
    assert by_sector["반도체"] == 300  # 같은 업종 여러 종목 합산
    assert by_sector["화학"] == 50


def test_empty_rows_returns_all_zero_result():
    result = compute_market_summary([])
    assert result.advancers_count == 0
    assert result.decliners_count == 0
    assert result.unchanged_count == 0
    assert result.total_trading_value_krw == 0
    assert result.top_sectors_by_value == []


# --- build_market_summary_inputs() — DEC-016 ALL 직접 재집계 검증 ---

_TARGET = date(2026, 9, 14)


def _stock_day(code: str, market: str, return_pct: Decimal | None) -> StockDayMetrics:
    return StockDayMetrics(
        stock_code=code,
        market=market,
        return_pct=return_pct,
        ma5_gap_pct=None,
        ma20_gap_pct=None,
        volume_anomaly_score=None,
        per_raw=None,
        pbr_raw=None,
        market_cap_raw_krw=None,
    )


def test_all_row_is_not_a_post_hoc_sum_of_kospi_and_kosdaq_top_sectors():
    """DEC-016 핵심 주장 검증: `ALL`의 업종별 거래대금 상위는 KOSPI/KOSDAQ 각각의
    상위 리스트를 합친 것이 아니라 전체 종목을 재집계한 결과다.

    같은 업종("IT")이 KOSPI와 KOSDAQ 양쪽에 걸쳐 존재하는 픽스처를 구성한다.
    만약 구현이 "KOSPI 상위 5 ∪ KOSDAQ 상위 5"를 사후 병합하는 방식이었다면,
    같은 업종이 두 시장에 걸쳐 있을 때 그 값이 시장별로 분리된 채 두 항목으로
    남거나 합산이 누락될 수 있다 — 이 테스트는 ALL 결과에서 "IT" 업종이 두
    시장의 거래대금을 정확히 합산한 **단일 항목**으로 나타나는지 확인한다.
    (5단계 note §0/§7이 수행한 "KOSPI 전용, KOSDAQ 0종목" 픽스처는 KOSDAQ
    기여분이 항상 0이라 이 구분을 실제로 검증하지 못했다는 방법론적 약점이
    있었다 — 이번 테스트가 그 공백을 메운다.)
    """
    rows = [
        _stock_day("A", "KOSPI", Decimal("1")),
        _stock_day("B", "KOSDAQ", Decimal("-1")),
    ]
    trading_value_by_code = {"A": 1_000_000, "B": 2_000_000}
    sector_by_code = {"A": "IT", "B": "IT"}  # 두 시장 모두 같은 업종

    inputs = build_market_summary_inputs(
        rows,
        trading_value_by_code=trading_value_by_code,
        sector_by_code=sector_by_code,
        target_date=_TARGET,
    )
    by_market = {i.market: i for i in inputs}

    assert by_market["KOSPI"].top_sectors_by_value == [
        {"sector": "IT", "trading_value_krw": 1_000_000}
    ]
    assert by_market["KOSDAQ"].top_sectors_by_value == [
        {"sector": "IT", "trading_value_krw": 2_000_000}
    ]
    # ALL은 KOSPI(100만)+KOSDAQ(200만)이 하나의 "IT" 항목(300만)으로 합산되어야
    # 한다 — 사후 병합이었다면 이 합산 자체가 구조적으로 불가능하다(병합 시
    # "어느 시장 값을 남길지" 결정이 필요해지고, 합산이라는 연산 자체가 없다).
    assert by_market["ALL"].top_sectors_by_value == [
        {"sector": "IT", "trading_value_krw": 3_000_000}
    ]
    assert by_market["ALL"].total_trading_value_krw == 3_000_000
    # ALL의 상승/하락 카운트도 KOSPI(상승1)+KOSDAQ(하락1)의 전체 재집계와 일치해야 한다.
    assert by_market["ALL"].advancers_count == 1
    assert by_market["ALL"].decliners_count == 1


def test_build_market_summary_inputs_kospi_only_kosdaq_empty_all_matches_kospi():
    """5단계 note §0/§7이 수행한 원래 시나리오(KOSPI만 존재, KOSDAQ 0종목)를
    그대로 재현한다 — 값 자체는 KOSPI와 우연히 같아지지만, 위 테스트(IT 업종
    교차 케이스)가 이미 "값이 같은 것은 우연이지 병합 경로가 아님"을
    구조적으로 증명했으므로, 이 테스트는 회귀 확인 목적으로만 유지한다."""
    rows = [_stock_day("A", "KOSPI", Decimal("1"))]
    trading_value_by_code = {"A": 1_000_000}
    sector_by_code = {"A": "반도체"}

    inputs = build_market_summary_inputs(
        rows,
        trading_value_by_code=trading_value_by_code,
        sector_by_code=sector_by_code,
        target_date=_TARGET,
    )
    by_market = {i.market: i for i in inputs}

    assert by_market["KOSDAQ"].advancers_count == 0
    assert by_market["KOSDAQ"].total_trading_value_krw == 0
    assert by_market["ALL"].advancers_count == by_market["KOSPI"].advancers_count == 1
    assert (
        by_market["ALL"].total_trading_value_krw
        == by_market["KOSPI"].total_trading_value_krw
        == 1_000_000
    )


def test_build_market_summary_inputs_excludes_stock_missing_trading_value():
    """AC-1 마지막 불릿 — 원본 시세 종목당 거래대금이 있는데
    `trading_value_by_code`에 없는 종목(데이터 정합성 이상)은 0으로 조용히
    대체되지 않고 집계에서 제외된다."""
    rows = [
        _stock_day("A", "KOSPI", Decimal("1")),
        _stock_day("B", "KOSPI", Decimal("1")),  # 거래대금 레코드 없음(정합성 이상)
    ]
    trading_value_by_code = {"A": 1_000_000}  # B 없음
    sector_by_code = {"A": "반도체", "B": "반도체"}

    inputs = build_market_summary_inputs(
        rows,
        trading_value_by_code=trading_value_by_code,
        sector_by_code=sector_by_code,
        target_date=_TARGET,
    )
    by_market = {i.market: i for i in inputs}
    # B가 조용히 0으로 대체되어 합산됐다면 advancers_count=2가 되어야 하지만,
    # 집계에서 완전히 제외되므로 A만 카운트된다.
    assert by_market["KOSPI"].advancers_count == 1
    assert by_market["KOSPI"].total_trading_value_krw == 1_000_000
    assert by_market["ALL"].advancers_count == 1
    assert by_market["ALL"].total_trading_value_krw == 1_000_000


def test_build_market_summary_inputs_empty_rows_returns_three_zero_rows():
    inputs = build_market_summary_inputs(
        [], trading_value_by_code={}, sector_by_code={}, target_date=_TARGET
    )
    assert {i.market for i in inputs} == {"KOSPI", "KOSDAQ", "ALL"}
    for i in inputs:
        assert i.advancers_count == 0
        assert i.total_trading_value_krw == 0
        assert i.top_sectors_by_value == []
