"""services/ingestion_batch/gov_data_client.py 단위테스트 (REQ-011, §5-4).

실제 공공데이터포털 서비스키로 검증하지 못했다(unit-02-note.md §2 참조).
이 테스트는 httpx.MockTransport로 네트워크를 완전히 대체해, 클라이언트의
파싱/재시도/오류분류 로직만 코드 레벨에서 검증한다 — 실제 API가 정확히
같은 응답을 내려주는지는 실 키 발급 후 별도로 재검증해야 한다.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from services.ingestion_batch.gov_data_client import (
    GovDataApiError,
    GovDataClientError,
    GovDataPortalClient,
)

TRADE_DATE = date(2026, 9, 11)
BAS_DT = "20260911"


def _success_body(items: list[dict] | dict | str, total_count: int) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "numOfRows": 1000,
                "pageNo": 1,
                "totalCount": total_count,
                "items": {"item": items} if items != "" else "",
            },
        }
    }


def _item(stock_code: str = "005930") -> dict:
    return {
        "basDt": BAS_DT,
        "srtnCd": stock_code,
        "itmsNm": "테스트종목",
        "mrktCtg": "KOSPI",
        "mkp": "70000",
        "hipr": "71000",
        "lopr": "69500",
        "clpr": "70500",
        "trqu": "12345678",
        "trPrc": "870000000000",
    }


def _make_client(handler, *, max_retries: int = 3, sleep=lambda s: None) -> GovDataPortalClient:
    transport = httpx.MockTransport(handler)
    return GovDataPortalClient(
        base_url="https://example.invalid/getStockPriceInfo",
        service_key="TEST-KEY",
        max_retries=max_retries,
        sleep=sleep,
        transport=transport,
    )


def test_fetch_ohlcv_success_single_item_as_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([_item()], total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_ohlcv(TRADE_DATE)

    assert result.total_count == 1
    assert len(result.records) == 1
    record = result.records[0]
    assert record.stock_code == "005930"
    assert record.trade_date == TRADE_DATE
    assert record.open == 70000
    assert record.close == 70500
    assert record.volume == 12345678
    assert record.trading_value == 870000000000


def test_fetch_ohlcv_success_single_item_as_dict_not_list():
    """결과가 1건이면 이 플랫폼이 item을 dict(리스트 아님)로 내려주는 경우를 정규화."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body(_item(), total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_ohlcv(TRADE_DATE)

    assert len(result.records) == 1


