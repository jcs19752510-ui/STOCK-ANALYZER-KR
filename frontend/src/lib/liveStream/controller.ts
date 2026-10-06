import type { LiveStore, Timers } from "./store.ts";
import type { LiveBar, LiveBook, LiveQuote, LiveSnapshot, LiveTick, ServerConnection } from "./types.ts";

/**
 * 브라우저 `EventSource` 수명 관리(연결·재연결·종료·오류 진단). React와 무관한 클래스라 Node에서 가짜 EventSource로 시험한다.
 * - 같은 주소로 연결을 딱 하나만 연다(`start`는 한 번, `stop`이면 닫고 다시 열지 않는다).
 * - 서버가 `end`를 보내면 닫고 **다시 연결하지 않는다**.
 * - 연결이 거절(HTTP 오류)되면 EventSource는 이유를 못 읽으므로 같은 주소를 `fetch`로 한 번 더 열어 JSON 오류 코드를 읽는다.
 *   (스트림이 열리면 즉시 취소한다. 스트림이 아닌 JSON 응답일 때만 코드를 읽는다.)
 */
export interface EventSourceLike {
  readonly readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  addEventListener(type: string, listener: (ev: { data?: string }) => void): void;
  close(): void;
}

export const ES_CONNECTING = 0;
export const ES_CLOSED = 2;

export interface ControllerOptions {
  url: string;
  store: LiveStore;
  createEventSource: (url: string) => EventSourceLike;
  fetchFn?: typeof fetch;
  timers?: Timers;
  /** 첫 `snapshot`을 받기 전에 이만큼 연속으로 실패하면 포기하고 기존 폴링으로 되돌아간다. */
  maxEarlyFailures?: number;
  backoffMs?: readonly number[];
}

const REAL_TIMERS: Timers = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
};

