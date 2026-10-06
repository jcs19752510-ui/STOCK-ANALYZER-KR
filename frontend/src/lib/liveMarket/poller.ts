/**
 * 전 종목 준실시간 시세 조회 수명 관리(DEC-084 B) — 브라우저 쪽. 보이는 종목 코드만 `GET /api/v1/local/market/quotes`로 주기 조회한다.
 * - 주기: 서버가 알려 준 한 바퀴 시간(`cycle_seconds`)의 절반, 3~15초(서버 호출 한도 600/분보다 훨씬 낮다). 첫 응답이 비어 있으면 2초 간격으로 다시 묻는다.
 * - 탭이 가려지면 조회를 멈추고, 다시 보이면 바로 한 번 조회한다.
 * - 권한 없음·기능 꺼짐·앱키 없음(401/403/404/503)은 이 화면에서 쓸 수 없다는 뜻이라 다시 묻지 않는다(`unavailable`). 한도 초과·네트워크 오류는 간격을 늘려 재시도한다.
 * - 코드 목록이 바뀌면 진행 중인 요청을 취소하고 새 목록으로 즉시 조회한다.
 * 시간·요청·가시성은 주입해서(가짜로 바꿔) 시험한다.
 */
import { EMPTY_LIVE_VIEW, type LiveMarketMeta, type LiveMarketQuote, type LiveMarketView } from "./merge.ts";

export const MARKET_CHUNK = 100;
export const MIN_POLL_MS = 3000;
export const MAX_POLL_MS = 15000;
export const EMPTY_RETRY_MS = 2000;
export const MAX_BACKOFF_MS = 30000;
const UNAVAILABLE_STATUS = new Set([401, 403, 404, 503]);

export interface MarketResponse {
  status: number;
  body: { data?: { quotes?: LiveMarketQuote[]; missing?: string[]; meta?: LiveMarketMeta } | null } | null;
}

export interface PollerDeps {
  request: (url: string, signal: AbortSignal) => Promise<MarketResponse>;
  baseUrl: string;
  onView: (view: LiveMarketView) => void;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (id: unknown) => void;
  isHidden: () => boolean;
  /** 현재 시각(epoch 초) */
  now: () => number;
}

export function nextDelayMs(meta: LiveMarketMeta | null, gotAny: boolean): number {
  if (!gotAny) return EMPTY_RETRY_MS;
  const cycle = meta?.cycle_seconds;
  const half = typeof cycle === "number" && Number.isFinite(cycle) ? (cycle * 1000) / 2 : 10000;
  return Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, half));
}

export class LiveMarketPoller {
  private codes: string[] = [];
  private timer: unknown = null;
  private controller: AbortController | null = null;
  private view: LiveMarketView = EMPTY_LIVE_VIEW;
  private failures = 0;
  private running = false;
  private stopped = false;
  private generation = 0;

  private readonly deps: PollerDeps;

  constructor(deps: PollerDeps) {
    this.deps = deps;
  }

  get current(): LiveMarketView {
    return this.view;
  }

  setCodes(codes: readonly string[]): void {
    const next = [...new Set(codes)];
    if (next.join(",") === this.codes.join(",")) return;
    this.codes = next;
    this.generation += 1;
    this.view = { ...this.view, quotes: {} };
    this.deps.onView(this.view);
    this.abort();
    this.schedule(0);
  }

  /** 탭 가시성이 바뀌었을 때 부른다. */
  visibilityChanged(): void {
    if (!this.deps.isHidden() && !this.running) this.schedule(0);
  }

  stop(): void {
    this.stopped = true;
    this.abort();
    this.clearTimer();
  }

  private abort(): void {
    this.controller?.abort();
    this.controller = null;
    this.running = false;
  }

  private clearTimer(): void {
    if (this.timer !== null) this.deps.clearTimeout(this.timer);
    this.timer = null;
  }

  private schedule(ms: number): void {
    if (this.stopped || this.view.unavailable) return;
    this.clearTimer();
    this.timer = this.deps.setTimeout(() => void this.tick(), ms);
  }

  private async tick(): Promise<void> {
    this.timer = null;
    if (this.stopped || this.view.unavailable || this.codes.length === 0) return;
    if (this.deps.isHidden()) return; // visibilityChanged()가 다시 깨운다
    const gen = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    this.running = true;
    const quotes: Record<string, LiveMarketQuote> = {};
    let meta: LiveMarketMeta | null = null;
    try {
      for (let i = 0; i < this.codes.length; i += MARKET_CHUNK) {
        const url = `${this.deps.baseUrl}/api/v1/local/market/quotes?codes=${this.codes.slice(i, i + MARKET_CHUNK).join(",")}`;
        const res = await this.deps.request(url, controller.signal);
        if (gen !== this.generation || this.stopped) return;
        if (UNAVAILABLE_STATUS.has(res.status)) {
          this.running = false;
          this.view = { ...EMPTY_LIVE_VIEW, unavailable: true };
          this.deps.onView(this.view);
          return;
        }
        const data = res.body?.data;
        if (res.status !== 200 || !data) throw new Error(`status ${res.status}`);
        for (const q of data.quotes ?? []) quotes[q.code] = q;
        meta = data.meta ?? meta;
      }
    } catch {
      if (controller.signal.aborted || gen !== this.generation || this.stopped) return;
      this.running = false;
      this.failures += 1;
      this.view = { ...this.view, failing: true };
      this.deps.onView(this.view);
      this.schedule(Math.min(MAX_BACKOFF_MS, MIN_POLL_MS * 2 ** this.failures));
      return;
    }
    this.running = false;
    this.failures = 0;
    this.view = { quotes, meta, unavailable: false, receivedAt: this.deps.now(), failing: false };
    this.deps.onView(this.view);
    this.schedule(nextDelayMs(meta, Object.keys(quotes).length > 0));
  }
}
