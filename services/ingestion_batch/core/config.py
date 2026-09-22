"""Ingestion Batch 환경설정 (REQ-011).

03-system-design.md §1-1 3차 방어(프로세스/배포 분리) 원칙에 따라, 이 서비스는
`batch_worker` DB 계정 접속 정보만 받는다(public_api의 `api_service`와 분리).

공공데이터포털 서비스키(`GOV_DATA_PORTAL_SERVICE_KEY`)는 실제 API 호출
시에만 필수다. `--dry-run`(네트워크 호출 없이 설정/로직만 점검) 경로에서는
없어도 되도록 `require_service_key` 플래그로 지연 검증한다 — 명시적 실패
원칙(조용한 기본값 대체 금지)은 유지하되, 키가 없는 개발 환경에서도 다른
경로(단위테스트, --dry-run)는 막지 않기 위함이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """필수 환경변수가 없을 때 명시적으로 발생시키는 예외(조용한 기본값 대체 금지)."""


# **2026-09-22 실측 확정(코디네이터 실 서비스키 발급 후 재검증)**: data.go.kr
# 마이페이지 "활용신청 상세기능정보"에 명시된 실제 오퍼레이션 경로는
# `getStockPriceInfo`가 아니라 `getStockPriceInfo_V2`이며, 서비스 자체도
# `GetStockSecuritiesInfoService_V2`다(구버전 `GetStockSecuritiesInfoService`는
# 이 프로젝트가 실 API 키 없이 문서 명세만으로 추정했던 옛 경로 — 웹상 다수의
# 예전 블로그/코드 예시가 여전히 구버전 경로를 쓰고 있어 혼동하기 쉬웠다).
# 실제 호출(`basDt=20240102, likeSrtnCd=005930`)로 `resultCode=00 NORMAL
# SERVICE`와 실제 삼성전자 시세(종가 79600원 등)를 확인해 이 URL이 맞다는
# 것을 검증했다. 환경변수로 언제든 재정의 가능하다.
DEFAULT_GOV_DATA_PORTAL_BASE_URL = (
    "https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2"
)


@dataclass(frozen=True)
class Settings:
    database_url: str
    gov_data_portal_base_url: str
    gov_data_portal_service_key: str | None
    dart_api_key: str | None = None
    request_timeout_seconds: float = 10.0
    max_retries: int = 3
    circuit_breaker_threshold: int = 3


def get_settings(
    *, require_service_key: bool, require_dart_key: bool = False
) -> Settings:
    database_url = os.environ.get("BATCH_DATABASE_URL")
    if not database_url:
        raise ConfigError(
            "환경변수 BATCH_DATABASE_URL이 설정되지 않았습니다. "
            "(raw_internal/public_serving 쓰기 권한이 있는 batch_worker 계정 접속 문자열 필요)"
        )

    service_key = os.environ.get("GOV_DATA_PORTAL_SERVICE_KEY")
    if require_service_key and not service_key:
        raise ConfigError(
            "환경변수 GOV_DATA_PORTAL_SERVICE_KEY가 설정되지 않았습니다. "
            "공공데이터포털에서 '금융위원회_주식시세정보' API 활용신청 후 발급받은 "
            "서비스키(디코딩 인증키)를 설정하세요."
        )

    dart_api_key = os.environ.get("DART_API_KEY")
    if require_dart_key and not dart_api_key:
        raise ConfigError(
            "환경변수 DART_API_KEY가 설정되지 않았습니다. "
            "opendart.fss.or.kr에서 발급받은 인증키(40자리)를 설정하세요."
        )

    base_url = os.environ.get("GOV_DATA_PORTAL_BASE_URL", DEFAULT_GOV_DATA_PORTAL_BASE_URL)

    return Settings(
        database_url=database_url,
        gov_data_portal_base_url=base_url,
        gov_data_portal_service_key=service_key,
        dart_api_key=dart_api_key,
    )
