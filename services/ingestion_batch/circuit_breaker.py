"""간이 서킷브레이커 (REQ-011, 03-system-design.md §5-4).

"하루 1~2회 배치 특성상 초단위 서킷브레이커는 불필요, '연속 실패 일수' 단위로
판단하는 것이 이 서비스 규모에 맞는 설계"(§5-4). 즉 이 서킷브레이커는 요청을
차단하지 않는다(배치는 매일 정상적으로 재시도한다) — 대신 최근 실행 이력이
연속 실패 임계치(기본 3일)에 도달하면 알림 심각도를 "고위험"으로 격상하는
신호만 낸다. 실제 배치 실행 여부에 영향을 주지 않는다(§5-4 원문 그대로).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CircuitBreakerStatus:
    is_open: bool
    consecutive_failures: int


def evaluate(statuses_most_recent_first: list[str], *, threshold: int) -> CircuitBreakerStatus:
    """가장 최근 실행부터 연속 FAILED 개수를 센다. PARTIAL/SUCCESS를 만나면 중단.

    `statuses_most_recent_first`는 이번에 방금 기록한 실행 결과까지 포함해야 한다
    (호출자가 finish_run() 이후 recent_ingest_statuses()로 조회한 결과를 그대로 전달).
    """
    consecutive_failures = 0
    for status in statuses_most_recent_first:
        if status != "FAILED":
            break
        consecutive_failures += 1

    return CircuitBreakerStatus(
        is_open=consecutive_failures >= threshold,
        consecutive_failures=consecutive_failures,
    )
