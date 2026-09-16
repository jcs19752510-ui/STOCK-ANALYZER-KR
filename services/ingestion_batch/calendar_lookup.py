"""`CalendarLookup` 구현 재노출(re-export) — UNIT-06에서 `shared.calendar_service`로 승격.

이 모듈은 더 이상 자체 구현을 갖지 않는다. 원래 이 파일에는
`services/public_api/db/calendar_repository.py`와 100% 동일한 로직이
의도적으로 중복되어 있었다(§1-3 서비스별 독립 배포 단위 원칙, `unit-02-note.md`
§2-3 참조). 그 노트는 "이 로직이 세 번째로 필요해지면(UNIT-06~08의 Derivation
Batch 등) `shared/calendar_service/`로 승격하는 것을 권고한다"고 명시했다 —
이번 유닛(UNIT-06)이 Derivation Batch를 만들며 그 세 번째 필요 시점에
도달해, 새 사본을 또 만드는 대신 실제로 승격했다(`shared/calendar_service/
sql_repository.py`). 기존 import 경로(`from services.ingestion_batch.
calendar_lookup import SqlCalendarRepository`)를 쓰는 `run_ingestion.py`/
`scripts/seed_stock_master.py`를 깨지 않기 위해 이 얇은 재노출만 남긴다.
"""

from __future__ import annotations

from shared.calendar_service.sql_repository import SqlCalendarRepository

__all__ = ["SqlCalendarRepository"]
