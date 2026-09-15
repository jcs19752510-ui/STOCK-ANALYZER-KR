"""services/ingestion_batch/circuit_breaker.py 단위테스트 (§5-4).

"3일 연속 실패(간이 서킷브레이커)"를 요청 차단이 아니라 알림 격상 신호로만
쓴다는 설계 의도(§5-4)를 그대로 검증한다.
"""

from services.ingestion_batch.circuit_breaker import evaluate


def test_below_threshold_is_closed():
    status = evaluate(["FAILED", "FAILED", "SUCCESS"], threshold=3)
    assert status.is_open is False
    assert status.consecutive_failures == 2


def test_exact_threshold_consecutive_failures_opens():
    status = evaluate(["FAILED", "FAILED", "FAILED"], threshold=3)
    assert status.is_open is True
    assert status.consecutive_failures == 3


def test_success_breaks_the_streak():
    status = evaluate(["FAILED", "SUCCESS", "FAILED"], threshold=3)
    assert status.is_open is False
    assert status.consecutive_failures == 1


def test_partial_breaks_the_streak_like_success():
    status = evaluate(["FAILED", "FAILED", "PARTIAL", "FAILED"], threshold=3)
    assert status.is_open is False
    assert status.consecutive_failures == 2


def test_empty_history_is_closed():
    status = evaluate([], threshold=3)
    assert status.is_open is False
    assert status.consecutive_failures == 0


def test_more_than_threshold_consecutive_failures_still_open():
    status = evaluate(["FAILED"] * 5, threshold=3)
    assert status.is_open is True
    assert status.consecutive_failures == 5
