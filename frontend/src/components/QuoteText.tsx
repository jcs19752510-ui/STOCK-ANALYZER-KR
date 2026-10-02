import { MiniCandle } from "@/components/MiniCandle";
import type { StockQuote } from "@/lib/types";

const nf = new Intl.NumberFormat("ko-KR");

/**
 * 목록 행의 시세 요약 — 증권사 앱 관심종목 행 구성: 큰 종가(상승 빨강·하락 파랑) + ▲▼ + 전일대비(위)·등락률(아래)
 * + 오른쪽 미니 캔들. 색에만 의존하지 않도록 ▲/▼ 기호와 스크린리더용 텍스트를 함께 쓴다. 일 단위 종가 기준이며
 * 실시간 시세가 아니다(기준일은 title로 제공).
 */
export function QuoteText({ quote }: { quote: StockQuote | undefined }) {
  if (!quote) return null;
  const { change, change_pct: pct } = quote;
  const dir = change === null || change === 0 ? "flat" : change > 0 ? "up" : "down";
  const label = dir === "up" ? "상승" : dir === "down" ? "하락" : "보합";
  const hasCandle =
    quote.open != null && quote.high != null && quote.low != null && Number.isFinite(quote.open);
  return (
    <span className={`quote-text quote-text--${dir}`} title={`${quote.trade_date} 종가 기준`}>
      <span className="quote-text__price">{nf.format(quote.close)}</span>
      {change !== null && pct !== null && (
        <>
          <span className="quote-text__tri" aria-hidden="true">
            {dir === "up" ? "▲" : dir === "down" ? "▼" : ""}
          </span>
          <span className="quote-text__stack">
            <span className="quote-text__change">
              <span className="sr-only">{label} </span>
              {nf.format(Math.abs(change))}
            </span>
            <span className="quote-text__pct">{Math.abs(pct).toFixed(2)}%</span>
          </span>
        </>
      )}
      {hasCandle && (
        <MiniCandle
          open={quote.open as number}
          high={quote.high as number}
          low={quote.low as number}
          close={quote.close}
        />
      )}
    </span>
  );
}
