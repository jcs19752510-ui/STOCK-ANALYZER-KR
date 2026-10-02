import type { StockQuote } from "@/lib/types";

const nf = new Intl.NumberFormat("ko-KR");

/**
 * 목록 행의 시세 요약(종가 + ▲▼ 전일대비·등락률). 색에만 의존하지 않도록 ▲/▼ 기호와 스크린리더용
 * 텍스트를 함께 쓴다. 일 단위 종가 기준이며 실시간 시세가 아니다(기준일은 title로 제공).
 */
export function QuoteText({ quote }: { quote: StockQuote | undefined }) {
  if (!quote) return null;
  const { change, change_pct: pct } = quote;
  const dir = change === null || change === 0 ? "flat" : change > 0 ? "up" : "down";
  const label = dir === "up" ? "상승" : dir === "down" ? "하락" : "보합";
  return (
    <span className="quote-text" title={`${quote.trade_date} 종가 기준`}>
      <span className="quote-text__price">{nf.format(quote.close)}</span>
      {change !== null && pct !== null && (
        <span className={`quote-text__change quote-text__change--${dir}`}>
          <span className="sr-only">{label} </span>
          {dir === "up" ? "▲" : dir === "down" ? "▼" : ""}
          {nf.format(Math.abs(change))} ({Math.abs(pct).toFixed(2)}%)
        </span>
      )}
    </span>
  );
}
