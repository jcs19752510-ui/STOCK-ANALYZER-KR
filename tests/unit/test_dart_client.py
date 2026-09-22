"""services/ingestion_batch/dart_client.py 단위테스트.

httpx.MockTransport로 네트워크를 완전히 대체해 파싱/재시도/오류분류 로직만
검증한다. account_id/sj_div 매칭 로직(지배기업 소유주지분 우선, 통계
테이블(SCE)과의 계정명 중복 방지)은 2026-09-22 삼성전자 실 데이터로 이미
수동 검증했다(테스트 결과서 참조) — 이 파일은 그 로직을 고정된 입력으로
회귀 검증한다.
"""

from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal

import httpx
import pytest

from services.ingestion_batch.dart_client import (
    DartApiError,
    DartClient,
    DartClientError,
    _find_account_amount,
    _parse_corp_code_xml,
)

API_KEY = "TEST-DART-KEY"


def _make_client(handler, *, max_retries: int = 3, sleep=lambda s: None) -> DartClient:
    transport = httpx.MockTransport(handler)
    return DartClient(api_key=API_KEY, max_retries=max_retries, sleep=sleep, transport=transport)


def _json_response(body: dict, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


# ---------------------------------------------------------------------------
# _find_account_amount: sj_div로 먼저 좁히고 account_id 우선순위대로 찾는다.
# ---------------------------------------------------------------------------


def test_find_account_amount_prefers_attributable_to_parent():
    items = [
        {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "999"},
        {
            "sj_div": "IS",
            "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "thstrm_amount": "44260956000000",
        },
    ]
    amount = _find_account_amount(
        items,
        sj_div="IS",
        account_ids=(
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "ifrs-full_ProfitLoss",
        ),
    )
    assert amount == Decimal("44260956000000")


def test_find_account_amount_falls_back_when_no_parent_split():
    """자회사가 없어 지배지분 세부 계정이 없는 개별(OFS) 케이스."""
    items = [
        {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "1234"},
    ]
    amount = _find_account_amount(
        items,
        sj_div="IS",
        account_ids=(
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "ifrs-full_ProfitLoss",
        ),
    )
    assert amount == Decimal("1234")


def test_find_account_amount_accepts_multiple_sj_div_for_cis_only_filers():
    """실측 확인된 함정(2026-09-22, 하이트진로 corp_code=00150244): 손익계산서와
    포괄손익계산서를 하나로 합쳐 "CIS"로만 제출하고 별도 "IS"가 없는 회사가
    실제로 있다 — sj_div="IS" 하나만 찾으면 당기순이익이 전부 None으로
    빠진다(--limit 15 실 데이터 검증 중 발견, 테스트 결과서 참조)."""
    items = [
        {
            "sj_div": "CIS",
            "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "thstrm_amount": "41492231483",
        },
        {
            "sj_div": "CIS",
            "account_id": "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent",
            "thstrm_amount": "99999999999",
        },
    ]
    amount = _find_account_amount(
        items,
        sj_div=("IS", "CIS"),
        account_ids=(
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "ifrs-full_ProfitLoss",
        ),
    )
    assert amount == Decimal("41492231483")


def test_find_account_amount_ignores_same_name_in_other_statement():
    """실측 확인된 함정: '자본총계'(ifrs-full_Equity)가 자본변동표(SCE)에도
    여러 줄 나온다 — sj_div="BS"로 좁히지 않으면 엉뚱한 값을 집을 수 있다."""
    items = [
        {"sj_div": "SCE", "account_id": "ifrs-full_Equity", "thstrm_amount": "111"},
        {"sj_div": "SCE", "account_id": "ifrs-full_Equity", "thstrm_amount": "222"},
        {"sj_div": "BS", "account_id": "ifrs-full_Equity", "thstrm_amount": "436320337000000"},
    ]
    amount = _find_account_amount(items, sj_div="BS", account_ids=("ifrs-full_Equity",))
    assert amount == Decimal("436320337000000")


def test_find_account_amount_returns_none_when_missing():
    amount = _find_account_amount([], sj_div="BS", account_ids=("ifrs-full_Equity",))
    assert amount is None


# ---------------------------------------------------------------------------
# corpCode.xml 파싱
# ---------------------------------------------------------------------------


def test_parse_corp_code_xml_extracts_listed_only():
    xml_bytes = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
        <list>
            <corp_code>00126380</corp_code>
            <corp_name>삼성전자</corp_name>
            <corp_eng_name>Samsung Electronics</corp_eng_name>
            <stock_code>005930</stock_code>
            <modify_date>20260101</modify_date>
        </list>
        <list>
            <corp_code>00430964</corp_code>
            <corp_name>비상장회사</corp_name>
            <corp_eng_name></corp_eng_name>
            <stock_code> </stock_code>
            <modify_date>20170630</modify_date>
        </list>
    </result>""".encode()

    entries = _parse_corp_code_xml(xml_bytes)
    assert len(entries) == 2
    assert entries[0].stock_code == "005930"
    assert entries[0].corp_code == "00126380"
    assert entries[1].stock_code is None  # 공백만 있으면 비상장으로 취급


# ---------------------------------------------------------------------------
# DartClient: fetch_company_overview / fetch_financials / fetch_corp_code_map
# ---------------------------------------------------------------------------


def test_fetch_company_overview_parses_induty_code():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("company.json")
        return _json_response(
            {
                "status": "000",
                "message": "정상",
                "corp_code": "00126380",
                "stock_code": "005930",
                "induty_code": "264",
            }
        )

    with _make_client(handler) as client:
        overview = client.fetch_company_overview("00126380")

    assert overview is not None
    assert overview.induty_code == "264"
    assert overview.stock_code == "005930"


def test_fetch_company_overview_no_data_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"status": "013", "message": "조회된 데이타가 없습니다."})

    with _make_client(handler) as client:
        overview = client.fetch_company_overview("00000000")

    assert overview is None


def test_fetch_financials_parses_net_income_and_equity():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("fnlttSinglAcntAll.json")
        assert request.url.params["fs_div"] == "CFS"
        return _json_response(
            {
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "sj_div": "IS",
                        "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                        "thstrm_amount": "44260956000000",
                    },
                    {
                        "sj_div": "BS",
                        "account_id": "ifrs-full_EquityAttributableToOwnersOfParent",
                        "thstrm_amount": "424313255000000",
                    },
                ],
            }
        )

    with _make_client(handler) as client:
        result = client.fetch_financials(
            "00126380", bsns_year="2025", reprt_code="11011", fs_div="CFS"
        )

    assert result is not None
    assert result.net_income == Decimal("44260956000000")
    assert result.equity == Decimal("424313255000000")
    assert result.fs_div == "CFS"


def test_fetch_financials_annualizes_quarterly_net_income_using_cumulative_field():
    """실측 확인(2026-09-22, 삼성전자 2026 반기보고서 corp_code=00126380):
    분기/반기보고서의 손익계산서 항목은 thstrm_amount가 '당기 3개월 단독'이고
    누적(연초부터)은 thstrm_add_amount에 따로 들어있다(DART 개발가이드 원문
    대조 확인). 반기(6개월) 누적이면 12개월 기준으로 2배 연환산해야 한다.
    자본총계(BS)는 시점 스냅샷이라 연환산하지 않는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["reprt_code"] == "11012"
        return _json_response(
            {
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "sj_div": "IS",
                        "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                        "thstrm_amount": "71269468000000",  # 당기 3개월 단독(연환산에 안 씀)
                        "thstrm_add_amount": "118370658000000",  # 당기 누적(반기, 6개월)
                    },
                    {
                        "sj_div": "BS",
                        "account_id": "ifrs-full_EquityAttributableToOwnersOfParent",
                        "thstrm_amount": "565064740000000",
                    },
                ],
            }
        )

    with _make_client(handler) as client:
        result = client.fetch_financials(
            "00126380", bsns_year="2026", reprt_code="11012", fs_div="CFS"
        )

    assert result is not None
    assert result.net_income == Decimal("118370658000000") * 2  # 6개월 -> 12개월 연환산
    assert result.equity == Decimal("565064740000000")  # 스냅샷, 연환산 없음


