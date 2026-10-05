"""관리자 회원 관리 (DEC-074): 목록·승인·거절·추가·수정·삭제·권한 변경·비밀번호 초기화·세션 취소.

- 호출자가 관리자인지는 이 모듈이 아니라 API 입구(`require_admin`)가 **매 호출마다 DB에서** 확인한다. 여기서는 이미 확인된 `actor`를 받는다.
- 모든 변경은 한 트랜잭션에서 대상 행을 잠그고(`FOR UPDATE`) 처리하며, 관리자 수가 줄어드는 작업은 전체 잠금(advisory lock) 아래에서 한다
  (두 관리자가 동시에 서로를 비활성화해 관리자가 0명이 되는 경주 상태 방지).
- 규칙: 자기 자신은 비활성화·삭제·강등할 수 없다(잠금 방지). 마지막 활성 관리자는 어떤 경로로도 없앨 수 없다.
- 모든 변경은 `auth.admin_audit`에 남긴다(비밀번호·해시는 기록하지 않는다).
"""

# ruff: noqa: E501  (한글 설명 주석·문구가 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.public_api.auth.policy import ROLE_ADMIN, ROLE_USER, ROLES
from services.public_api.auth.service import AuthUser
from shared.auth.passwords import (
    PolicyError,
    hash_password,
    normalize_display_name,
    normalize_username,
)

ADMIN_LOCK_KEY = 74_001  # advisory lock 번호(관리자 수가 줄어들 수 있는 작업의 직렬화)

ACTIONS = (
    "create",
    "approve",
    "reject",
    "enable",
    "disable",
    "set_role",
    "rename",
    "reset_password",
    "revoke_sessions",
    "delete",
)


class AdminError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class MemberRow:
    username: str
    display_name: str
    role: str
    status: str  # pending(승인 대기) / active / disabled
    created_at: str
    last_login_at: str | None
    locked: bool
    active_sessions: int


def list_members(session: Session, limit: int = 1000) -> list[MemberRow]:
    rows = (
        session.execute(
            text(
                "SELECT u.username, u.display_name, u.role, "
                " CASE WHEN u.approved_at IS NULL THEN 'pending' WHEN u.is_active THEN 'active' ELSE 'disabled' END AS status, "
                " u.created_at, u.last_login_at, COALESCE(u.locked_until > now(), false) AS locked, "
                " (SELECT count(*) FROM auth.user_sessions s WHERE s.user_id = u.user_id AND s.revoked_at IS NULL AND s.expires_at > now()) AS sessions "
                "FROM auth.app_users u "
                "ORDER BY (u.approved_at IS NULL) DESC, u.role = 'admin' DESC, u.created_at, u.username LIMIT :n"
            ),
            {"n": limit},
        )
        .mappings()
        .all()
    )
    session.rollback()
    return [
        MemberRow(
            username=r["username"],
            display_name=r["display_name"],
            role=r["role"],
            status=r["status"],
            created_at=r["created_at"].isoformat(),
            last_login_at=r["last_login_at"].isoformat() if r["last_login_at"] else None,
            locked=bool(r["locked"]),
            active_sessions=int(r["sessions"]),
        )
        for r in rows
    ]


def _audit(session: Session, actor: AuthUser, action: str, target: str | None, detail: str | None = None) -> None:
    session.execute(
        text(
            "INSERT INTO auth.admin_audit (actor_user_id, actor_username, action, target_username, detail) "
            "VALUES (CAST(:a AS uuid), :an, :act, :t, :d)"
        ),
        {"a": actor.user_id, "an": actor.username, "act": action, "t": target, "d": detail},
    )


def _revoke_all(session: Session, user_id: str) -> int:
    return session.execute(
        text("UPDATE auth.user_sessions SET revoked_at = now() WHERE user_id = CAST(:u AS uuid) AND revoked_at IS NULL"),
        {"u": user_id},
    ).rowcount or 0


