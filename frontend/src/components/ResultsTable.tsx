import Link from "next/link";
import { QuoteText } from "@/components/QuoteText";
import { formatMatchedMetric } from "@/lib/screenMetricFormat";
import type { ScreenResultItem, StockQuote } from "@/lib/types";

/**
 * 04-ux-design.md §4/§6 `ResultsTable` — 태블릿 이상(§6 `md`, ≥768px) 가로
 * 표. §5-7: "결과 표는 `<table>` + `<caption>`(시각적으로 숨겨도 됨) +
 * `<th scope="col">` 사용(순수 `<div>` 그리드로 표를 흉내내지 않음)".
 */
interface ResultsTableProps {
  items: ScreenResultItem[];
  metricKeys: string[];
  captionText: string;
  /** 로컬 모드에서만 넘긴다: "현재가" 열을 추가한다(조건 판정은 일봉 기준 그대로). */
  quotes?: Record<string, StockQuote>;
}

export function ResultsTable({ items, metricKeys, captionText, quotes }: ResultsTableProps) {
  const columnLabels = metricKeys.map((key) => ({
    key,
    label: formatMatchedMetric(key, null).label,
  }));

  return (
    <table className="results-table">
      <caption className="sr-only">{captionText}</caption>
      <thead>
        <tr>
          <th scope="col">종목명</th>
          <th scope="col">시장</th>
          {quotes && <th scope="col">현재가</th>}
          {columnLabels.map((column) => (
            <th scope="col" key={column.key}>
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.stock_code}>
            <th scope="row">
              <Link href={`/stocks/${item.stock_code}`} className="results-table__link">
                {item.name} <span className="results-table__code">({item.stock_code})</span>
              </Link>
            </th>
            <td>
              <span className="market-badge">{item.market}</span>
            </td>
            {quotes && (
              <td>
                {quotes[item.stock_code] ? (
                  <QuoteText quote={quotes[item.stock_code]} />
                ) : (
                  <span aria-label="시세 없음">-</span>
                )}
              </td>
            )}
            {metricKeys.map((key) => {
              const formatted = formatMatchedMetric(key, item.matched_metrics[key] ?? null);
              return (
                <td key={key} className={formatted.valueClassName}>
                  {formatted.srOnlyPrefix && (
                    <span className="sr-only">{formatted.srOnlyPrefix} </span>
                  )}
                  {formatted.text}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
