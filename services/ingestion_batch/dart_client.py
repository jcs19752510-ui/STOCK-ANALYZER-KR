"""DART(전자공시시스템) OpenAPI 클라이언트 (PER/PBR·업종 실데이터 대체 소스).

**배경**: 공공데이터포털 "금융위원회_주식시세정보"는 PER/PBR을 제공하지
않는다는 사실이 실측으로 확정됐다(`gov_data_client.py` DEF-005 정정 참조).
대체로 검토한 KRX Open API의 "주식" 카테고리(8개 API, 2026-09-22 실측)에도
PER/PBR·업종분류가 없었고, KRX Data Marketplace의 해당 상품("PER/PBR/배당
수익률(개별종목)", "업종분류현황")은 "데이터상품" 메뉴의 **유료 구매** 항목으로
확인됐다(사용자 실측 스크린샷, 2026-09-22). 상업적 이용을 현재 하지 않기로
한 프로젝트 방침과도 맞지 않아, 무료·즉시발급 API인 DART로 전환했다.

**설계 원칙(이 파일 전반)**: DART가 실제로 제공하는 필드만 다룬다.
- PER/PBR을 DART가 직접 주지 않으므로, 시가총액(이미 raw_fundamentals에
  적재됨) 대비 재무제표 원문(당기순이익/자본총계)으로 **호출자가** 계산한다
  (이 클라이언트는 원문만 파싱, 비율 계산은 `run_ingestion.py`/
  `repository.py` 책임).
- 연결재무제표(CFS)가 있으면 "지배기업 소유주지분" 기준(비지배지분 제외,
  실제 주주 몫)을 우선 사용하고, 없으면(개별 OFS, 또는 지배지분 세부 계정이
  없는 완전자회사 없음 케이스) 총계로 대체한다. 실 데이터로 삼성전자
  연결(CFS) 사업보고서를 호출해 두 계정이 모두 실제로 존재함을 확인했다
  (`ifrs-full_ProfitLossAttributableToOwnersOfParent`,
  `ifrs-full_EquityAttributableToOwnersOfParent`).
- 같은 계정과목명이 재무제표 종류(sj_div)마다 중복 등장한다(예: "자본총계"가
  재무상태표(BS)뿐 아니라 자본변동표(SCE)에도 여러 줄 나타남 — 실측 확인).
  그래서 계정 매칭은 반드시 `sj_div`(BS/IS)로 먼저 좁힌 뒤 `account_id`로
  찾는다. `account_id`(XBRL 표준계정ID) 기준으로 매칭하고 한글
  `account_nm`은 참고용으로만 쓴다 — 같은 개념이라도 회사마다 계정명
  표기가 미세하게 다를 수 있기 때문이다.
"""

from __future__ import annotations

import io
import json
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

_BASE_URL = "https://opendart.fss.or.kr/api"

# DART 오류코드(공시검색 API 개발가이드, 2026-09-22 실측 확인). 000만 성공이고
# 013은 "조회된 데이타가 없습니다"로 정상적인 빈 결과(예: 이 회사는 CFS
# 미제출)다 — 예외가 아니라 호출자가 판단할 수 있도록 None으로 반환한다.
_STATUS_OK = "000"
_STATUS_NO_DATA = "013"
_STATUS_RATE_LIMITED = "020"


class DartClientError(RuntimeError):
    """API 호출 자체가 실패했거나(재시도 소진 포함) 응답이 명백히 비정상일 때."""


class DartApiError(DartClientError):
    """DART가 명시적으로 오류를 반환했을 때(인증키 오류, 파라미터 오류 등).

    `retryable=True`는 요청 제한 초과(020)처럼 잠시 후 재시도하면 해소될
    가능성이 있는 오류, `False`는 인증키 미등록 등 재시도해도 같은 결과가
    나올 오류다.
    """

    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class CorpCodeEntry:
    """`corpCode.xml`(전체 공시대상회사 고유번호 매핑) 1건."""

    corp_code: str
    corp_name: str
    stock_code: str | None


@dataclass(frozen=True)
class CompanyOverviewRecord:
    """`기업개황`(company.json) 응답에서 업종분류에 필요한 부분만 추출."""

    corp_code: str
    stock_code: str | None
    induty_code: str | None


