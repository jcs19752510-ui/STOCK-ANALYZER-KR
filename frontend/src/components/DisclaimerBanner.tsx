import copy from "@/content/copy.ko.json";

/**
 * REQ-007 — 투자자문 아님 면책 문구 상시 노출(04-ux-design.md §2-0).
 * 닫기 버튼 없음, 말줄임 없음, API 응답을 기다리지 않고 즉시 렌더된다
 * (로컬 카피 리소스만으로 렌더되는 서버 컴포넌트 — 로딩/에러 상태 자체가 없음).
 */
export function DisclaimerBanner() {
  return (
    <div className="disclaimer-banner" role="note" aria-label="투자자문 아님 고지">
      <p className="disclaimer-banner__text">
        {copy.disclaimer.banner}{" "}
        <a href="/about" className="disclaimer-banner__link">
          {copy.disclaimer.bannerMoreLinkText}
        </a>
      </p>
    </div>
  );
}
