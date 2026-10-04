"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import copy from "@/content/copy.ko.json";

/**
 * 머리글의 회원 메뉴(DEC-067): 이름 + "회원 목록" 링크 + 로그아웃. 로그인을 켠 빌드(`NEXT_PUBLIC_AUTH_ENABLED=true`)에서만 동작하며,
 * 쿠키를 서버(`/auth/me`)에 물어 이름을 받는다(쿠키는 JS가 읽을 수 없다). 로그인 전이면 아무것도 그리지 않는다.
 * 정적 화면이 많아 서버에서 쿠키를 읽지 않고 이렇게 브라우저에서 확인한다.
 */
const AUTH_BUILD = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

export function MemberMenu() {
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    if (!AUTH_BUILD) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/auth/me", { credentials: "same-origin", cache: "no-store" });
        if (!response.ok) return;
        const body = (await response.json()) as { display_name?: unknown };
        if (!cancelled && typeof body.display_name === "string") setName(body.display_name);
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

  if (!AUTH_BUILD || name === null) return null;
  return (
    <div className="member-menu" role="group" aria-label={copy.auth.memberMenuLabel}>
      <span className="member-menu__name">
        {name}
        {copy.auth.memberSuffix}
      </span>
      <Link href="/members" className="member-menu__link">
        {copy.auth.membersLink}
      </Link>
      <button type="button" className="member-menu__logout" onClick={logout}>
        {copy.auth.logout}
      </button>
    </div>
  );
}
