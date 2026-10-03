"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  DRAWINGS_STORAGE_PREFIX,
  parseDrawings,
  serializeDrawings,
  type Drawing,
} from "@/lib/chartDrawings";

/**
 * 종목별 그린 선 저장소 훅(DEC-059). 이 브라우저 localStorage에만 저장하고, 접근이 막혀 있으면(시크릿 창 등) 그 화면 세션
 * 동안만 메모리에 둔다. 같은 브라우저의 다른 탭 변경도 `storage` 이벤트로 반영한다.
 */
const EMPTY: Drawing[] = [];
const memory = new Map<string, Drawing[]>();
const cache = new Map<string, { raw: string | null; list: Drawing[] }>();
const listeners = new Set<() => void>();

function readRaw(code: string): string | null {
  try {
    return window.localStorage.getItem(DRAWINGS_STORAGE_PREFIX + code);
  } catch {
    return null;
  }
}

function getSnapshot(code: string): Drawing[] {
  const mem = memory.get(code);
  if (mem) return mem;
  const raw = readRaw(code);
  const hit = cache.get(code);
  if (hit && hit.raw === raw) return hit.list;
  const list = raw === null ? EMPTY : parseDrawings(raw);
  cache.set(code, { raw, list });
  return list;
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key.startsWith(DRAWINGS_STORAGE_PREFIX)) cb();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

function commit(code: string, next: Drawing[]): void {
  try {
    if (next.length === 0) window.localStorage.removeItem(DRAWINGS_STORAGE_PREFIX + code);
    else window.localStorage.setItem(DRAWINGS_STORAGE_PREFIX + code, serializeDrawings(next));
    memory.delete(code);
  } catch {
    memory.set(code, next); // 저장 불가: 이 화면 세션 동안만 유지
  }
  listeners.forEach((l) => l());
}

export function useChartDrawings(code: string | undefined): {
  drawings: Drawing[];
  update: (fn: (list: Drawing[]) => Drawing[]) => void;
} {
  const key = code ?? "";
  const drawings = useSyncExternalStore(
    subscribe,
    () => (key === "" ? EMPTY : getSnapshot(key)),
    () => EMPTY,
  );
  const update = useCallback(
    (fn: (list: Drawing[]) => Drawing[]) => {
      if (key !== "") commit(key, fn(getSnapshot(key)));
    },
    [key],
  );
  return { drawings, update };
}
