import Link from "next/link";
import copy from "@/content/copy.ko.json";
import { GlobalNav } from "@/components/GlobalNav";

/**
 * 04-ux-design.md §2-0/§4 — 헤더: 서비스명 워드마크(홈 링크 겸용) +
 * 전역 내비게이션(`GlobalNav`). UNIT-04는 워드마크만 있는 최소 헤더를
 * 남겨뒀고(unit-04-note.md §2 편차 3), 이번 유닛(UNIT-05)이 `GlobalNav`를
 * 추가해 확장한다.
 */
export function Header() {
  return (
    <header className="site-header">
      <div className="site-header__bar">
        <Link href="/" aria-label={copy.nav.homeLinkLabel} className="site-header__wordmark">
          국내주식 조건 스크리닝 정보 서비스
        </Link>
        <GlobalNav />
      </div>
    </header>
  );
}
