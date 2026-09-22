"""공공데이터포털 "금융위원회_주식시세정보" API 클라이언트 (REQ-011).

**정상 응답(실제 시세 데이터)은 유효한 서비스키가 없어 검증하지 못했다**
— unit-02-note.md §2 "확인 필요" 참조. 다만 게이트웨이 오류 응답 형태는
실제로 이 프로젝트가 서비스키 없이 실 엔드포인트
(`https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/
getStockPriceInfo`)를 직접 호출해 **실측**했다(2026-09-15). 추측으로
필드를 지어내지 않았다:

1. data.go.kr에 공개된 "금융위원회_주식시세정보"(GetStockSecuritiesInfoService,
   오퍼레이션 getStockPriceInfo) 서비스 문서에 기재된 요청 파라미터
   (serviceKey, numOfRows, pageNo, resultType, basDt 등)와 응답 필드명
   (basDt, srtnCd, isinCd, itmsNm, mrktCtg, clpr, mkp, hipr, lopr, trqu,
   trPrc, lstgStCnt, mrktTotAmt) — 정상 응답 봉투 형태(`{"response":
   {"header": {"resultCode", "resultMsg"}, "body": {"items": {"item":
   [...]}, "numOfRows", "pageNo", "totalCount"}}}`, `resultCode=="00"`이
   성공)는 이 문서 명세를 근거로 했을 뿐 실제 성공 응답으로 검증하지
   못했다.
2. **실측 확인된 게이트웨이 오류 동작(서비스키 미등록 케이스로 재현)**:
   - `resultType` 생략 또는 `xml` 지정 시: HTTP 403 + XML 봉투
     (`<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>.../<returnAuthMsg>
     .../<returnReasonCode>30</...>`).
   - `resultType=json` 지정 시에도 정상 응답 봉투(`response.header`)가
     아니라 **HTTP 403 + `{"OpenAPI_ServiceResponse": {"cmmMsgHeader":
     {...}}}` 형태의 JSON**으로 내려온다(같은 필드명, XML이 아님) — 이
     플랫폼이 "resultType=json 요청 시 게이트웨이 오류도 XML로만
     내려온다"는 일부 통념과 다르다는 것을 실측으로 확인했다.
   - 위 두 형태 모두 `_parse_gateway_error_envelope()`가 처리한다.
   - 한도초과(returnReasonCode=22 등) 케이스는 실 트래픽으로 재현하지
     못해 코드 22/05를 재시도 대상으로 둔 것은 여전히 미검증 가정이다.
   - 조회 결과가 0건이면 `items`가 `{"item": []}`이 아니라 빈 문자열
     `""`로 내려오는 경우가 있다는 것은 XML→JSON 변환 플랫폼(공공데이터
     포털 계열 API 전반)에 보고된 특성을 근거로 한 가정이며(이 오퍼레이션
     자체로 실측하지 못함), 이 경우를 "결과 0건"으로 명시적으로 처리한다
     (대상 거래일 데이터 미배포 감지에 사용, run_ingestion.py 참조).

**(2026-09-22 추가, DEF-005 정정 반영)** PER/PBR/시가총액 중 **시가총액
(`mrktTotAmt`)만 이 오퍼레이션이 실제로 제공하는 것으로 확인됐다** —
data.go.kr 공식 Swagger 원문 대조 결과(traceability.md DEF-005). PER/PBR은
여전히 이 오퍼레이션에 없는 것으로 판단해 파싱하지 않는다(상상으로 필드를
지어내지 않는다는 원칙 유지 — `services/ingestion_batch/models.py`
`RawFundamentals` 문서 참조. `per`/`pbr` 컬럼이 nullable인 이유이기도 하다).
실 서비스키로 `mrktTotAmt`가 진짜 응답에 포함되는지는 아직 실측하지
못했다(서비스키 활성화 대기 중) — 이 파싱 로직 자체는 문서 명세 기준으로
작성했고, 실측 검증은 키 활성화 후 별도로 진행한다.

**(UNIT-03 추가)** `itmsNm`(종목명)/`mrktCtg`(시장구분)도 이 오퍼레이션의
같은 응답 item에 함께 내려오는 필드로 문서에 기재되어 있다(위 필드 목록
참조, 실측은 못 함 — 위와 동일한 한계). `public_serving.stock_master`(REQ-001)
시드 데이터는 새로운 외부 데이터 소스를 조사하는 대신 이 필드를 재사용해
채운다(03-system-design.md §1-2 "Ingestion Batch만 외부 데이터 소스와
통신한다" 원칙에 따라, 이 파일이 아닌 별도 모듈이 공공데이터포털을 직접
호출하지 않는다). `mrktCtg`의 실제 값이 한글("코스피"/"코스닥")인지 영문
("KOSPI"/"KOSDAQ")인지도 실측하지 못해 `_MARKET_CATEGORY_TO_LISTED_MARKET`이
두 표기를 모두 방어적으로 처리한다. 코스피/코스닥 외 값(코넥스 등)은
REQ-001 범위 밖이라 조용히 건너뛴다(예외 아님).
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx


class GovDataClientError(RuntimeError):
    """API 호출 자체가 실패했거나(재시도 소진 포함) 응답이 명백히 비정상일 때."""


class GovDataApiError(GovDataClientError):
    """API가 명시적으로 오류를 반환했을 때(게이트웨이 인증 오류, resultCode!=00 등).

    타임아웃/5xx처럼 재시도로 해소될 수 있는 오류와 달리, 이 예외는 재시도해도
    같은 결과가 나올 가능성이 높은 오류(예: 서비스키 미등록, 파라미터 오류)다.
    """

    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class RawOhlcvRecord:
    """getStockPriceInfo 응답 item 1건을 파싱한 결과.

    `market`은 이 API의 `mrktCtg`(상장시장 KOSPI/KOSDAQ)가 아니라 이 프로젝트의
    거래소 세션 구분(§3-1-1)이다. MVP는 KRX 정규장만 다루므로(DEC-010) 호출자가
    고정값 "KRX"를 채워 넣는다 — 이 클라이언트는 `mrktCtg` 값 자체를 raw_ohlcv에
    싣지 않는다(스키마에 그런 컬럼이 없음, §3-2).
    """

    stock_code: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trading_value: int


@dataclass(frozen=True)
class FetchResult:
    records: list[RawOhlcvRecord]
    total_count: int


@dataclass(frozen=True)
class StockMasterSnapshotRecord:
    """getStockPriceInfo 응답 item에서 종목 마스터(REQ-001)에 필요한 부분만 추출.

    `market`은 이 프로젝트의 상장시장 구분(§3-1-1, KOSPI/KOSDAQ)이며
    `RawOhlcvRecord`가 다루는 거래소 세션 구분(KRX/NXT)과는 다른 축이다.
    """

    stock_code: str
    name: str
    market: str


@dataclass(frozen=True)
class StockMasterFetchResult:
    records: list[StockMasterSnapshotRecord]
    total_count: int


@dataclass(frozen=True)
class RawFundamentalsRecord:
    """getStockPriceInfo 응답 item에서 재무지표(raw_fundamentals 대상)를 추출.

    `per`/`pbr`은 이 오퍼레이션이 제공하지 않는 것으로 판단해 항상 `None`이다
    (§0 docstring DEF-005 정정 참조 — 상상으로 채우지 않는다). `market_cap`
    (`mrktTotAmt`)만 파싱한다.
    """

    stock_code: str
    trade_date: date
    per: Decimal | None
    pbr: Decimal | None
    market_cap: int | None


@dataclass(frozen=True)
class FundamentalsFetchResult:
    records: list[RawFundamentalsRecord]
    total_count: int


def _parse_decimal(value: str, *, field: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise GovDataClientError(f"필드 {field} 값을 숫자로 파싱할 수 없습니다: {value!r}") from exc


def _parse_int(value: str, *, field: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise GovDataClientError(f"필드 {field} 값을 정수로 파싱할 수 없습니다: {value!r}") from exc


def _parse_item(item: dict, *, expected_trade_date: date) -> RawOhlcvRecord:
    required = ("srtnCd", "basDt", "mkp", "hipr", "lopr", "clpr", "trqu", "trPrc")
    missing = [f for f in required if f not in item]
    if missing:
        raise GovDataClientError(f"응답 item에 필수 필드가 없습니다: {missing} (item={item!r})")

    bas_dt = item["basDt"]
    if bas_dt != expected_trade_date.strftime("%Y%m%d"):
        raise GovDataClientError(
            f"요청한 basDt({expected_trade_date:%Y%m%d})와 응답 item의 basDt({bas_dt})가 "
            "다릅니다. API가 다른 날짜 데이터를 반환했을 가능성이 있어 명시적으로 실패시킵니다."
        )

    return RawOhlcvRecord(
        stock_code=item["srtnCd"],
        trade_date=expected_trade_date,
        open=_parse_decimal(item["mkp"], field="mkp"),
        high=_parse_decimal(item["hipr"], field="hipr"),
        low=_parse_decimal(item["lopr"], field="lopr"),
        close=_parse_decimal(item["clpr"], field="clpr"),
        volume=_parse_int(item["trqu"], field="trqu"),
        trading_value=_parse_int(item["trPrc"], field="trPrc"),
    )


# mrktCtg 실제 표기(한글/영문)를 실측하지 못해 두 형태 모두 방어적으로 처리한다
# (§0 docstring 참조). 코스피/코스닥 외 값(코넥스 등)은 매핑에 없으므로 None 처리된다.
_MARKET_CATEGORY_TO_LISTED_MARKET = {
    "코스피": "KOSPI",
    "코스닥": "KOSDAQ",
    "KOSPI": "KOSPI",
    "KOSDAQ": "KOSDAQ",
}


def _parse_stock_master_item(
    item: dict, *, expected_trade_date: date
) -> StockMasterSnapshotRecord | None:
    required = ("srtnCd", "itmsNm", "mrktCtg", "basDt")
    missing = [f for f in required if f not in item]
    if missing:
        raise GovDataClientError(f"응답 item에 필수 필드가 없습니다: {missing} (item={item!r})")

    bas_dt = item["basDt"]
    if bas_dt != expected_trade_date.strftime("%Y%m%d"):
        raise GovDataClientError(
            f"요청한 basDt({expected_trade_date:%Y%m%d})와 응답 item의 basDt({bas_dt})가 "
            "다릅니다. API가 다른 날짜 데이터를 반환했을 가능성이 있어 명시적으로 실패시킵니다."
        )

    market = _MARKET_CATEGORY_TO_LISTED_MARKET.get(item["mrktCtg"])
    if market is None:
        # 코스피/코스닥 외 시장 구분(코넥스 등)은 REQ-001 범위 밖이라 건너뛴다.
        return None

    name = item["itmsNm"].strip()
    if not name:
        raise GovDataClientError(f"종목명(itmsNm)이 비어 있습니다: item={item!r}")

    return StockMasterSnapshotRecord(stock_code=item["srtnCd"], name=name, market=market)


def _parse_fundamentals_item(item: dict, *, expected_trade_date: date) -> RawFundamentalsRecord:
    """`mrktTotAmt`(시가총액)만 파싱한다. `per`/`pbr`은 이 오퍼레이션이 제공하지
    않는 것으로 판단해 항상 `None`(§0 docstring DEF-005 정정 참조).

    `srtnCd`/`basDt`는 OHLCV와 동일하게 필수로 취급한다(이 값들이 없으면 어느
    종목/거래일의 시가총액인지조차 알 수 없어 행 자체가 무의미하다). 반면
    `mrktTotAmt`는 이 항목만 빠지는 경우가 있을 수 있다고 보고(공식 문서가
    "관리종목/거래정지 등 일부 케이스는 값이 없을 수 있다"를 명시하지 않았지만,
    raw_fundamentals.market_cap이 애초에 nullable로 설계된 이유이기도 함),
    필드 자체가 없거나 빈 문자열이면 조용히 `None`으로 두고, 값이 있는데
    숫자로 파싱이 안 되면(진짜 이상값) 그때는 다른 필드와 동일하게 명시적으로
    실패시킨다.
    """
    required = ("srtnCd", "basDt")
    missing = [f for f in required if f not in item]
    if missing:
        raise GovDataClientError(f"응답 item에 필수 필드가 없습니다: {missing} (item={item!r})")

    bas_dt = item["basDt"]
    if bas_dt != expected_trade_date.strftime("%Y%m%d"):
        raise GovDataClientError(
            f"요청한 basDt({expected_trade_date:%Y%m%d})와 응답 item의 basDt({bas_dt})가 "
            "다릅니다. API가 다른 날짜 데이터를 반환했을 가능성이 있어 명시적으로 실패시킵니다."
        )

    raw_market_cap = item.get("mrktTotAmt")
    market_cap: int | None = None
    if raw_market_cap not in (None, ""):
        market_cap = _parse_int(raw_market_cap, field="mrktTotAmt")

    return RawFundamentalsRecord(
        stock_code=item["srtnCd"],
        trade_date=expected_trade_date,
        per=None,
        pbr=None,
        market_cap=market_cap,
    )


def _gateway_error_from_fields(
    err_msg: str | None, reason: str | None, code: str | None
) -> GovDataApiError:
    err_msg = err_msg or "UNKNOWN_GATEWAY_ERROR"
    reason = reason or ""
    code = code or ""
    # 한도초과/일시 오류(returnReasonCode 22=한도초과, 05=타임아웃성 서버오류 등)는
    # 재시도 여지가 있고, 서비스키 미등록(30, 실측 확인 — unit-02-note.md §2)/
    # 파라미터 오류는 재시도해도 동일하므로 재시도 대상에서 제외한다. data.go.kr
    # 플랫폼 공통 반환코드 표에 근거하되, 22/05는 실 트래픽으로 재현하지 못해
    # 안전 측(재시도 허용)으로 취급한다(실 키 확보 후 재검증 필요).
    retryable = code in {"22", "05"}
    return GovDataApiError(
        f"공공데이터포털 게이트웨이 오류: {err_msg} (reason={reason}, code={code})",
        retryable=retryable,
    )


def _parse_gateway_error_envelope(body: str) -> GovDataApiError | None:
    """게이트웨이 레벨 오류 봉투(`OpenAPI_ServiceResponse`)를 감지/파싱한다.

    실측 확인(unit-02-note.md §2): `resultType=json`을 요청해도 서비스키 미등록
    같은 게이트웨이 오류는 XML(HTTP 200 또는 403)로 내려올 수도, `{"OpenAPI_
    ServiceResponse": {...}}` 형태의 JSON(HTTP 403)으로 내려올 수도 있다 — 두
    형태 모두 같은 필드(errMsg/returnAuthMsg/returnReasonCode)를 담고 있어
    이 함수가 둘 다 처리한다.
    """
    stripped = body.lstrip()
    if stripped.startswith("<"):
        try:
            root = ET.fromstring(stripped)
        except ET.ParseError:
            return None
        if not root.tag.endswith("OpenAPI_ServiceResponse"):
            return None
        err_msg_el = root.find(".//errMsg")
        reason_el = root.find(".//returnAuthMsg")
        code_el = root.find(".//returnReasonCode")
        return _gateway_error_from_fields(
            err_msg_el.text if err_msg_el is not None else None,
            reason_el.text if reason_el is not None else None,
            code_el.text if code_el is not None else None,
        )

    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            return None
        envelope = payload.get("OpenAPI_ServiceResponse") if isinstance(payload, dict) else None
        if not isinstance(envelope, dict):
            return None
        header = envelope.get("cmmMsgHeader", {})
        return _gateway_error_from_fields(
            header.get("errMsg"), header.get("returnAuthMsg"), header.get("returnReasonCode")
        )

    return None


class GovDataPortalClient:
    """공공데이터포털 "금융위원회_주식시세정보" getStockPriceInfo 클라이언트.

    재시도(§5-4): 타임아웃/5xx/네트워크 오류에 한해 최대 `max_retries`회,
    지수 백오프(1s/2s/4s)로 재시도한다. 서비스키 오류 등 재시도해도 결과가
    같을 오류는 즉시(재시도 없이) 예외로 전파한다.
    """

    def __init__(
        self,
        *,
        base_url: str,
        service_key: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base_url = base_url
        self._service_key = service_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GovDataPortalClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_ohlcv(
        self, trade_date: date, *, page_no: int = 1, num_of_rows: int = 1000
    ) -> FetchResult:
        """지정 거래일의 전체 종목 시세를 조회한다(필요 시 페이지네이션 반복은 호출자 책임).

        totalCount가 num_of_rows를 넘으면 호출자가 page_no를 늘려 반복 호출해야 한다
        (design §2-2: 종목 목록 일괄 조회 엔드포인트를 하루 1~2회 호출하는 수준으로 설계).
        """
        raw_items, total_count = self._fetch_raw_items(
            trade_date, page_no=page_no, num_of_rows=num_of_rows
        )
        records = [_parse_item(item, expected_trade_date=trade_date) for item in raw_items]
        return FetchResult(records=records, total_count=total_count)

    def fetch_stock_master_snapshot(
        self, trade_date: date, *, page_no: int = 1, num_of_rows: int = 1000
    ) -> StockMasterFetchResult:
        """지정 거래일의 전체 종목 스냅샷에서 종목코드/종목명/상장시장만 추출한다(REQ-001).

        `fetch_ohlcv`와 동일한 오퍼레이션(getStockPriceInfo)·동일한 요청/재시도/오류
        처리 경로(`_fetch_raw_items`)를 공유하고, item당 파싱 방식만 다르다(OHLCV
        필드 대신 `itmsNm`/`mrktCtg`). 새로운 외부 API를 추가로 호출하지 않는다
        (03-system-design.md §1-2 "Ingestion Batch만 외부 데이터 소스와 통신한다").
        """
        raw_items, total_count = self._fetch_raw_items(
            trade_date, page_no=page_no, num_of_rows=num_of_rows
        )
        records = [
            record
            for item in raw_items
            if (record := _parse_stock_master_item(item, expected_trade_date=trade_date))
            is not None
        ]
        return StockMasterFetchResult(records=records, total_count=total_count)

    def fetch_fundamentals(
        self, trade_date: date, *, page_no: int = 1, num_of_rows: int = 1000
    ) -> FundamentalsFetchResult:
        """지정 거래일의 전체 종목 시가총액(raw_fundamentals 대상)을 조회한다.

        `fetch_ohlcv`/`fetch_stock_master_snapshot`와 동일한 오퍼레이션·요청 경로를
        공유한다(새 외부 API를 추가하지 않는다는 원칙 동일). `per`/`pbr`은 이
        오퍼레이션이 제공하지 않아 항상 `None`으로 채워진 레코드가 반환된다
        (§0 docstring, `_parse_fundamentals_item` 참조).
        """
        raw_items, total_count = self._fetch_raw_items(
            trade_date, page_no=page_no, num_of_rows=num_of_rows
        )
        records = [
            _parse_fundamentals_item(item, expected_trade_date=trade_date) for item in raw_items
        ]
        return FundamentalsFetchResult(records=records, total_count=total_count)

    def _fetch_raw_items(
        self, trade_date: date, *, page_no: int, num_of_rows: int
    ) -> tuple[list[dict], int]:
        """요청/재시도/게이트웨이 오류 처리를 공통으로 수행하고 원시 item 목록을 반환한다.

        `fetch_ohlcv`/`fetch_stock_master_snapshot`가 이 메서드를 공유해, 같은
        네트워크 계층 로직(재시도/백오프/오류분류)이 두 곳에 중복되지 않게 한다.
        """
        params = {
            "serviceKey": self._service_key,
            "resultType": "json",
            "basDt": trade_date.strftime("%Y%m%d"),
            "numOfRows": str(num_of_rows),
            "pageNo": str(page_no),
        }

        last_error: Exception | None = None
        backoffs = [2**i for i in range(self._max_retries)]  # 1s, 2s, 4s, ...
        for attempt, backoff in enumerate([0.0, *backoffs][: self._max_retries + 1]):
            if backoff:
                self._sleep(backoff)
            try:
                response = self._client.get(self._base_url, params=params)
            except httpx.TimeoutException as exc:
                last_error = exc
                continue
            except httpx.TransportError as exc:
                last_error = exc
                continue

            # 게이트웨이 레벨 오류(서비스키 미등록 등)는 HTTP 200이 아니라 4xx로
            # 내려올 수 있고(실측: 403, unit-02-note.md §2 참조), resultType=json을
            # 요청해도 XML이 아니라 "OpenAPI_ServiceResponse" 키를 가진 JSON으로
            # 내려올 수도 있다 — 그래서 상태코드 분기보다 먼저 본문 형태로 감지한다.
            gateway_error = _parse_gateway_error_envelope(response.text)
            if gateway_error is not None:
                if gateway_error.retryable and attempt < self._max_retries:
                    last_error = gateway_error
                    continue
                raise gateway_error

            if response.status_code >= 500:
                last_error = GovDataClientError(
                    f"공공데이터포털 서버 오류: HTTP {response.status_code}"
                )
                continue
            if response.status_code >= 400:
                raise GovDataClientError(
                    f"공공데이터포털 요청 오류(재시도 무의미): HTTP {response.status_code} "
                    f"body={response.text[:500]!r}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise GovDataClientError(
                    f"응답을 JSON으로 파싱할 수 없습니다: {response.text[:500]!r}"
                ) from exc

            return self._parse_success_envelope(payload)

        raise GovDataClientError(
            f"{self._max_retries}회 재시도 후에도 요청에 실패했습니다: {last_error}"
        ) from last_error

    @staticmethod
    def _parse_success_envelope(payload: dict) -> tuple[list[dict], int]:
        """정상 응답 봉투를 검증하고 (원시 item 목록, totalCount)를 반환한다.

        item당 도메인 필드 파싱(OHLCV vs 종목마스터)은 호출자(`fetch_ohlcv`/
        `fetch_stock_master_snapshot`)의 책임이다 — 이 메서드는 봉투/resultCode/
        items 정규화까지만 공통으로 처리한다.
        """
        try:
            response_body = payload["response"]
            header = response_body["header"]
            body = response_body["body"]
        except (KeyError, TypeError) as exc:
            raise GovDataClientError(f"응답 형식이 예상과 다릅니다: {payload!r}") from exc

        result_code = header.get("resultCode")
        if result_code != "00":
            raise GovDataApiError(
                f"API가 오류를 반환했습니다: resultCode={result_code} "
                f"resultMsg={header.get('resultMsg')!r}",
                retryable=False,
            )

        total_count = body.get("totalCount", 0)
        items_field = body.get("items", "")
        if items_field == "" or items_field is None:
            # 조회 결과 0건(예: 대상 거래일 데이터가 아직 배포되지 않음).
            return [], int(total_count)

        raw_items = items_field.get("item", [])
        if isinstance(raw_items, dict):
            # 결과가 정확히 1건이면 이 플랫폼은 item을 리스트가 아닌 단일 dict로
            # 내려주는 경우가 있다(XML→JSON 변환 특성, 이 플랫폼 공통 이슈).
            raw_items = [raw_items]

        return raw_items, int(total_count)
