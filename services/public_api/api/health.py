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


@router.get("/live", response_model=Envelope[dict])
def live() -> Envelope[dict]:
    """프로세스가 살아 있는지만 확인한다(DB를 조회하지 않음, DEC-063).

    `/health`는 `SELECT 1`을 실행하므로, 이것을 호스팅의 헬스체크나 주기적 접속에 쓰면
    유휴 시 정지되는 DB(Neon)가 계속 깨어 있어 무료 사용 시간을 쓴다. 그런 용도는 이 경로를 쓴다.
    """
    return Envelope[dict](
        meta=Meta(generated_at=datetime.now(KST)),
        data={"status": "ok"},
    )
