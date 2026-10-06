"use client";

/**
 * 장중 기준 재계산(DEC-089) React 연결: 접근 확인·켜짐 기억·조회 훅. 호출은 `browserApiBase()`를 거친다(로그인을 켠 로컬은 웹 서버 대행 경로, 끈 로컬은 API 직접).
 * 로컬 모드가 아니거나(운영 빌드·공개 주소) 관리자가 아니면 **요청을 하나도 보내지 않는다**: 접근이 확인되기 전에는 컨트롤러를 만들지 않는다.
 */
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { browserApiBase } from "@/lib/apiBase";
import { LOCAL_INTRADAY_FLAG } from "@/lib/localIntraday";
import { useLocalMode } from "@/lib/psearch/react";
import { LiveScreenController, EMPTY_LIVE_VIEW, type LiveHttp, type LiveQuery, type LiveScreenView } from "./controller.ts";
import { newCodes, nextNewExpiryMs, readStoredToggle, writeStoredToggle } from "./logic.ts";

const AUTH_BUILD = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

let adminMemo: boolean | null = null;
let adminInflight: Promise<boolean> | null = null;

/** 로그인을 켠 로컬 빌드에서만 `/auth/me`로 관리자인지 확인한다(일반 회원이면 false → 이 기능의 요청은 만들어지지 않는다). 로그인을 끈 로컬은 내 PC 본인이다. */
function loadIsAdmin(): Promise<boolean> {
  if (!AUTH_BUILD) return Promise.resolve(true);
  if (adminMemo !== null) return Promise.resolve(adminMemo);
  adminInflight ??= fetch("/auth/me", { credentials: "same-origin", cache: "no-store" })
    .then(async (r) => (r.ok ? (((await r.json()) as { role?: unknown }).role === "admin") : false))
    .catch(() => false)
    .then((v) => {
      adminMemo = v;
      return v;
    })
    .finally(() => {
      adminInflight = null;
    });
  return adminInflight;
}

/** "장중 기준" 전환을 보여도 되는가: 로컬 모드(내 PC 주소 + 로컬 빌드)이고 관리자일 때만 true. 서버 렌더·하이드레이션 중에는 false. */
export function useLiveScreenAccess(): boolean {
  const local = useLocalMode();
  const [admin, setAdmin] = useState<boolean>(adminMemo ?? false);
  useEffect(() => {
    if (!LOCAL_INTRADAY_FLAG || local !== "yes") return;
    let alive = true;
    void loadIsAdmin().then((v) => {
      if (alive) setAdmin(v);
    });
    return () => {
      alive = false;
    };
  }, [local]);
  return local === "yes" && admin;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

const toggleListeners = new Set<() => void>();
/** 저장소를 쓸 수 없을 때(차단·사설 창)에도 이 탭에서는 켜고 끌 수 있도록 메모리에 같이 둔다. */
let memoryOn: boolean | null = null;

function subscribeToggle(cb: () => void): () => void {
  toggleListeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    toggleListeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

const toggleSnapshot = (): boolean => memoryOn ?? readStoredToggle(storage());

/** 켜짐 상태(이 브라우저에만 기억). 접근이 확인되기 전에는 항상 꺼짐이고, 접근이 있으면 기억해 둔 값을 쓴다. 서버 렌더에서는 항상 꺼짐. */
export function useLiveToggle(access: boolean): [boolean, (on: boolean) => void] {
  const stored = useSyncExternalStore(subscribeToggle, toggleSnapshot, () => false);
  const set = useCallback((next: boolean) => {
    memoryOn = next;
    writeStoredToggle(storage(), next);
    toggleListeners.forEach((fn) => fn());
  }, []);
  return [stored && access, set];
}

async function request(url: string, signal: AbortSignal): Promise<LiveHttp> {
  const res = await fetch(url, { signal, cache: "no-store" });
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

export interface LiveScreenApi<T> {
  view: LiveScreenView<T>;
  setQuery: (query: LiveQuery, page?: number) => void;
  setPage: (page: number) => void;
  pause: () => void;
  resume: () => void;
  refreshNow: () => void;
  clear: () => void;
}

/**
 * 컨트롤러를 만들고 화면 상태로 연결한다. `enabled`가 거짓이면 컨트롤러가 없고 요청도 없다.
 * 켜지면 만들고, 꺼지거나 화면을 떠나면 요청·타이머를 정리한다. 탭 가시성 이벤트도 여기서 연결한다.
 */
export function useLiveScreen<T extends { items: unknown[]; page: number }>(enabled: boolean): LiveScreenApi<T> {
  const [view, setView] = useState<LiveScreenView<T>>(EMPTY_LIVE_VIEW as unknown as LiveScreenView<T>);
  const ref = useRef<LiveScreenController<T> | null>(null);

  useEffect(() => {
    // 운영 빌드에서는 이 상수가 빌드 때 거짓으로 박혀 아래 요청 코드가 번들에서 제거된다(운영 빌드 비노출, 번들 검사로 확인).
    if (!LOCAL_INTRADAY_FLAG || !enabled) return;
    const base = browserApiBase();
    if (!base) return;
    const ctl = new LiveScreenController<T>({
      request,
      baseUrl: base.replace(/\/$/, ""),
      onView: (v) => setView(v as unknown as LiveScreenView<T>),
      setTimeout: (fn, ms) => window.setTimeout(fn, ms),
      clearTimeout: (id) => window.clearTimeout(id as number),
      isHidden: () => document.hidden,
      now: () => Date.now() / 1000,
    });
    ref.current = ctl;
    const onVisibility = () => ctl.visibilityChanged();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      ctl.stop();
      ref.current = null;
      setView(EMPTY_LIVE_VIEW as unknown as LiveScreenView<T>);
    };
  }, [enabled]);

  return useMemo(
    () => ({
      view,
      setQuery: (q, page) => ref.current?.setQuery(q, page),
      setPage: (p) => ref.current?.setPage(p),
      pause: () => void ref.current?.pause(),
      resume: () => ref.current?.resume(),
      refreshNow: () => ref.current?.refreshNow(),
      clear: () => ref.current?.clearQuery(),
    }),
    [view],
  );
}

/** 지금 "신규"로 보일 종목. 가장 먼저 끝나는 표지 시점에 한 번만 다시 계산한다(목록 전체를 매초 다시 그리지 않는다). */
export function useNewCodes(view: LiveScreenView<unknown>): ReadonlySet<string> {
  const [nowSec, setNowSec] = useState(() => Date.now() / 1000);
  const log = view.changeLog;
  useEffect(() => {
    const ms = nextNewExpiryMs(log, Date.now() / 1000);
    if (ms === null) return;
    const id = window.setTimeout(() => setNowSec(Date.now() / 1000), ms);
    return () => window.clearTimeout(id);
  }, [log, nowSec]);
  return useMemo(() => newCodes(log, nowSec), [log, nowSec]);
}

/** 초 단위 시계(배너의 "N초 전"·지연 판정용). 탭이 가려지면 멈추고 보이면 바로 갱신한다. */
export function useNowSeconds(active: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => {
      if (!document.hidden) setNow(Date.now() / 1000);
    }, 1000);
    const onVisibility = () => !document.hidden && setNow(Date.now() / 1000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active]);
  return now;
}
