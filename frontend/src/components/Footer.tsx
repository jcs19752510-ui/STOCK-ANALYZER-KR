import copy from "@/content/copy.ko.json";
import { PRICE_EXPOSURE_ENABLED } from "@/lib/priceExposure";

/** REQ-007 이중 노출(배너+푸터) + REQ-008 데이터 가공/출처 고지(04-ux-design.md §2-0). */
export function Footer() {
  return (
    <footer className="site-footer">
      <p className="site-footer__disclaimer">{copy.disclaimer.footerFull}</p>
      <p>{copy.disclaimer.footerDataSource}</p>
      {/* 시세 원값 공개 스위치(DEC-048/050)와 문구를 맞춘다: 켜져 있으면 "원본 시세 비제공" 문구를 쓰지 않는다. */}
      <p>
        {PRICE_EXPOSURE_ENABLED ? copy.disclaimer.footerWithPrices : copy.disclaimer.footerNoRawData}
      </p>
      <a href="/about">{copy.disclaimer.footerAboutLinkText}</a>
    </footer>
  );
}