@dataclass(frozen=True)
class CorpFinancialsRecord:
    """`단일회사 전체 재무제표`(fnlttSinglAcntAll.json)에서 추출한 당기순이익/자본총계.

    `fs_div`는 실제로 값을 얻어낸 재무제표 구분("CFS" 또는 "OFS")을 그대로
    남긴다 — 호출자가 CFS를 먼저 시도하고 실패 시 OFS로 대체하므로, 저장된
    값이 어느 기준인지 나중에 추적할 수 있어야 한다(원칙: 출처를 숨기지 않음).

    `reprt_code`가 사업보고서(11011)가 아니면 `net_income`은 실제 보고된
    누적 실적이 아니라 **12개월 기준으로 연환산한 값**이다(예: 1분기보고서면
    누적 3개월 실적 × 4) — 서로 다른 보고 주기의 PER을 같은 기준으로 비교할
    수 있게 하기 위한 근사치다. `equity`는 시점 스냅샷이라 연환산하지 않는다.
    """

    corp_code: str
    bsns_year: str
    reprt_code: str
    fs_div: str
    net_income: Decimal | None
    equity: Decimal | None


# sj_div(재무제표 구분)로 먼저 좁힌 뒤 이 순서대로 account_id를 찾는다.
# 1순위: 지배기업 소유주지분 기준(비지배지분 제외). 2순위: 총계(개별 재무제표이거나
# 완전자회사만 있어 지배지분 세부 계정이 없는 경우).
#
# 당기순이익은 sj_div가 "IS"(손익계산서) 하나가 아니라 **"IS" 또는
# "CIS"(포괄손익계산서) 둘 중 하나**일 수 있다 — 실측 확인(2026-09-22,
# 하이트진로 corp_code=00150244): 이 회사는 손익계산서와 포괄손익계산서를
# 하나로 합쳐 "CIS"로만 제출하고 별도 "IS"가 없다. 이런 회사에 sj_div="IS"만
# 찾으면 당기순이익이 전부 None으로 빠진다(실제로 이 버그를 삼성전자 외
# 다른 실 종목으로 --limit 검증하다 발견). 반대로 삼성전자처럼 IS/CIS를
# 모두 제출하는 회사는 "당기순이익"(ProfitLoss 계열)이 IS에만 있고 CIS에는
# "총포괄손익"(ComprehensiveIncome 계열, 다른 account_id)만 있어 중복/충돌이
# 없음을 확인했다 — 그래서 "IS" 우선, 없으면 "CIS"를 순서대로 시도해도 안전하다.
_NET_INCOME_SJ_DIVS = ("IS", "CIS")
_NET_INCOME_ACCOUNT_IDS = (
    "ifrs-full_ProfitLossAttributableToOwnersOfParent",
    "ifrs-full_ProfitLoss",
)
_EQUITY_SJ_DIV = "BS"
_EQUITY_ACCOUNT_IDS = (
    "ifrs-full_EquityAttributableToOwnersOfParent",
    "ifrs-full_Equity",
)

# **(2026-09-22 추가)** 분기/반기 재수집 지원 — 사업보고서(11011) 외의
# reprt_code를 다루기 전에 DART 공식 개발가이드로 실측 확인한 사실
# (opendart.fss.or.kr 개발가이드 DS003/2019020 "필드 설명" 원문 대조):
# 분기/반기보고서의 손익계산서(IS/CIS) 항목은 `thstrm_amount`가 **당기 3개월
# 단독** 금액이고, **연초부터의 누적** 금액은 별도 필드 `thstrm_add_amount`에
# 들어있다(재무상태표(BS)는 애초에 특정 시점 스냅샷이라 이 구분 자체가 없고
# `thstrm_amount` 하나뿐 — 삼성전자 2026 반기보고서 실측으로 BS 항목에
# add_amount류 필드가 아예 없음을 확인). 사업보고서(11011)는 이 구분이 없고
# `thstrm_amount` 자체가 이미 연간 금액이다(2025 사업보고서 실측 시
# thstrm_add_amount 필드 자체가 없었음).
#
# 그래서 당기순이익은 "연간(11011)이면 thstrm_amount, 그 외(분기/반기)면
# thstrm_add_amount(누적)"를 읽어야 하고, 서로 다른 보고서 기간(3/6/9/12개월)의
# PER을 같은 기준으로 비교하려면 12개월로 연환산해야 한다(그렇지 않으면 1분기
# 보고서만 반영된 종목은 실적이 1/4만 잡혀 PER이 부당하게 높게/낮게 보임).
# 자본총계는 시점 스냅샷이라 연환산 대상이 아니다(REPRT_MONTHS_COVERED는
# 당기순이익에만 적용).
REPRT_MONTHS_COVERED = {
    "11011": 12,  # 사업보고서(연간)
    "11012": 6,  # 반기보고서
    "11013": 3,  # 1분기보고서
    "11014": 9,  # 3분기보고서
}


