"""로그인 검증 서비스 (DEC-067, 설계서 §4).

- 없는 아이디·비활성·잠긴 계정도 **실제 비밀번호 검증과 같은 비용**의 해시 계산(`dummy_verify`)을 하고, 호출자에게는 모두 같은 실패로 보인다
  (응답 문구·시간으로 아이디 존재 여부를 알아내지 못하게). 어떤 이유였는지는 로그인 기록(`auth.login_audit`)에만 남는다.
- 비밀번호 검증(느린 CPU 작업) 동안 DB 트랜잭션·행 잠금을 잡지 않는다. 실패 횟수 증가·잠금은 **한 문장의 원자적 UPDATE**로,
  성공 처리는 "그 사이 잠기지 않았고 활성일 때만" 조건을 붙여 실행한다(검증 중에 잠긴 계정이 맞는 비밀번호로 통과하는 경주 상태 차단).
- 비밀번호·해시는 로그·기록·예외 메시지에 넣지 않는다.
"""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.public_api.auth.policy import (
    LOCK_BASE_MINUTES,
    LOCK_LEVEL_CAP,
    LOCK_MAX_MINUTES,
    MAX_FAILED_ATTEMPTS,
    MAX_PENDING_SIGNUPS,
    ROLE_ADMIN,
    SESSION_SECONDS_DEFAULT,
    SESSION_SECONDS_REMEMBER,
)
from shared.auth.passwords import (
    PolicyError,
    dummy_verify,
    hash_password,
    hash_password_unchecked,
    needs_rehash,
    normalize_display_name,
    normalize_username,
    validate_password,
    verify_password,
)


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    username: str
    display_name: str
    role: str = "user"


@dataclass(frozen=True)
class AuthOutcome:
    ok: bool
    user: AuthUser | None = None
    # 실패 때의 상태: "invalid"(틀림·없음·잠김 등 구분 불가) / "pending"(가입 승인 대기) / "disabled"(사용 중지).
    # pending·disabled는 **비밀번호가 맞았을 때만** 알려 준다(계정 존재 여부를 비밀번호 없이는 알 수 없다).
    state: str = "invalid"


def mask_ip(raw: str | None) -> str | None:
    """기록용 접속 주소: IPv4는 마지막 옥텟, IPv6는 앞 3그룹만 남기고 가린다(개인정보 최소화, 설계서 §9-4)."""
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv4Address):
        a, b, c, _d = str(addr).split(".")
        return f"{a}.{b}.{c}.x"
    groups = addr.exploded.split(":")
    return ":".join(groups[:3]) + "::x"


def _printable_prefix(raw: str, limit: int = 64) -> str:
    return "".join(ch for ch in raw if ch.isprintable())[:limit]


def _audit(session: Session, *, user_id: str | None, attempted: str, result: str, ip: str | None) -> None:
    session.execute(
        text(
            "INSERT INTO auth.login_audit (user_id, username_attempted, result, client_ip) "
            "VALUES (:uid, :name, :result, :ip)"
        ),
        {"uid": user_id, "name": attempted, "result": result, "ip": mask_ip(ip)},
    )


def _record_and_fail(session: Session, *, user_id: str | None, attempted: str, result: str, ip: str | None) -> AuthOutcome:
    _audit(session, user_id=user_id, attempted=attempted, result=result, ip=ip)
    session.commit()
    return AuthOutcome(ok=False)


