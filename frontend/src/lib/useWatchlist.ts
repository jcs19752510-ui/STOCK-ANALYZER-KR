"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  WATCHLIST_STORAGE_KEY,
  emptyState,
  parseState,
  serialize,
  type WatchlistState,
} from "@/lib/watchlist";

/**
 * 관심종목 저장소 훅(DEC-055). 이 브라우저 localStorage에만 저장하며 접근이 막혀 있어도(시크릿 창 등) 화면은 동작한다
 * (그 경우 새로고침 전까지만 유지). 같은 브라우저의 다른 탭 변경도 `storage` 이벤트로 반영한다.
 */
let memory: WatchlistState | null = null; // 저장소가 막힌 환경의 대체 보관
let cachedRaw: string | null | undefined;
let cachedState: WatchlistState = emptyState();
const listeners = new Set<() => void>();

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(WATCHLIST_STORAGE_KEY);
  } catch {
    return null;
  }
}

function getSnapshot(): WatchlistState {
  if (memory) return memory;
  const raw = readRaw();
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedState = parseState(raw);
  }
  return cachedState;
}

const serverSnapshot = emptyState();
const getServerSnapshot = () => serverSnapshot;

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === WATCHLIST_STORAGE_KEY || e.key === null) cb();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

function commit(next: WatchlistState): void {
  try {
    window.localStorage.setItem(WATCHLIST_STORAGE_KEY, serialize(next));
    memory = null;
  } catch {
    memory = next; // 저장 불가: 이 화면 세션 동안만 유지
  }
  listeners.forEach((l) => l());
}

export function useWatchlist(): {
  state: WatchlistState;
  update: (fn: (s: WatchlistState) => WatchlistState) => void;
} {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const update = useCallback((fn: (s: WatchlistState) => WatchlistState) => {
    commit(fn(getSnapshot()));
  }, []);
  return { state, update };
}
