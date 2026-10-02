"""신규 종목 상세 엔드포인트 공통 입력 검증 (DEC-041, UNIT-24)."""

from __future__ import annotations

import re

from services.public_api.errors import ApiError

_STOCK_CODE = re.compile(r"^[0-9A-Za-z]{6}$")


def require_stock_code(code: str) -> str:
    """6자리 영숫자 종목코드만 DB 조회로 보낸다. 그 외는 입력을 되돌려 주지 않고 404로 답한다.

    잘못된 값(인젝션 시도·초장문 등)을 에러 메시지에 반사하지 않으며, DB 쿼리도 만들지 않는다.
    """
    if not _STOCK_CODE.fullmatch(code):
        raise ApiError(status_code=404, code="STOCK_NOT_FOUND", message="종목을 찾을 수 없습니다.")
    return code
