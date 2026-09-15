"""`public_serving.batch_run` 기록/조회 (REQ-011, 03-system-design.md §3-2).

Ingestion Batch가 매 실행마다 시작/종료 상태를 남긴다. `run_type='ingest'`로
고정한다(`'derive'`는 UNIT-06~08의 Derivation Batch 소관).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db_models.public_serving import BatchRun


def start_run(session: Session) -> uuid.UUID:
    run = BatchRun(
        batch_run_id=uuid.uuid4(),
        run_type="ingest",
        status="FAILED",  # finish_run()이 실제 결과로 덮어쓸 때까지의 안전한 기본값
        validation_passed=False,
    )
    session.add(run)
    session.flush()
    return run.batch_run_id


def finish_run(
    session: Session,
    batch_run_id: uuid.UUID,
    *,
    status: str,
    trade_date_covered: date | None,
    validation_passed: bool,
    error_summary: str | None,
) -> None:
    run = session.get(BatchRun, batch_run_id)
    if run is None:
        raise ValueError(f"batch_run_id={batch_run_id}를 찾을 수 없습니다.")
    run.finished_at = datetime.now(UTC)
    run.status = status
    run.trade_date_covered = trade_date_covered
    run.validation_passed = validation_passed
    run.error_summary = error_summary


def recent_ingest_statuses(session: Session, limit: int) -> list[str]:
    """가장 최근 ingest 배치 실행 상태를 최신순으로 최대 `limit`건 조회한다."""
    stmt = (
        select(BatchRun.status)
        .where(BatchRun.run_type == "ingest")
        .order_by(BatchRun.started_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())