/** 다시 시도해도 소용없는 HTTP 상태 → 기본 오류 코드(응답 본문에 코드가 있으면 그것을 쓴다). */
const FATAL_STATUS: Record<number, string> = {
  401: "FORBIDDEN",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  429: "REALTIME_CAPACITY",
  503: "LOCAL_INTRADAY_NOT_CONFIGURED",
};

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function parse(raw: string | undefined): unknown {
  if (typeof raw !== "string") return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export class LiveStreamController {
  private readonly o: Required<Pick<ControllerOptions, "maxEarlyFailures" | "backoffMs">> & ControllerOptions;
  private es: EventSourceLike | null = null;
  private stopped = false;
  private ended = false;
  private failures = 0;
  private retryTimer: unknown = null;
  private diagAbort: AbortController | null = null;

  constructor(options: ControllerOptions) {
    this.o = { maxEarlyFailures: 3, backoffMs: [3000, 6000, 12000, 30000], ...options };
  }

  private get timers(): Timers {
    return this.o.timers ?? REAL_TIMERS;
  }

  start(): void {
    if (this.stopped || this.es) return;
    this.o.store.setStatus("connecting");
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.closeEs();
    this.diagAbort?.abort();
    this.diagAbort = null;
    if (this.retryTimer !== null) this.timers.clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  private closeEs(): void {
    const es = this.es;
    this.es = null;
    if (es) {
      es.onopen = null;
      es.onerror = null;
      es.close();
    }
  }

  private open(): void {
    if (this.stopped || this.ended) return;
    const es = this.o.createEventSource(this.o.url);
    this.es = es;
    const store = this.o.store;

    es.onopen = () => {
      if (this.es !== es) return;
      this.failures = 0;
      store.setStatus("live");
    };
    es.onerror = () => {
      if (this.es !== es || this.stopped || this.ended) return;
      if (es.readyState === ES_CLOSED) {
        // 연결이 거절됐다(HTTP 오류·잘못된 응답). 브라우저는 다시 시도하지 않는다 → 이유를 확인한다.
        this.closeEs();
        void this.diagnose();
        return;
      }
      // 연결이 끊겼고 브라우저가 서버가 알려 준 간격(retry: 3000)으로 다시 연결하는 중이다.
      this.failures += 1;
      if (!store.hasSnapshot() && this.failures >= this.o.maxEarlyFailures) {
        this.closeEs();
        store.setStatus("error", "NETWORK_ERROR");
        return;
      }
      store.setStatus(store.hasSnapshot() ? "reconnecting" : "connecting");
    };

    es.addEventListener("snapshot", (ev) => {
      const d = parse(ev.data);
      if (!isObj(d) || !Array.isArray(d.ticks) || !Array.isArray(d.bars)) return;
      store.dispatch({ type: "snapshot", data: d as unknown as LiveSnapshot });
    });
    es.addEventListener("tick", (ev) => {
      const d = parse(ev.data);
      if (isObj(d) && typeof d.price === "number" && typeof d.time === "string") store.dispatch({ type: "tick", data: d as unknown as LiveTick });
    });
    es.addEventListener("bar", (ev) => {
      const d = parse(ev.data);
      if (isObj(d) && typeof d.close === "number" && typeof d.time === "string") store.dispatch({ type: "bar", data: d as unknown as LiveBar });
    });
    es.addEventListener("quote", (ev) => {
      const d = parse(ev.data);
      if (isObj(d) && typeof d.price === "number") store.dispatch({ type: "quote", data: d as unknown as LiveQuote });
    });
    es.addEventListener("book", (ev) => {
      const d = parse(ev.data);
      if (isObj(d) && Array.isArray(d.asks) && Array.isArray(d.bids)) store.dispatch({ type: "book", data: d as unknown as LiveBook });
    });
    es.addEventListener("status", (ev) => {
      const d = parse(ev.data);
      if (isObj(d) && typeof d.connection === "string") store.setServerConnection(d.connection as ServerConnection);
    });
    es.addEventListener("end", (ev) => {
      const d = parse(ev.data);
      const reason = isObj(d) && typeof d.reason === "string" ? d.reason : "forbidden";
      this.ended = true; // 다시 연결하지 않는다
      this.closeEs();
      store.setStatus("ended", reason);
    });
  }

  /** 거절된 연결의 이유를 같은 주소를 `fetch`로 열어 확인한다. */
  private async diagnose(): Promise<void> {
    const store = this.o.store;
    const doFetch = this.o.fetchFn ?? (typeof fetch === "function" ? fetch : null);
    if (!doFetch) {
      store.setStatus("error", "NETWORK_ERROR");
      return;
    }
    const ac = new AbortController();
    this.diagAbort = ac;
    let res: Response;
    try {
      res = await doFetch(this.o.url, { cache: "no-store", signal: ac.signal, headers: { Accept: "application/json" } });
    } catch {
      if (this.stopped) return;
      this.transient();
      return;
    }
    if (this.stopped) {
      ac.abort();
      return;
    }
    const type = res.headers.get("content-type") ?? "";
    if (res.ok && type.includes("text/event-stream")) {
      ac.abort(); // 스트림이 열렸다(서버가 회복됨): 읽지 않고 닫고, 정상 경로로 다시 연결한다
      this.transient();
      return;
    }
    let code: string | null = null;
    try {
      const body: unknown = await res.json();
      if (isObj(body) && isObj(body.error) && typeof body.error.code === "string") code = body.error.code;
    } catch {
      code = null;
    }
    if (this.stopped) return;
    if (res.ok) {
      store.setStatus("error", code ?? "STREAM_UNAVAILABLE"); // 200인데 스트림이 아님(예: 로그인 화면으로 바뀜)
      return;
    }
    const fatal = FATAL_STATUS[res.status];
    if (fatal) {
      store.setStatus("error", code ?? fatal);
      return;
    }
    this.transient();
  }

  /** 잠깐의 오류(서버 5xx·네트워크): 간격을 늘려 가며 다시 연다. 처음부터 계속 실패하면 포기하고 폴링으로 되돌아간다. */
  private transient(): void {
    const store = this.o.store;
    if (this.stopped || this.ended) return;
    this.failures += 1;
    if (!store.hasSnapshot() && this.failures >= this.o.maxEarlyFailures) {
      store.setStatus("error", "NETWORK_ERROR");
      return;
    }
    store.setStatus(store.hasSnapshot() ? "reconnecting" : "connecting");
    const wait = this.o.backoffMs[Math.min(this.failures - 1, this.o.backoffMs.length - 1)];
    this.retryTimer = this.timers.setTimeout(() => {
      this.retryTimer = null;
      this.open();
    }, wait);
  }
}
