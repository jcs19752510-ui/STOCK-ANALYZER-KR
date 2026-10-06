"""한국투자증권(KIS) Open API 시세 조회 클라이언트(읽기 전용, 실전 도메인) — DEC-052.

- 인증: `POST /oauth2/tokenP`(client_credentials). 토큰은 24시간 유효하고 재발급이 6시간에 1회로 제한되므로 로컬 파일
  (`.local/kis_token.json`, 권한 0600)에 만료 시각과 함께 캐시해 재시작해도 새로 받지 않는다.
- 호출 제한: 계정 단위 초당 건수 제한을 넘지 않도록 요청 사이 최소 간격을 둔다(기본 0.12초 ≈ 초당 8건). 한도 초과 응답이면
  1회 대기 후 재시도한다.
- 보안: 앱키·시크릿·토큰은 요청 헤더에만 쓰고 예외 메시지·로그에 싣지 않는다(`KisError.message`는 안전한 문구만).
- 주문·계좌 API는 호출하지 않는다(시세 조회 엔드포인트 6개만 상수로 둔다).
"""

# ruff: noqa: E501  (한글 설명 주석이 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from services.public_api.intraday.config import IntradaySettings

KST = timezone(timedelta(hours=9))

# 엔드포인트와 tr_id(공식 샘플 저장소 koreainvestment/open-trading-api 기준, 실전·모의 공통 값).
PATH_MINUTE_TODAY = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
TR_MINUTE_TODAY = "FHKST03010200"
PATH_MINUTE_PAST = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
TR_MINUTE_PAST = "FHKST03010230"
PATH_ORDERBOOK = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
TR_ORDERBOOK = "FHKST01010200"
PATH_CCNL = "/uapi/domestic-stock/v1/quotations/inquire-ccnl"
TR_CCNL = "FHKST01010300"
PATH_CONCLUSION = "/uapi/domestic-stock/v1/quotations/inquire-time-itemconclusion"
TR_CONCLUSION = "FHPST01060000"

PATH_INVESTOR = "/uapi/domestic-stock/v1/quotations/inquire-investor"
TR_INVESTOR = "FHKST01010900"

# 관심종목 멀티종목 시세(한 번에 최대 30종목) — 준실시간 전 종목 스냅샷용
PATH_MULTI_PRICE = "/uapi/domestic-stock/v1/quotations/intstock-multprice"
TR_MULTI_PRICE = "FHKST11300006"
MULTI_PRICE_MAX_CODES = 30
# HTS 조건검색(서버 저장 조건) 목록·결과 — 공식 샘플 koreainvestment/open-trading-api `psearch_title.py`·`psearch_result.py` 기준.
# HTS(eFriend Plus) [0110] 조건검색에서 조건을 만들고 "서버저장"한 것만 보인다. 결과는 조건당 최대 100건이며 0건이면 증권사가 오류를 돌려준다.
PATH_PSEARCH_TITLE = "/uapi/domestic-stock/v1/quotations/psearch-title"
TR_PSEARCH_TITLE = "HHKST03900300"
PATH_PSEARCH_RESULT = "/uapi/domestic-stock/v1/quotations/psearch-result"
TR_PSEARCH_RESULT = "HHKST03900400"
LOW_PRIORITY_YIELD_SECONDS = 0.02  # 낮은 우선순위 호출이 양보하며 기다리는 단위
LOW_PRIORITY_MAX_YIELDS = 100  # 최대 2초까지만 양보한다

_TOKEN_PATH = "/oauth2/tokenP"
_TOKEN_SAFETY_SECONDS = 600
_MARKET_DIV = "J"  # KRX

_EXPIRED_TOKEN_CODES = {"EGW00121", "EGW00123"}
_RATE_LIMIT_CODES = {"EGW00201"}