def authenticate(session: Session, raw_username: str, password: str, client_ip: str | None = None) -> AuthOutcome:
    try:
        username = normalize_username(raw_username)
    except PolicyError:
        username = None
    attempted = username or _printable_prefix(raw_username or "")

    row = None
    if username is not None:
        row = (
            session.execute(
                text(
                    "SELECT user_id::text AS user_id, username, display_name, password_hash, is_active, role, "
                    "(approved_at IS NULL) AS is_pending, "
                    "COALESCE(locked_until > now(), false) AS is_locked "
                    "FROM auth.app_users WHERE username = :u"
                ),
                {"u": username},
            )
            .mappings()
            .first()
        )
    session.rollback()  # 읽기 전용 조회 트랜잭션을 끝낸다(검증 동안 열어 두지 않는다)

    if row is None:
        dummy_verify(password)
        return _record_and_fail(session, user_id=None, attempted=attempted, result="FAIL", ip=client_ip)
    if row["is_locked"]:
        dummy_verify(password)
        return _record_and_fail(session, user_id=row["user_id"], attempted=attempted, result="LOCKED", ip=client_ip)

    if not verify_password(row["password_hash"], password):
        session.execute(
            text(
                "UPDATE auth.app_users SET "
                " locked_until = CASE WHEN failed_attempts + 1 >= :max_failed "
                "   THEN now() + LEAST(:base * (2 ^ LEAST(lockout_level, :cap)), :max_minutes) * interval '1 minute' "
                "   ELSE locked_until END, "
                " lockout_level = CASE WHEN failed_attempts + 1 >= :max_failed THEN lockout_level + 1 ELSE lockout_level END, "
                " failed_attempts = CASE WHEN failed_attempts + 1 >= :max_failed THEN 0 ELSE failed_attempts + 1 END, "
                " updated_at = now() "
                "WHERE user_id = CAST(:uid AS uuid)"
            ),
            {
                "uid": row["user_id"],
                "max_failed": MAX_FAILED_ATTEMPTS,
                "base": LOCK_BASE_MINUTES,
                "cap": LOCK_LEVEL_CAP,
                "max_minutes": LOCK_MAX_MINUTES,
            },
        )
        return _record_and_fail(session, user_id=row["user_id"], attempted=attempted, result="FAIL", ip=client_ip)

    if not row["is_active"]:
        # 비밀번호는 맞지만 로그인할 수 없는 계정: 승인 대기 / 사용 중지. 비밀번호를 아는 본인에게만 이유를 알려 준다.
        state = "pending" if row["is_pending"] else "disabled"
        _audit(session, user_id=row["user_id"], attempted=attempted, result="PENDING" if state == "pending" else "INACTIVE", ip=client_ip)
        session.commit()
        return AuthOutcome(ok=False, state=state)

    new_hash = hash_password_unchecked(password) if needs_rehash(row["password_hash"]) else None
    updated = session.execute(
        text(
            "UPDATE auth.app_users SET failed_attempts = 0, lockout_level = 0, locked_until = NULL, "
            " last_login_at = now(), updated_at = now(), password_hash = COALESCE(:new_hash, password_hash) "
            "WHERE user_id = CAST(:uid AS uuid) AND is_active AND (locked_until IS NULL OR locked_until <= now()) "
            "RETURNING user_id"
        ),
        {"uid": row["user_id"], "new_hash": new_hash},
    ).first()
    if updated is None:  # 검증하는 동안 잠기거나 비활성화됨
        session.rollback()
        return _record_and_fail(session, user_id=row["user_id"], attempted=attempted, result="LOCKED", ip=client_ip)
    _audit(session, user_id=row["user_id"], attempted=attempted, result="SUCCESS", ip=client_ip)
    session.commit()
    return AuthOutcome(
        ok=True,
        user=AuthUser(user_id=row["user_id"], username=row["username"], display_name=row["display_name"], role=row["role"]),
    )


def create_session(session: Session, user_id: str, remember: bool) -> tuple[str, int]:
    """로그인 성공 직후 서버 쪽 세션을 만든다(DEC-070). (session_id, 절대 수명 초)를 돌려준다. 수명은 서버가 정한다(요청 값 아님)."""
    seconds = SESSION_SECONDS_REMEMBER if remember else SESSION_SECONDS_DEFAULT
    row = session.execute(
        text(
            "INSERT INTO auth.user_sessions (user_id, remember, expires_at) "
            "VALUES (CAST(:uid AS uuid), :rm, now() + :sec * interval '1 second') RETURNING session_id::text"
        ),
        {"uid": user_id, "rm": remember, "sec": seconds},
    ).one()
    session.commit()
    return row[0], seconds