def test_fetch_ohlcv_zero_results_returns_empty_list():
    """items가 빈 문자열로 내려오는 0건 케이스(+1영업일 지연 감지에 사용)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body("", total_count=0))

    with _make_client(handler) as client:
        result = client.fetch_ohlcv(TRADE_DATE)

    assert result.records == []
    assert result.total_count == 0


def test_fetch_ohlcv_business_error_result_code_not_00_raises_immediately():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED"},
                    "body": {},
                }
            },
        )

    with _make_client(handler) as client, pytest.raises(GovDataApiError) as exc_info:
        client.fetch_ohlcv(TRADE_DATE)

    assert exc_info.value.retryable is False
    assert call_count == 1  # 재시도하지 않음


def test_fetch_ohlcv_gateway_xml_auth_error_non_retryable():
    """XML 형태 게이트웨이 오류(resultType 미지정/xml 요청 시 실측 형태)."""
    xml_body = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader>"
        "<errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg>"
        "<returnAuthMsg>등록되지 않은 서비스키</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode>"
        "</cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # 실측(unit-02-note.md §2): 이 오류는 HTTP 200이 아니라 403으로 내려온다.
        return httpx.Response(403, content=xml_body, headers={"content-type": "application/xml"})

    with _make_client(handler) as client, pytest.raises(GovDataApiError) as exc_info:
        client.fetch_ohlcv(TRADE_DATE)

    assert exc_info.value.retryable is False
    assert call_count == 1


def test_fetch_ohlcv_gateway_json_auth_error_non_retryable():
    """resultType=json을 요청해도 게이트웨이 오류는 XML이 아니라 별도 JSON 봉투로
    내려올 수 있다 — data.go.kr 실제 엔드포인트에 서비스키 없이 호출해 확인한
    실측 형태 그대로다(unit-02-note.md §2, 상상으로 지어낸 응답이 아님)."""
    json_body = (
        '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{'
        '"errMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR",'
        '"returnAuthMsg":"등록되지 않은 서비스키",'
        '"returnReasonCode":"30"}}}'
    )
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(403, content=json_body, headers={"content-type": "application/json"})

    with _make_client(handler) as client, pytest.raises(GovDataApiError) as exc_info:
        client.fetch_ohlcv(TRADE_DATE)

    assert exc_info.value.retryable is False
    assert call_count == 1
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in str(exc_info.value)


def test_fetch_ohlcv_gateway_xml_rate_limit_error_retryable_then_raises():
    xml_body = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader>"
        "<errMsg>LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR</errMsg>"
        "<returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>"
        "<returnReasonCode>22</returnReasonCode>"
        "</cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    call_count = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=xml_body, headers={"content-type": "application/xml"})

    with (
        _make_client(handler, max_retries=3, sleep=sleeps.append) as client,
        pytest.raises(GovDataApiError) as exc_info,
    ):
        client.fetch_ohlcv(TRADE_DATE)

    assert exc_info.value.retryable is True
    assert call_count == 4  # 최초 시도 + 3회 재시도
    assert sleeps == [1, 2, 4]  # 지수 백오프 1s/2s/4s (§5-4)


def test_fetch_ohlcv_http_500_retries_then_raises_client_error():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, text="service unavailable")

    with (
        _make_client(handler, max_retries=3, sleep=lambda s: None) as client,
        pytest.raises(GovDataClientError),
    ):
        client.fetch_ohlcv(TRADE_DATE)

    assert call_count == 4


def test_fetch_ohlcv_timeout_retries_then_raises():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectTimeout("boom", request=request)

    with (
        _make_client(handler, max_retries=2, sleep=lambda s: None) as client,
        pytest.raises(GovDataClientError),
    ):
        client.fetch_ohlcv(TRADE_DATE)

    assert call_count == 3  # 최초 시도 + 2회 재시도


def test_fetch_ohlcv_http_400_raises_immediately_without_retry():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, text="bad request")

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_ohlcv(TRADE_DATE)

    assert call_count == 1


def test_fetch_ohlcv_recovers_after_transient_failure():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, text="temporary")
        return httpx.Response(200, json=_success_body([_item()], total_count=1))

    with _make_client(handler, sleep=lambda s: None) as client:
        result = client.fetch_ohlcv(TRADE_DATE)

    assert len(result.records) == 1
    assert call_count == 2


def test_fetch_ohlcv_bas_dt_mismatch_raises():
    item = _item()
    item["basDt"] = "20260910"  # 요청한 날짜(20260911)와 불일치

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_ohlcv(TRADE_DATE)


def test_fetch_ohlcv_missing_required_field_raises():
    item = _item()
    del item["clpr"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_ohlcv(TRADE_DATE)


# --- fetch_stock_master_snapshot (UNIT-03, REQ-001) ---
# `_fetch_raw_items`를 fetch_ohlcv와 공유하므로 재시도/게이트웨이 오류 분기
# 자체는 위 테스트들로 이미 커버된다. 여기서는 이 메서드 고유의 파싱 로직
# (itmsNm/mrktCtg 추출, 코스피/코스닥 외 값 필터링)만 검증한다.


def test_fetch_stock_master_snapshot_success_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([_item()], total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_stock_master_snapshot(TRADE_DATE)

    assert result.total_count == 1
    assert len(result.records) == 1
    record = result.records[0]
    assert record.stock_code == "005930"
    assert record.name == "테스트종목"
    assert record.market == "KOSPI"


def test_fetch_stock_master_snapshot_maps_korean_market_category():
    item = _item()
    item["mrktCtg"] = "코스닥"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_stock_master_snapshot(TRADE_DATE)

    assert result.records[0].market == "KOSDAQ"


def test_fetch_stock_master_snapshot_filters_out_non_kospi_kosdaq():
    """코넥스 등 코스피/코스닥 외 시장 구분은 REQ-001 범위 밖이라 건너뛴다(예외 아님)."""
    kospi_item = _item(stock_code="005930")
    konex_item = _item(stock_code="900001")
    konex_item["mrktCtg"] = "코넥스"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_success_body([kospi_item, konex_item], total_count=2)
        )

    with _make_client(handler) as client:
        result = client.fetch_stock_master_snapshot(TRADE_DATE)

    assert result.total_count == 2  # API가 보고한 원본 건수는 그대로 유지
    assert len(result.records) == 1  # 필터링 후 남은 레코드만
    assert result.records[0].stock_code == "005930"


def test_fetch_stock_master_snapshot_single_item_as_dict_not_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body(_item(), total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_stock_master_snapshot(TRADE_DATE)

    assert len(result.records) == 1


def test_fetch_stock_master_snapshot_bas_dt_mismatch_raises():
    item = _item()
    item["basDt"] = "20260910"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_stock_master_snapshot(TRADE_DATE)


def test_fetch_stock_master_snapshot_missing_required_field_raises():
    item = _item()
    del item["itmsNm"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_stock_master_snapshot(TRADE_DATE)


def test_fetch_stock_master_snapshot_empty_name_raises():
    item = _item()
    item["itmsNm"] = "   "

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_stock_master_snapshot(TRADE_DATE)


def test_fetch_stock_master_snapshot_shares_gateway_error_handling():
    """`_fetch_raw_items` 공유 검증 — fetch_ohlcv에서 이미 실측 기반으로 검증한
    게이트웨이 오류 처리(unit-02-note.md §0-2)가 이 메서드에도 그대로 적용된다."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=_success_body([_item()], total_count=1))

    with _make_client(handler) as client:
        client.fetch_stock_master_snapshot(TRADE_DATE)

    assert call_count == 1


