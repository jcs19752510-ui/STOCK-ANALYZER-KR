"use client";

import { useSyncExternalStore } from "react";

/**
 * 종목 상세 위쪽 "일 단위 종가 기준" 안내가, 개인 로컬 모드에서 호가·체결·분·틱을 보는 동안에는 "내 증권사 시세" 안내로
 * 바뀌게 하는 작은 공유 상태(DEC-056). 탭과 차트가 각자 켜고 끄며, 하나라도 켜져 있으면 장중 보기로 본다.
 */
const flags = new Set<string>();
const listeners = new Set<() => void>();
let snapshot = false;

export function setIntradayFlag(key: string, on: boolean): void {
  if (on) flags.add(key);
  else flags.delete(key);
  const next = flags.size > 0;
  if (next !== snapshot) {
    snapshot = next;
    listeners.forEach((l) => l());
  }
}

export function useIntradayView(): boolean {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => snapshot,
    () => false,
  );
}
