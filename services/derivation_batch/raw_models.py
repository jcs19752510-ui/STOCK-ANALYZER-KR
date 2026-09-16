"""`raw_internal` 읽기 전용 프로젝션 (REQ-002, Derivation Batch 전용).

03-system-design.md §1-2: "Derivation Batch — raw_internal을 읽어... 계산해
public_serving에 쓴다. 이 컴포넌트가 유일하게 raw→public 경계를 넘나드는
지점". §1-3은 "/shared: raw 데이터 모델 코드 없음"을 요구하므로, 이 모듈은
`shared/`가 아니라 이 서비스 전용 모듈에 둔다(`services/ingestion_batch/
models.py`와 동일한 원칙, 그 파일 docstring 참조).

**전체 ORM 모델을 다시 선언하지 않고, 이 배치가 실제로 읽는 컬럼만 담은
최소 `sqlalchemy.Table` 프로젝션만 정의한다.** 이 모듈은 SELECT 전용이라
(INSERT/UPDATE 없음) 원본 ENUM 타입을 생성(`CREATE TYPE`)할 필요는 없지만,
**타입 자체는 반드시 실제 컬럼과 일치시켜야 한다** — 로컬 실 PostgreSQL로
검증하는 과정에서 `market`을 평범한 `String`으로 선언했더니 psycopg가
바인드 파라미터에 `::VARCHAR` 캐스트를 붙여 `reference.market_session`
ENUM 컬럼과 비교할 때 `UndefinedFunction`(연산자 없음) 오류가 실제로
발생함을 확인했다(§7 로컬 동작 확인 로그 참조). 그래서 `reference.
market_session` ENUM(0001, `create_type=False`로 재사용 — 새 타입을 만들지
않음)을 그대로 가져와 쓴다.
"""

from __future__ import annotations

import sqlalchemy as sa

from shared.db_models.reference import market_session_enum

_metadata = sa.MetaData(schema="raw_internal")

raw_ohlcv_table = sa.Table(
    "raw_ohlcv",
    _metadata,
    sa.Column("stock_code", sa.String(6), primary_key=True),
    sa.Column("trade_date", sa.Date, primary_key=True),
    sa.Column("market", market_session_enum, primary_key=True),
    sa.Column("close", sa.Numeric),
    sa.Column("volume", sa.BigInteger),
)

raw_fundamentals_table = sa.Table(
    "raw_fundamentals",
    _metadata,
    sa.Column("stock_code", sa.String(6), primary_key=True),
    sa.Column("trade_date", sa.Date, primary_key=True),
    sa.Column("per", sa.Numeric),
    sa.Column("pbr", sa.Numeric),
    sa.Column("market_cap", sa.BigInteger),
)

__all__ = ["raw_fundamentals_table", "raw_ohlcv_table"]
