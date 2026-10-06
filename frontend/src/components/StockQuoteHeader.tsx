"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { WatchStar } from "@/components/WatchStar";
import copy from "@/content/copy.ko.json";
import { useLiveQuote } from "@/lib/liveStream/react";
import { useValueFlash } from "@/lib/useValueFlash";

/**
 * 종목 상세 상단 띠(증권사 앱 구성): ← 종목명 ◢ · 현재가 ▲전일대비 등락률 · 검색 아이콘. 띠 색은 상승 빨강·하락 파랑·보합 회색.
 * 색에만 의존하지 않도록 ▲/▼ 기호와 스크린리더용 텍스트를 함께 쓴다. 기본은 일 단위 종가 기준(실시간 아님)이고,
 * 개인 로컬 모드의 실시간 스트림이 열려 있으면(DEC-084) 그 현재가·전일대비로 갱신하며 값이 바뀔 때 짧게 강조한다.
 */
interface StockQuoteHeaderProps {
  name: string;
  stockCode: string;
  market: string;
  close: number;
  change: number | null;
  changePct: number | null;
  tradeDate: string;
}

const nf = new Intl.NumberFormat("ko-KR");

export function StockQuoteHeader({
  name,
  stockCode,
  market,
  close: dailyClose,
  change: dailyChange,
  changePct: dailyChangePct,
  tradeDate,
}: StockQuoteHeaderProps) {
  const router = useRouter();
  const quote = useLiveQuote();
  const live = quote !== null;
  const close = quote ? quote.price : dailyClose;
  const change = quote ? quote.change : dailyChange;
  const changePct = quote ? quote.change_pct : dailyChangePct;
  const flash = useValueFlash(quote ? quote.price : null);
  const dir = change === null || change === 0 ? "flat" : change > 0 ? "up" : "down";
  const label = dir === "up" ? copy.stockDetail.up : dir === "down" ? copy.stockDetail.down : copy.stockDetail.flat;
  return (
    <header className={`quote-band quote-band--${dir}`}>
      <button
        type="button"
        className="quote-band__icon"
        aria-label={copy.stockDetail.backLabel}
        onClick={() => router.back()}
      >
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <path d="m15 5-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <div className="quote-band__center">
        <h1 className="quote-band__name">
          {name}
          <span className="quote-band__caret" aria-hidden="true" />
          <span className="sr-only">
            {" "}
            ({stockCode}, {market})
          </span>
        </h1>
        <p
          className="quote-band__price"
          data-live={live ? "true" : undefined}
          title={live ? copy.stockDetail.liveQuoteTitle : copy.stockDetail.priceBasis.replace("{date}", tradeDate)}
        >
          <span
            key={flash ? flash.n : 0}
            className={flash ? `quote-band__close quote-flash quote-flash--${flash.dir}` : "quote-band__close"}
          >
            {nf.format(close)}
          </span>
          {change !== null && changePct !== null && (
            <>
              <span className="quote-band__chg">
                <span aria-hidden="true">{dir === "up" ? "▲" : dir === "down" ? "▼" : ""}</span>
                <span className="sr-only">{label} </span>
                {nf.format(Math.abs(change))}
              </span>
              <span className="quote-band__pct">{Math.abs(changePct).toFixed(2)}%</span>
            </>
          )}
        </p>
      </div>
      <WatchStar item={{ code: stockCode, name, market }} variant="band" />
      <Link href="/stocks" className="quote-band__icon" aria-label={copy.stockDetail.searchLabel}>
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <circle cx="10.500" cy="10.500" r="6.500" fill="none" stroke="currentColor" strokeWidth="2.200" />
          <path d="m15.500 15.500 5 5" fill="none" stroke="currentColor" strokeWidth="2.200" strokeLinecap="round" />
        </svg>
      </Link>
    </header>
  );
}
