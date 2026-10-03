"""`public_serving.batch_run` 기록/조회 (REQ-011, 03-system-design.md §3-2).

Ingestion Batch가 매 실행마다 시작/종료 상태를 남긴다. `run_type='ingest'`로
고정한다(`'derive'`는 UNIT-06~08의 Derivation Batch 소관).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from shared.db_models.public_serving import BatchRun

# 백필 실행 행 식별자: `error_summary`가 이 접두로 시작하면 서킷브레이커 집계에서 제외된다.
BACKFILL_ERROR_SUMMARY_PREFIX = "BACKFILL"

# "대상 거래일 데이터가 아직 공개되지 않음(0건)" 행 식별자(DEC-058).
# 공공데이터는 +1영업일 뒤에 올라오므로 주말·휴장 뒤에는 정상적으로 며칠씩 0건이다.
# 이 행은 FAILED로 기록되지만 서킷브레이커의 "연속 실패" 집계에서는 성공도 실패도 아닌
# "대기"로 보아 제외한다(진짜 지연은 신선도 점검 `scripts/check_data_freshness.py`가 따로
# 알린다). 접두 도입 이전에 기록된 같은 사유의 행도 문구로 함께 제외한다.
NOT_PUBLISHED_ERROR_SUMMARY_PREFIX = "NOT_PUBLISHED"
LEGACY_NOT_PUBLISHED_TEXT = "대상 거래일 데이터가 0건 반환되었습니다"


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
    """가장 최근 ingest 배치 실행 상태를 최신순으로 최대 `limit`건 조회한다.

    과거 시세 백필(`scripts/backfill_ohlcv.py`, REQ-031) 실행 행은 제외한다 — 백필도
    `run_type='ingest'`로 기록되는데(`batch_run_type` ENUM에 별도 값이 없음), 그 결과가
    일일 수집의 "연속 실패 일수"(서킷브레이커, §5-4) 집계에 섞이면 백필 SUCCESS가 실제
    연속 실패를 끊어 장애 알림이 약해지고 백필 FAILED는 알림을 오작동시킨다.
    "데이터 미공개(0건)" 행도 같은 이유로 제외한다(DEC-058, 위 상수 참조).
    `error_summary`가 NULL인 일반 행은 그대로 포함한다.
    """
    stmt = (
        select(BatchRun.status)
        .where(BatchRun.run_type == "ingest")
        .where(
            or_(
                BatchRun.error_summary.is_(None),
                (
                    BatchRun.error_summary.not_like(f"{BACKFILL_ERROR_SUMMARY_PREFIX}%")
                    & BatchRun.error_summary.not_like(f"{NOT_PUBLISHED_ERROR_SUMMARY_PREFIX}%")
                    & BatchRun.error_summary.not_like(f"{LEGACY_NOT_PUBLISHED_TEXT}%")
                ),
            )
        )
        .order_by(BatchRun.started_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())
