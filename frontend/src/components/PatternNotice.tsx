import copy from "@/content/copy.ko.json";

/**
 * 패턴 스크리닝 비예측 고지(REQ-034, 03-ux-design.md §4). **상시 노출 — 닫기 버튼 없음.** 정상·로딩·빈·
 * 준비 중·오류 등 어떤 상태에서도 항상 렌더된다(면책 배너 `DisclaimerBanner`와는 별도 문구·스타일).
 * 별도 `InlineNotice` 컴포넌트는 없고 기존 CSS 클래스(`inline-notice--info`)를 직접 쓰는 것이 이 코드베이스의 관례다.
 */
export function PatternNotice() {
  return <p className="inline-notice inline-notice--info pattern-notice">{copy.pattern.notice}</p>;
}
