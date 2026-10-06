"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import copy from "@/content/copy.ko.json";

/**
 * 머리글의 회원 메뉴(DEC-067): 이름 + (관리자만) "회원 관리" 링크 + 로그아웃. 로그인을 켠 빌드(`NEXT_PUBLIC_AUTH_ENABLED=true`)에서만 동작하며,
 * 쿠키를 서버(`/auth/me`)에 물어 이름을 받는다(쿠키는 JS가 읽을 수 없다). 로그인 전이면 아무것도 그리지 않는다.
 * 정적 화면이 많아 서버에서 쿠키를 읽지 않고 이렇게 브라우저에서 확인한다.
 */
const AUTH_BUILD = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

export function MemberMenu() {
  const [name, setName] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!AUTH_BUILD) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/auth/me", { credentials: "same-origin", cache: "no-store" });
        if (!response.ok) return;
        const body = (await response.json()) as { display_name?: unknown; role?: unknown };
        if (!cancelled && typeof body.display_name === "string") {
          setName(body.display_name);
          setIsAdmin(body.role === "admin"); // 화면 표시용. 관리자 화면·작업은 서버가 매번 다시 확인한다
        }
      } catch {
        /* 메뉴는 보조 기능이라 실패하면 그리지 않는다 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function logout() {
    try {
      await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      window.location.assign(new URL("/login", window.location.origin).toString()); // 전체 화면 이동(쿠키 삭제를 서버 화면에 바로 반영)
    }
  }

  async function logoutAll() {
    if (busy) return;
    if (!window.confirm(copy.auth.logoutAllConfirm)) return; // 실수로 누르는 것을 막는 확인
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch("/auth/logout-all", { method: "POST", credentials: "same-origin" });
      if (response.ok) {
        window.location.assign(new URL("/login", window.location.origin).toString());
        return; // 화면이 바뀌므로 잠금은 그대로 둔다
      }
      // 서버 취소가 확인되지 않으면 성공처럼 보이지 않게 하고 로그인은 그대로 둔다(다시 시도 가능)
      setNotice(response.status === 401 ? copy.auth.logoutAllInvalid : copy.auth.logoutAllFailed);
    } catch {
      setNotice(copy.auth.logoutAllFailed);
    }
    setBusy(false);
  }

  if (!AUTH_BUILD || name === null) return null;
  return (
    <div className="member-menu" role="group" aria-label={copy.auth.memberMenuLabel}>
      <span className="member-menu__name">
        {name}
        {copy.auth.memberSuffix}
      </span>
      {isAdmin ? (
        <Link href="/admin/members" className="member-menu__link">
          {copy.auth.adminLink}
        </Link>
      ) : null}
      <button type="button" className="member-menu__logout" onClick={logout}>
        {copy.auth.logout}
      </button>
      <button type="button" className="member-menu__logout member-menu__logout--all" onClick={logoutAll} disabled={busy}>
        {busy ? copy.auth.logoutAllBusy : copy.auth.logoutAll}
      </button>
      {notice ? (
        <p className="member-menu__notice" role="alert">
          {notice}
        </p>
      ) : null}
    </div>
  );
}
