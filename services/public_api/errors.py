"""API 에러 공통 처리 (03-system-design.md §4-1).

`error.code`가 있는 명시적 에러 응답을 강제하기 위한 예외 클래스.
FastAPI 기본 HTTPException은 `{"detail": ...}` 형태라 설계서의 envelope
(`{meta, data: null, error: {code, message}}`)과 다르므로 별도로 정의한다.
"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        # 선택 부가 정보(진행 상황 등, 비밀값 금지). 없으면 응답에 `details` 키를 넣지 않는다.
        self.details = details
