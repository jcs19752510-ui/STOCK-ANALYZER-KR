"""`raw_internal` 스키마 모델 (REQ-011, 03-system-design.md §3-2).

**의도적으로 `shared/db_models/`에 두지 않는다.** 03-system-design.md §1-3:
"/shared: 캘린더 계산 유틸, 응답 스키마 정의 등 (raw 데이터 모델 코드
없음)". raw_internal에 대한 DB 자격증명 자체가 public_api 프로세스에
주입되지 않는 3차 방어(§1-1)와 정합되게, 코드 레벨에서도 raw 모델을 다른
서비스가 import조차 할 수 없는 위치(이 서비스 전용 모듈)에 둔다.

이 파일은 `shared.db_models.Base`(공용 메타데이터)를 상속하지 않고 별도의
`DeclarativeBase`를 쓴다 — public_api/derivation_batch가 `shared.db_models`를
import할 때 raw 테이블 정의가 같은 메타데이터 레지스트리에 딸려오는 것 자체를
피하기 위함이다(이 프로젝트의 모든 Alembic 리비전은 autogenerate가 아니라
수기 DDL이므로, 별도 메타데이터를 쓰더라도 마이그레이션 동작에는 영향 없다).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from shared.calendar_service.types import Market
from shared.db_models.reference import market_session_enum


class RawInternalBase(DeclarativeBase):
    """raw_internal 전용 베이스. shared.db_models.Base와 별도 메타데이터."""


class RawOhlcv(RawInternalBase):
    """원본 OHLCV. 03-system-design.md §3-2 `raw_internal.raw_ohlcv`.

    `market`은 거래소 세션 구분(KRX/NXT, §3-1-1)이며, `reference.market_calendar`와
    동일한 Postgres ENUM(`reference.market_session`)을 그대로 재사용한다(마이그레이션
    참조) — 별도 ENUM을 새로 만들지 않아 두 테이블의 값 집합이 갈라질 여지를 없앤다.
    """

    __tablename__ = "raw_ohlcv"
    __table_args__ = {"schema": "raw_internal"}

    stock_code: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(primary_key=True)
    market: Mapped[Market] = mapped_column(market_session_enum, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trading_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    source_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class RawFundamentals(RawInternalBase):
    """원본 재무지표 원문. 03-system-design.md §3-2 `raw_internal.raw_fundamentals`.

    **중요(unit-02-note.md 참조)**: 이 유닛은 이 테이블의 스키마만 만들고,
    Ingestion Batch는 아직 이 테이블에 실제로 데이터를 적재하지 않는다.
    채택 API(공공데이터포털 "금융위원회_주식시세정보")가 PER/PBR을 이
    엔드포인트에서 실제로 제공하는지 실 API 키 없이 확인할 수 없었기
    때문이다(추측으로 필드명을 지어내지 않는다 — unit-02-note.md §2 참조).
    """

    __tablename__ = "raw_fundamentals"
    __table_args__ = {"schema": "raw_internal"}

    stock_code: Mapped[str] = mapped_column(String(6), primary_key=True)
    trade_date: Mapped[date] = mapped_column(primary_key=True)
    per: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pbr: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    market_cap: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    source_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
