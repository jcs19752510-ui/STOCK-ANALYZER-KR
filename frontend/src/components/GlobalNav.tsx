"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §1-0/§6 — 전역 내비게이션 3항목(홈/조건 스크리닝/종목 검색).
 * "About/이용안내"는 §1-0이 명시적으로 1차 내비게이션에서 제외했으므로(배너/
 * 푸터 링크로만 노출) 여기 추가하지 않는다.
 */
const NAV_ITEMS = [
  { href: "/", label: copy.nav.home },
  { href: "/screener", label: copy.nav.screener },
  { href: "/stocks", label: copy.nav.stocks },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * 데스크톱 상단 탭 / 모바일 하단 탭바(04-ux-design.md §4 `GlobalNav`, §6).
 * 동일한 DOM을 유지하고 CSS 미디어쿼리로 위치·배치만 전환한다 — 두 개의
 * 별도 내비게이션을 렌더링하면 스크린리더/탭 순서가 중복되므로 피한다.
 */
export function GlobalNav() {
  const pathname = usePathname();

  return (
    <nav className="global-nav" aria-label={copy.nav.ariaLabel}>
      <ul className="global-nav__list">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className="global-nav__item">
              <Link
                href={item.href}
                className="global-nav__link"
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
