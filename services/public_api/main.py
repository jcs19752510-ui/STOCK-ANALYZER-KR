from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.public_api.api import calendar, health, metrics, stocks
from services.public_api.errors import ApiError
from services.public_api.schemas.envelope import Envelope, ErrorDetail, Meta

KST = ZoneInfo("Asia/Seoul")

app = FastAPI(title="Stock Screener Public API", version="0.1.0")

app.include_router(health.router, prefix="/api/v1")
app.include_router(calendar.router, prefix="/api/v1")
app.include_router(stocks.router, prefix="/api/v1")
app.include_router(metrics.router, prefix="/api/v1")


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
