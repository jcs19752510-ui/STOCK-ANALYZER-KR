"use client";

import { browserApiBase } from "@/lib/apiBase";
import { useEffect, useState } from "react";
import { useOverlaidQuotes } from "@/lib/liveMarket/react";
import { localIntradayAvailable } from "@/lib/localIntraday";
import { PRICE_EXPOSURE_ENABLED } from "@/lib/priceExposure";
import type { Envelope, StockQuote } from "@/lib/types";

/**
 * 목록 화면용 시세 요약(DEC-041): 종목 코드 목록의 최신 종가·전일대비를 `GET /stocks/quotes`로 가져온다.
 * 보조 정보라 실패하면 조용히 비운다(목록 자체의 에러 상태를 만들지 않는다). 요청은 코드 변경 시 취소된다.
 * 개인 로컬 모드(관리자, 내 PC)에서는 그 위에 전 종목 준실시간 시세를 덮어쓴다(DEC-084 B, `liveMarket/`). 그 밖의 환경은 예전과 동일하다.
 */
const CHUNK = 50;

export function useQuotes(codes: readonly string[]): Record<string, StockQuote> {
  const daily = useDailyQuotes(codes);
  return useOverlaidQuotes(codes, daily).quotes;
}

function useQuotesState(codes: readonly string[]): { quotes: Record<string, StockQuote>; unavailable: boolean } {
  const daily = useDailyQuotes(codes);
  const { quotes, unavailable } = useOverlaidQuotes(codes, daily);
  return { quotes, unavailable };
}

/** 로컬 모드일 때만 시세를 부르는 목록(조건 스크리닝 결과)용. 운영 화면은 예전처럼 시세 열이 없다. */
export function useLocalQuotes(codes: readonly string[]): { quotes: Record<string, StockQuote>; enabled: boolean } {
  const local = localIntradayAvailable();
  const { quotes, unavailable } = useQuotesState(local ? codes : EMPTY);
  // 서버가 이 계정에 준실시간 시세를 주지 않으면(일반 회원 등) 시세 열·안내를 보이지 않는다.
  return { quotes, enabled: local && !unavailable };
}

const EMPTY: readonly string[] = [];

function useDailyQuotes(codes: readonly string[]): Record<string, StockQuote> {
  const [quotes, setQuotes] = useState<Record<string, StockQuote>>({});
  const key = codes.join(",");

  useEffect(() => {
    const baseUrl = browserApiBase();
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
