"""공통 응답 미들웨어 (보안 헤더 + 요청 단위 타임아웃).

DEF-SEC-02(09-security-audit.md §6, Medium)·DEF-FS-01/REQ-025(High) 대응.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.public_api.schemas.envelope import Envelope, ErrorDetail, Meta

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)

_SERVICE_UNAVAILABLE_MESSAGE = "일시적인 서비스 장애입니다. 잠시 후 다시 시도해 주세요."


def _service_unavailable_response() -> JSONResponse:
    envelope = Envelope(
        meta=Meta(generated_at=datetime.now(KST)),
        data=None,
        error=ErrorDetail(code="SERVICE_UNAVAILABLE", message=_SERVICE_UNAVAILABLE_MESSAGE),
    )
    return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    """마지막 안전망(catch-all) — 09-security-audit.md TC-SEC-24/25(DEF-FS-01/
    REQ-025 확장판) 대응.

    `main.py`가 `ApiError`/`RequestValidationError`/`DBAPIError`/
    (SQLAlchemy) `TimeoutError`에 대해 명시적 핸들러를 등록해 두지만, 그
    외의 임의의 미처리 예외(예: bigint 범위를 벗어난 파라미터로 인한
    예상치 못한 드라이버 예외, 기타 버그)는 여전히 남는다. 09단계가 실측한
    문제는 이런 경우 FastAPI가 Envelope 없는 raw "Internal Server Error"
    (500)를 60~90초 뒤에야 반환한다는 것이었다.

    **구현 위치를 `@app.exception_handler(Exception)`이 아니라 이 미들웨어로
    둔 이유**: Starlette는 `Exception`(또는 상태코드 500)에 등록된 핸들러를
    일반 `exception_handlers` 딕셔너리가 아니라 가장 바깥쪽
    `ServerErrorMiddleware`의 `handler`로 특별 취급한다(즉 우리가 만든
    `SecurityHeadersMiddleware`/`RateLimitMiddleware`/`CORSMiddleware`보다도
    바깥에서, 이들을 모두 우회한 채 처리된다) — 실제로 확인한 결과 그
    경로는 응답을 보낸 뒤에도 예외를 항상 재-raise해(`starlette/middleware/
    errors.py`, "We always continue to raise the exception") `TestClient`의
    기본 동작(`raise_server_exceptions=True`)을 깨뜨리고, 보안 헤더/CORS
    미들웨어를 건너뛰는 부작용이 있었다(이 재작업 중 직접 재현해 확인함,
    unit-01-note.md §6-1 참조). 이 미들웨어를 다른 커스텀 미들웨어보다
    안쪽(라우터에 가장 가까운 위치)에 등록하면, 예외를 정상적인 `Response`
    반환으로 변환해 바깥쪽 미들웨어들이 평소와 동일하게(보안 헤더 추가,
    CORS 헤더 추가) 처리할 수 있다.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("처리되지 않은 예외: %s", request.url.path)
            return _service_unavailable_response()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """03-system-design.md §6-3(Must): CSP / X-Content-Type-Options / HSTS.

    이 서비스는 순수 JSON API(HTML을 직접 렌더링하지 않음)이므로
    `default-src 'none'`으로 기본 차단하는 것이 OWASP 권고와 부합한다.
    HSTS는 HTTPS로 서빙될 때만 브라우저가 실제로 존중하므로, 호스팅 벤더가
    아직 미확정(§2-1)인 현재도 미리 선언해 두는 것 자체는 무해하다.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith(LOCAL_INTRADAY_PREFIX):
            # 개인 로컬 모드 증권사 시세(DEC-052)는 어디에도 캐시되지 않게 한다.
            response.headers["Cache-Control"] = "no-store"
        return response


DEFAULT_REQUEST_TIMEOUT_SECONDS = 4.5
# 개인 로컬 모드 분봉은 증권사를 여러 쪽(최대 14회) 호출해 모으므로
# 일반 한도(4.5초)로는 부족하다. 허용 IP에서만 응답하는 경로에 한해
# 넉넉한 한도를 준다(다른 경로는 그대로 4.5초).
LOCAL_INTRADAY_PREFIX = "/api/v1/local/"
LOCAL_INTRADAY_TIMEOUT_SECONDS = 30.0


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """요청 단위 타임아웃 (09-security-audit.md §4-6, DEF-FS-01/REQ-025 권고 사항).

    모든 라우터 함수가 동기 `def`로 선언되어 스레드풀(anyio worker thread,
    기본 상한 40)에서 실행된다(§4-6이 확인한 사실). `db/session.py`의
    `connect_timeout`/`statement_timeout`이 DB 장애 시 스레드 점유 시간을
    수 초로 이미 크게 줄이지만, 이 미들웨어는 그와 무관하게 발생할 수 있는
    다른 지연(예상치 못한 경합 등)에 대한 2차 안전망으로, 클라이언트가
    `03-system-design.md` §5-4가 요구하는 "5초 이내" 응답을 항상 받도록
    보장한다.

    **알려진 구조적 한계**: `asyncio.wait_for`는 이 async 래퍼 자체를
    취소할 뿐, 이미 스레드풀에서 동기적으로 블로킹 중인 라우터 함수(예:
    소켓 I/O 대기)를 강제로 중단시키지 못한다(파이썬 스레드는 외부에서
    강제 종료할 수 없음). 즉 클라이언트는 이 타임아웃 덕분에 빠르게 응답을
    받지만, 그 스레드풀 슬롯 자체는 실제 DB 호출이 자연 종료(주로
    `connect_timeout`/`statement_timeout`에 의해 수 초 내)될 때까지 계속
    점유된다 — 스레드 점유 시간을 근본적으로 줄이는 주된 방어선은 여전히
    `db/session.py`의 타임아웃 설정이며, 이 미들웨어는 "클라이언트 체감
    응답시간"을 보장하는 보조 안전망이다.
    """

    def __init__(self, app, *, timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS) -> None:
        super().__init__(app)
        self._timeout_seconds = timeout_seconds

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        timeout = (
            max(self._timeout_seconds, LOCAL_INTRADAY_TIMEOUT_SECONDS)
            if request.url.path.startswith(LOCAL_INTRADAY_PREFIX)
            else self._timeout_seconds
        )
        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "요청 처리 시간이 %s초를 초과해 타임아웃 처리했습니다: %s",
                timeout,
                request.url.path,
            )
            return _service_unavailable_response()


class PeerDiagnosticsMiddleware(BaseHTTPMiddleware):
    """임시 진단(DEC-063): 앞단 프록시가 어떤 주소로 접속해 오는지 로그로 확인한다.

    관리형 호스팅(Render 등)은 프록시 IP 대역이 문서로 확인되지 않을 수 있다. 이 값을 모르고
    `PUBLIC_API_TRUSTED_PROXY_IPS`를 비우면 모든 방문자가 한도(분당 60회)를 공유하고, `*`로 두면
    한도를 우회할 수 있다. 그래서 **처음 몇 건만** 접속 주소(TCP peer)와 X-Forwarded-For 헤더를 남겨
    운영자가 실제 대역을 확인하게 한다. 방문자 IP가 로그에 남으므로 확인이 끝나면 반드시 끈다.
    기본은 꺼짐이며 `PUBLIC_API_LOG_PEER_IPS=1`일 때만 등록된다. 최대 MAX_LOGGED 건만 기록한다.
    """

    MAX_LOGGED = 20
    _logged = 0

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cls = type(self)
        if cls._logged < self.MAX_LOGGED and request.url.path != "/api/v1/live":
            cls._logged += 1
            peer = request.client.host if request.client else "unknown"
            logger.warning(
                "PEER-DIAG %d/%d peer=%s x-forwarded-for=%r path=%s",
                cls._logged,
                self.MAX_LOGGED,
                peer,
                request.headers.get("x-forwarded-for"),
                request.url.path,
            )
        return await call_next(request)
