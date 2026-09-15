"""`public_serving` 스키마 모델 (REQ-011 배치 실행 이력).

03-system-design.md §3-2 `public_serving.batch_run` 정의를 반영한다.
`public_serving`은 원본(raw) 데이터가 아니므로(§1-3 "shared: raw 데이터 모델
코드 없음"과 무관), 이 모델은 이 저장소(shared)에 두는 것이 원칙과 상충하지
않는다. `raw_internal` 모델(RawOhlcv/RawFundamentals)은 반드시 여기 두지
않는다 — `services/ingestion_batch/models.py` 참조.

UNIT-02에서는 이 테이블 중 Ingestion Batch가 사용하는 부분만 채웠다.
UNIT-03이 `StockMaster`(REQ-001)를 추가한다. `public_serving`의 나머지
테이블(derived_metrics_daily, market_summary_daily, current_published_batch)은
여전히 UNIT-06~08 소관이라 이번에도 만들지 않는다(범위 외 확장 금지).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from shared.db_models.base import Base
from shared.market_types import ListedMarket

batch_run_type_enum = Enum(
    "ingest",
    "derive",
    name="batch_run_type",
    schema="public_serving",
    create_constraint=True,
    validate_strings=True,
)

batch_run_status_enum = Enum(
    "SUCCESS",
    "FAILED",
    "PARTIAL",
    name="batch_run_status",
    schema="public_serving",
    create_constraint=True,
    validate_strings=True,
)


class BatchRun(Base):
    """배치(Ingestion/Derivation) 실행 이력. 03-system-design.md §3-2."""

    __tablename__ = "batch_run"
    __table_args__ = {"schema": "public_serving"}

    batch_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_type: Mapped[str] = mapped_column(batch_run_type_enum, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(batch_run_status_enum, nullable=False)
    trade_date_covered: Mapped[date | None] = mapped_column(Date, nullable=True)
    validation_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


listed_market_enum = Enum(
    "KOSPI",
    "KOSDAQ",
    name="listed_market",
    schema="public_serving",
    create_constraint=True,
    validate_strings=True,
)


class StockMaster(Base):
    """상장 종목 마스터(REQ-001). 03-system-design.md §3-2.

    `market`은 **상장시장 구분**(KOSPI/KOSDAQ, §3-1-1)이며, `reference.
    market_calendar`/`raw_internal.raw_ohlcv`의 거래소 세션 구분(KRX/NXT)과는
    다른 축이므로 별도 ENUM(`listed_market`)을 사용한다(혼용 금지).

    설계서 §3-2 컬럼 목록에는 없으나, `listing_date`(상장일)는 이번 유닛이
    채택한 데이터 소스(getStockPriceInfo 일별 시세 스냅샷)에서 얻을 수 없어
    nullable로 둔다(§8-2 항목8이 이미 `sector`에 적용한 것과 동일한 처리
    원칙 — 출처 미확정 필드는 상상으로 채우지 않고 null로 유지, unit-03-note.md
    "설계서 대비 편차" 참조). `updated_at`은 설계서 표에 없지만 DEF-004
    (updated_at 갱신 누락) 재발 방지를 위해 이 유닛부터 마스터성 테이블에
    일관되게 추가한다(reference.market_calendar와 동일 패턴).
    """

    __tablename__ = "stock_master"
    __table_args__ = {"schema": "public_serving"}

    stock_code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[ListedMarket] = mapped_column(listed_market_enum, nullable=False)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    listing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