def check_session_user(session: Session, user_id: str, session_id: str) -> AuthUser | None:
    """로그인 후에도 이 세션이 유효하고 회원이 활성인지 확인한다(5분마다 호출).
    세션이 이 회원 것이고, 취소·만료되지 않았고, 회원이 활성일 때만 정보를 돌려준다. 이유는 구분하지 않는다."""
    row = (
        session.execute(
            text(
                "SELECT u.user_id::text AS user_id, u.username, u.display_name, u.role "
                "FROM auth.user_sessions s JOIN auth.app_users u ON u.user_id = s.user_id "
                "WHERE s.session_id = CAST(:sid AS uuid) AND s.user_id = CAST(:uid AS uuid) "
                "AND s.revoked_at IS NULL AND s.expires_at > now() AND u.is_active"
            ),
            {"uid": user_id, "sid": session_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        session.rollback()
        return None
    session.execute(
        text("UPDATE auth.user_sessions SET last_check_at = now() WHERE session_id = CAST(:sid AS uuid)"),
        {"sid": session_id},
    )
    session.commit()
    return AuthUser(**row)


def revoke_session(session: Session, user_id: str, session_id: str) -> bool:
    """로그아웃: 이 세션 하나를 취소한다(다른 기기의 세션은 그대로). 이미 취소됐거나 남의 세션·없는 세션이면 False."""
    done = session.execute(
        text(
            "UPDATE auth.user_sessions SET revoked_at = now() "
            "WHERE session_id = CAST(:sid AS uuid) AND user_id = CAST(:uid AS uuid) AND revoked_at IS NULL "
            "RETURNING session_id"
        ),
        {"uid": user_id, "sid": session_id},
    ).first()
    session.commit()
    return done is not None


def revoke_all_sessions(session: Session, user_id: str, session_id: str) -> int | None:
    """"모든 기기에서 로그아웃"(DEC-071): 이 회원의 유효한 세션을 전부 취소하고 취소한 건수를 돌려준다.
    요청한 세션 자체가 이 회원의 살아 있는 세션일 때만 실행한다(이미 취소·만료된 쿠키로는 못 한다). 아니면 None."""
    live = session.execute(
        text(
            "SELECT 1 FROM auth.user_sessions s JOIN auth.app_users u ON u.user_id = s.user_id "
            "WHERE s.session_id = CAST(:sid AS uuid) AND s.user_id = CAST(:uid AS uuid) "
            "AND s.revoked_at IS NULL AND s.expires_at > now() AND u.is_active"
        ),
        {"uid": user_id, "sid": session_id},
    ).first()
    if live is None:
        session.rollback()
        return None
    result = session.execute(
        text("UPDATE auth.user_sessions SET revoked_at = now() WHERE user_id = CAST(:uid AS uuid) AND revoked_at IS NULL"),
        {"uid": user_id},
    )
    session.commit()
    return result.rowcount or 0


class SignupError(Exception):
    """가입 신청 거절 사유. `code`는 API 오류 코드, `status`는 HTTP 상태."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def signup(session: Session, raw_username: str, raw_display_name: str, password: str) -> str:
    """회원가입 신청(DEC-074): **승인 대기** 계정을 만든다. 로그인은 관리자가 승인한 뒤에만 가능하다.
    권한(role)·활성·승인 여부는 정할 수 없다(DB 열 권한으로도 막혀 있다: 아이디·이름·비밀번호 해시만 INSERT). 아이디를 돌려준다."""
    try:
        username = normalize_username(raw_username)
        display_name = normalize_display_name(raw_display_name)
        validate_password(password, username=username)
    except PolicyError as exc:
        raise SignupError(400, "INVALID_INPUT", " ".join(exc.messages)) from exc
    pending = session.execute(text("SELECT count(*) FROM auth.app_users WHERE approved_at IS NULL")).scalar_one()
    session.rollback()
    if pending >= MAX_PENDING_SIGNUPS:
        raise SignupError(503, "SIGNUP_CLOSED", "지금은 가입 신청을 받을 수 없습니다. 잠시 후 다시 시도해 주세요.")
    password_hash = hash_password(password, username=username)  # 느린 계산: 트랜잭션 밖에서
    created = session.execute(
        text(
            "INSERT INTO auth.app_users (username, display_name, password_hash) VALUES (:u, :d, :h) "
            "ON CONFLICT (username) DO NOTHING RETURNING user_id"
        ),
        {"u": username, "d": display_name, "h": password_hash},
    ).first()
    session.commit()
    if created is None:
        raise SignupError(409, "USERNAME_TAKEN", "이미 사용 중인 아이디입니다.")
    return username


def require_admin(session: Session, user_id: str, session_id: str) -> AuthUser | None:
    """관리자 작업을 요청한 사람이 **지금 이 순간** 유효한 세션을 가진 활성 관리자인지 DB에서 확인한다
    (웹 서버가 전달한 값이나 쿠키 속 권한을 믿지 않는다). 아니면 None."""
    user = check_session_user(session, user_id, session_id)
    return user if user is not None and user.role == ROLE_ADMIN else None
