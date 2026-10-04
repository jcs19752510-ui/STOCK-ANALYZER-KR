"""회원 아이디·표시 이름·비밀번호 규칙과 argon2id 해시 (DEC-067, `docs/harness/login-feature-design.md` §3~§5).

- 비밀번호 원문은 어디에도 저장·기록하지 않는다. 해시는 argon2id(OWASP 권장 계열).
- 정책 기본값(사용자 승인): 최소 12자, 아이디와 동일 금지, 흔하고 약한 비밀번호 거부. 최대 128자(과도하게 긴 입력으로 서버를 느리게 하는 공격 방지).
- 존재하지 않는 아이디도 같은 시간이 걸리도록 더미 해시와 비교하는 `dummy_verify`를 제공한다(아이디 존재 여부 추측 방지).
"""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import re
import unicodedata

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# argon2id 매개변수. 메모리 46MiB·반복 3·병렬 1: OWASP 최소 권장(19MiB/2회)보다 높고 무료 호스팅(512MB)에서 동시 로그인이 드문 용도에 맞춘다.
# 값을 바꾸면 기존 해시는 `needs_rehash`로 감지되어 다음 로그인 때 새 값으로 갱신된다.
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 47104
ARGON2_PARALLELISM = 1

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
DISPLAY_NAME_MAX_LENGTH = 40
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


class PolicyError(ValueError):
    """입력이 규칙에 맞지 않을 때. `messages`는 사용자에게 그대로 보여 줄 수 있는 한국어 문구(비밀번호 원문 불포함)."""

    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


def normalize_username(raw: str) -> str:
    """앞뒤 공백 제거 + 소문자. 3~32자, 영문 소문자·숫자·`.`·`_`·`-`, 첫 글자는 영문·숫자."""
    value = (raw or "").strip().lower()
    if not USERNAME_PATTERN.fullmatch(value):
        raise PolicyError(["아이디는 3~32자의 영문 소문자·숫자·점(.)·밑줄(_)·하이픈(-)만 쓸 수 있고, 첫 글자는 영문 또는 숫자여야 합니다."])
    return value


def normalize_display_name(raw: str) -> str:
    value = unicodedata.normalize("NFC", (raw or "").strip())
    if not value or len(value) > DISPLAY_NAME_MAX_LENGTH:
        raise PolicyError([f"이름은 1~{DISPLAY_NAME_MAX_LENGTH}자여야 합니다."])
    if any(unicodedata.category(ch).startswith("C") for ch in value):
        raise PolicyError(["이름에 제어 문자를 쓸 수 없습니다."])
    return value


# 흔하고 약한 비밀번호의 뿌리 단어. 앞뒤의 숫자·기호를 떼고 이 단어이거나, 이 단어를 반복한 것이면 거부한다.
_WEAK_ROOTS = frozenset(
    """
    password passw0rd passwd pass1234 qwerty qwertyuiop asdfgh asdfghjkl zxcvbn zxcvbnm admin administrator root toor
    welcome letmein iloveyou monkey dragon master login secret changeme default guest test tester user username
    abc abcd abcdef abcdefgh samsung hyundai naver daum kakao korea seoul stock stocks screener 대한민국 비밀번호 사랑해
    """.split()
)
_COMMON_FULL = frozenset(
    """
    123456789012 1234567890123 12345678901234 111111111111 000000000000 qwertyuiop12 1q2w3e4r5t6y 1q2w3e4r5t6y7u
    q1w2e3r4t5y6 qazwsxedcrfv zaq12wsxcde3 password1234 password12345 passw0rd1234 iloveyou1234 welcome12345
    administrator1 administrator12 abcdefghijkl abcdefghijklm abcd12345678 asdfghjkl123 zxcvbnm12345
    """.split()
)


def _strip_non_letters(value: str) -> str:
    return re.sub(r"^[^a-z가-힣]+|[^a-z가-힣]+$", "", value)


def _is_repeated_root(value: str) -> bool:
    for root in _WEAK_ROOTS:
        if len(root) >= 4 and value and set(value) and value == (root * (len(value) // len(root) + 1))[: len(value)]:
            return True
    return False


def _is_sequence(value: str) -> bool:
    if len(value) < 6:
        return False
    steps = {ord(b) - ord(a) for a, b in zip(value, value[1:], strict=False)}
    return steps in ({1}, {-1})


def password_problems(password: str, *, username: str | None = None) -> list[str]:
    """규칙에 어긋나는 점의 목록(비어 있으면 통과). 비밀번호 원문은 결과에 넣지 않는다."""
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"비밀번호는 {PASSWORD_MIN_LENGTH}자 이상이어야 합니다.")
    if len(password) > PASSWORD_MAX_LENGTH:
        problems.append(f"비밀번호는 {PASSWORD_MAX_LENGTH}자 이하여야 합니다.")
    if any(ch in "\x00\r\n" for ch in password):
        problems.append("비밀번호에 줄바꿈·널 문자를 쓸 수 없습니다.")
    lowered = password.lower()
    if username and lowered == username.strip().lower():
        problems.append("비밀번호는 아이디와 같을 수 없습니다.")
    if len(set(lowered)) < 5:
        problems.append("서로 다른 글자가 5개 이상 들어가야 합니다.")
    elif lowered in _COMMON_FULL or _strip_non_letters(lowered) in _WEAK_ROOTS or _is_repeated_root(lowered):
        problems.append("너무 흔하거나 추측하기 쉬운 비밀번호입니다.")
    elif _is_sequence(lowered):
        problems.append("연속된 글자·숫자로만 이루어진 비밀번호는 쓸 수 없습니다.")
    return problems


def validate_password(password: str, *, username: str | None = None) -> None:
    problems = password_problems(password, username=username)
    if problems:
        raise PolicyError(problems)


def hash_password(password: str, *, username: str | None = None) -> str:
    """정책을 검사한 뒤 argon2id 해시 문자열을 돌려준다."""
    validate_password(password, username=username)
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """맞으면 True. 틀림·형식 오류·과도하게 긴 입력은 모두 False(예외를 밖으로 내보내지 않는다)."""
    if len(password) > PASSWORD_MAX_LENGTH * 4:  # 비정상적으로 긴 입력은 해시 계산 자체를 하지 않는다
        return False
    try:
        return bool(_hasher.verify(stored_hash, password))
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


_dummy_hash: str | None = None


def dummy_verify(password: str) -> None:
    """없는 아이디·비활성 계정에도 실제 계정과 같은 비용의 해시 계산을 한다(응답 시간으로 존재 여부를 알아내는 공격 방지)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("dummy-password-for-timing-equalisation")
    verify_password(_dummy_hash, password[: PASSWORD_MAX_LENGTH * 4])
