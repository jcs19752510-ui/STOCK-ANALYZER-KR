import Link from "next/link";
import type { StockSearchItem } from "@/lib/types";

/**
 * 04-ux-design.md §2-3/§4 `StockListItem` — 종목명 + 코드 + 시장 뱃지.
 * `/stocks/[code]`(UNIT-06)로 이동하는 표준 `<Link>` 하나뿐이라 별도 포커스
 * 관리가 필요 없다(`unit-09-note.md` 접근성 사전 점검 참조). 시장 뱃지는
 * `/stocks/[code]` 상세 화면(`StockDetailPage`)이 이미 쓰는 `.market-badge`
 * 클래스를 그대로 재사용한다(새 뱃지 스타일을 만들지 않음).
 */
interface StockListItemProps {
  item: StockSearchItem;
}

export function StockListItem({ item }: StockListItemProps) {
  return (
    <li className="stock-list__item">
      <Link href={`/stocks/${item.stock_code}`} className="stock-list__link">
        <span className="stock-list__name">{item.name}</span>
        <span className="stock-list__code">{item.stock_code}</span>
        <span className="market-badge">{item.market}</span>
      </Link>
    </li>
  );
}
