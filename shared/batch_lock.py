"""일일 배치 중복 실행 방지 락 (DEC-063).

PC(작업 스케줄러)와 GitHub Actions가 같은 DB에 배치를 돌리면 두 실행이 겹칠 수 있다.
수집·가공은 멱등 upsert라 데이터가 깨지진 않지만, 공공데이터 호출 한도를 두 배로 쓰고 서로의 쓰기를
기다리게 만든다. PostgreSQL **세션 단위 advisory lock**으로 "한 번에 하나만" 실행되게 한다.

주의:
  * 세션 락은 연결이 살아 있는 동안만 유효하다. Neon은 **직접(direct) 접속 주소**를 써야 한다
    (PgBouncer 트랜잭션 풀러 주소는 세션 락이 의미 없다).
  * 락 확인 자체가 실패하면(DB 연결 불가 등) 배치를 막지 않는다 — 경고만 남기고 계속한다.
    배치의 각 단계가 어차피 DB 오류를 스스로 보고하기 때문이다.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum

# 임의의 고정 키(프로젝트 전용). 다른 advisory lock 사용처와 겹치지 않게 큰 수로 둔다.
DAILY_BATCH_LOCK_KEY = 7_302_025_001


class LockState(StrEnum):
    ACQUIRED = "acquired"  # 락을 잡았다 → 실행해도 된다
    HELD = "held"  # 다른 실행이 잡고 있다 → 이번 실행은 양보한다
    UNAVAILABLE = "unavailable"  # 확인 실패 → 막지 않고 계속한다


@contextmanager
def daily_batch_lock(
    database_url: str | None, *, key: int = DAILY_BATCH_LOCK_KEY
) -> Iterator[LockState]:
    """`with daily_batch_lock(url) as state:` — state가 HELD면 호출자가 실행을 건너뛴다."""
    if not database_url:
        yield LockState.UNAVAILABLE
        return

    conn = None
    state = LockState.UNAVAILABLE
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(database_url, connect_args={"connect_timeout": 10})
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
        state = LockState.ACQUIRED if got else LockState.HELD
    except Exception as exc:  # 락 확인 실패는 배치를 막지 않는다
        print(f"[경고] 중복 실행 방지 락을 확인하지 못해 계속 진행합니다: {exc}", file=sys.stderr)
        state = LockState.UNAVAILABLE

    try:
        yield state
    finally:
        if conn is not None:
            try:
                if state is LockState.ACQUIRED:
                    from sqlalchemy import text

                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            except Exception:
                pass  # 연결이 끊기면 서버가 락을 자동으로 놓는다
            try:
                conn.close()
            except Exception:
                pass
