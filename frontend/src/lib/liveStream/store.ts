import { initialLiveData, reduceLive } from "./reducer.ts";
import type { LiveData, LiveEvent, LiveMeta, LiveStatus, ServerConnection } from "./types.ts";

/**
 * 라이브 데이터 저장소(React 밖의 순수 객체). 이벤트는 바로 작업용 복사본에 반영하고, 화면(구독자)에는 `flushMs`(기본 100ms)마다
 * 한 번만 알려 폭주 종목에서도 렌더가 초당 10회를 넘지 않게 한다. 상태 변화(연결·끊김)는 곧바로 알린다.
 * `useSyncExternalStore`로 읽으며, `getData()`·`getMeta()`는 알림 사이에 같은 객체를 돌려준다.
 */
export interface Timers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

const REAL_TIMERS: Timers = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
};

export const FLUSH_MS = 100;
/** "마지막 수신" 표시는 초당 1회만 바꾼다(스크린리더·렌더 부담 방지). */
export const RECEIVED_STAMP_MS = 1000;
/** 연결이 이만큼(ms) 계속 끊겨 있으면 "재연결 중"이 아니라 "끊겼습니다"로 안내한다. */
export const DOWN_AFTER_MS = 30_000;

export interface LiveStoreOptions {
  flushMs?: number;
  downAfterMs?: number;
  now?: () => number;
  timers?: Timers;
}

export interface LiveStore {
  getData(): LiveData;
  getMeta(): LiveMeta;
  /** 첫 snapshot을 이미 받았는가(아직 화면에 알리기 전이어도 최신 값). */
  hasSnapshot(): boolean;
  subscribe(listener: () => void): () => void;
  dispatch(ev: LiveEvent): void;
  setStatus(status: LiveStatus, errorCode?: string | null): void;
  setServerConnection(conn: ServerConnection): void;
  /** 대기 중인 갱신을 지금 화면에 알린다(시험·정리용). */
  flush(): void;
  dispose(): void;
}

export const INITIAL_META: LiveMeta = {
  status: "off",
  errorCode: null,
  serverConnection: null,
  lastReceivedAt: null,
  hasSnapshot: false,
  everConnected: false,
  down: false,
};