def _parse_amount(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "")
    if cleaned == "":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _find_account_amount(
    items: list[dict],
    *,
    sj_div: str | tuple[str, ...],
    account_ids: tuple[str, ...],
    amount_field: str = "thstrm_amount",
) -> Decimal | None:
    sj_divs = (sj_div,) if isinstance(sj_div, str) else sj_div
    candidates = [item for item in items if item.get("sj_div") in sj_divs]
    for account_id in account_ids:
        for item in candidates:
            if item.get("account_id") == account_id:
                amount = _parse_amount(item.get(amount_field))
                if amount is not None:
                    return amount
    return None


def _parse_corp_code_xml(xml_bytes: bytes) -> list[CorpCodeEntry]:
    root = ET.fromstring(xml_bytes)  # noqa: S314 - DART 공식 API 자체 응답, 신뢰 소스
    entries: list[CorpCodeEntry] = []
    for node in root.findall("list"):
        corp_code = (node.findtext("corp_code") or "").strip()
        corp_name = (node.findtext("corp_name") or "").strip()
        stock_code_raw = (node.findtext("stock_code") or "").strip()
        if not corp_code:
            continue
        entries.append(
            CorpCodeEntry(
                corp_code=corp_code,
                corp_name=corp_name,
                stock_code=stock_code_raw or None,
            )
        )
    return entries


