"""장중 재계산 응답 스키마(DEC-089, 계약서 §3). 기존 `/screen`·`/screen/pattern` 응답에 `basis`와 `meta.live`만 더한다."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class LiveBaseFill(BaseModel):
    gap_days: int
    state: Literal["none", "running", "ready", "failed"]
    done: int
    total: int
    filled: int
    excluded: int
    mismatched: int
    pending: int
    source: Literal["kis_daily_price"] | None = None


class LiveChanges(BaseModel):
    entered: list[str]
    left: list[str]


class LiveMeta(BaseModel):
    snapshot_id: str
    as_of: float
    basis_trade_date: str
    expected_trade_date: str
    today: str
    quotes_covered: int
    quotes_total: int
    coverage_ratio: float
    oldest_quote_age_seconds: float | None
    stale: bool
    volume_partial: Literal[True] = True
    recomputed: list[str]
    fixed_daily: list[str]
    return_rank_policy: Literal["live", "daily"]
    compute_ms: float
    refresh_seconds: float
    priority_codes: int
    priority_cycle_seconds: float | None
    base_fill: LiveBaseFill
    changes: LiveChanges | None = None


def live_meta_from(info: dict[str, Any], *, snapshot_id: str, priority_codes: int,
                   priority_cycle_seconds: float | None, changes: dict[str, list[str]] | None) -> dict[str, Any]:
    return LiveMeta(
        snapshot_id=snapshot_id,
        priority_codes=priority_codes,
        priority_cycle_seconds=priority_cycle_seconds,
        changes=LiveChanges(**changes) if changes is not None else None,
        **info,
    ).model_dump(mode="json")
