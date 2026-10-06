import Link from "next/link";
import copy from "@/content/copy.ko.json";
import { GlobalNav } from "@/components/GlobalNav";
import { MemberMenu } from "@/components/MemberMenu";

/**
 * 04-ux-design.md §2-0/§4 — 헤더: 서비스명 워드마크(홈 링크 겸용) + 회원 메뉴.
 * 전역 내비게이션(`GlobalNav`)은 헤더 **바로 아래의 형제 요소**다 — 헤더 안에 두면 화면을 내려도 따라오는(sticky) 줄을 만들 수 없다
 * (sticky는 부모 요소 안에서만 붙어 있다). 2026-10-06: 모바일 하단 탭바를 상단 고정 메뉴 줄로 바꾸면서 분리.
 */
export function Header() {
  return (
    <>
      <header className="site-header">
        <div className="site-header__bar">
          <Link href="/" aria-label={copy.nav.homeLinkLabel} className="site-header__wordmark">
            국내주식 조건 스크리닝 정보 서비스
          </Link>
          <MemberMenu />
        </div>
      </header>
      <GlobalNav />
    </>
  );
}
