"""`CalendarLookup` 구현 재노출(re-export) — UNIT-06에서 `shared.calendar_service`로 승격.

이 모듈은 더 이상 자체 구현을 갖지 않는다. `unit-02-note.md` §2-3이 "세 번째
필요 시점(UNIT-06~08 Derivation Batch)에 shared로 승격"을 권고했고, 이번
유닛(UNIT-06)이 그 시점이라 실제로 승격했다(`shared/calendar_service/sql_repository.py`).
기존 import 경로(`from services.public_api.db.calendar_repository import
SqlCalendarRepository`)를 쓰는 `services/public_api/api/calendar.py` 등을
깨지 않기 위해 이 얇은 재노출만 남긴다.
"""

from __future__ import annotations

from shared.calendar_service.sql_repository import SqlCalendarRepository

__all__ = ["SqlCalendarRepository"]