class DartClient:
    """DART OpenAPI 클라이언트. `GovDataPortalClient`와 동일한 재시도 원칙을 따른다:
    타임아웃/5xx/요청제한초과(020)는 재시도, 그 외 API 오류는 즉시 전파한다.

    **(2026-09-22 추가, 실측으로 발견)** 요청 사이 최소 간격을 두지 않고
    ~2,900종목을 초당 여러 건씩 연속 호출했더니, DART 응답이 명시적
    오류코드(020 등) 없이 **연결 자체가 리셋**되기 시작했다(`opendart.fss.or.kr`
    홈페이지 접속조차 실패 — curl 재현 확인). 공식 문서에 없는 IP 단위
    비공식 속도 제한/악용 방지로 추정된다(재현: corpCode.xml을 짧은 시간에
    반복 다운로드 + 수백 건 연속 호출). 그래서 요청 사이 최소 간격
    (`min_interval_seconds`)을 두는 방어적 페이싱을 추가했다 — 재시도만으로는
    막을 수 없는 문제였다(재시도할수록 오히려 같은 문제를 더 빨리 유발함).
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        min_interval_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ):
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._min_interval_seconds = min_interval_seconds
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DartClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_corp_code_map(self) -> dict[str, str]:
        """전체 공시대상회사의 (상장 종목코드 -> DART 고유번호) 매핑을 반환한다.

        `corpCode.xml`은 ZIP으로 내려오며 상장 여부와 무관한 모든 공시대상
        회사를 포함한다 — `stock_code`가 빈 값인(비상장) 항목은 제외한다.
        """
        content = self._request_bytes("corpCode.xml", params={"crtfc_key": self._api_key})
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            inner_name = next(n for n in zf.namelist() if n.upper().endswith(".XML"))
            xml_bytes = zf.read(inner_name)
        entries = _parse_corp_code_xml(xml_bytes)
        return {e.stock_code: e.corp_code for e in entries if e.stock_code}

    def fetch_company_overview(self, corp_code: str) -> CompanyOverviewRecord | None:
        """기업개황(업종코드 등)을 조회한다. 데이터 없음(013)이면 None."""
        payload = self._request_json(
            "company.json", params={"crtfc_key": self._api_key, "corp_code": corp_code}
        )
        if payload is None:
            return None
        return CompanyOverviewRecord(
            corp_code=payload.get("corp_code", corp_code),
            stock_code=(payload.get("stock_code") or "").strip() or None,
            induty_code=(payload.get("induty_code") or "").strip() or None,
        )

    def fetch_financials(
        self, corp_code: str, *, bsns_year: str, reprt_code: str, fs_div: str
    ) -> CorpFinancialsRecord | None:
        """단일회사 전체 재무제표에서 당기순이익/자본총계를 추출한다.

        해당 `fs_div`로 제출된 재무제표가 없으면(013) None을 반환한다 —
        호출자가 CFS 실패 시 OFS로 대체 시도하는 판단 근거로 쓴다.

        `reprt_code`가 사업보고서(11011)가 아니면(분기/반기) 당기순이익은
        `thstrm_amount`(당기 3개월 단독)가 아니라 `thstrm_add_amount`(연초
        누적)를 읽고, 12개월 기준으로 연환산한다(모듈 상단 `REPRT_MONTHS_COVERED`
        주석 참조 — DART 개발가이드 원문 대조로 실측 확정한 필드 의미).
        자본총계는 특정 시점 스냅샷이라 연환산하지 않는다.
        """
        payload_list = self._request_json_list(
            "fnlttSinglAcntAll.json",
            params={
                "crtfc_key": self._api_key,
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
        )
        if payload_list is None:
            return None

        months_covered = REPRT_MONTHS_COVERED[reprt_code]
        amount_field = "thstrm_amount" if reprt_code == "11011" else "thstrm_add_amount"
        net_income = _find_account_amount(
            payload_list,
            sj_div=_NET_INCOME_SJ_DIVS,
            account_ids=_NET_INCOME_ACCOUNT_IDS,
            amount_field=amount_field,
        )
        if net_income is not None and months_covered != 12:
            net_income = net_income * 12 / months_covered

        equity = _find_account_amount(
            payload_list, sj_div=_EQUITY_SJ_DIV, account_ids=_EQUITY_ACCOUNT_IDS
        )
        if net_income is None and equity is None:
            return None

        return CorpFinancialsRecord(
            corp_code=corp_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            net_income=net_income,
            equity=equity,
        )

    def _request_json(self, path: str, *, params: dict[str, str]) -> dict | None:
        content = self._request_bytes(path, params=params)
        body = json.loads(content)
        status = body.get("status")
        if status == _STATUS_NO_DATA:
            return None
        if status != _STATUS_OK:
            raise DartApiError(
                f"DART API 오류(status={status}): {body.get('message')}", retryable=False
            )
        return body

    def _request_json_list(self, path: str, *, params: dict[str, str]) -> list[dict] | None:
        body = self._request_json(path, params=params)
        if body is None:
            return None
        return body.get("list", [])

    def _pace(self) -> None:
        if self._min_interval_seconds <= 0 or self._last_request_at is None:
            self._last_request_at = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._min_interval_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)
        self._last_request_at = time.monotonic()

    def _request_bytes(self, path: str, *, params: dict[str, str]) -> bytes:
        url = f"{_BASE_URL}/{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._pace()
            try:
                response = self._client.get(url, params=params)
            except httpx.TimeoutException as exc:
                last_exc = exc
                self._backoff_sleep(attempt)
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                self._backoff_sleep(attempt)
                continue

            if response.status_code >= 500:
                last_exc = DartClientError(
                    f"DART 서버 오류(HTTP {response.status_code}): {path}"
                )
                self._backoff_sleep(attempt)
                continue

            if response.status_code != 200:
                raise DartApiError(
                    f"DART API HTTP 오류: {response.status_code} {path}", retryable=False
                )

            # JSON 응답이면서 요청 제한 초과(020)인 경우에만 재시도한다. 그 외
            # 콘텐츠(zip 등)는 상태코드 판별이 불가능하므로 그대로 반환한다.
            if response.headers.get("content-type", "").startswith("application/json"):
                try:
                    parsed = json.loads(response.content)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict) and parsed.get("status") == _STATUS_RATE_LIMITED:
                    last_exc = DartApiError(
                        f"DART 요청 제한 초과(020): {path}", retryable=True
                    )
                    self._backoff_sleep(attempt)
                    continue

            return response.content

        assert last_exc is not None
        raise DartClientError(
            f"DART API 호출이 {self._max_retries}회 재시도 후에도 실패했습니다: {path}"
        ) from last_exc

    def _backoff_sleep(self, attempt: int) -> None:
        if attempt < self._max_retries:
            self._sleep(2**attempt)


__all__ = [
    "CompanyOverviewRecord",
    "CorpCodeEntry",
    "CorpFinancialsRecord",
    "DartApiError",
    "DartClient",
    "DartClientError",
]
