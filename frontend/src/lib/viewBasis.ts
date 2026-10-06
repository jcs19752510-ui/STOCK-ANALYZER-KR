"use client";

import { useSyncExternalStore } from "react";

/**
 * 종목 상세 위쪽 "일 단위 종가 기준" 안내가, 개인 로컬 모드에서 호가·체결·분·틱을 보는 동안에는 "내 증권사 시세" 안내로
 * 바뀌게 하는 작은 공유 상태(DEC-056). 탭과 차트가 각자 켜고 끄며, 하나라도 켜져 있으면 장중 보기로 본다.
 *
 * 실시간 스트림(DEC-084)이 현재가를 갱신하는 동안에는 한 단계 더 나아가 "내 증권사 실시간 시세(본인 전용)"로 바뀐다(`setLiveFlag`).
 */
const flags = new Set<string>();
const listeners = new Set<() => void>();
let snapshot = false;
let liveSnapshot = false;

function emit(): void {
  listeners.forEach((l) => l());
}

export function setIntradayFlag(key: string, on: boolean): void {
  if (on) flags.add(key);
  else flags.delete(key);
  const next = flags.size > 0;
  if (next !== snapshot) {
    snapshot = next;
    emit();
  }
}

/** 실시간 스트림이 현재가를 보여 주는 중인지. */
export function setLiveFlag(on: boolean): void {
  if (on !== liveSnapshot) {
    liveSnapshot = on;
    emit();
  }
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function useIntradayView(): boolean {
  return useSyncExternalStore(subscribe, () => snapshot, () => false);
}

export function useLiveView(): boolean {
  return useSyncExternalStore(subscribe, () => liveSnapshot, () => false);
}
