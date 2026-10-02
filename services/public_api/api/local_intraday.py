"""개인 로컬 모드 장중 시세 API (DEC-052): 분봉·체결(틱)·호가·투자자별 순매수. **내 PC 전용**, 기본 꺼짐.

접근 통제(모두 만족해야 한다, 하나라도 아니면 존재를 드러내지 않도록 404 FEATURE_DISABLED):
  1) `LOCAL_INTRADAY_ENABLED=true`
  2) 요청 클라이언트 주소가 허용 목록(`LOCAL_INTRADAY_ALLOWED_IPS`, 기본 loopback)에 있음
  3) 리버스 프록시·터널이 붙이는 헤더(`X-Forwarded-For`, `CF-Connecting-IP` 등)가 없음
  4) `Host` 헤더가 localhost 또는 사설/루프백 IP (공개 도메인으로 들어온 요청은 거부)
설정이 켜져 있어도 앱키가 없으면 503 LOCAL_INTRADAY_NOT_CONFIGURED. 응답은 `Cache-Control: no-store`.
"""

# ruff: noqa: E501  (한글 설명 주석이 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response

from services.public_api.api.common import require_stock_code
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.intraday import config as cfg
from services.public_api.intraday.kis_client import KisClient, KisError
from services.public_api.intraday.service import (
    DEFAULT_TICK_LIMIT,
    MAX_TICK_LIMIT,
    VALID_INTERVALS,
    IntradayService,
)
from services.public_api.schemas.envelope import Envelope, Meta
from services.public_api.schemas.intraday import (
    InvestorData,
    LocalStatus,
    MinutesData,
    OrderBookData,
    TicksData,
)
from shared.calendar_service import get_last_trading_day

KST = ZoneInfo("Asia/Seoul")
router = APIRouter(prefix="/local", tags=["local-intraday"])

_service_lock = threading.Lock()
_service: tuple[str, IntradayService] | None = None


def _disabled() -> ApiError:
    return ApiError(status_code=404, code="FEATURE_DISABLED", message="이 기능은 현재 제공되지 않습니다.")


def require_local_mode(request: Request, response: Response) -> cfg.IntradaySettings:
    try:
        settings = cfg.get_settings()
    except cfg.IntradayConfigError as exc:
        raise ApiError(status_code=503, code="LOCAL_INTRADAY_MISCONFIGURED", message=str(exc)) from exc
    host = request.client.host if request.client is not None else None
    proxied = any(h in request.headers for h in cfg.PROXY_HEADERS)
    if (
        not settings.enabled
        or proxied
        or not cfg.client_allowed(host, settings)
        or not cfg.host_header_is_private(request.headers.get("host"))
    ):
        raise _disabled()
    response.headers["Cache-Control"] = "no-store"
    return settings


def get_intraday_service(
    settings: cfg.IntradaySettings = Depends(require_local_mode),
) -> IntradayService:
    """프로세스당 하나(토큰·호출 간격·캐시를 공유). 앱키가 바뀌면 새로 만든다."""
    global _service
    if not settings.configured:
        raise ApiError(
            status_code=503,
            code="LOCAL_INTRADAY_NOT_CONFIGURED",
            message="증권사 앱키가 설정되지 않았습니다. KIS_APP_KEY·KIS_APP_SECRET을 확인하세요.",
        )
    fingerprint = f"{settings.app_key}|{settings.base_url}"
    with _service_lock:
        if _service is None or _service[0] != fingerprint:
            _service = (fingerprint, IntradayService(KisClient(settings)))
        return _service[1]


def reset_intraday_service() -> None:
    """테스트 전용: 캐시된 서비스 인스턴스를 버린다."""
    global _service
    with _service_lock:
        _service = None


def _error(exc: KisError) -> ApiError:
    status = {
        "INVALID_INTERVAL": 400,
        "AUTH_FAILED": 502,
        "RATE_LIMITED": 429,
        "NOT_CONFIGURED": 503,
    }.get(exc.code, 502)
    return ApiError(status_code=status, code=f"INTRADAY_{exc.code}", message=exc.message)


def _envelope(data):
    return Envelope(meta=Meta(generated_at=datetime.now(KST)), data=data)


@router.get("/status", response_model=Envelope[LocalStatus])
def local_status(settings: cfg.IntradaySettings = Depends(require_local_mode)) -> Envelope[LocalStatus]:
    return _envelope(LocalStatus(enabled=True, configured=settings.configured))


@router.get("/stocks/{code}/minutes", response_model=Envelope[MinutesData])
def get_minutes(
    code: str,
    interval: int = Query(1, description=f"분봉 간격({', '.join(map(str, VALID_INTERVALS))})"),
    day: date | None = Query(None, alias="date", description="조회 일자(생략 시 오늘, 비어 있으면 직전 거래일)"),
    service: IntradayService = Depends(get_intraday_service),
    db=Depends(get_db),
) -> Envelope[MinutesData]:
    code = require_stock_code(code)
    if interval not in VALID_INTERVALS:
        raise ApiError(status_code=400, code="INVALID_PARAMETER", message="지원하지 않는 분봉 간격입니다.")
    fallback = None
    if day is None:
        try:
            fallback = get_last_trading_day("KRX", datetime.now(KST), SqlCalendarRepository(db))
        except Exception:  # 캘린더를 못 읽어도(미적재 등) 오늘 분봉은 조회한다
            fallback = None
    try:
        return _envelope(service.minutes(code, interval, day=day, fallback_day=fallback))
    except KisError as exc:
        raise _error(exc) from exc


@router.get("/stocks/{code}/ticks", response_model=Envelope[TicksData])
def get_ticks(
    code: str,
    limit: int = Query(DEFAULT_TICK_LIMIT, ge=1, le=MAX_TICK_LIMIT, description="최근 체결 건수"),
    service: IntradayService = Depends(get_intraday_service),
) -> Envelope[TicksData]:
    code = require_stock_code(code)
    try:
        return _envelope(service.ticks(code, limit))
    except KisError as exc:
        raise _error(exc) from exc


@router.get("/stocks/{code}/orderbook", response_model=Envelope[OrderBookData])
def get_orderbook(
    code: str,
    service: IntradayService = Depends(get_intraday_service),
) -> Envelope[OrderBookData]:
    code = require_stock_code(code)
    try:
        return _envelope(service.orderbook(code))
    except KisError as exc:
        raise _error(exc) from exc


@router.get("/stocks/{code}/investor", response_model=Envelope[InvestorData])
def get_investor(
    code: str,
    service: IntradayService = Depends(get_intraday_service),
) -> Envelope[InvestorData]:
    code = require_stock_code(code)
    try:
        return _envelope(service.investor(code))
    except KisError as exc:
        raise _error(exc) from exc
