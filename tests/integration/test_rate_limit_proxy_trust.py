"""실제 uvicorn 프로세스 기반 회귀 테스트 — DEF-SEC-03 대응.

`09-security-audit.md` §11-3(TC-SEC-45/46/47)가 지적한 문제: `fastapi.testclient.
TestClient`는 ASGI를 인프로세스로 직접 호출하기 때문에 uvicorn의
`ProxyHeadersMiddleware`(실제 TCP 계층 + uvicorn 서버 옵션에서만 작동)를 아예
거치지 않는다 — 즉 이 벡터는 `TestClient` 기반 `tests/unit` 스위트로는 구조적으로
검증이 불가능하다. 이 파일은 `scripts/run_public_api.py`(DEF-SEC-03 수정으로 신설된
공식 기동 스크립트)로 실제 uvicorn 서브프로세스를 띄우고, 실제 소켓을 통해
`X-Forwarded-For` 스푸핑을 시도해 더 이상 rate limit을 우회할 수 없음을 확인한다.

`pytest tests/unit -q`에는 포함되지 않는다 — 실제 프로세스 기동/포트 바인딩이
필요해 `tests/unit`보다 느리므로 별도로 `pytest tests/integration -q`로 실행한다.

**DB에 의존하지 않는다.** `RateLimitMiddleware`는 라우팅(핸들러 매칭)보다 앞선
공통 미들웨어라 존재하지 않는 라우트에도 동일하게 적용된다(라우팅 자체는 그
안쪽에서 이뤄지므로 404 응답도 카운터를 소모한다) — 이를 이용해 실제 DB 접속
결과와 무관한, 존재하지 않는 경로(`/api/v1/__integration_test_probe__`)로
rate limit 한도 소진 여부만 빠르고 결정론적으로 검증한다. `PUBLIC_API_DATABASE_URL`을
설정하지 않아도 이 경로는 DB 세션을 전혀 생성하지 않으므로(지연 생성,
`services/public_api/db/session.py`) 앱이 정상 기동한다.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_ROOT / "scripts" / "run_public_api.py"

_PROBE_PATH = "/api/v1/__integration_test_probe__"
_READY_TIMEOUT_SECONDS = 15.0
# 기본 한도(분당 60회)를 그대로 쓰면 이 테스트가 실제 TCP 연결을 60회 이상
# 빠르게 맺어야 하는데, 로컬 루프백 소켓 스택 특성상(환경에 따라 다름) 연속
# 요청 50회 안팎부터 개별 요청이 간헐적으로 지연되는 현상이 관찰됐다. 이는
# 애플리케이션 동작과 무관한 테스트 환경의 소켓 처리량 문제이므로, rate limit
# 로직 자체는 건드리지 않고 `PUBLIC_API_RATE_LIMIT_PER_MINUTE`(rate_limit.py
# 신규 — 테스트 전용 환경변수)로 한도만 낮춰 필요한 실제 요청 수를 최소화한다.
_TEST_RATE_LIMIT = 5
_RATE_LIMIT_SEARCH_ATTEMPTS = _TEST_RATE_LIMIT + 10


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(base_url: str) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}{_PROBE_PATH}", timeout=2.0)
        except httpx.HTTPError as exc:
            last_error = exc
        else:
            # 존재하지 않는 경로이므로 정상 기동 시 404가 기대값이다.
            if response.status_code == 404:
                return
            last_error = RuntimeError(f"unexpected status {response.status_code}")
        time.sleep(0.2)
    raise RuntimeError(f"서버가 {_READY_TIMEOUT_SECONDS}초 내에 기동하지 않았습니다: {last_error}")


@pytest.fixture
def live_server() -> Iterator[str]:
    """`scripts/run_public_api.py`로 실제 uvicorn 서브프로세스를 기동한다.

    `PUBLIC_API_TRUSTED_PROXY_IPS`를 의도적으로 설정하지 않는다 — 이 스크립트의
    기본(fail closed) 동작을 그대로 검증하기 위함이다(10단계 배포 시 실제 리버스
    프록시 IP를 명시적으로 신뢰 목록에 추가하기 전까지는 이 기본값이 적용된다).
    `PUBLIC_API_DATABASE_URL`도 설정하지 않는다 — 이 테스트가 쓰는 경로는 DB
    세션을 생성하지 않아(위 모듈 docstring 참조) 필요 없다.
    """
    port = _free_port()
    env = dict(os.environ)
    env["PUBLIC_API_HOST"] = "127.0.0.1"
    env["PUBLIC_API_PORT"] = str(port)
    env["PUBLIC_API_RATE_LIMIT_PER_MINUTE"] = str(_TEST_RATE_LIMIT)
    env.pop("PUBLIC_API_DATABASE_URL", None)
    env.pop("PUBLIC_API_TRUSTED_PROXY_IPS", None)

    process = subprocess.Popen(
        [sys.executable, str(RUN_SCRIPT)],
        env=env,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_ready(base_url)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _get(base_url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """매 호출마다 새 연결을 맺는다(`httpx.Client`의 keep-alive 연결 재사용 시
    이 로컬 환경에서 간헐적으로 응답이 지연되는 현상이 관찰되어, 준비 폴링
    함수(`_wait_until_ready`)와 동일하게 요청마다 독립적인 연결을 사용한다).

    이 테스트 환경(로컬 루프백 소켓)에서는 애플리케이션 동작과 무관하게
    간헐적으로 개별 요청이 지연되는 현상이 관찰되어(백신 등 로컬 네트워크
    스택 개입 추정), 진짜 응답 지연/행(hang)과 이 환경 노이즈를 구분하기 위해
    타임아웃 시 짧게 재시도한다 — rate limit 로직 자체는 재시도와 무관하게
    항상 서버 측 카운터에만 의존하므로, 재시도가 결과를 왜곡하지 않는다.
    """
    last_exc: httpx.TimeoutException | None = None
    for attempt in range(3):
        try:
            return httpx.get(f"{base_url}{_PROBE_PATH}", headers=headers, timeout=5.0)
        except httpx.TimeoutException as exc:
            last_exc = exc
            time.sleep(0.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def test_x_forwarded_for_spoofing_no_longer_bypasses_rate_limit(live_server: str) -> None:
    """09-security-audit.md §11-3 TC-SEC-45 재현 절차: 한도 소진 → 429 →
    `X-Forwarded-For`를 매 요청 다른 값으로 바꿔 보내도 여전히 429(우회 불가)."""
    # 준비(readiness) 폴링도 동일한 카운터를 소모하므로, 정확히 60회를 세는
    # 대신 429가 나올 때까지 반복해 한도를 실제로 소진시킨다.
    reached_limit = False
    for _ in range(_RATE_LIMIT_SEARCH_ATTEMPTS):
        response = _get(live_server)
        if response.status_code == 429:
            reached_limit = True
            break
        assert response.status_code == 404, (
            f"한도 소진 전 요청은 (존재하지 않는 경로이므로) 404여야 한다"
            f"(실제: {response.status_code})"
        )
    assert reached_limit, (
        f"{_RATE_LIMIT_SEARCH_ATTEMPTS}회 반복해도 rate limit(429)에 도달하지 못했다"
    )

    for spoofed_ip in ("9.9.9.9", "10.0.0.1", "203.0.113.5"):
        response = _get(live_server, headers={"X-Forwarded-For": spoofed_ip})
        assert response.status_code == 429, (
            f"X-Forwarded-For={spoofed_ip} 스푸핑으로 rate limit이 우회됐다 "
            f"(DEF-SEC-03 회귀, 실제 상태코드: {response.status_code})"
        )


def test_normal_client_without_spoofing_is_not_penalized_by_rate_limit_reset(
    live_server: str,
) -> None:
    """정상 회귀 확인: 별도의 새 서버 인스턴스(카운터 초기화 상태)에서는 스푸핑
    없이 보낸 정상 요청이 한도 내에서 여전히 정상 처리됨(429가 아님)을 확인한다."""
    response = _get(live_server)
    assert response.status_code == 404
