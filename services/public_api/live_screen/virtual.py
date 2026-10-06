"""장중 재계산 행을 SQL "가상 테이블"로 넣는 도구 — `jsonb_to_recordset`(DEC-089 §1).

`public_serving.derived_metrics_daily` 자리에 같은 열을 가진 서브쿼리를 넣어, 기존 필터·정렬·패턴 조건식(SQL)이 **그대로** 판정하게 한다.
`api_service`는 읽기 전용이지만 `jsonb_to_recordset`은 권한이 필요 없다(테이블을 만들지 않는다). 값은 전부 바인드 파라미터 하나(JSON 문자열)로 전달한다.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Text, cast, column, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from shared.db_models.public_serving import DerivedMetricsDaily

# 시장(상장시장) 열은 PostgreSQL enum이라 가상 테이블에서는 text로 받는다(비교 시 문자열 리터럴과 맞는다).
_TEXT_COLUMNS = {"market"}


def row_columns() -> list[str]:
    """가상 행이 가져야 하는 열 이름(발행 테이블과 같다)."""
    return [c.key for c in DerivedMetricsDaily.__table__.columns]


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)  # 정밀도를 잃지 않게 문자열로 보낸다(PostgreSQL이 numeric으로 읽는다)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bool):  # pragma: no cover — bool은 JSON이 그대로 처리
        return value
    raise TypeError(f"JSON으로 보낼 수 없는 값: {type(value).__name__}")


def dump_rows(rows: Sequence[dict[str, Any]], *, trade_date: date) -> str:
    """가상 행들을 JSON 한 덩어리로 만든다. 모든 행의 `trade_date`는 필터 키(`trade_date`)로 통일한다(실제 계산 기준일은 응답 meta에 따로 있다)."""
    cols = row_columns()
    out = []
    for r in rows:
        item = {c: r.get(c) for c in cols}
        item["trade_date"] = trade_date
        out.append(item)
    return json.dumps(out, default=_json_default, ensure_ascii=False, separators=(",", ":"))


def build_virtual_source(payload: str) -> Any:
    """`DerivedMetricsDaily`와 같은 속성을 가진 별칭 엔티티를 만든다(SELECT·WHERE·정렬 모두 기존 코드가 그대로 쓴다)."""
    cols = []
    for c in DerivedMetricsDaily.__table__.columns:
        cols.append(column(c.key, Text if c.key in _TEXT_COLUMNS else c.type))
    recordset = (
        func.jsonb_to_recordset(cast(literal(payload), JSONB))
        .table_valued(*cols)
        .render_derived(with_types=True)
    )
    subq = select(recordset).subquery("derived_metrics_daily_live")
    return aliased(DerivedMetricsDaily, subq, adapt_on_names=True)
