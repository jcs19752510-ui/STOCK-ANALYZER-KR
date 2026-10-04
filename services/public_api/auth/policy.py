"""로그인 잠금 정책(사용자 승인 기본값, 설계서 §4·§9): 5회 연속 실패 → 15분 잠금, 반복할수록 2배(최대 24시간)."""

MAX_FAILED_ATTEMPTS = 5
LOCK_BASE_MINUTES = 15
LOCK_MAX_MINUTES = 24 * 60
# `lockout_level`이 이보다 커져도 2의 거듭제곱 계산이 커지지 않게 상한을 둔다(15분 × 2^7 = 1920분 > 24시간).
LOCK_LEVEL_CAP = 7

# ruff: noqa: E501
