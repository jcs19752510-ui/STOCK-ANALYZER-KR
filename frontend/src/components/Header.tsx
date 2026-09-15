import Link from "next/link";
import copy from "@/content/copy.ko.json";

/**
 * 최소 헤더(워드마크만). 전역 내비게이션(`GlobalNav`, 홈/조건 스크리닝/종목 검색
 * 탭)은 04-ux-design.md §4가 별도 컴포넌트로 정의하며 UNIT-05(반응형 UI 셸)
 * 책임 범위다 — 여기서는 REQ-007 배너와 레이아웃 구조를 검증할 최소 헤더만 둔다.
 */
export function Header() {
  return (
    <header className="site-header">
      <Link href="/" aria-label={copy.nav.homeLinkLabel} className="site-header__wordmark">
        국내주식 조건 스크리닝 정보 서비스
      </Link>
    </header>
  );
}
