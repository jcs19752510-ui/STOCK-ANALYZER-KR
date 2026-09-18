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
        return response


DEFAULT_REQUEST_TIMEOUT_SECONDS = 4.5


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
        try:
            return await asyncio.wait_for(call_next(request), timeout=self._timeout_seconds)
        except TimeoutError:
            logger.warning(
                "요청 처리 시간이 %s초를 초과해 타임아웃 처리했습니다: %s",
                self._timeout_seconds,
                request.url.path,
            )
            return _service_unavailable_response()
