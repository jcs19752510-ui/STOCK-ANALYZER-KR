"use client";

import { useEffect, useState } from "react";
import { PRICE_EXPOSURE_ENABLED } from "@/lib/priceExposure";
import type { Envelope, StockQuote } from "@/lib/types";

/**
 * 목록 화면용 시세 요약(DEC-041): 종목 코드 목록의 최신 종가·전일대비를 `GET /stocks/quotes`로 가져온다.
 * 보조 정보라 실패하면 조용히 비운다(목록 자체의 에러 상태를 만들지 않는다). 요청은 코드 변경 시 취소된다.
 */
const CHUNK = 50;

export function useQuotes(codes: readonly string[]): Record<string, StockQuote> {
  const [quotes, setQuotes] = useState<Record<string, StockQuote>>({});
  const key = codes.join(",");

  useEffect(() => {
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
    if (!PRICE_EXPOSURE_ENABLED || !baseUrl || key === "") return; // 시세 비공개(DEC-048)면 호출하지 않는다
    // // 코드가 없으면 요청하지 않는다(이전 값은 조회 키가 달라 쓰이지 않음)
    const controller = new AbortController();
    const all = key.split(",");
    (async () => {
      const merged: Record<string, StockQuote> = {};
      for (let i = 0; i < all.length; i += CHUNK) {
        const url = new URL("/api/v1/stocks/quotes", baseUrl);
        url.searchParams.set("codes", all.slice(i, i + CHUNK).join(","));
        try {
          const response = await fetch(url.toString(), { signal: controller.signal });
          if (!response.ok) continue;
          const body = (await response.json()) as Envelope<{ quotes: StockQuote[] }>;
          for (const q of body.data?.quotes ?? []) merged[q.stock_code] = q;
        } catch {
          if (controller.signal.aborted) return;
        }
      }
      if (!controller.signal.aborted) setQuotes(merged);
    })();
    return () => controller.abort();
  }, [key]);

  return quotes;
}
