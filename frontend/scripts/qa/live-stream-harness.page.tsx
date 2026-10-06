/**
 * 실시간 화면 시험용 임시 페이지(`scripts/qa/live-stream.mjs`가 `src/app/qa-live/page.tsx`로 복사했다가 끝나면 지운다. 운영 코드가 아니다).
 * 실제 종목 상세(`app/stocks/[code]/page.tsx`)는 서버가 DB(일봉·가공 지표)를 읽어야 열려, DB 없이 같은 부품을 같은 순서로 붙여 본다:
 * LiveStreamProvider → StockQuoteHeader → 기준 안내(PriceBasisNote) → LiveStatusBadge → StockDetailTabs.
 * 일봉은 합성 값이다(실제 시세 아님).
 */
import { LiveStatusBadge } from "@/components/LiveStatusBadge";
import { PriceBasisNote } from "@/components/PriceBasisNote";
import { StockDetailTabs } from "@/components/StockDetailTabs";
import { StockQuoteHeader } from "@/components/StockQuoteHeader";
import { LiveStreamProvider } from "@/lib/liveStream/react";
import type { StockPricePoint } from "@/lib/types";

function fakePrices(): StockPricePoint[] {
  const out: StockPricePoint[] = [];
  let close = 19000;
  for (let i = 0; i < 70; i++) {
    const d = new Date(Date.UTC(2026, 6, 1 + i));
    const prev = close;
    close = Math.max(1000, Math.round(close + Math.sin(i / 3) * 200 + (i % 5) * 20 - 40));
    out.push({
      trade_date: d.toISOString().slice(0, 10),
      open: prev,
      high: Math.max(prev, close) + 120,
      low: Math.min(prev, close) - 120,
      close,
      volume: 100000 + i * 777,
      trading_value: 0,
      change: close - prev,
      change_pct: Number((((close - prev) / prev) * 100).toFixed(2)),
    });
  }
  return out;
}

export default async function QaLivePage({ searchParams }: { searchParams: Promise<{ code?: string }> }) {
  const { code = "005930" } = await searchParams;
  const prices = fakePrices();
  const latest = prices[prices.length - 1];
  return (
    <LiveStreamProvider stockCode={code}>
      <section className="stock-detail-page">
        <StockQuoteHeader
          name="시험 종목"
          stockCode={code}
          market="KOSPI"
          close={latest.close}
          change={latest.change}
          changePct={latest.change_pct}
          tradeDate={latest.trade_date}
        />
        <p className="stock-quote__basis">
          <span className="market-badge">KOSPI</span> {code} · <PriceBasisNote tradeDate={latest.trade_date} />
        </p>
        <LiveStatusBadge />
        <StockDetailTabs stockCode={code} stockName="시험 종목" prices={prices} />
      </section>
    </LiveStreamProvider>
  );
}
