import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "종목 검색 | 국내주식 조건 스크리닝 정보 서비스",
};

/**
 * 임시 자리표시자. 실제 검색 입력/결과 리스트(REQ-001, 04-ux-design.md
 * §2-3)는 UNIT-06 범위다. 이 유닛(UNIT-05)은 전역 내비게이션이 가리키는
 * 라우트가 404 없이 존재하도록만 만든다.
 */
export default function StocksPage() {
  return (
    <section>
      <h1>종목 검색</h1>
      <p>
        종목 검색 화면은 후속 작업 단위(UNIT-06)에서 구현됩니다. 이 페이지는
        전역 내비게이션 라우트가 정상 동작하는지 확인하기 위한 임시
        자리표시자입니다.
      </p>
    </section>
  );
}
