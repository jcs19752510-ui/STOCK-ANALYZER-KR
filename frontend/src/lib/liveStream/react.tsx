"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { browserApiBase } from "@/lib/apiBase";
import { localIntradayAvailable } from "@/lib/localIntraday";
import { setLiveFlag } from "@/lib/viewBasis";
import { LiveStreamController, type EventSourceLike } from "./controller.ts";
import {
  OFF_DATA,
  OFF_META,
  createLiveStore,
  effectiveState,
  liveMode,
  type EffectiveState,
  type LiveMode,
  type LiveStore,
} from "./store.ts";
import type { LiveBar, LiveBook, LiveMeta, LiveQuote, LiveTick } from "./types.ts";

/**
 * 종목 상세 화면의 실시간 연결(DEC-084). 화면에는 `EventSource`를 **딱 하나**만 두고(브라우저는 같은 서버로 HTTP/1.1 연결을 6개까지만 연다),
 * 현재가·호가·체결·차트가 이 공급자의 저장소를 함께 읽는다. 언마운트하면 반드시 연결을 닫는다.
 * 개인 로컬 모드(`localIntradayAvailable()`)가 아니거나 서버 렌더일 때는 아무것도 하지 않고, 하위 화면은 기존 폴링을 그대로 쓴다.
 */
const noopSubscribe = () => () => {};

const OFF_STORE: LiveStore = {
  getData: () => OFF_DATA,
  getMeta: () => OFF_META,
  hasSnapshot: () => false,
  subscribe: () => () => {},
  dispatch: () => {},
  setStatus: () => {},
  setServerConnection: () => {},
  flush: () => {},
  dispose: () => {},
};

const LiveStoreContext = createContext<LiveStore>(OFF_STORE);

export function LiveStreamProvider({ stockCode, children }: { stockCode: string; children: ReactNode }) {
  // 브라우저 주소가 내 PC/사설망이고 스위치가 켜졌을 때만 true(서버 렌더·공개 도메인·운영 빌드에서는 false)
  const enabled = useSyncExternalStore(noopSubscribe, localIntradayAvailable, () => false);
  const store = useMemo(() => createLiveStore(stockCode), [stockCode]);

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const base = browserApiBase();
    if (!base) return;
    const url = new URL(`/api/v1/local/stocks/${encodeURIComponent(stockCode)}/stream`, base).toString();
    const controller = new LiveStreamController({
      url,
      store,
      createEventSource: (u) => new EventSource(u) as unknown as EventSourceLike,
    });
    controller.start();
    return () => {
      controller.stop(); // 화면을 떠나면 연결을 닫는다(서버는 유예 뒤 증권사 구독을 해지)
      store.setStatus("off");
    };
  }, [enabled, stockCode, store]);

  return (
    <LiveStoreContext.Provider value={store}>
      <LiveBasisSync />
      {children}
    </LiveStoreContext.Provider>
  );
}

/** 헤더에 라이브 시세가 표시되는 동안 위쪽 기준 안내를 "내 증권사 실시간 시세"로 바꾼다(`viewBasis`). */
function LiveBasisSync() {
  const quote = useLiveQuote();
  const on = quote !== null;
  useEffect(() => {
    setLiveFlag(on);
    return () => setLiveFlag(false);
  }, [on]);
  return null;
}

function useSlice<T>(select: (s: LiveStore) => T, server: T): T {
  const store = useContext(LiveStoreContext);
  return useSyncExternalStore(
    store.subscribe,
    () => select(store),
    () => server,
  );
}

export function useLiveMeta(): LiveMeta {
  return useSlice((s) => s.getMeta(), OFF_META);
}

/** 이 화면이 스트림 데이터를 쓸지(`live`·`pending`) 기존 폴링으로 돌아갈지(`fallback`). */
export function useLiveMode(): LiveMode {
  return useSlice((s) => liveMode(s.getMeta()), "fallback" as LiveMode);
}

export function useLiveState(): EffectiveState {
  return useSlice((s) => effectiveState(s.getMeta()), "off" as EffectiveState);
}

export function useLiveQuote(): LiveQuote | null {
  return useSlice((s) => s.getData().quote, null);
}

export function useLiveBook(): LiveBook | null {
  return useSlice((s) => s.getData().book, null);
}

const NO_TICKS: LiveTick[] = [];
const NO_BARS: LiveBar[] = [];

/** `enabled`가 false면 빈 목록을 돌려주고 갱신에도 다시 그리지 않는다(쓰지 않는 화면이 초당 10번 그려지지 않게). */
export function useLiveTicks(enabled = true): LiveTick[] {
  return useSlice((s) => (enabled ? s.getData().ticks : NO_TICKS), NO_TICKS);
}

export function useLiveBars(enabled = true): LiveBar[] {
  return useSlice((s) => (enabled ? s.getData().bars : NO_BARS), NO_BARS);
}

export function useLiveBusinessDate(): string | null {
  return useSlice((s) => s.getData().businessDate, null);
}

/** 값이 자주 바뀌어도 화면에는 `ms`마다 한 번만 반영한다(무거운 차트용). */
export function useThrottled<T>(value: T, ms: number): T {
  const [shown, setShown] = useState(value);
  const lastShownAt = useRef(0);
  useEffect(() => {
    if (Object.is(shown, value)) return;
    // 반영 시각을 기준으로 한 절대 시각에 맞춘다(값이 계속 바뀌어도 타이머가 밀리지 않는다)
    const wait = Math.max(0, lastShownAt.current + ms - Date.now());
    const timer = setTimeout(() => {
      lastShownAt.current = Date.now();
      setShown(value);
    }, wait);
    return () => clearTimeout(timer);
  }, [value, shown, ms]);
  return shown;
}