def test_fetch_fundamentals_success_parses_market_cap_and_leaves_per_pbr_none():
    item = _item()
    item["mrktTotAmt"] = "500000000000000"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_fundamentals(TRADE_DATE)

    assert result.total_count == 1
    assert len(result.records) == 1
    record = result.records[0]
    assert record.stock_code == "005930"
    assert record.trade_date == TRADE_DATE
    assert record.market_cap == 500000000000000
    # PER/PBR은 이 오퍼레이션이 제공하지 않는 것으로 판단해 항상 None이어야 한다
    # (DEF-005 정정 — 상상으로 채우지 않는다).
    assert record.per is None
    assert record.pbr is None


def test_fetch_fundamentals_missing_market_cap_field_defaults_to_none():
    """mrktTotAmt 필드 자체가 없는 item은 실패시키지 않고 market_cap=None으로 둔다."""
    item = _item()
    assert "mrktTotAmt" not in item

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_fundamentals(TRADE_DATE)

    assert result.records[0].market_cap is None


def test_fetch_fundamentals_empty_string_market_cap_defaults_to_none():
    item = _item()
    item["mrktTotAmt"] = ""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_fundamentals(TRADE_DATE)

    assert result.records[0].market_cap is None


def test_fetch_fundamentals_unparseable_market_cap_raises():
    """필드가 존재하는데 숫자가 아니면(진짜 이상값) 조용히 넘기지 않고 명시적으로 실패한다."""
    item = _item()
    item["mrktTotAmt"] = "not-a-number"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_fundamentals(TRADE_DATE)


def test_fetch_fundamentals_bas_dt_mismatch_raises():
    item = _item()
    item["basDt"] = "20260101"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_fundamentals(TRADE_DATE)


def test_fetch_fundamentals_missing_required_field_raises():
    item = _item()
    del item["srtnCd"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body([item], total_count=1))

    with _make_client(handler) as client, pytest.raises(GovDataClientError):
        client.fetch_fundamentals(TRADE_DATE)


def test_fetch_fundamentals_single_item_as_dict_not_list():
    item = _item()
    item["mrktTotAmt"] = "123456789"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body(item, total_count=1))

    with _make_client(handler) as client:
        result = client.fetch_fundamentals(TRADE_DATE)

    assert len(result.records) == 1
    assert result.records[0].market_cap == 123456789


def test_fetch_fundamentals_shares_gateway_error_handling():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "OpenAPI_ServiceResponse": {
                    "cmmMsgHeader": {
                        "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                        "returnAuthMsg": "등록되지 않은 서비스키",
                        "returnReasonCode": "30",
                    }
                }
            },
        )

    with _make_client(handler) as client, pytest.raises(GovDataApiError) as exc_info:
        client.fetch_fundamentals(TRADE_DATE)
    assert exc_info.value.retryable is False
