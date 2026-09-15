import copy from "@/content/copy.ko.json";

/** REQ-007 이중 노출(배너+푸터) + REQ-008 데이터 가공/출처 고지(04-ux-design.md §2-0). */
export function Footer() {
  return (
    <footer className="site-footer">
      <p className="site-footer__disclaimer">{copy.disclaimer.footerFull}</p>
      <p>{copy.disclaimer.footerDataSource}</p>
      <p>{copy.disclaimer.footerNoRawData}</p>
      <a href="/about">{copy.disclaimer.footerAboutLinkText}</a>
    </footer>
  );
}
