import Link from "next/link";
import copy from "@/content/copy.ko.json";
import { GlobalNav } from "@/components/GlobalNav";
import { MemberMenu } from "@/components/MemberMenu";

/**
 * 04-ux-design.md §2-0/§4 — 상단 영역. 위에서부터 ① 전역 메뉴 줄(`GlobalNav`, 화면을 내려도 배너 아래에 붙어 따라옴) → ② 회원 메뉴 → ③ 서비스명 워드마크(홈 링크).
 * 사용자 지정 순서(2026-10-06, 화면 캡처의 1·2·3 표시). 메뉴 줄은 헤더 밖 형제 요소다 — sticky는 부모 요소 안에서만 붙어 있기 때문.
 * 데스크톱(≥1024px)은 ②와 ③이 한 줄에 놓이고 시각 순서만 제목(왼쪽) → 회원 메뉴(오른쪽)로 둔다(CSS `order`).
 */
export function Header() {
  return (
    <>
      <GlobalNav />
      <header className="site-header">
        <div className="site-header__bar">
          <MemberMenu />
          <Link href="/" aria-label={copy.nav.homeLinkLabel} className="site-header__wordmark">
            국내주식 조건 스크리닝 정보 서비스
          </Link>
        </div>
      </header>
    </>
  );
}
