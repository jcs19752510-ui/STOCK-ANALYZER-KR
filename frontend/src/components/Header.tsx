import Link from "next/link";
import copy from "@/content/copy.ko.json";
import { GlobalNav } from "@/components/GlobalNav";
import { MemberMenu } from "@/components/MemberMenu";

/**
 * 04-ux-design.md §2-0/§4 — 상단 영역. 위에서부터 ① 전역 메뉴 줄(`GlobalNav`, 화면을 내려도 배너 아래에 붙어 따라옴) → ② 회원 메뉴 → ③ 서비스명 워드마크(홈 링크).
 * 사용자 지정 순서(2026-10-06, 화면 캡처의 1·2·3 표시). 메뉴 줄은 헤더 밖 형제 요소다 — sticky는 부모 요소 안에서만 붙어 있기 때문.
 * 모든 폭(데스크톱 포함)에서 세 줄로 쌓는다(DEC-083). 문서 순서와 화면 순서가 같아 키보드 Tab 순서도 일치한다.
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
