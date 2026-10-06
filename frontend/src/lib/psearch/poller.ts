/**
 * 증권사 조건검색 결과 주기 조회(DEC-088, 계약서 §5) — 브라우저 쪽 수명 관리. 시간·요청·가시성은 주입해서 시험한다(`liveMarket/poller.ts`와 같은 방식).
 * - 간격: `max(5초, cache_ttl_seconds)`(서버 상한 60초). 응답마다 서버가 알려 준 값으로 다시 계산한다.
 * - 탭이 가려지면 조회를 멈추고(진행 중 요청도 취소), 다시 보이면 바로 한 번 조회한다.
 * - 401·403·404·503은 이 화면을 쓸 수 없다는 뜻이라 다시 묻지 않는다(`unavailable`). 400(INVALID_SEQ)도 같은 조건으로는 다시 물어도 같으므로 멈춘다(`fatal`, 조건을 바꾸면 풀림).
 * - 429·502·네트워크 오류·모양이 어긋난 응답은 간격을 두 배씩 늘려(상한 30초) 다시 시도하고, 마지막 값은 지우지 않는다(`failing`).
 * - 조건이 바뀌면 진행 중 요청을 취소하고, 늦게 도착한 이전 조건의 응답은 버린다(세대 번호 + 응답의 seq 확인).
 */
import {
  UNAVAILABLE_STATUS,
  backoffMs,
  diffCodes,
  errorInfo,
  intervalMs,
  mergeNames,
  normalizeResults,
  MIN_POLL_MS,
  type PsearchHttp,
  type PsearchResults,
} from "./logic.ts";

export interface PsearchErrorInfo {
  status: number;
  code: string | null;
  message: string | null;
}

/** 화면 낭독용 사건. 같은 사건이 되풀이되지 않게 번호(`id`)가 바뀔 때만 새 사건이다. */
export interface PsearchEvent {
  id: number;
  kind: "loaded" | "changed" | "failing" | "recovered";
  /** 사건이 일어난 시각(브라우저 epoch 초) */
  at: number;
  count: number;
  added: number;
  removed: number;
}

export interface PsearchView {
  /** 이 값이 어느 조건(seq)의 것인지. 화면이 선택한 조건과 다르면 아직 바뀌는 중이다. */
  seq: string | null;
  data: PsearchResults | null;
  /** 마지막으로 성공 응답을 받은 시각(브라우저 epoch 초) */
  receivedAt: number | null;
  /** 본 적 있는 종목 이름(이탈 종목 표시용) */
  names: Record<string, string>;
  /** 쓸 수 없는 상태(다시 묻지 않음). 값이 있으면 결과는 비어 있다. */
  unavailable: PsearchErrorInfo | null;
  /** 같은 조건으로는 다시 물어도 소용없는 오류(INVALID_SEQ) */
  fatal: PsearchErrorInfo | null;
  /** 최근 조회가 실패 중(마지막 값은 남아 있을 수 있음) */
  failing: boolean;
  failures: number;
  lastError: PsearchErrorInfo | null;
  /** 실패 중일 때 다음 시도까지 간격(ms) */
  retryInMs: number | null;
  /** 정상일 때 조회 간격(ms) */
  intervalMs: number;
  event: PsearchEvent | null;
}

export const EMPTY_PSEARCH_VIEW: PsearchView = {
  seq: null,
  data: null,
  receivedAt: null,
  names: {},
  unavailable: null,
  fatal: null,
  failing: false,
  failures: 0,
  lastError: null,
  retryInMs: null,
  intervalMs: MIN_POLL_MS,
  event: null,
};

/** 탭이 다시 보일 때 바로 조회하되, 직전 요청 시작과 이 간격(ms)은 둔다(탭을 빠르게 껐다 켜도 요청이 몰리지 않게). */
export const MIN_GAP_MS = 1000;

export interface PollerDeps {
  request: (url: string, signal: AbortSignal) => Promise<PsearchHttp>;
  baseUrl: string;
  onView: (view: PsearchView) => void;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (id: unknown) => void;
  isHidden: () => boolean;
  /** 현재 시각(epoch 초) */
  now: () => number;
}

export class PsearchPoller {
  private seq: string | null = null;
  private timer: unknown = null;
  private controller: AbortController | null = null;
  private view: PsearchView = EMPTY_PSEARCH_VIEW;
  private failures = 0;
  private running = false;
  private stopped = false;
  private generation = 0;
  private eventId = 0;
  private lastStartAt: number | null = null;

  private readonly deps: PollerDeps;

  constructor(deps: PollerDeps) {
    this.deps = deps;
  }

  get current(): PsearchView {
    return this.view;
  }

