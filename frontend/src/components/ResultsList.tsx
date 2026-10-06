import Link from "next/link";
import { LiveItemMarks } from "@/components/LiveItemMarks";
import { QuoteText } from "@/components/QuoteText";
import { formatMatchedMetric } from "@/lib/screenMetricFormat";
import type { ScreenResultItem, StockQuote } from "@/lib/types";

/**
 * 04-ux-design.md §4/§6 `ResultsList` — 모바일(< 768px, §6 `md` 미만) 카드
 * 리스트. 각 항목은 종목명/코드 상단 + 조건 지표 값들을 라벨-값 쌍으로
 * 세로 나열한다. `ResultsTable`과 동일 데이터를 사용하며, 표 시맨틱이
 * 필요 없는 이 뷰에서는 `<table>`을 아예 렌더링하지 않는다(§6).
 */
interface ResultsListProps {
  items: ScreenResultItem[];
  metricKeys: string[];
  /** 로컬 모드에서만 넘긴다: 카드에 현재가를 보인다. */
  quotes?: Record<string, StockQuote>;
  /** 장중 기준(DEC-089)일 때만 넘긴다: "신규"·"일봉" 표지를 그린다. */
  live?: { newCodes: ReadonlySet<string> };
}

export function ResultsList({ items, metricKeys, quotes, live }: ResultsListProps) {
  return (
    <ul className="results-list">
      {items.map((item) => (
        <li key={item.stock_code} className="results-list__item">
          <Link href={`/stocks/${item.stock_code}`} className="results-list__link">
            <div className="results-list__header">
              <span className="results-list__name">{item.name}</span>
              <span className="results-list__code">({item.stock_code})</span>
              <span className="market-badge">{item.market}</span>
              {live && <LiveItemMarks isNew={live.newCodes.has(item.stock_code)} isDaily={item.basis === "daily"} />}
            </div>
            {quotes && quotes[item.stock_code] && (
              <div className="results-list__quote">
                <QuoteText quote={quotes[item.stock_code]} />
              </div>
            )}
            <dl className="results-list__metrics">
              {metricKeys.map((key) => {
                const formatted = formatMatchedMetric(key, item.matched_metrics[key] ?? null);
                return (
                  <div key={key} className="results-list__metric-row">
                    <dt>{formatted.label}</dt>
                    <dd className={formatted.valueClassName}>
                      {formatted.srOnlyPrefix && (
                        <span className="sr-only">{formatted.srOnlyPrefix} </span>
                      )}
                      {formatted.text}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </Link>
        </li>
      ))}
    </ul>
  );
}
