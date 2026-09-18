"""IP 기준 rate limiting (03-system-design.md §6-3, Must).

DEF-SEC-01(09-security-audit.md §6, High) 대응. 목적은 인증이 아니라
"스크레이핑/대량 재배포 방지"(§4-3 데이터 가공 원칙, REQ-022 리스크)다.

**단일 인스턴스 배포 전제**: 03-system-design.md §5-2("초기 규모에서는
단일 인스턴스로 충분")를 근거로, 프로세스 메모리 내 고정 윈도(fixed window)
카운터로 구현한다. 멀티 인스턴스로 수평 확장하면 인스턴스마다 카운터가
독립적으로 리셋되어 실질 허용치가 인스턴스 수배로 커지는 한계가 있다 —
이는 알려진 제약으로 남겨두고(단일 인스턴스 전제가 깨지는 시점, 즉 실제
트래픽 실측 후 확장이 필요해지는 시점에 Redis 등 공유 스토어 기반으로
재구현해야 한다, §5-2와 동일 원칙: 과설계 방지), 이번 MVP 범위에서는
새로운 인프라(Redis 등)를 도입하지 않는다.

**신뢰 경계(DEF-SEC-03, 09-security-audit.md §11-3/§11-5) — 반드시 읽을 것**:
아래 `dispatch()`는 `request.client.host`만 참조하고 `X-Forwarded-For` 등
클라이언트가 보낸 헤더는 전혀 읽지 않는다. 그러나 `request.client.host`
자체가 이미 신뢰 불가능한 값일 수 있다 — uvicorn의 `ProxyHeadersMiddleware`
(기본값 `proxy_headers=True`)가 이 애플리케이션 코드에 도달하기 *전에*
ASGI scope의 `client`를 `X-Forwarded-For` 헤더값으로 덮어쓰기 때문이다
(loopback 연결을 프록시로 암묵 신뢰하는 uvicorn 기본 설정 때문에 발생 —
09단계가 실제 uvicorn 프로세스로 재현·확정함). 즉 이 모듈만 코드 리뷰해서는
안전해 보이지만, 실제 안전성은 **uvicorn이 어떤 옵션으로 기동됐는지**에
전적으로 달려 있다. 이 서비스는 반드시 `scripts/run_public_api.py`로
기동해야 한다 — 이 스크립트가 기본값으로 프록시 헤더 신뢰 자체를 끈다
(`proxy_headers=False`, fail closed). `uvicorn services.public_api.main:app`을
직접 실행하면 이 방어가 적용되지 않는다.
"""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.public_api.schemas.envelope import Envelope, ErrorDetail, Meta

KST = ZoneInfo("Asia/Seoul")

# 03-system-design.md §6-3 예시 수치("분당 60회")를 그대로 채택. 환경변수로
# 재정의 가능하게 둔 이유는 오직 테스트 편의를 위함이다(예:
# tests/integration/test_rate_limit_proxy_trust.py가 실제 uvicorn 프로세스로
# 수십 회의 실제 TCP 요청을 보내지 않고도 한도 초과 상황을 빠르게 재현할 수
# 있게 한다) — 미설정 시 기본값은 §6-3이 명시한 수치 그대로다.
DEFAULT_LIMIT = int(os.environ.get("PUBLIC_API_RATE_LIMIT_PER_MINUTE", "60"))
DEFAULT_WINDOW_SECONDS = 60.0
# 이 상한을 넘으면 만료된 항목을 정리한다(고유 방문 IP가 매우 많아질 때
# 메모리가 무한정 늘어나는 것을 막는 방어적 조치, 정상 트래픽에서는
# 도달하지 않는 값).
_MAX_TRACKED_CLIENTS = 10_000

# 모듈 레벨 상태로 둔 이유: 테스트가 `reset_rate_limit_state()`로 카운터를
# 초기화할 수 있어야 한다(미들웨어 인스턴스는 Starlette가 내부적으로 생성/
# 보관해 테스트 코드에서 직접 핸들을 얻기 어렵다).
_counters: dict[str, tuple[float, int]] = {}


def reset_rate_limit_state() -> None:
    """테스트 전용 헬퍼: IP별 카운터를 초기화한다(unit-01-note.md §6-1 참조)."""
    _counters.clear()


def _evict_expired(now: float, window_seconds: float) -> None:
    expired = [
        ip
        for ip, (window_start, _) in _counters.items()
        if now - window_start >= window_seconds
    ]
    for ip in expired:
        del _counters[ip]


def _rate_limited_response() -> JSONResponse:
    envelope = Envelope(
        meta=Meta(generated_at=datetime.now(KST)),
        data=None,
        error=ErrorDetail(
            code="RATE_LIMITED",
            message="요청 빈도 제한을 초과했습니다. 잠시 후 다시 시도해 주세요.",
        ),
    )
    return JSONResponse(status_code=429, content=envelope.model_dump(mode="json"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        limit: int = DEFAULT_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        super().__init__(app)
        self._limit = limit
        self._window_seconds = window_seconds

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        client_ip = request.client.host if request.client is not None else "unknown"
        now = time.monotonic()

        if len(_counters) > _MAX_TRACKED_CLIENTS:
            _evict_expired(now, self._window_seconds)

        window_start, count = _counters.get(client_ip, (now, 0))
        if now - window_start >= self._window_seconds:
            window_start, count = now, 0
        count += 1
        _counters[client_ip] = (window_start, count)

        if count > self._limit:
            return _rate_limited_response()

        return await call_next(request)
