"""`public_serving.batch_run` 기록 — Derivation Batch용 (`run_type='derive'`).

`services/ingestion_batch/batch_run_repository.py`와 거의 동일하지만
`run_type='derive'`로 고정된 별도 사본이다. §1-3(서비스별 독립 배포 단위)
원칙에 따라 서비스 간 코드 import를 만들지 않는다(`unit-02-note.md` §2-3과
동일한 의도적 최소 중복 — 두 서비스가 공유하는 것은 오직 `shared.db_models.
public_serving.BatchRun`(원본이 아닌 스키마 모델)뿐이다).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from shared.db_models.public_serving import BatchRun


def start_run(session: Session) -> uuid.UUID:
    run = BatchRun(
        batch_run_id=uuid.uuid4(),
        run_type="derive",
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


__all__ = ["finish_run", "start_run"]
