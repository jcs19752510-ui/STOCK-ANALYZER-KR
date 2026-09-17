"""`public_serving` 스키마 모델 (REQ-011 배치 실행 이력).

03-system-design.md §3-2 `public_serving.batch_run` 정의를 반영한다.
`public_serving`은 원본(raw) 데이터가 아니므로(§1-3 "shared: raw 데이터 모델
코드 없음"과 무관), 이 모델은 이 저장소(shared)에 두는 것이 원칙과 상충하지
않는다. `raw_internal` 모델(RawOhlcv/RawFundamentals)은 반드시 여기 두지
않는다 — `services/ingestion_batch/models.py` 참조.

UNIT-02에서는 이 테이블 중 Ingestion Batch가 사용하는 부분만 채웠다.
UNIT-03이 `StockMaster`(REQ-001)를 추가했다. UNIT-06이 `DerivedMetricsDaily`/
`CurrentPublishedBatch`(REQ-002, Derivation Batch 산출물)를 추가한다.
`market_summary_daily`(REQ-004)는 여전히 UNIT-08 소관이라 이번에도 만들지
않는다(범위 외 확장 금지).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from shared.calendar_service.types import Market
from shared.db_models.base import Base
from shared.db_models.reference import market_session_enum
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


class DerivedMetricsDaily(Base):
    """종목별 가공 지표(REQ-002). 03-system-design.md §3-2 `derived_metrics_daily`.

    원본 시세 컬럼(open/high/low/close/volume)이 이 테이블에 애초에 존재하지
    않는다 — §4-3 데이터 가공 원칙의 1차 방어(스키마 분리)가 이 테이블에도
    그대로 적용된다. `per_raw`/`pbr_raw`/`market_cap_raw_krw`는 스크리닝
    필터링(UNIT-07)을 위해 DB에는 존재하지만, API 응답 화이트리스트에서는
    항상 제외된다(§3-2 Q5, DEC-014 — `services/public_api/schemas/metrics.py`
    참조).

    `market`은 **상장시장 구분**(KOSPI/KOSDAQ, §3-1-1)이며 `stock_master.market`을
    Derivation Batch가 조인해 그대로 복제한 값이다(`raw_ohlcv.market`(거래소
    세션)에서 유도하지 않음 — §3-2 본문).
    """

    __tablename__ = "derived_metrics_daily"
    __table_args__ = {"schema": "public_serving"}

    stock_code: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    market: Mapped[ListedMarket] = mapped_column(listed_market_enum, primary_key=True)
    return_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    return_rank_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    ma5_gap_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    ma20_gap_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    volume_anomaly_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    per_raw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pbr_raw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    market_cap_raw_krw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 필터 전용(REQ-003 `GET /screen?volume_min=`), API 응답에 절대 노출하지
    # 않는다 — per_raw/pbr_raw/market_cap_raw_krw와 동일한 원칙(0007 마이그레이션,
    # `unit-07-note.md` §2 참조). 대응하는 `*_percentile` 컬럼은 만들지 않는다
    # (04-ux-design.md에 "거래량 백분위" 표시 문구/개념이 정의되어 있지 않음).
    volume_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    per_percentile: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pbr_percentile: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    market_cap_percentile: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    batch_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public_serving.batch_run.batch_run_id"), nullable=False
    )


class CurrentPublishedBatch(Base):
    """"현재 서빙 중" 데이터 포인터(§3-2, §5-3 롤백/무결성). REQ-002/003/004 공용 인프라.

    설계서 §3-2 표는 `market(PK)`만 명시하고 어느 축(상장시장 KOSPI/KOSDAQ vs
    거래소 세션 KRX/NXT)인지 못박지 않았다 — 04-ux-design.md §7-1 Q1~Q7과
    같은 성격의 설계 공백이다(unit-03-note.md §0과 동일하게, 새 REQ 없이
    구현 세부를 확정해야 하는 사안이라 사용자에게 되묻지 않고 이 유닛이
    직접 확정한다, `unit-06-note.md` §2 참조). `meta.data_freshness.market`
    (§3-4)이 거래소 세션 구분이고, 이 포인터가 "그 세션의 배치가 어디까지
    발행됐는지"를 가리키는 것이 자연스러우므로 `reference.market_session`
    ENUM(KRX/NXT)을 재사용한다 — 상장시장 ENUM(`listed_market`)이 아니다.
    """

    __tablename__ = "current_published_batch"
    __table_args__ = {"schema": "public_serving"}

    market: Mapped[Market] = mapped_column(market_session_enum, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    batch_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public_serving.batch_run.batch_run_id"), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
