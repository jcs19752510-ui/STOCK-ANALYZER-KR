"use client";

import { useEffect, useState } from "react";

/**
 * 04-ux-design.md §6 — `md`(≥768px)부터 결과 리스트가 `ResultsTable`(표)로
 * 전환되고, `lg`(≥1024px)부터 조건 필터 패널이 사이드 패널로 전환된다.
 * "표 시맨틱이 필요 없는 뷰에서는 애초에 `<table>`을 렌더링하지 않는다"(§6)
 * 원칙을 지키려면 서버가 아니라 실제 뷰포트 폭으로 분기해야 한다.
 *
 * 이 화면(`/screener`)은 사용자가 조건을 적용하기 전까지 결과를 전혀
 * 렌더링하지 않으므로(§1-2 Flow B 초기 상태), 이 훅이 초기 렌더에서
 * `false`를 반환했다가 마운트 후 실제 값으로 갱신되어도 하이드레이션
 * 불일치(hydration mismatch)를 일으키지 않는다 — 결과/패널 전환 대상
 * 컴포넌트는 항상 사용자 상호작용 이후에만 나타난다.
 */
export function useIsDesktopViewport(breakpointPx: number): boolean {
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia(`(min-width: ${breakpointPx}px)`);
    const update = () => setIsDesktop(mediaQuery.matches);
    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, [breakpointPx]);

  return isDesktop;
}
