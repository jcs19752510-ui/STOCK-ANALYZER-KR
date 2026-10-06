"use client";

import Link from "next/link";
import copy from "@/content/copy.ko.json";
import { useBrokerAccess } from "@/lib/psearch/react";

/**
 * 스크리닝 방식 전환의 세 번째 항목 "증권사 조건검색"(DEC-088). `ScreeningModeNav`(서버 컴포넌트) 안에 끼우는 작은 클라이언트 컴포넌트다.
 * 서버 렌더에서는 아무것도 그리지 않고, 브라우저에서 로컬 모드이고 `/api/v1/local/psearch/conditions`가 200일 때만 나타난다
 * (403·404·503이거나 운영 빌드면 항목도 요청도 없음 — 판단은 `useBrokerAccess`).
 */
export function BrokerModeNavItem({ current }: { current: boolean }) {
  const allowed = useBrokerAccess();
  if (!allowed) return null;
  return (
    <li className="screening-mode-nav__item">
      <Link
        href="/screener/broker"
        className="screening-mode-nav__link"
        aria-current={current ? "page" : undefined}
      >
        {copy.broker.label}
      </Link>
    </li>
  );
}