def _lock_target(session: Session, username: str) -> dict:
    row = (
        session.execute(
            text(
                "SELECT user_id::text AS user_id, username, role, is_active, (approved_at IS NULL) AS is_pending "
                "FROM auth.app_users WHERE username = :u FOR UPDATE"
            ),
            {"u": username},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AdminError(404, "MEMBER_NOT_FOUND", "회원을 찾을 수 없습니다.")
    return dict(row)


def _other_active_admins(session: Session, target_user_id: str) -> int:
    return session.execute(
        text(
            "SELECT count(*) FROM auth.app_users WHERE role = 'admin' AND is_active AND user_id <> CAST(:t AS uuid)"
        ),
        {"t": target_user_id},
    ).scalar_one()


def _guard_admin_loss(session: Session, actor: AuthUser, target: dict, what: str) -> None:
    """대상이 활성 관리자이고 이 작업으로 관리자 자격을 잃을 때: 본인 불가, 마지막 활성 관리자 불가."""
    if target["user_id"] == actor.user_id:
        raise AdminError(409, "SELF_PROTECTED", f"본인 계정은 {what}할 수 없습니다. 다른 관리자에게 요청하세요.")
    if target["role"] == ROLE_ADMIN and target["is_active"] and _other_active_admins(session, target["user_id"]) < 1:
        raise AdminError(409, "LAST_ADMIN", "마지막 활성 관리자는 변경할 수 없습니다.")


def perform(
    session: Session,
    actor: AuthUser,
    action: str,
    username: str,
    *,
    role: str | None = None,
    display_name: str | None = None,
    password: str | None = None,
) -> str:
    """관리 작업 하나를 실행하고 결과 요약(문구 코드)을 돌려준다. 실패는 `AdminError`/`PolicyError`."""
    if action not in ACTIONS:
        raise AdminError(400, "INVALID_ACTION", "알 수 없는 작업입니다.")
    try:
        name = normalize_username(username)
    except PolicyError as exc:
        raise AdminError(400, "INVALID_INPUT", " ".join(exc.messages)) from exc

    try:
        # 느린 해시 계산은 잠금을 잡기 전에 끝낸다.
        new_hash = None
        if action in ("create", "reset_password"):
            if password is None:
                raise AdminError(400, "INVALID_INPUT", "비밀번호를 입력해 주세요.")
            try:
                new_hash = hash_password(password, username=name)
            except PolicyError as exc:
                raise AdminError(400, "INVALID_INPUT", " ".join(exc.messages)) from exc
        if action in ("create", "set_role") and role not in ROLES:
            raise AdminError(400, "INVALID_INPUT", "권한은 일반 사용자 또는 관리자 중에서 선택해 주세요.")
        clean_display = None
        if action in ("create", "rename"):
            try:
                clean_display = normalize_display_name(display_name or "")
            except PolicyError as exc:
                raise AdminError(400, "INVALID_INPUT", " ".join(exc.messages)) from exc

        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADMIN_LOCK_KEY})

        if action == "create":
            created = session.execute(
                text(
                    "INSERT INTO auth.app_users (username, display_name, password_hash) VALUES (:u, :d, :h) "
                    "ON CONFLICT (username) DO NOTHING RETURNING user_id::text"
                ),
                {"u": name, "d": clean_display, "h": new_hash},
            ).first()
            if created is None:
                raise AdminError(409, "USERNAME_TAKEN", "이미 사용 중인 아이디입니다.")
            session.execute(
                text("UPDATE auth.app_users SET role = :r, is_active = true, approved_at = now(), updated_at = now() WHERE username = :u"),
                {"r": role, "u": name},
            )
            _audit(session, actor, "create", name, f"role={role}")
            session.commit()
            return "created"

        target = _lock_target(session, name)
        uid = target["user_id"]

        if action == "approve":
            if not target["is_pending"]:
                raise AdminError(409, "NOT_PENDING", "승인 대기 중인 신청이 아닙니다.")
            session.execute(
                text("UPDATE auth.app_users SET is_active = true, approved_at = now(), updated_at = now() WHERE user_id = CAST(:u AS uuid)"),
                {"u": uid},
            )
            _audit(session, actor, "approve", name)
            result = "approved"
        elif action == "reject":
            if not target["is_pending"]:
                raise AdminError(409, "NOT_PENDING", "승인 대기 중인 신청이 아닙니다. 승인된 회원은 삭제를 사용하세요.")
            session.execute(text("DELETE FROM auth.app_users WHERE user_id = CAST(:u AS uuid)"), {"u": uid})
            _audit(session, actor, "reject", name)
            result = "rejected"
        elif action == "enable":
            if target["is_pending"]:
                raise AdminError(409, "PENDING", "승인 대기 중인 신청입니다. 먼저 승인하세요.")
            session.execute(
                text(
                    "UPDATE auth.app_users SET is_active = true, updated_at = now() WHERE user_id = CAST(:u AS uuid)"
                ),
                {"u": uid},
            )
            _audit(session, actor, "enable", name)
            result = "enabled"
        elif action == "disable":
            if target["is_pending"]:
                raise AdminError(409, "PENDING", "승인 대기 중인 신청입니다. 거절을 사용하세요.")
            _guard_admin_loss(session, actor, target, "비활성화")
            session.execute(
                text("UPDATE auth.app_users SET is_active = false, updated_at = now() WHERE user_id = CAST(:u AS uuid)"),
                {"u": uid},
            )
            _revoke_all(session, uid)
            _audit(session, actor, "disable", name)
            result = "disabled"
        elif action == "set_role":
            if target["is_pending"]:
                raise AdminError(409, "PENDING", "승인 대기 중인 신청입니다. 먼저 승인하세요.")
            if role == target["role"]:
                raise AdminError(409, "NO_CHANGE", "이미 같은 권한입니다.")
            if role == ROLE_USER:
                _guard_admin_loss(session, actor, target, "강등")
            session.execute(
                text("UPDATE auth.app_users SET role = :r, updated_at = now() WHERE user_id = CAST(:u AS uuid)"),
                {"r": role, "u": uid},
            )
            _audit(session, actor, "set_role", name, f"{target['role']}->{role}")
            result = "role_changed"
        elif action == "rename":
            session.execute(
                text("UPDATE auth.app_users SET display_name = :d, updated_at = now() WHERE user_id = CAST(:u AS uuid)"),
                {"d": clean_display, "u": uid},
            )
            _audit(session, actor, "rename", name)
            result = "renamed"
        elif action == "reset_password":
            session.execute(
                text(
                    "UPDATE auth.app_users SET password_hash = :h, failed_attempts = 0, lockout_level = 0, locked_until = NULL, "
                    "updated_at = now() WHERE user_id = CAST(:u AS uuid)"
                ),
                {"h": new_hash, "u": uid},
            )
            _revoke_all(session, uid)  # 비밀번호를 바꾸면 기존 로그인은 모두 끊는다
            _audit(session, actor, "reset_password", name)
            result = "password_reset"
        elif action == "revoke_sessions":
            count = _revoke_all(session, uid)
            _audit(session, actor, "revoke_sessions", name, f"count={count}")
            result = "sessions_revoked"
        else:  # delete
            if target["is_pending"]:
                raise AdminError(409, "PENDING", "승인 대기 중인 신청입니다. 거절을 사용하세요.")
            _guard_admin_loss(session, actor, target, "삭제")
            session.execute(text("DELETE FROM auth.app_users WHERE user_id = CAST(:u AS uuid)"), {"u": uid})
            _audit(session, actor, "delete", name)
            result = "deleted"
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
