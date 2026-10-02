import Link from "next/link";
import { ConditionStatusBadge } from "@/components/ConditionStatusBadge";
import { QuoteText } from "@/components/QuoteText";
import { PATTERN_CONDITION_IDS } from "@/lib/patternApi";
import { conditionTitle, evidenceText } from "@/lib/patternFormat";
import type { PatternDefinition, PatternItem, StockQuote } from "@/lib/types";

/**
 * 결과 카드 리스트(<1024px, 03-ux-design.md §2-2). 카드 1개 = 종목명·코드·시장 + 조건 6행 체크리스트
 * (`<dl>`): 각 행 `조건명 | 상태 배지 | 근거 문장`. 가로 페이지 스크롤을 만들지 않는다(320px 포함).
 */
interface PatternResultsListProps {
  items: PatternItem[];
  definition: PatternDefinition;
  quotes?: Record<string, StockQuote>;
}

export function PatternResultsList({
  items,
  definition,
  quotes = {},
}: PatternResultsListProps) {
  return (
    <ul className="results-list pattern-list">
      {items.map((item) => (
        <li key={item.stock_code} className="results-list__item">
          <div className="pattern-list__card">
            <div className="results-list__header">
              <Link href={`/stocks/${item.stock_code}`} className="pattern-list__link">
                <span className="results-list__name">{item.name}</span>{" "}
                <span className="results-list__code">({item.stock_code})</span>
              </Link>
              <span className="market-badge">{item.market}</span>
            </div>
            <QuoteText quote={quotes[item.stock_code]} />
            <dl className="pattern-list__conditions">
              {PATTERN_CONDITION_IDS.map((id) => (
                <div key={id} className="pattern-list__row">
                  <dt>{conditionTitle(id)}</dt>
                  <dd>
                    <ConditionStatusBadge result={item.conditions[id]} />
                    <span className="pattern-evidence">{evidenceText(id, item, definition)}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </li>
      ))}
    </ul>
  );
}
