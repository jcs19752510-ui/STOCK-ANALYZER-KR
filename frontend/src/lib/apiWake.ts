/**
 * 무료 호스팅의 "깨어나는 중" 안내 로직(DEC-063). 무료 서버/DB는 한동안 접속이 없으면 잠들어서 첫 요청이
 * 수십 초 걸릴 수 있다. API 요청이 `thresholdMs` 넘게 끝나지 않으면 안내를 띄우고, 끝나면 내린다.
 * 화면 의존 없는 순수 로직이라 노드 테스트로 검증한다(scripts/check-api-wake.mjs).
 */

export const WAKE_NOTICE_THRESHOLD_MS = 4500;

/** fetch 대상이 우리 API인지 판단한다(서비스 밖 요청은 세지 않는다). */
export function isApiRequest(input: string, apiBase: string | undefined): boolean {
  if (!apiBase) return false;
  try {
    const base = new URL(apiBase);
    const target = new URL(input, base);
    return target.origin === base.origin && target.pathname.startsWith("/api/");
  } catch {
    return false;
  }
}

export interface WakeTimers {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

const defaultTimers: WakeTimers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (h) => globalThis.clearTimeout(h as ReturnType<typeof setTimeout>),
};

/**
 * 진행 중인 요청을 세다가, 가장 오래된 요청이 임계값을 넘으면 `onChange(true)`, 모두 끝나면 `onChange(false)`.
 * 같은 값으로는 다시 알리지 않는다.
 */
export function createWakeTracker(
  onChange: (visible: boolean) => void,
  thresholdMs: number = WAKE_NOTICE_THRESHOLD_MS,
  timers: WakeTimers = defaultTimers,
) {
  let nextId = 0;
  const pending = new Map<number, unknown>();
  const slow = new Set<number>();
  let visible = false;

  const publish = () => {
    const now = slow.size > 0;
    if (now !== visible) {
      visible = now;
      onChange(now);
    }
  };

  return {
    begin(): () => void {
      const id = nextId++;
      pending.set(id, timers.setTimeout(() => {
        if (pending.has(id)) {
          slow.add(id);
          publish();
        }
      }, thresholdMs));
      let done = false;
      return () => {
        if (done) return;
        done = true;
        timers.clearTimeout(pending.get(id));
        pending.delete(id);
        slow.delete(id);
        publish();
      };
    },
    pendingCount: () => pending.size,
    isVisible: () => visible,
  };
}

/** `fetch`를 감싸 API 요청만 추적한다. 반환값은 원래 fetch로 되돌리는 함수. */
export function installWakeTracking(
  target: { fetch: typeof fetch },
  apiBase: string | undefined,
  tracker: ReturnType<typeof createWakeTracker>,
): () => void {
  const original = target.fetch;
  target.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!isApiRequest(url, apiBase)) return original.call(target, input, init);
    const end = tracker.begin();
    return original.call(target, input, init).finally(end);
  }) as typeof fetch;
  return () => {
    target.fetch = original;
  };
}
