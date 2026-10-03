"""개인 로컬 모드 투자자별 순매수 정규화·서비스 단위 테스트. 네트워크 없음."""

from __future__ import annotations

from datetime import date

from services.public_api.intraday.normalize import normalize_investor_rows
from services.public_api.intraday.service import INVESTOR_MAX_DAYS, IntradayService


def _row(day: str, p="100", f="-50", o="-50", pa="10", fa="-5", oa="-5"):
    return {
        "stck_bsop_date": day, "prsn_ntby_qty": p, "frgn_ntby_qty": f, "orgn_ntby_qty": o,
        "prsn_ntby_tr_pbmn": pa, "frgn_ntby_tr_pbmn": fa, "orgn_ntby_tr_pbmn": oa,
    }  # fmt: skip


def test_parses_numbers_with_commas_and_negative_values():
    rows = normalize_investor_rows([_row("20261002", p="-1,234", f="+500", pa="-12")])
    assert len(rows) == 1
    r = rows[0]
    assert r.date == date(2026, 10, 2)
    assert (r.personal_quantity, r.foreign_quantity, r.institution_quantity) == (-1234, 500, -50)
    assert r.personal_amount_million == -12


def test_blank_values_stay_none_not_zero():
    blank = _row("20261002", p="", f="abc", o="30", pa="", fa="", oa="")
    rows = normalize_investor_rows([blank])
    r = rows[0]
    assert r.personal_quantity is None and r.foreign_quantity is None
    assert r.institution_quantity == 30
    assert r.personal_amount_million is None


def test_all_blank_row_and_bad_dates_are_dropped_and_duplicates_collapsed():
    rows = normalize_investor_rows(
        [
            _row("20261003", p="", f="", o="", pa="", fa="", oa=""),  # 장중 미확정 당일
            _row("2026-10-02"),  # 형식 오류
            _row("20261340"),  # 없는 날짜
            _row(""),
            _row("20261001", p="1"),
            _row("20261001", p="999"),  # 같은 날짜는 첫 행만
            _row("20260930"),
        ]
    )
    assert [r.date.isoformat() for r in rows] == ["2026-10-01", "2026-09-30"]
    assert rows[0].personal_quantity == 1


def test_non_mapping_garbage_values_do_not_crash():
    assert normalize_investor_rows([]) == []
    assert normalize_investor_rows([{"stck_bsop_date": None}]) == []


class _Client:
    def __init__(self, output):
        self.output = output
        self.calls = 0

    def investor(self, code):
        self.calls += 1
        return {"output": self.output}


def test_service_limits_days_and_caches():
    days = [date(2026, 9, 1 + i).strftime("%Y%m%d") for i in range(28)]
    days += [date(2026, 10, 1 + i).strftime("%Y%m%d") for i in range(5)]
    client = _Client([_row(d) for d in reversed(days)])
    svc = IntradayService(client)
    data = svc.investor("005930")
    assert len(data.rows) == INVESTOR_MAX_DAYS and data.stock_code == "005930"
    svc.investor("005930")
    assert client.calls == 1  # 30초 캐시


def test_service_accepts_single_object_output_and_missing_output():
    one = IntradayService(_Client(_row("20261002")))
    assert len(one.investor("005930").rows) == 1
    none = IntradayService(_Client(None))
    assert none.investor("005930").rows == []