class KisError(Exception):
    """KIS 호출 실패. `message`는 사용자에게 보여도 안전한 문구만 담는다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_provider_message(text: object) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:120]


def _fingerprint(app_key: str) -> str:
    return hashlib.sha256(app_key.encode("utf-8")).hexdigest()[:12]


class KisClient:
    def __init__(
        self,
        settings: IntradaySettings,
        http: httpx.Client | None = None,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = 0.12,
    ) -> None:
        if not settings.configured:
            raise KisError("NOT_CONFIGURED", "증권사 앱키가 설정되지 않았습니다.")
        self._s = settings
        self._http = http or httpx.Client(timeout=10.0)
        self._clock = clock
        self._sleep = sleep
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._prio_lock = threading.Lock()  # `_lock`은 호출 간격 대기 중에도 잡혀 있어, 우선순위 카운터는 별도 잠금으로 보호한다
        self._priority_pending = 0  # 지금 진행 중인(대기 포함) 일반(상세 화면) 호출 수
        self._last_call = 0.0
        self._token: str | None = None
        self._token_expires_at = 0.0

    # ── 토큰 ─────────────────────────────────────────────────────────────────────────────
    def _load_cached_token(self) -> bool:
        path = self._s.token_cache_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if (
            data.get("fp") == _fingerprint(self._s.app_key or "")
            and isinstance(data.get("token"), str)
            and float(data.get("expires_at", 0)) > self._clock() + _TOKEN_SAFETY_SECONDS
        ):
            self._token = data["token"]
            self._token_expires_at = float(data["expires_at"])
            return True
        return False

    def _save_token(self) -> None:
        path = self._s.token_cache_path
        payload = json.dumps(
            {
                "fp": _fingerprint(self._s.app_key or ""),
                "token": self._token,
                "expires_at": self._token_expires_at,
            }
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except OSError:
            pass  # 캐시를 못 써도 동작에는 영향이 없다(다음 기동 때 새로 발급)

    def _issue_token(self) -> None:
        try:
            resp = self._http.post(
                self._s.base_url + _TOKEN_PATH,
                json={
                    "grant_type": "client_credentials",
                    "appkey": self._s.app_key,
                    "appsecret": self._s.app_secret,
                },
                headers={"content-type": "application/json; charset=utf-8"},
            )
        except httpx.HTTPError as exc:
            raise KisError("UPSTREAM_UNAVAILABLE", "증권사 서버에 연결하지 못했습니다.") from exc
        try:
            body = resp.json()
        except ValueError as exc:
            raise KisError("UPSTREAM_BAD_RESPONSE", "증권사 응답을 해석할 수 없습니다.") from exc
        token = body.get("access_token") if isinstance(body, dict) else None
        if resp.status_code != 200 or not isinstance(token, str) or not token:
            raise KisError("AUTH_FAILED", "증권사 인증에 실패했습니다(앱키·시크릿을 확인하세요).")
        expires_in = body.get("expires_in")
        ttl = float(expires_in) if isinstance(expires_in, (int, float)) else 86400.0
        self._token = token
        self._token_expires_at = self._clock() + ttl
        self._save_token()

    def _ensure_token(self, *, force: bool = False) -> str:
        with self._lock:
            if force:
                self._token = None
            now = self._clock()
            if self._token and self._token_expires_at > now + _TOKEN_SAFETY_SECONDS:
                return self._token
            if not force and self._load_cached_token() and self._token:
                return self._token
            self._issue_token()
            assert self._token is not None
            return self._token

    # ── 요청 ─────────────────────────────────────────────────────────────────────────────
    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_call + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_call = self._clock()

    def _yield_to_priority(self) -> None:
        """낮은 우선순위 호출(전 종목 순환)이 상세 화면 호출에 양보한다: 일반 호출이 진행 중이면 잠시 기다린다.

        최대 `LOW_PRIORITY_MAX_YIELDS × LOW_PRIORITY_YIELD_SECONDS`(기본 2초)만 기다리고 그 뒤에는 그냥 진행해 굶지 않는다.
        호출 간격(`_throttle`)은 두 종류가 같은 인스턴스에서 공유하므로 합산 호출률은 양보와 무관하게 `1/min_interval` 이하다.
        """
        for _ in range(LOW_PRIORITY_MAX_YIELDS):
            with self._prio_lock:
                if self._priority_pending <= 0:
                    return
            self._sleep(LOW_PRIORITY_YIELD_SECONDS)

    def _get(self, path: str, tr_id: str, params: dict[str, str], *, low_priority: bool = False) -> dict[str, Any]:
        if low_priority:
            self._yield_to_priority()
            return self._request(path, tr_id, params)
        with self._prio_lock:
            self._priority_pending += 1
        try:
            return self._request(path, tr_id, params)
        finally:
            with self._prio_lock:
                self._priority_pending -= 1

    def _request(self, path: str, tr_id: str, params: dict[str, str]) -> dict[str, Any]:
        for attempt in (1, 2):
            token = self._ensure_token(force=attempt == 2 and self._token is None)
            self._throttle()
            try:
                resp = self._http.get(
                    self._s.base_url + path,
                    params=params,
                    headers={
                        "content-type": "application/json; charset=utf-8",
                        "authorization": f"Bearer {token}",
                        "appkey": self._s.app_key or "",
                        "appsecret": self._s.app_secret or "",
                        "tr_id": tr_id,
                        "custtype": "P",
                    },
                )
            except httpx.HTTPError as exc:
                raise KisError("UPSTREAM_UNAVAILABLE", "증권사 서버에 연결하지 못했습니다.") from exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise KisError("UPSTREAM_BAD_RESPONSE", "증권사 응답을 해석할 수 없습니다.") from exc
            if not isinstance(body, dict):
                raise KisError("UPSTREAM_BAD_RESPONSE", "증권사 응답 형식이 올바르지 않습니다.")
            msg_cd = str(body.get("msg_cd", ""))
            if attempt == 1 and (resp.status_code in (401, 403) or msg_cd in _EXPIRED_TOKEN_CODES):
                with self._lock:
                    self._token = None  # 만료·무효 토큰: 한 번만 새로 받아 재시도
                continue
            if resp.status_code == 429 or msg_cd in _RATE_LIMIT_CODES:
                if attempt == 1:
                    self._sleep(1.0)
                    continue
                raise KisError("RATE_LIMITED", "증권사 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
            if resp.status_code != 200 or str(body.get("rt_cd", "0")) != "0":
                detail = _safe_provider_message(body.get("msg1"))
                raise KisError("UPSTREAM_ERROR", f"증권사가 요청을 거절했습니다. {detail}".strip())
            return body
        raise KisError("UPSTREAM_ERROR", "증권사 요청에 실패했습니다.")

    # ── 시세 조회(읽기 전용) ───────────────────────────────────────────────────────────────
    def minute_today(self, code: str, hhmmss: str) -> dict[str, Any]:
        """당일 분봉. 입력 시각 이전 최대 30건(최근 → 과거 순)."""
        return self._get(
            PATH_MINUTE_TODAY,
            TR_MINUTE_TODAY,
            {
                "FID_COND_MRKT_DIV_CODE": _MARKET_DIV,
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": hhmmss,
                "FID_PW_DATA_INCU_YN": "N",
                "FID_ETC_CLS_CODE": "",
            },
        )

    def minute_past(self, code: str, yyyymmdd: str, hhmmss: str) -> dict[str, Any]:
        """과거 일자 분봉. 입력 일시 이전 최대 120건(최근 → 과거 순), 최대 1년 보관."""
        return self._get(
            PATH_MINUTE_PAST,
            TR_MINUTE_PAST,
            {
                "FID_COND_MRKT_DIV_CODE": _MARKET_DIV,
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": hhmmss,
                "FID_INPUT_DATE_1": yyyymmdd,
                "FID_PW_DATA_INCU_YN": "N",
                "FID_FAKE_TICK_INCU_YN": "",
            },
        )

    def orderbook(self, code: str) -> dict[str, Any]:
        return self._get(
            PATH_ORDERBOOK,
            TR_ORDERBOOK,
            {"FID_COND_MRKT_DIV_CODE": _MARKET_DIV, "FID_INPUT_ISCD": code},
        )

    def recent_ccnl(self, code: str) -> dict[str, Any]:
        """현재가 체결(최근 체결 목록)."""
        return self._get(
            PATH_CCNL,
            TR_CCNL,
            {"FID_COND_MRKT_DIV_CODE": _MARKET_DIV, "FID_INPUT_ISCD": code},
        )

    def investor(self, code: str) -> dict[str, Any]:
        """주식현재가 투자자(최근 거래일부터 일별 투자자별 순매수, 최근 → 과거 순)."""
        return self._get(
            PATH_INVESTOR,
            TR_INVESTOR,
            {"FID_COND_MRKT_DIV_CODE": _MARKET_DIV, "FID_INPUT_ISCD": code},
        )

    def conclusion_before(self, code: str, hhmmss: str) -> dict[str, Any]:
        """당일 시간대별 체결(입력 시각 이전)."""
        return self._get(
            PATH_CONCLUSION,
            TR_CONCLUSION,
            {
                "FID_COND_MRKT_DIV_CODE": _MARKET_DIV,
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": hhmmss,
            },
        )

    def multi_price(self, codes: list[str]) -> dict[str, Any]:
        """관심종목 멀티종목 시세(최대 30종목). 응답 본문 전체를 돌려준다(행은 `output`, 필드는 normalize.MULTI_PRICE_FIELDS).

        요청 파라미터는 `FID_COND_MRKT_DIV_CODE_n`/`FID_INPUT_ISCD_n`(n=1..종목 수). 같은 토큰·호출 간격·오류 처리(`_get`)를 쓴다.
        """
        if not codes:
            raise ValueError("종목코드가 비어 있습니다.")
        if len(codes) > MULTI_PRICE_MAX_CODES:
            raise ValueError(f"한 번에 최대 {MULTI_PRICE_MAX_CODES}종목까지 조회할 수 있습니다.")
        params: dict[str, str] = {}
        for i, code in enumerate(codes, start=1):
            params[f"FID_COND_MRKT_DIV_CODE_{i}"] = _MARKET_DIV
            params[f"FID_INPUT_ISCD_{i}"] = code
        return self._get(PATH_MULTI_PRICE, TR_MULTI_PRICE, params, low_priority=True)  # 상세 화면 호출에 양보

    def psearch_titles(self, user_id: str) -> dict[str, Any]:
        """HTS에 서버저장한 내 조건검색 목록(`output2`: seq·grp_nm·condition_nm)."""
        if not user_id:
            raise ValueError("HTS ID가 비어 있습니다.")
        return self._get(PATH_PSEARCH_TITLE, TR_PSEARCH_TITLE, {"user_id": user_id})

    def psearch_result(self, user_id: str, seq: str) -> dict[str, Any]:
        """조건 하나의 현재 결과 종목(`output2`, 최대 100건). `seq`는 `psearch_titles` 결과의 조건 키값."""
        if not user_id or seq == "":
            raise ValueError("HTS ID와 조건 키값이 필요합니다.")
        return self._get(PATH_PSEARCH_RESULT, TR_PSEARCH_RESULT, {"user_id": user_id, "seq": str(seq)})


def kst_now(clock: Callable[[], float] = time.time) -> datetime:
    return datetime.fromtimestamp(clock(), tz=KST)
