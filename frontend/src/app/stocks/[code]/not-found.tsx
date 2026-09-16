import Link from "next/link";
import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §2-4 "404 STOCK_NOT_FOUND: 전체 화면 에러 상태 +
 * '종목 검색으로 돌아가기' CTA". `notFound()`가 호출되면 Next.js가 이
 * 라우트 세그먼트 전용 파일을 렌더링한다(라우트 그룹 내에서만 적용되고
 * 루트 레이아웃의 배너/헤더/푸터는 그대로 유지된다).
 */
export default function StockNotFound() {
  return (
    <section>
      <h1>{copy.stockDetail.notFoundHeading}</h1>
      <Link href="/stocks">{copy.stockDetail.backToSearchCta}</Link>
    </section>
  );
}
