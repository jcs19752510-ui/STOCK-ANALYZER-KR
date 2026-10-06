"""본인 전용 실시간 시세 스트림(SSE) (DEC-084). **내 PC 전용**, 기본 꺼짐, 소유자(관리자)만.

`GET /api/v1/local/stocks/{code}/stream` — 연결 직후 `snapshot`(최신 시세·호가·최근 체결·오늘 1분봉)을 보내고, 이후 `tick`·`bar`·`quote`·`book`·`status`를
바뀔 때마다 보낸다(초당 최대 10회로 합쳐서). 15초마다 `: hb` 하트비트.
접근 통제(모두 만족해야 하며 하나라도 아니면 존재를 드러내지 않도록 404):
  1) 개인 로컬 모드 4중 통제(`require_local_mode`: 스위치·허용 IP·프록시 헤더 없음·사설 Host)
  2) 로그인을 켠 환경이면 요청마다 DB에서 "유효한 세션 + 활성 + 관리자"를 확인(웹 서버가 전달한 값만 믿지 않음) — 아니면 403
앱키·접속키는 이 응답·로그에 나오지 않는다. 증권사 구독은 서버가 종목당 1개만 유지하고 화면이 닫히면 유예 뒤 해지한다.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from services.public_api.api.common import require_stock_code
from services.public_api.api.local_intraday import require_local_mode, shared_intraday_service
from services.public_api.core.config import internal_token_enforced
from services.public_api.db.auth_session import get_auth_session_factory
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.session import get_session_factory
from services.public_api.errors import ApiError
from services.public_api.intraday import config as cfg
from services.public_api.realtime.connection import GRACE_SECONDS, CapacityError, KisWsManager
from services.public_api.realtime.service import RealtimeService, make_seed_fetcher
from shared.calendar_service import get_last_trading_day

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/local", tags=["local-realtime"])

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
FLUSH_INTERVAL_SECONDS = 0.1  # 초당 최대 10회 전송
HEARTBEAT_SECONDS = 15.0
RECHECK_SECONDS = 300.0  # 스트림이 이어지는 동안 소유자 권한을 다시 확인하는 간격(로그아웃·사용 중지·권한 회수를 반영)

_service: tuple[str, RealtimeService] | None = None


def _owner_valid(uid: str, sid: str) -> bool:
    """이 세션이 지금 유효한 관리자 세션인지 DB로 확인한다(동기 — 스레드에서 실행). 연결은 바로 반납한다."""
    from services.public_api.auth.service import require_admin

    session = get_auth_session_factory()()
    try:
        return require_admin(session, uid, sid) is not None
    finally:
        session.close()  # 스트림이 몇 시간 이어져도 DB 연결을 붙잡지 않는다


def _auth_headers(request: Request) -> tuple[str, str] | None:
    uid = request.headers.get("x-auth-user", "").strip()
    sid = request.headers.get("x-auth-session", "").strip()
    return (uid, sid) if _UUID.fullmatch(uid) and _UUID.fullmatch(sid) else None


def require_owner(request: Request, settings: cfg.IntradaySettings = Depends(require_local_mode)) -> cfg.IntradaySettings:
    """로그인을 켠 환경에서는 요청한 사람이 지금 유효한 관리자 세션인지 DB로 확인한다(동기 함수 — 스레드풀에서 실행)."""
    if not internal_token_enforced():
        return settings  # 로그인을 끈 로컬: 내 PC 한 명뿐이다(개인 로컬 모드 4중 통제는 이미 통과)
    auth = _auth_headers(request)
    if auth is None or not _owner_valid(*auth):
        raise ApiError(status_code=403, code="FORBIDDEN", message="접근 권한이 없습니다.")
    return settings


def _fallback_day():
    """오늘 분봉이 비어 있을 때(장 시작 전·휴장일) 보여줄 직전 거래일. 캘린더를 못 읽으면 None."""
    session = None
    try:
        session = get_session_factory()()
        return get_last_trading_day("KRX", datetime.now(KST), SqlCalendarRepository(session))
    except Exception:
        return None
    finally:
        if session is not None:
            session.close()


def get_realtime_service(settings: cfg.IntradaySettings) -> RealtimeService:
    """프로세스당 하나. 앱키·주소가 바뀌면 새로 만든다(옛 연결은 이벤트 루프에서 정리)."""
    global _service
    fingerprint = f"{settings.app_key}|{settings.base_url}|{settings.ws_url}"
    if _service is None or _service[0] != fingerprint:
        old = _service[1] if _service else None
        fetcher = make_seed_fetcher(shared_intraday_service(settings), _fallback_day)
        grace = float(os.environ.get("KIS_REALTIME_GRACE_SECONDS", GRACE_SECONDS))  # 화면이 닫힌 뒤 구독을 유지하는 시간(시험용으로 줄일 수 있음)
        factory = functools.partial(KisWsManager, grace=grace)
        _service = (fingerprint, RealtimeService(settings, fetcher, manager_factory=factory))
        if old is not None:
            asyncio.get_running_loop().create_task(old.stop())
    return _service[1]


async def shutdown_realtime() -> None:
    global _service
    if _service is not None:
        service, _service = _service[1], None
        await service.stop()


def reset_realtime_service() -> None:
    """테스트 전용: 서비스 인스턴스를 버린다(연결 정리는 호출 쪽 책임)."""
    global _service
    _service = None


def _recheck_seconds() -> float:
    """권한 재확인 간격(초). 환경변수 `KIS_REALTIME_RECHECK_SECONDS`가 있으면 그 값(시험용), 없으면 기본 5분."""
    raw = os.environ.get("KIS_REALTIME_RECHECK_SECONDS", "").strip()
    try:
        return max(0.2, float(raw)) if raw else RECHECK_SECONDS
    except ValueError:
        return RECHECK_SECONDS


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def _event_stream(service: RealtimeService, sub, snapshot: dict[str, Any], request: Request, auth: tuple[str, str] | None) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    recheck = _recheck_seconds()
    next_check = loop.time() + recheck
    try:
        yield "retry: 3000\n\n"  # 끊기면 브라우저가 3초 뒤 자동 재연결
        yield _sse("snapshot", snapshot)
        while True:
            try:
                await asyncio.wait_for(sub.wake.wait(), timeout=min(HEARTBEAT_SECONDS, recheck))
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": hb\n\n"
            if auth is not None and loop.time() >= next_check:
                next_check = loop.time() + recheck
                try:
                    valid = await asyncio.to_thread(_owner_valid, *auth)
                except Exception:  # 회원 DB를 잠깐 못 읽으면 이번에는 유지하고 다음 점검 때 다시 확인한다
                    logger.warning("실시간 소유자 재확인 실패(일시적 오류로 보고 유지)")
                    valid = True
                if not valid:
                    yield _sse("end", {"reason": "forbidden"})  # 권한이 사라졌다: 화면은 다시 연결하지 않는다
                    return
            for event, data in sub.drain():
                yield _sse(event, data)
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
    finally:
        await service.close(sub)


@router.get("/realtime/status")
async def realtime_status(settings: cfg.IntradaySettings = Depends(require_owner)) -> dict[str, Any]:
    if not settings.configured:
        return {"data": {"configured": False}, "error": None}
    info = get_realtime_service(settings).status()
    info["configured"] = True
    return {"data": info, "error": None}


@router.get("/stocks/{code}/stream")
async def stream(code: str, request: Request, settings: cfg.IntradaySettings = Depends(require_owner)) -> StreamingResponse:
    code = require_stock_code(code)
    if not settings.configured:
        raise ApiError(
            status_code=503,
            code="LOCAL_INTRADAY_NOT_CONFIGURED",
            message="증권사 앱키가 설정되지 않았습니다. KIS_APP_KEY·KIS_APP_SECRET을 확인하세요.",
        )
    service = get_realtime_service(settings)
    try:
        sub, snapshot = await service.open(code)
    except CapacityError as exc:
        raise ApiError(status_code=429, code=exc.code, message=exc.message) from exc
    auth = _auth_headers(request) if internal_token_enforced() else None
    return StreamingResponse(
        _event_stream(service, sub, snapshot, request, auth),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
