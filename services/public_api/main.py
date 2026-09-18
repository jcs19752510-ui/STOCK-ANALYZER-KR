from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from services.public_api.api import calendar, health, market_summary, metrics, screen, stocks
from services.public_api.core.config import get_cors_allowed_origins
from services.public_api.errors import ApiError
from services.public_api.middleware import (
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
    UnhandledExceptionMiddleware,
)
from services.public_api.rate_limit import RateLimitMiddleware
from services.public_api.schemas.envelope import Envelope, ErrorDetail, Meta

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)

app = FastAPI(title="Stock Screener Public API", version="0.1.0")

# 미들웨어 등록 순서(Starlette는 "나중에 add_middleware된 것이 가장 바깥쪽"
# 이라 요청을 가장 먼저 받고 응답을 가장 나중에 처리한다 — 직접
# TestClient로 실행해 실측 확인함, unit-01-note.md §0-e 참조):
#   안쪽(라우터에 가까움) → 바깥쪽(클라이언트에 가까움)
#   UnhandledExceptionMiddleware → RequestTimeoutMiddleware → RateLimitMiddleware
#   → SecurityHeadersMiddleware → CORSMiddleware
# - UnhandledExceptionMiddleware가 가장 안쪽인 이유: 이 미들웨어는 라우터가
#   던진 임의의 예외를 정상적인 Response로 "변환"하는 역할이라, 그보다
#   바깥의 모든 미들웨어(보안 헤더, rate limit, CORS)가 그 결과를 평소와
#   동일하게 마저 처리할 수 있어야 한다(middleware.py의
#   UnhandledExceptionMiddleware 문서 참조 — `@app.exception_handler
#   (Exception)`을 쓰지 않은 이유도 거기 기록돼 있다).
# - **SecurityHeadersMiddleware는 RequestTimeoutMiddleware/RateLimitMiddleware
#   보다 바깥쪽(더 나중에 add_middleware)에 둬야 한다(DEF-005, 06단계
#   unit-01-test.md v5 §4-5 TC-090/091이 재현).** 이 두 미들웨어는
#   `call_next()`를 호출하지 않고 자체적으로 응답을 반환(short-circuit)하는
#   경로(429 rate-limited, 요청 타임아웃 503)를 갖는다 — SecurityHeaders가
#   그보다 안쪽에 있으면 그 short-circuit 응답에는 SecurityHeaders.dispatch()
#   자체가 아예 실행되지 않아 보안 헤더가 누락된다. SecurityHeaders를
#   바깥쪽에 두면, RateLimit/RequestTimeout가 무엇을 반환하든(정상 호출
#   결과든 short-circuit이든) 그 응답이 SecurityHeaders.dispatch()의
#   call_next() 반환값으로 항상 돌아와 헤더가 붙는다(각 short-circuit
#   생성 지점마다 헤더 추가 코드를 중복시키는 대신, 미들웨어 순서 하나로
#   해결해 DRY 유지).
# - CORS를 가장 바깥에 두는 이유: rate limit(429)·타임아웃(503) 등 어떤
#   내부 계층이 응답을 만들어도 CORSMiddleware가 마지막에 감싸며 Origin
#   헤더를 일관되게 붙여야 브라우저가 에러 응답도 정상적으로 읽을 수 있다.
#   또한 CORSMiddleware는 preflight(OPTIONS) 요청을 라우터까지 보내지 않고
#   자체 처리하므로, preflight가 rate limit 카운터를 불필요하게 소모하지
#   않는다. 이번 재배치로도 CORS는 여전히 최후단(가장 바깥)에 남아, 이
#   전제는 그대로 유지된다.
app.add_middleware(UnhandledExceptionMiddleware)
app.add_middleware(RequestTimeoutMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# 03-system-design.md §6-3: CORS는 자사 프론트엔드 오리진으로만 제한. 이 API는
# 인증/쿠키가 없으므로(§6-1 REQ-016 Out-of-Scope) allow_credentials=False, 모든
# 엔드포인트가 읽기 전용 GET만 제공하므로(§1-2) allow_methods도 GET만 허용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(calendar.router, prefix="/api/v1")
app.include_router(stocks.router, prefix="/api/v1")
app.include_router(metrics.router, prefix="/api/v1")
app.include_router(screen.router, prefix="/api/v1")
app.include_router(market_summary.router, prefix="/api/v1")


def _error_envelope(status_code: int, code: str, message: str) -> JSONResponse:
    envelope = Envelope(
        meta=Meta(generated_at=datetime.now(KST)),
        data=None,
        error=ErrorDetail(code=code, message=message),
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return _error_envelope(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_envelope(400, "INVALID_PARAMETER", str(exc.errors()))


_SERVICE_UNAVAILABLE_MESSAGE = "일시적인 서비스 장애입니다. 잠시 후 다시 시도해 주세요."


# 09-security-audit.md TC-SEC-24/25(DEF-FS-01/REQ-025 확장판): main.py에
# ApiError/RequestValidationError 외 어떤 미처리 예외 핸들러도 없어, DB
# 연결/쿼리 실패는 물론 그 외 모든 미처리 예외가 Envelope 없는 raw 500(또는
# 60~90초 지연)으로 응답됐다. 아래 두 핸들러로 그 공백을 03-system-design.md
# §5-4가 요구하는 503 SERVICE_UNAVAILABLE Envelope으로 통일한다.
@app.exception_handler(DBAPIError)
async def handle_db_error(request: Request, exc: DBAPIError) -> JSONResponse:
    # OperationalError는 DBAPIError의 하위클래스라 이 핸들러 하나로 함께
    # 커버된다(TC-SEC-25). connect_timeout/statement_timeout(db/session.py)이
    # 설정돼 있어 이 예외는 이제 수 초 내에 발생한다.
    logger.exception("DB 연결/쿼리 오류")
    return _error_envelope(503, "SERVICE_UNAVAILABLE", _SERVICE_UNAVAILABLE_MESSAGE)


@app.exception_handler(SATimeoutError)
async def handle_db_pool_timeout(request: Request, exc: SATimeoutError) -> JSONResponse:
    # DBAPIError와 별도 클래스 계층(SQLAlchemyError 직계)이라 별도 등록이
    # 필요하다 — §5-4 "커넥션 풀 고갈" 시나리오.
    logger.exception("DB 커넥션 풀 타임아웃")
    return _error_envelope(503, "SERVICE_UNAVAILABLE", _SERVICE_UNAVAILABLE_MESSAGE)


# 그 외 모든 미처리 예외(DB와 무관한 버그 등, TC-SEC-11/TC-SEC-25)는 이 파일이
# 아니라 `middleware.UnhandledExceptionMiddleware`가 최종 안전망으로 처리한다.
# `@app.exception_handler(Exception)`을 여기 등록하지 않은 이유는
# `middleware.py`의 `UnhandledExceptionMiddleware` 문서에 상세히 기록했다
# (요약: Starlette가 그 등록 방식을 `ServerErrorMiddleware`로 특별 취급해
# 보안 헤더/CORS 미들웨어를 우회하고 예외를 항상 재-raise하는 부작용이
# 있어, 이 재작업 중 직접 재현해 확인하고 미들웨어 방식으로 전환했다).
