#!/usr/bin/env python
"""Public API 기동 스크립트 (DEF-SEC-03 대응, `09-security-audit.md` §11-3/§11-5).

`uvicorn services.public_api.main:app`을 CLI에서 직접 실행하면 uvicorn의 기본값
(`proxy_headers=True`, `forwarded_allow_ips` 미지정 시 `127.0.0.1`(loopback) 암묵
신뢰)이 그대로 적용된다. 이 저장소는 아직 리버스 프록시의 실제 IP가 확정된 배포
아티팩트(Dockerfile/Procfile 등)가 없으므로(03-system-design.md §5-2, 09단계 §11-3
"주의" 참조), 이 신뢰를 기본으로 켜 두면 loopback을 통해 들어오는 모든 연결이
`X-Forwarded-For` 헤더를 무조건 신뢰하게 되어, `rate_limit.py`의 IP 기준 rate
limiting이 그 헤더 하나만 바꿔가며 보내는 것으로 완전히 무력화된다(DEF-SEC-03).

**이 스크립트가 이 서비스의 공식 기동 방법이다** — `uvicorn services.public_api.main:app`을
직접 실행하지 말 것(직접 실행하면 이 방어가 적용되지 않는다).

기본 동작은 `X-Forwarded-For` 등 프록시 헤더를 전혀 신뢰하지 않는다(fail closed).
실제 리버스 프록시를 두게 되는 시점(10단계 배포 아티팩트 확정 시)에는, 그 프록시의
실제 IP(들)를 `PUBLIC_API_TRUSTED_PROXY_IPS`(쉼표 구분)에 명시적으로 설정해야만
프록시 헤더 신뢰가 켜진다 — 운영자가 신뢰 범위를 명시적으로 결정하게 강제하며,
설정하지 않으면(빈 값) 암묵적으로 아무것도 신뢰하지 않는다.

사용법:
    python scripts/run_public_api.py

환경변수:
    PUBLIC_API_HOST                기본값 "0.0.0.0"
    PUBLIC_API_PORT                기본값 "8000"
    PUBLIC_API_TRUSTED_PROXY_IPS   쉼표 구분 IP 목록. 비어 있으면(기본) 프록시
                                    헤더를 전혀 신뢰하지 않는다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import uvicorn  # noqa: E402


def main() -> None:
    host = os.environ.get("PUBLIC_API_HOST", "0.0.0.0")
    port = int(os.environ.get("PUBLIC_API_PORT", "8000"))
    trusted_proxy_ips = os.environ.get("PUBLIC_API_TRUSTED_PROXY_IPS", "").strip()

    uvicorn.run(
        "services.public_api.main:app",
        host=host,
        port=port,
        # 명시적으로 신뢰 대상 IP를 설정한 경우에만 프록시 헤더를 신뢰한다(opt-in).
        # 빈 문자열(기본값)이면 proxy_headers=False가 되어 uvicorn이
        # ProxyHeadersMiddleware 자체를 적용하지 않으므로, request.client.host는
        # 항상 실제 TCP peer 주소를 그대로 반영한다(DEF-SEC-03 근본 해결).
        proxy_headers=bool(trusted_proxy_ips),
        forwarded_allow_ips=trusted_proxy_ips or None,
    )


if __name__ == "__main__":
    main()
