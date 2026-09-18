from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.public_api.api import calendar, health, market_summary, metrics, screen, stocks
from services.public_api.core.config import get_cors_allowed_origins
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import Envelope, ErrorDetail, Meta

KST = ZoneInfo("Asia/Seoul")

app = FastAPI(title="Stock Screener Public API", version="0.1.0")

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