export function createLiveStore(code: string, opts: LiveStoreOptions = {}): LiveStore {
  const flushMs = opts.flushMs ?? FLUSH_MS;
  const downAfterMs = opts.downAfterMs ?? DOWN_AFTER_MS;
  const now = opts.now ?? Date.now;
  const timers = opts.timers ?? REAL_TIMERS;

  let work: LiveData = initialLiveData(code);
  let metaWork: LiveMeta = { ...INITIAL_META };
  let rawReceivedAt: number | null = null;
  let published: LiveData = work;
  let publishedMeta: LiveMeta = metaWork;
  let flushTimer: unknown = null;
  let downTimer: unknown = null;
  let disposed = false;
  const listeners = new Set<() => void>();

  const notify = () => listeners.forEach((l) => l());

  function flush(): void {
    if (flushTimer !== null) {
      timers.clearTimeout(flushTimer);
      flushTimer = null;
    }
    if (disposed) return;
    let changed = false;
    if (work !== published) {
      published = work;
      changed = true;
    }
    // "마지막 수신" 시각은 초당 1회만 바꾼다. 상태가 바뀌는 순간(끊김 등)에는 정확한 값을 쓴다.
    if (rawReceivedAt !== null && (publishedMeta.lastReceivedAt === null || rawReceivedAt - publishedMeta.lastReceivedAt >= RECEIVED_STAMP_MS)) {
      metaWork = { ...metaWork, lastReceivedAt: rawReceivedAt };
    }
    if (metaWork !== publishedMeta) {
      publishedMeta = metaWork;
      changed = true;
    }
    if (changed) notify();
  }

  function schedule(): void {
    if (flushTimer === null && !disposed) flushTimer = timers.setTimeout(flush, flushMs);
  }

  function patchMeta(patch: Partial<LiveMeta>): void {
    metaWork = { ...metaWork, ...patch };
  }

  /** 연결이 흔들리는 중인지(재연결 중) — 이 상태가 `downAfterMs` 넘게 이어지면 `down`으로 바꾼다. */
  function degraded(m: LiveMeta): boolean {
    if (m.status === "reconnecting") return true;
    if (m.status !== "live") return false;
    return m.serverConnection === "reconnecting" || (m.everConnected && (m.serverConnection === "connecting" || m.serverConnection === "idle"));
  }

  function updateDown(): void {
    if (degraded(metaWork)) {
      if (downTimer === null && !metaWork.down) {
        downTimer = timers.setTimeout(() => {
          downTimer = null;
          if (disposed || !degraded(metaWork)) return;
          patchMeta({ down: true });
          flush();
        }, downAfterMs);
      }
    } else {
      if (downTimer !== null) {
        timers.clearTimeout(downTimer);
        downTimer = null;
      }
      if (metaWork.down) patchMeta({ down: false });
    }
  }

  return {
    getData: () => published,
    getMeta: () => publishedMeta,
    hasSnapshot: () => metaWork.hasSnapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispatch(ev) {
      if (disposed) return;
      work = reduceLive(work, ev);
      rawReceivedAt = now();
      if (ev.type === "snapshot") {
        const conn = ev.data.connection ?? null;
        patchMeta({
          hasSnapshot: true,
          serverConnection: conn ?? metaWork.serverConnection,
          everConnected: metaWork.everConnected || conn === "connected",
        });
        updateDown();
      }
      schedule();
    },
    setStatus(status, errorCode = null) {
      if (disposed) return;
      patchMeta({ status, errorCode });
      if (rawReceivedAt !== null) patchMeta({ lastReceivedAt: rawReceivedAt });
      updateDown();
      flush();
    },
    setServerConnection(conn) {
      if (disposed) return;
      patchMeta({ serverConnection: conn, everConnected: metaWork.everConnected || conn === "connected" });
      updateDown();
      flush();
    },
    flush,
    dispose() {
      disposed = true;
      if (flushTimer !== null) timers.clearTimeout(flushTimer);
      if (downTimer !== null) timers.clearTimeout(downTimer);
      flushTimer = null;
      downTimer = null;
      listeners.clear();
    },
  };
}

/** 라이브 기능이 꺼진 화면(공개·운영·서버 렌더·공급자 없음)이 쓰는 고정 저장소. */
export const OFF_META: LiveMeta = INITIAL_META;
export const OFF_DATA: LiveData = initialLiveData("");

export type EffectiveState = "off" | "connecting" | "live" | "reconnecting" | "down" | "ended" | "error";

/** 화면(배지·갱신 방식)이 보는 최종 상태. 브라우저↔API 연결과 API↔증권사 연결을 합친다. */
export function effectiveState(m: LiveMeta): EffectiveState {
  switch (m.status) {
    case "off":
      return "off";
    case "error":
      return "error";
    case "ended":
      return "ended";
    case "connecting":
      return "connecting";
    case "reconnecting":
      return m.down ? "down" : "reconnecting";
    case "live": {
      const c = m.serverConnection;
      if (c === null || c === "connected") return "live";
      if ((c === "connecting" || c === "idle") && !m.everConnected) return "connecting";
      return m.down ? "down" : "reconnecting";
    }
    default:
      return "off";
  }
}

/**
 * 호가·체결·차트가 어느 데이터를 쓸지.
 * - `live`: 스트림 데이터 사용(폴링 안 함)  - `pending`: 첫 `snapshot`을 기다리는 중(폴링도 안 함)  - `fallback`: 기존 폴링 화면
 * 스트림이 열리지 않으면(404·403·429·503·네트워크 오류) 곧바로 `fallback`이다. 이미 받은 데이터가 있으면 끊겨도 마지막 값을 유지한다.
 */
export type LiveMode = "live" | "pending" | "fallback";

export function liveMode(m: LiveMeta): LiveMode {
  if (m.status === "off") return "fallback";
  if (m.hasSnapshot) return "live";
  if (m.status === "connecting" || m.status === "reconnecting" || m.status === "live") return "pending";
  return "fallback"; // error·ended
}
