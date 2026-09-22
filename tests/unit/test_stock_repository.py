"""`SqlStockSearchRepository`의 LIKE 와일드카드 이스케이프 회귀 테스트 (DEF-006).

`_escape_like_pattern()`은 DB 세션이 필요 없는 순수 함수라 여기서 직접
검증한다. 실제 Postgres ILIKE로 "%"/"_" 입력 시 전체 종목이 매칭되지
않는지는 로컬 Docker DB로 별도 수동 검증했다(unit 테스트만으로는 ILIKE의
실제 이스케이프 해석까지 검증할 수 없음 — `escape=` 파라미터가 SQL로
올바르게 컴파일되는지는 DB 엔진의 책임).
"""

from __future__ import annotations

from services.public_api.db.stock_repository import _escape_like_pattern


def test_escape_like_pattern_percent():
    assert _escape_like_pattern("50%") == "50\\%"


def test_escape_like_pattern_underscore():
    assert _escape_like_pattern("_") == "\\_"


def test_escape_like_pattern_backslash_itself():
    assert _escape_like_pattern("a\\b") == "a\\\\b"


def test_escape_like_pattern_plain_text_unchanged():
    assert _escape_like_pattern("삼성전자") == "삼성전자"


def test_escape_like_pattern_mixed():
    assert _escape_like_pattern("50%_off\\") == "50\\%\\_off\\\\"
