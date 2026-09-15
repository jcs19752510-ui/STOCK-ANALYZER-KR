from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.public_api.db.session import get_db
from services.public_api.schemas.envelope import Envelope, Meta

router = APIRouter(tags=["health"])

KST = ZoneInfo("Asia/Seoul")

logger = logging.getLogger(__name__)


@router.get("/health", response_model=Envelope[dict])
def health(db: Session = Depends(get_db)) -> Envelope[dict]:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        logger.exception("헬스체크 DB 연결 확인 실패")
        db_status = "degraded"

    return Envelope[dict](
        meta=Meta(generated_at=datetime.now(KST)),
        data={"status": "ok", "db": db_status},
    )
