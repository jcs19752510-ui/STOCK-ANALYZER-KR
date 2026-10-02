import Link from "next/link";
import copy from "@/content/copy.ko.json";
import { PATTERN_SCREEN_ENABLED } from "@/lib/patternFeature";

/**
 * 스크리닝 방식 전환 링크 2개(03-ux-design.md §1). ARIA `tablist`가 아니라 **페이지 이동 링크**다 —
 * 실제로 라우트가 바뀌므로 `<nav aria-label>` + 현재 항목 `aria-current="page"`를 쓴다.
 * 기능 스위치가 꺼져 있으면(`NEXT_PUBLIC_PATTERN_SCREEN_ENABLED="false"`) 아무것도 렌더하지 않는다.
 * 패턴 화면의 이름은 `copy.pattern.label` 한 곳에서만 가져온다(명칭 단일 출처).
 */
interface ScreeningModeNavProps {
  current: "manual" | "pattern";
}

export function ScreeningModeNav({ current }: ScreeningModeNavProps) {
  if (!PATTERN_SCREEN_ENABLED) return null;

  const items = [
    { key: "manual", href: "/screener", label: copy.pattern.modeManualLabel },
    { key: "pattern", href: "/screener/pattern", label: copy.pattern.label },
  ] as const;

  return (
    <nav className="screening-mode-nav" aria-label={copy.pattern.modeNavAriaLabel}>
      <ul className="screening-mode-nav__list">
        {items.map((item) => (
          <li key={item.key} className="screening-mode-nav__item">
            <Link
              href={item.href}
              className="screening-mode-nav__link"
              aria-current={item.key === current ? "page" : undefined}
            >
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
