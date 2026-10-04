"""회원 아이디·이름·비밀번호 규칙과 argon2id 해시 시험 (DEC-067, 설계서 §3·§5)."""

# ruff: noqa: E501
from __future__ import annotations

import statistics
import time

import pytest
from argon2 import PasswordHasher, Type

from shared.auth import passwords as pw

STRONG = "Tr0ub4dor&3-horse-staple"


# ------------------------------------------------------------------ 아이디
@pytest.mark.parametrize("raw,expected", [("kim", "kim"), (" Kim.Lee ", "kim.lee"), ("a1_-.b", "a1_-.b"), ("0abc", "0abc")])
def test_username_normalization_accepts_valid(raw, expected):
    assert pw.normalize_username(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "ab", "a" * 33, "_abc", "-abc", ".abc", "ab c", "kim!", "김철수", "ki\nm", "a@b.com", None])
def test_username_normalization_rejects_invalid(raw):
    with pytest.raises(pw.PolicyError):
        pw.normalize_username(raw)


def test_username_length_boundaries():
    assert pw.normalize_username("abc") == "abc"
    assert pw.normalize_username("a" * 32) == "a" * 32


# ------------------------------------------------------------------ 표시 이름
def test_display_name_valid_and_normalized():
    assert pw.normalize_display_name("  홍길동 ") == "홍길동"
    assert pw.normalize_display_name("가" * 40) == "가" * 40


@pytest.mark.parametrize("raw", ["", "   ", "가" * 41, "이름\x00", "이\n름", "a​b‮"])
def test_display_name_rejects_bad(raw):
    with pytest.raises(pw.PolicyError):
        pw.normalize_display_name(raw)


# ------------------------------------------------------------------ 비밀번호 정책
def test_strong_password_passes():
    assert pw.password_problems(STRONG, username="kim") == []
    assert pw.password_problems("가나다라마바사아자차카타파하", username="kim") == []


def test_length_boundaries():
    assert pw.password_problems("Zq8!Zq8!Zq8") != []  # 11자
    assert pw.password_problems("Zq8!Zq8!Zq8x") == []  # 12자
    assert pw.password_problems("Zq8!Xk2@" * 16) == []  # 128자
    assert any("128" in m for m in pw.password_problems("Zq8!Xk2@" * 16 + "x"))  # 129자


@pytest.mark.parametrize(
    "weak",
    [
        "aaaaaaaaaaaa", "abababababab", "123456789012", "abcdefghijkl", "zyxwvutsrqpo", "password1234", "Password1234!!", "PASSWORD!!!!!!!!",
        "passwordpassword", "qwertyuiop12", "1q2w3e4r5t6y", "administrator1", "welcome12345", "iloveyou1234", "비밀번호123456",
    ],
)
def test_weak_passwords_rejected(weak):
    assert pw.password_problems(weak, username="someone") != [], weak


def test_password_equal_to_username_rejected_case_insensitive():
    problems = pw.password_problems("Kim.Chulsoo.2026", username="kim.chulsoo.2026")
    assert any("아이디와 같" in m for m in problems)


def test_newline_and_nul_rejected():
    assert pw.password_problems("Zq8!Zq8!Zq8x\n") != []
    assert pw.password_problems("Zq8!Zq8!\x00Zq8x") != []


def test_policy_messages_never_contain_the_password():
    secret = "AbCdEfGhIjKl-unique"
    for message in pw.password_problems(secret[:5]) + pw.password_problems(secret, username=secret.lower()):
        assert secret not in message


def test_validate_password_raises_policy_error_with_messages():
    with pytest.raises(pw.PolicyError) as exc:
        pw.validate_password("short")
    assert exc.value.messages and "12자" in exc.value.messages[0]


# ------------------------------------------------------------------ 해시
def test_hash_is_argon2id_with_expected_parameters_and_unique_salt():
    h1, h2 = pw.hash_password(STRONG), pw.hash_password(STRONG)
    assert h1.startswith(f"$argon2id$v=19$m={pw.ARGON2_MEMORY_COST_KIB},t={pw.ARGON2_TIME_COST},p={pw.ARGON2_PARALLELISM}$")
    assert h1 != h2  # 솔트가 달라 같은 비밀번호도 해시가 다르다
    assert STRONG not in h1


def test_verify_password_success_and_failures():
    h = pw.hash_password(STRONG)
    assert pw.verify_password(h, STRONG) is True
    assert pw.verify_password(h, STRONG + "x") is False
    assert pw.verify_password(h, "") is False
    assert pw.verify_password("not-a-hash", STRONG) is False
    assert pw.verify_password("", STRONG) is False
    assert pw.verify_password("$argon2id$v=19$m=1,t=1,p=1$bad$bad", STRONG) is False


def test_oversized_input_is_rejected_without_hashing():
    h = pw.hash_password(STRONG)
    start = time.perf_counter()
    assert pw.verify_password(h, "x" * 100_000) is False
    assert time.perf_counter() - start < 0.05  # 해시 계산 없이 즉시 거부


def test_hash_password_enforces_policy():
    with pytest.raises(pw.PolicyError):
        pw.hash_password("password1234")
    with pytest.raises(pw.PolicyError):
        pw.hash_password("Kim.Chulsoo.2026", username="KIM.CHULSOO.2026")


def test_needs_rehash_detects_old_parameters():
    fresh = pw.hash_password(STRONG)
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID).hash(STRONG)
    assert pw.needs_rehash(fresh) is False
    assert pw.needs_rehash(old) is True
    assert pw.needs_rehash("garbage") is True


def test_dummy_verify_costs_about_as_much_as_a_real_verify():
    h = pw.hash_password(STRONG)
    pw.dummy_verify("warm-up")  # 더미 해시 만들기(첫 호출 비용 제외)

    def timed(fn):
        samples = []
        for _ in range(3):
            t = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - t)
        return statistics.median(samples)

    real = timed(lambda: pw.verify_password(h, "wrong-password-xyz"))
    dummy = timed(lambda: pw.dummy_verify("wrong-password-xyz"))
    assert dummy > real * 0.5, f"더미 비교가 너무 빠르다: real={real:.3f}s dummy={dummy:.3f}s"
