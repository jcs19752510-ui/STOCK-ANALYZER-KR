"use client";

import { useEffect, useState } from "react";
import type { Envelope } from "@/lib/types";

/**
 * 탭을 처음 열 때만 API를 호출하는 클라이언트 훅(DEC-041).
 *
 * 왜 서버 렌더가 아니라 브라우저에서 호출하는가: 공개 API의 rate limit은 IP 기준(분당 60회)인데,
 * 서버 컴포넌트가 호출하면 모든 방문자가 프론트 서버 한 IP로 합산된다. 상세 화면에서 보조 정보
 * (실적·조건 체크)까지 서버가 매번 부르면 방문자 전체가 분당 15화면만 쓸 수 있게 된다. 탭을 열 때
 * 브라우저가 직접 부르면 방문자별로 세어지고, 보지 않는 탭은 호출 자체가 없다.
 */
export type LazyState<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error" };

export function useLazyApi<T>(path: string, enabled: boolean): LazyState<T> {
  const [state, setState] = useState<LazyState<T>>({ kind: "idle" });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    (async () => {
      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
      if (!baseUrl) {
        setState({ kind: "error" });
        return;
      }
      setState({ kind: "loading" });
      try {
        const response = await fetch(new URL(path, baseUrl).toString(), {
          signal: controller.signal,
        });
        const body = (await response.json()) as Envelope<T>;
        if (controller.signal.aborted) return;
        setState(response.ok && body.data ? { kind: "ready", data: body.data } : { kind: "error" });
      } catch {
        if (!controller.signal.aborted) setState({ kind: "error" });
      }
    })();
    return () => controller.abort();
  }, [path, enabled]);

  return state;
}
