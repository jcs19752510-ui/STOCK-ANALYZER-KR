import copy from "@/content/copy.ko.json";

/** 04-ux-design.md §2-0/§5-3 — 키보드 포커스 시에만 노출되는 본문 바로가기 링크. */
export function SkipLink() {
  return (
    <a href="#main-content" className="skip-link">
      {copy.nav.skipLink}
    </a>
  );
}
