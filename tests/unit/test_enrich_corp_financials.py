"""scripts/enrich_corp_financials.py 단위테스트.

`upsert_corp_financials`/`upsert_stock_sector`/`apply_dart_valuation`은
PostgreSQL 전용 `ON CONFLICT` 구문을 쓰므로 SQLite로 대체 검증할 수 없다
(test_seed_stock_master.py와 동일한 이유 — 로컬 Docker PostgreSQL로 수동
검증했다, 테스트 결과서 참조). 이 파일은 DB 세션 없이 검증 가능한 순수
로직(정기보고서 재수집 시점 판단)만 다룬다.

`resolve_target_report()`의 4개 체크포인트(4/5, 5/20, 8/20, 11/20)는
자본시장법 정기보고서 법정 제출기한(사업보고서 90일/분기·반기 45일, 12월
결산 법인 기준 마감 3/31, 5/15, 8/14, 11/14)에서 지각 제출 기업을 감안해
며칠 여유를 둔 시점이다(2026-09-22 시장 관행 조사 후 사용자 승인, 대화
맥락 참조).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.enrich_corp_financials import resolve_target_report

KST = ZoneInfo("Asia/Seoul")


def test_after_nov20_uses_this_year_q3():
    assert resolve_target_report(datetime(2026, 11, 20, tzinfo=KST)) == ("2026", "11014")
    assert resolve_target_report(datetime(2026, 12, 31, tzinfo=KST)) == ("2026", "11014")


def test_between_aug20_and_nov20_uses_this_year_half_year():
    assert resolve_target_report(datetime(2026, 8, 20, tzinfo=KST)) == ("2026", "11012")
    assert resolve_target_report(datetime(2026, 11, 19, tzinfo=KST)) == ("2026", "11012")


def test_between_may20_and_aug20_uses_this_year_q1():
    assert resolve_target_report(datetime(2026, 5, 20, tzinfo=KST)) == ("2026", "11013")
    assert resolve_target_report(datetime(2026, 8, 19, tzinfo=KST)) == ("2026", "11013")


def test_between_apr5_and_may20_uses_last_year_annual():
    assert resolve_target_report(datetime(2026, 4, 5, tzinfo=KST)) == ("2025", "11011")
    assert resolve_target_report(datetime(2026, 5, 19, tzinfo=KST)) == ("2025", "11011")


def test_before_apr5_falls_back_to_last_years_q3():
    # 1~4/4는 전년도 사업보고서 마감(3/31) 직후라 아직 못 받았을 수 있어,
    # 안전하게 전년도 3분기보고서(가장 최근 확정된 실적)를 쓴다.
    assert resolve_target_report(datetime(2026, 1, 1, tzinfo=KST)) == ("2025", "11014")
    assert resolve_target_report(datetime(2026, 4, 4, tzinfo=KST)) == ("2025", "11014")


def test_year_boundary_rolls_over_correctly():
    assert resolve_target_report(datetime(2027, 2, 1, tzinfo=KST)) == ("2026", "11014")
