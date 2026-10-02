# ruff: noqa: E501
"""개인 로컬 모드 설정(환경변수). 요청 시점에 읽으므로 재시작만으로 반영된다."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

KIS_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
_KIS_REAL_HOST = "openapi.koreainvestment.com"

ENABLED_ENV = "LOCAL_INTRADAY_ENABLED"
APP_KEY_ENV = "KIS_APP_KEY"
APP_SECRET_ENV = "KIS_APP_SECRET"
BASE_URL_ENV = "KIS_BASE_URL"
ALLOW_CUSTOM_BASE_ENV = "KIS_ALLOW_CUSTOM_BASE_URL"
ALLOWED_IPS_ENV = "LOCAL_INTRADAY_ALLOWED_IPS"
TOKEN_CACHE_ENV = "KIS_TOKEN_CACHE_PATH"
DEFAULT_ALLOWED_IPS = "127.0.0.1,::1"
DEFAULT_TOKEN_CACHE = ".local/kis_token.json"


class IntradayConfigError(RuntimeError):
    """설정이 잘못됐을 때(비밀값은 메시지에 싣지 않는다)."""


@dataclass(frozen=True)
class IntradaySettings:
    enabled: bool
    app_key: str | None
    app_secret: str | None
    base_url: str
    allowed_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    token_cache_path: Path

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret)


def _parse_networks(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError as exc:
            raise IntradayConfigError(f"{ALLOWED_IPS_ENV}에 IP/CIDR이 아닌 값이 있습니다.") from exc
    return tuple(nets)


def _resolve_base_url(env: dict[str, str]) -> str:
    raw = env.get(BASE_URL_ENV, "").strip() or KIS_REAL_BASE_URL
    parsed = urlparse(raw)
    allow_custom = env.get(ALLOW_CUSTOM_BASE_ENV, "").strip().lower() == "true"
    # 앱키가 엉뚱한 서버로 나가지 않도록(오설정·SSRF 방어) 기본은 실전 도메인만 허용한다.
    # 테스트용 모의 서버를 쓸 때만 KIS_ALLOW_CUSTOM_BASE_URL=true로 명시한다.
    if not allow_custom and not (parsed.scheme == "https" and parsed.hostname == _KIS_REAL_HOST):
        raise IntradayConfigError(
            f"{BASE_URL_ENV}는 한국투자증권 실전 도메인(https://{_KIS_REAL_HOST})만 허용됩니다."
        )
    return raw.rstrip("/")


def get_settings(env: dict[str, str] | None = None) -> IntradaySettings:
    source = dict(os.environ) if env is None else env
    enabled = source.get(ENABLED_ENV, "").strip().lower() == "true"
    return IntradaySettings(
        enabled=enabled,
        app_key=(source.get(APP_KEY_ENV) or "").strip() or None,
        app_secret=(source.get(APP_SECRET_ENV) or "").strip() or None,
        base_url=_resolve_base_url(source) if enabled else KIS_REAL_BASE_URL,
        allowed_networks=_parse_networks(source.get(ALLOWED_IPS_ENV, DEFAULT_ALLOWED_IPS)),
        token_cache_path=Path(source.get(TOKEN_CACHE_ENV, DEFAULT_TOKEN_CACHE)),
    )


def client_allowed(host: str | None, settings: IntradaySettings) -> bool:
    """요청 클라이언트 주소가 허용 목록에 있는지. 주소를 해석할 수 없으면 거부한다(fail closed)."""
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in settings.allowed_networks)


# 리버스 프록시·터널(Cloudflare Tunnel, ngrok, nginx 등)을 거친 요청은 TCP 상대 주소가 127.0.0.1로 보이므로 주소 검사만으로는
# 외부 요청을 구분할 수 없다. 이런 요청이 남기는 헤더가 있으면 개인 로컬 모드는 응답하지 않는다(fail closed).
PROXY_HEADERS = (
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "forwarded",
    "via",
    "cf-connecting-ip",
    "cf-ray",
    "true-client-ip",
    "x-original-forwarded-for",
)


def host_header_is_private(host_header: str | None) -> bool:
    """`Host` 헤더의 호스트가 localhost·사설/루프백 IP일 때만 True. 공개 도메인이면 False."""
    if not host_header:
        return False
    host = host_header.strip()
    if host.startswith("["):  # [::1]:4001
        host = host[1 : host.find("]")] if "]" in host else host
    elif host.count(":") == 1:  # name:port, 1.2.3.4:port
        host = host.split(":", 1)[0]
    if host.lower() == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private
