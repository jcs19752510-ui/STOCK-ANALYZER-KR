"use client";

import { type RefObject, useEffect, useRef } from "react";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * 04-ux-design.md §5-3 — "모바일 바텀시트(조건 필터 패널)는 열렸을 때
 * 포커스 트랩(Tab이 시트 내부에서만 순환) 적용, `Esc` 키로 닫기, 닫을 때
 * 포커스를 시트를 연 트리거 버튼으로 복귀." UNIT-05가 `GlobalNav`에는
 * 적용 대상이 없다고 명시적으로 미뤄둔 요구사항(unit-05-note.md §2 편차1)을
 * 이 유닛(`ConditionFilterPanel`)이 이행한다.
 */
export function useFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
  isActive: boolean,
  onEscape: () => void
): void {
  const previouslyFocused = useRef<HTMLElement | null>(null);

  // 부모가 매 렌더마다 새 인라인 함수를 넘겨도(`ScreenerClient.tsx`처럼)
  // 트랩 effect 자체가 재실행되지 않도록, 최신 콜백은 ref로만 추적하고
  // effect 의존성 배열에는 넣지 않는다(DEF-U07-01 원인(b)).
  const onEscapeRef = useRef(onEscape);
  useEffect(() => {
    onEscapeRef.current = onEscape;
  }, [onEscape]);

  useEffect(() => {
    if (!isActive) return;

    const container = containerRef.current;
    if (!container) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;

    const getFocusable = (): HTMLElement[] =>
      Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));

    // 패널 표시는 `visibility: hidden -> visible` CSS 전환으로 구현되어
    // 있어(globals.css), 이 effect가 실행되는 시점에는 브라우저가 아직
    // 전환 후 스타일을 반영하지 않아 `visibility: hidden`인 채로 남아있다
    // (DEF-U07-01 원인(a), 헤드리스 Chromium 실측: class 변경 직후는 물론
    // 애니메이션 프레임 1회 뒤에도 `getComputedStyle().visibility`가 여전히
    // `hidden`이고, 2회째 프레임에서야 `visible`로 반영됨을 별도 최소 재현
    // 페이지로 확인함) — 이 상태에서 `.focus()`를 호출하면 조용히 무시된다.
    // 프레임을 두 번 넘겨(더블 rAF) 전환이 실제로 반영된 뒤 포커스를 이동시킨다.
    let rafId2 = 0;
    const rafId1 = requestAnimationFrame(() => {
      rafId2 = requestAnimationFrame(() => {
        const items = getFocusable();
        (items[0] ?? container).focus();
      });
    });

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onEscapeRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const items = getFocusable();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      cancelAnimationFrame(rafId1);
      cancelAnimationFrame(rafId2);
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused.current?.focus();
    };
  }, [isActive, containerRef]);
}