  /** 조건을 바꾼다(null이면 조회하지 않음). 같은 조건이면 아무것도 하지 않는다. */
  setSeq(seq: string | null): void {
    if (seq === this.seq) return;
    this.seq = seq;
    this.generation += 1;
    this.failures = 0;
    this.abort();
    this.clearTimer();
    // 쓸 수 없음(unavailable)은 조건과 무관해서 유지하고, 나머지는 새 조건으로 처음부터 시작한다.
    this.view = { ...EMPTY_PSEARCH_VIEW, seq, unavailable: this.view.unavailable, event: this.view.event };
    this.deps.onView(this.view);
    this.schedule(0);
  }

  /** 탭 가시성이 바뀌었을 때 부른다. */
  visibilityChanged(): void {
    if (this.stopped) return;
    if (this.deps.isHidden()) {
      this.abort();
      this.clearTimer();
      return;
    }
    if (this.running || this.seq === null) return;
    const sinceMs = this.lastStartAt === null ? Infinity : (this.deps.now() - this.lastStartAt) * 1000;
    this.schedule(Math.max(0, MIN_GAP_MS - sinceMs));
  }

  stop(): void {
    this.stopped = true;
    this.abort();
    this.clearTimer();
  }

  private blocked(): boolean {
    return this.stopped || this.seq === null || this.view.unavailable !== null || this.view.fatal !== null;
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
    if (this.blocked()) return;
    this.clearTimer();
    if (this.deps.isHidden()) return; // visibilityChanged()가 다시 깨운다
    this.timer = this.deps.setTimeout(() => void this.tick(), ms);
  }

  private emit(patch: Partial<PsearchView>): void {
    this.view = { ...this.view, ...patch };
    this.deps.onView(this.view);
  }

  private async tick(): Promise<void> {
    this.timer = null;
    const seq = this.seq;
    if (this.blocked() || seq === null || this.deps.isHidden()) return;
    const gen = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    this.running = true;
    this.lastStartAt = this.deps.now();
    let res: PsearchHttp;
    try {
      res = await this.deps.request(
        `${this.deps.baseUrl}/api/v1/local/psearch/results?seq=${encodeURIComponent(seq)}`,
        controller.signal,
      );
    } catch {
      if (controller.signal.aborted || gen !== this.generation || this.stopped) return;
      this.running = false;
      this.fail({ status: 0, code: "NETWORK_ERROR", message: null });
      return;
    }
    if (controller.signal.aborted || gen !== this.generation || this.stopped) return; // 조건이 바뀌었거나 멈춤: 늦은 응답은 버린다
    this.running = false;

    if (UNAVAILABLE_STATUS.has(res.status)) {
      const { code, message } = errorInfo(res.body);
      this.clearTimer();
      this.emit({
        ...EMPTY_PSEARCH_VIEW,
        seq,
        names: this.view.names,
        unavailable: { status: res.status, code, message },
        event: this.view.event,
      });
      return;
    }
    if (res.status === 400) {
      const { code, message } = errorInfo(res.body);
      if (code === "INVALID_SEQ") {
        this.clearTimer();
        this.emit({ data: null, receivedAt: null, failing: false, retryInMs: null, fatal: { status: 400, code, message } });
        return;
      }
    }
    const data = res.status === 200 ? normalizeResults(res.body, seq) : null;
    if (!data) {
      const { code, message } = errorInfo(res.body);
      this.fail({ status: res.status, code: code ?? (res.status === 200 ? "BAD_RESPONSE" : null), message });
      return;
    }

    const prev = this.view.data;
    const wasFailing = this.view.failing;
    const diff = prev ? diffCodes(prev.items, data.items) : { added: 0, removed: 0 };
    const at = this.deps.now();
    let event = this.view.event;
    if (!prev) event = this.makeEvent("loaded", at, data.items.length, 0, 0);
    else if (diff.added > 0 || diff.removed > 0) event = this.makeEvent("changed", at, data.items.length, diff.added, diff.removed);
    else if (wasFailing) event = this.makeEvent("recovered", at, data.items.length, 0, 0);

    this.failures = 0;
    const interval = intervalMs(data.cache_ttl_seconds);
    this.emit({
      data,
      receivedAt: at,
      names: mergeNames(this.view.names, data.items),
      failing: false,
      failures: 0,
      lastError: null,
      retryInMs: null,
      intervalMs: interval,
      event,
    });
    this.schedule(interval);
  }

  private makeEvent(kind: PsearchEvent["kind"], at: number, count: number, added: number, removed: number): PsearchEvent {
    this.eventId += 1;
    return { id: this.eventId, kind, at, count, added, removed };
  }

  private fail(error: PsearchErrorInfo): void {
    this.failures += 1;
    const base = intervalMs(this.view.data?.cache_ttl_seconds);
    const delay = backoffMs(base, this.failures);
    const hadData = this.view.data !== null;
    const event = hadData && !this.view.failing ? this.makeEvent("failing", this.deps.now(), this.view.data?.items.length ?? 0, 0, 0) : this.view.event;
    this.emit({ failing: true, failures: this.failures, lastError: error, retryInMs: delay, event });
    this.schedule(delay);
  }
}
