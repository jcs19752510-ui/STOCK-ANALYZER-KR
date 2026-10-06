"use client";

import { useEffect, useState } from "react";

/**
 * 값이 바뀔 때 짧게(기본 0.45초) 강조할 방향을 돌려준다. 오르면 "up", 내리면 "down", 평소에는 null.
 * `prefers-reduced-motion: reduce`이면 강조하지 않는다. 같은 방향으로 연달아 바뀌어도 `n`이 늘어 매번 새로 시작한다(`key`로 쓴다).
 */
export interface ValueFlash {
  dir: "up" | "down";
  n: number;
}

function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useValueFlash(value: number | null, ms = 450): ValueFlash | null {
  const [prev, setPrev] = useState(value);
  const [flash, setFlash] = useState<ValueFlash | null>(null);
  if (value !== prev) {
    // 렌더 중 상태 갱신(공식 허용 패턴): 직전 값과 비교해 방향을 정한다
    setPrev(value);
    if (prev !== null && value !== null && !reducedMotion()) {
      setFlash((f) => ({ dir: value > prev ? "up" : "down", n: (f?.n ?? 0) + 1 }));
    }
  }
  useEffect(() => {
    if (flash === null) return;
    const timer = setTimeout(() => setFlash(null), ms);
    return () => clearTimeout(timer);
  }, [flash, ms]);
  return flash;
}
