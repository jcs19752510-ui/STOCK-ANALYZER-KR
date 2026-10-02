"use client";

import { useEffect, useRef, useState } from "react";
import { fetchIntraday, type IntradayResult } from "@/lib/localIntraday";

/**
 * 장중 시세를 주기적으로 다시 불러온다(개인 로컬 모드, DEC-052). 탭이 숨겨져 있으면(document.hidden) 건너뛰고, 컴포넌트가
 * 사라지거나 경로가 바뀌면 진행 중 요청을 취소한다. 실패해도 직전 성공 데이터는 유지하며(`stale`) 오류를 함께 알린다.
 */
export interface IntradayPollState<T> {
  data: T | null;
  loading: boolean;
  error: { code: string; message: string } | null;
  updatedAt: number | null;
}

interface Internal<T> extends IntradayPollState<T> {
  /** 이 상태가 어느 경로의 결과인지. 경로가 바뀐 직후 한 번 렌더되는 동안 이전 경로의 데이터를 내보내지 않기 위함. */
  path: string | null;
}

export function useIntradayPoll<T>(path: string | null, intervalMs: number): IntradayPollState<T> {
  const [state, setState] = useState<Internal<T>>({
    path,
    data: null,
    loading: path !== null,
    error: null,
    updatedAt: null,
  });
  const pathRef = useRef(path);

  useEffect(() => {
    pathRef.current = path;
    if (path === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;

    const reset = () => setState({ path, data: null, loading: true, error: null, updatedAt: null });
    reset();

    const tick = async () => {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.hidden) {
        timer = setTimeout(tick, intervalMs);
        return;
      }
      controller = new AbortController();
      const result: IntradayResult<T> = await fetchIntraday<T>(path, controller.signal);
      if (cancelled || pathRef.current !== path) return;
      if (result.kind === "success") {
        setState({ path, data: result.data, loading: false, error: null, updatedAt: Date.now() });
      } else if (result.code !== "ABORTED") {
        setState((s) => ({
          ...s,
          path,
          loading: false,
          error: { code: result.code, message: result.message },
        }));
      }
      // 한도 초과·연결 오류면 간격을 늘려 증권사·서버에 부담을 주지 않는다.
      const backoff = result.kind === "error" ? Math.min(intervalMs * 3, 30_000) : intervalMs;
      timer = setTimeout(tick, backoff);
    };
    void tick();

    return () => {
      cancelled = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [path, intervalMs]);

  if (state.path !== path) {
    return { data: null, loading: path !== null, error: null, updatedAt: null };
  }
  return state;
}
