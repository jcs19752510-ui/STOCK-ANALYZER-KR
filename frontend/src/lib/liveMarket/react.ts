"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { browserApiBase } from "@/lib/apiBase";
import { localIntradayAvailable } from "@/lib/localIntraday";
import type { StockQuote } from "@/lib/types";
import { EMPTY_LIVE_VIEW, overlayAll, type LiveMarketView } from "./merge.ts";
import { LiveMarketPoller, type MarketResponse } from "./poller.ts";

async function request(url: string, signal: AbortSignal): Promise<MarketResponse> {
  const res = await fetch(url, { signal, cache: "no-store" });
  let body: MarketResponse["body"] = null;
  try {
    body = (await res.json()) as MarketResponse["body"];
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

/** 보이는 종목 코드의 준실시간 시세. 로컬 모드가 아니거나 서버가 허용하지 않으면 빈 값(`unavailable`)이다. */
export function useLiveMarket(codes: readonly string[]): LiveMarketView {
  const [view, setView] = useState<LiveMarketView>(EMPTY_LIVE_VIEW);
  const key = codes.join(",");
  const pollerRef = useRef<LiveMarketPoller | null>(null);

  useEffect(() => {
    if (!localIntradayAvailable()) return;
    const baseUrl = browserApiBase();
    if (!baseUrl) return;
    const poller = new LiveMarketPoller({
      request,
      baseUrl: baseUrl.replace(/\/$/, ""),
      onView: setView,
      setTimeout: (fn, ms) => window.setTimeout(fn, ms),
      clearTimeout: (id) => window.clearTimeout(id as number),
      isHidden: () => document.hidden,
      now: () => Date.now() / 1000,
    });
    pollerRef.current = poller;
    const onVisibility = () => poller.visibilityChanged();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      poller.stop();
      pollerRef.current = null;
    };
  }, []);

  useEffect(() => {
    pollerRef.current?.setCodes(key === "" ? [] : key.split(","));
  }, [key]);

  return view;
}

/** 일 종가 요약 위에 준실시간 시세를 덮어쓴 값. 시각 표시를 위해 값이 바뀔 때마다 현재 시각을 새로 읽는다. */
export function useOverlaidQuotes(
  codes: readonly string[],
  daily: Record<string, StockQuote>,
): { quotes: Record<string, StockQuote>; live: boolean; unavailable: boolean } {
  const view = useLiveMarket(codes);
  const key = codes.join(",");
  const quotes = useMemo(
    () => overlayAll(daily, view, key === "" ? [] : key.split(",")),
    [daily, view, key],
  );
  return { quotes, live: !view.unavailable && Object.keys(view.quotes).length > 0, unavailable: view.unavailable };
}