def test_fetch_financials_no_data_returns_none_for_fallback():
    """CFS 미제출 회사 — 호출자가 OFS로 재시도할 수 있도록 None을 반환해야 한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"status": "013", "message": "조회된 데이타가 없습니다."})

    with _make_client(handler) as client:
        result = client.fetch_financials(
            "00000000", bsns_year="2025", reprt_code="11011", fs_div="CFS"
        )

    assert result is None


def test_fetch_financials_raises_on_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"status": "010", "message": "등록되지 않은 키입니다."})

    with _make_client(handler) as client:
        with pytest.raises(DartApiError) as exc_info:
            client.fetch_financials(
                "00126380", bsns_year="2025", reprt_code="11011", fs_div="CFS"
            )
    assert exc_info.value.retryable is False


def test_rate_limit_status_020_is_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _json_response({"status": "020", "message": "요청 제한을 초과하였습니다."})
        return _json_response(
            {"status": "000", "message": "정상", "corp_code": "00126380", "induty_code": "264"}
        )

    with _make_client(handler, sleep=lambda s: None) as client:
        overview = client.fetch_company_overview("00126380")

    assert calls["n"] == 2
    assert overview is not None


def test_http_5xx_is_retried_then_exhausts():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"service unavailable")

    with _make_client(handler, max_retries=2, sleep=lambda s: None) as client:
        with pytest.raises(DartClientError):
            client.fetch_company_overview("00126380")


def test_fetch_corp_code_map_extracts_zip_and_maps_stock_codes():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
        <list>
            <corp_code>00126380</corp_code>
            <corp_name>삼성전자</corp_name>
            <corp_eng_name>Samsung Electronics</corp_eng_name>
            <stock_code>005930</stock_code>
            <modify_date>20260101</modify_date>
        </list>
    </result>""".encode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml_content)
    zip_bytes = buf.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("corpCode.xml")
        return httpx.Response(
            200, content=zip_bytes, headers={"content-type": "application/x-zip-compressed"}
        )

    with _make_client(handler) as client:
        mapping = client.fetch_corp_code_map()

    assert mapping == {"005930": "00126380"}
