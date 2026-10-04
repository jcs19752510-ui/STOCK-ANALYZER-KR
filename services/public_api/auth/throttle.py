"""로그인 시도 빈도 제한(프로세스 메모리, 고정 윈도 1분). 비밀번호 해시 계산이 CPU를 많이 쓰므로(무료 서버는 더 느림)
같은 접속 주소당 상한과 서버 전체 상한을 둘 다 둔다. 단일 인스턴스 전제(`rate_limit.py`와 같은 한계)."""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import threading
import time

from services.public_api.core.config import get_login_rate_limits

WINDOW_SECONDS = 60.0
_MAX_TRACKED = 10_000
_lock = threading.Lock()
_per_key: dict[str, tuple[float, int]] = {}
_global: list[float | int] = [0.0, 0]


def reset_login_throttle() -> None:
    """테스트 전용: 카운터 초기화."""
    with _lock:
        _per_key.clear()
        _global[0], _global[1] = 0.0, 0


def allow_login_attempt(client_key: str | None, *, now: float | None = None) -> bool:
    """이번 시도를 받아도 되면 True(그리고 횟수를 센다). 상한을 넘으면 False."""
    per_key_limit, global_limit = get_login_rate_limits()
    key = client_key or "unknown"
    t = time.monotonic() if now is None else now
    with _lock:
        if t - float(_global[0]) >= WINDOW_SECONDS:
            _global[0], _global[1] = t, 0
        if int(_global[1]) + 1 > global_limit:
            return False
        if len(_per_key) > _MAX_TRACKED:
            for k in [k for k, (s, _c) in _per_key.items() if t - s >= WINDOW_SECONDS]:
                del _per_key[k]
        start, count = _per_key.get(key, (t, 0))
        if t - start >= WINDOW_SECONDS:
            start, count = t, 0
        if count + 1 > per_key_limit:
            return False
        _per_key[key] = (start, count + 1)
        _global[1] = int(_global[1]) + 1
        return True
