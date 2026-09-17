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

  useEffect(() => {
    if (!isActive) return;

    const container = containerRef.current;
    if (!container) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;

    const getFocusable = (): HTMLElement[] =>
      Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));

    const focusable = getFocusable();
    (focusable[0] ?? container).focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onEscape();
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
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused.current?.focus();
    };
  }, [isActive, containerRef, onEscape]);
}
