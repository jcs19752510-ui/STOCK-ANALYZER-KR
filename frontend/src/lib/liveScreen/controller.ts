/**
 * 장중 기준 재계산 화면(DEC-089, 계약서 §3·§4)의 조회 수명 관리 — 브라우저 쪽. 시간·요청·가시성은 주입해서(가짜로 바꿔) 시험한다(`scripts/check-live-screen.mjs`).
 *
 * - 자동 갱신: 성공할 때마다 `meta.live.refresh_seconds`(5~60초, 기본 10)만큼 뒤에 다시 묻는다. 탭이 가려지면 멈추고(진행 중 요청도 취소), 보이면 바로 한 번 묻는다.
 * - 일시정지: 그 순간의 `snapshot_id`에 고정한다. 쪽을 넘겨도 같은 `snapshot_id`를 보낸다. 410(`SNAPSHOT_EXPIRED`)이 오면 고정을 풀고 한 번 새로 계산한다(일시정지는 유지, 새 스냅샷에 다시 고정).
 * - 실패: 마지막 값은 그대로 두고(화면이 "지연"으로 표시) 간격을 기본 간격부터 두 배씩, 상한 30초로 늘려 다시 시도한다. 다시 묻지 않는 오류(`logic.retryPolicy`)는 멈춘다.
 * - 같은 주소의 요청이 진행 중이면 새로 보내지 않고, 다른 주소(조건·쪽 변경)면 이전 요청을 취소한다. 취소·교체된 요청의 늦은 응답은 버린다.
 * - 목록은 제자리에서 바꾼다: 새 응답이 올 때까지 이전 값을 지우지 않는다(조건이 바뀔 때만 비운다).
 */
import { MIN_REFRESH_SECONDS, applyChanges, mergeNames, nextBackoffMs } from "./logic.ts";
import { buildLiveUrl, mapLiveError, parseLiveSuccess, retryPolicy } from "./protocol.ts";
import { EMPTY_LIVE_VIEW, type LiveHttp, type LiveQuery, type LiveScreenView } from "./view.ts";
import type { LiveError } from "./types.ts";

export { EMPTY_LIVE_VIEW };
export type { LiveHttp, LiveQuery, LiveScreenView };

export interface ControllerDeps {
  request: (url: string, signal: AbortSignal) => Promise<LiveHttp>;
  baseUrl: string;
  onView: (view: LiveScreenView<never>) => void;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (id: unknown) => void;
  isHidden: () => boolean;
  /** 현재 시각(epoch 초) */
  now: () => number;
}

type Reason = "start" | "tick" | "retry" | "visible" | "manual" | "page" | "resume" | "expired";

interface Inflight {
  url: string;
  controller: AbortController;
  reason: Reason;
}

export class LiveScreenController<T extends { items: unknown[]; page: number }> {
  private view = EMPTY_LIVE_VIEW as unknown as LiveScreenView<T>;
  private timer: unknown = null;
  private inflight: Inflight | null = null;
  private stopped = false;
  private expiredRetried = false;
  private readonly deps: ControllerDeps;

  constructor(deps: ControllerDeps) {
    this.deps = deps;
  }

  get current(): LiveScreenView<T> {
    return this.view;
  }

  // ── 화면에서 부르는 동작 ───────────────────────────────────────────────

  /**
   * 조건을 정해 계산을 시작한다("조건 적용"). 같은 조건·같은 쪽이면 제자리 새로고침(새로 계산), 같은 조건의 다른 쪽이면 쪽 이동이다.
   * 조건이 다르면 이전 결과를 비우고 처음부터 시작한다. 일시정지 중이었다면 일시정지는 유지하고 새 결과의 스냅샷에 다시 고정한다.
   */
  setQuery(query: LiveQuery, page = 1): void {
    if (this.stopped) return;
    const cur = this.view.query;
    if (cur && cur.kind === query.kind && cur.params === query.params) {
      if (page === this.view.page) this.refreshNow();
      else this.setPage(page);
      return;
    }
    this.abortInflight();
    this.clearTimer();
    this.expiredRetried = false;
    this.view = {
      ...EMPTY_LIVE_VIEW,
      names: this.view.names,
      query,
      page,
      paused: this.view.paused,
      seq: this.view.seq,
    } as unknown as LiveScreenView<T>;
    this.emit({});
    this.run("start");
  }

  /** 쪽 이동. 일시정지 중이면 같은 `snapshot_id`로, 아니면 최신으로 요청한다. 새 응답이 올 때까지 현재 목록을 그대로 둔다. */
  setPage(page: number): void {
    if (this.stopped || !this.view.query) return;
    const next = Math.max(1, Math.floor(page));
    if (next === this.view.page && this.inflight) return;
    this.emit({ page: next });
    this.run("page");
  }

  /** "일시정지": 지금 보이는 결과의 스냅샷에 고정한다. 아직 결과가 없으면 아무것도 하지 않는다. */
  pause(): boolean {
    const meta = this.view.meta;
    if (this.stopped || this.view.paused || !meta || !this.view.query) return false;
    this.clearTimer();
    const pending = this.inflight;
    this.abortInflight();
    this.emit({ paused: true, pinnedSnapshotId: meta.snapshot_id, retryInMs: null, expiredNotice: false, loading: false });
    if (pending?.reason === "page") this.run("page"); // 쪽 이동 중이었다면 고정한 스냅샷으로 다시 요청
    return true;
  }

  /** 일시정지 해제: 고정을 풀고 바로 새로 계산해 자동 갱신을 다시 시작한다. */
  resume(): void {
    if (this.stopped || !this.view.paused) return;
    this.emit({ paused: false, pinnedSnapshotId: null, expiredNotice: false });
    this.run("resume");
  }

  /** "새로 계산": 지금 한 번 새로 계산한다(일시정지 중이면 새 스냅샷에 다시 고정). 서버 최소 계산 간격 안이면 서버가 직전 스냅샷을 줄 수 있다. */
  refreshNow(): void {
    if (this.stopped || !this.view.query) return;
    this.emit({ expiredNotice: false });
    this.run("manual");
  }

  /** 탭이 보이거나 가려질 때 부른다. */
  visibilityChanged(): void {
    if (this.stopped || !this.view.query) return;
    if (this.deps.isHidden()) {
      this.clearTimer();
      if (this.inflight) {
        this.abortInflight();
        this.emit({ loading: false });
      }
      return;
    }
    const err = this.view.error;
    if (err && retryPolicy(err.kind) === "none") return; // 다시 물어도 같은 오류: 사용자가 누를 때까지
    const needs = !this.view.paused || this.view.data === null || this.view.data.page !== this.view.page;
    if (needs) this.run("visible");
  }

  /** 켜짐을 끌 때: 요청·타이머를 정리하고 초기 상태로 돌아간다(다시 켜면 `setQuery`부터). */
  clearQuery(): void {
    this.abortInflight();
    this.clearTimer();
    this.expiredRetried = false;
    this.view = { ...EMPTY_LIVE_VIEW, names: this.view.names, seq: this.view.seq } as unknown as LiveScreenView<T>;
    this.emit({});
  }

  stop(): void {
    this.stopped = true;
    this.abortInflight();
    this.clearTimer();
  }

  // ── 내부 ───────────────────────────────────────────────────────────────

  private emit(patch: Partial<LiveScreenView<T>>): void {
    this.view = { ...this.view, ...patch, seq: this.view.seq + 1 };
    this.deps.onView(this.view as unknown as LiveScreenView<never>);
  }

  private clearTimer(): void {
    if (this.timer !== null) this.deps.clearTimeout(this.timer);
    this.timer = null;
  }

  private abortInflight(): void {
    this.inflight?.controller.abort();
    this.inflight = null;
  }

  private schedule(ms: number, reason: Reason): void {
    this.clearTimer();
    if (this.stopped) return;
    this.timer = this.deps.setTimeout(() => {
      this.timer = null;
      this.run(reason);
    }, ms);
  }

  private run(reason: Reason): void {
    const query = this.view.query;
    if (this.stopped || !query) return;
    if (this.deps.isHidden() && (reason === "tick" || reason === "retry")) return; // visibilityChanged()가 다시 깨운다
    this.clearTimer();
    // 일시정지 중에는 고정한 스냅샷으로 묻는다. 새로 계산("manual")·만료 뒤 재계산("expired")만 고정을 쓰지 않는다.
    const pin = this.view.paused && reason !== "manual" && reason !== "expired" ? this.view.pinnedSnapshotId : null;
    const url = buildLiveUrl(this.deps.baseUrl, query.kind, query.params, this.view.page, pin);
    if (this.inflight) {
      if (this.inflight.url === url) return; // 같은 요청이 이미 진행 중: 합친다
      this.abortInflight();
    }
    const controller = new AbortController();
    const mine: Inflight = { url, controller, reason };
    this.inflight = mine;
    if (!this.view.loading) this.emit({ loading: true });
    this.deps
      .request(url, controller.signal)
      .then((res) => {
        if (this.inflight !== mine || controller.signal.aborted || this.stopped) return; // 취소·교체된 요청의 늦은 응답은 버린다
        this.inflight = null;
        this.handle(res, reason);
      })
      .catch(() => {
        if (this.inflight !== mine || controller.signal.aborted || this.stopped) return;
        this.inflight = null;
        this.fail(mapLiveError(0, null), reason);
      });
  }

  private handle(res: LiveHttp, reason: Reason): void {
    if (res.status === 200) {
      const parsed = parseLiveSuccess<T>(res.body);
      if (!parsed) {
        this.fail(mapLiveError(200, res.body), reason);
        return;
      }
      const now = this.deps.now();
      const { data, meta, generatedAt } = parsed;
      this.expiredRetried = false;
      const paused = this.view.paused;
      this.emit({
        data,
        meta,
        receivedAt: now,
        generatedAt,
        loading: false,
        error: null,
        failures: 0,
        retryInMs: null,
        refreshSeconds: meta.refresh_seconds,
        pinnedSnapshotId: paused ? meta.snapshot_id : null,
        changeLog: applyChanges(this.view.changeLog, meta.snapshot_id, meta.as_of, meta.changes, now),
        names: mergeNames(this.view.names, data.items),
        expiredNotice: reason === "expired" ? true : this.view.expiredNotice,
      });
      if (!paused) this.schedule(meta.refresh_seconds * 1000, "tick");
      return;
    }
    this.fail(mapLiveError(res.status, res.body), reason);
  }

  private fail(error: LiveError, reason: Reason): void {
    const policy = retryPolicy(error.kind);
    if (policy === "immediate") {
      if (!this.expiredRetried) {
        // 고정한 계산 결과가 만료됨: 고정을 풀고 한 번 새로 계산한다(일시정지는 유지, 새 스냅샷에 다시 고정).
        this.expiredRetried = true;
        this.emit({ pinnedSnapshotId: null, loading: false });
        this.run("expired");
        return;
      }
      this.fail({ ...error, kind: "server" }, reason); // 새로 계산했는데도 만료로 오면 일반 오류로 취급(무한 반복 방지)
      return;
    }
    if (policy === "none") {
      // 다시 물어도 같은 오류: 더는 믿을 수 없는 이전 값을 지우고 멈춘다.
      this.emit({
        data: null,
        meta: null,
        receivedAt: null,
        generatedAt: null,
        paused: false,
        pinnedSnapshotId: null,
        loading: false,
        error,
        retryInMs: null,
      });
      this.clearTimer();
      return;
    }
    const base = (this.view.meta?.refresh_seconds ?? this.view.refreshSeconds) * 1000;
    let delay: number;
    let failures = this.view.failures;
    if (policy === "fast") {
      delay = MIN_REFRESH_SECONDS * 1000; // 진행 중인 준비 상태: 진행률을 보이며 짧은 고정 간격으로 다시 묻는다
    } else {
      failures += 1;
      delay = nextBackoffMs(base, failures);
    }
    const retry = !this.view.paused; // 일시정지 중에는 자동 재시도하지 않는다(사용자가 "새로 계산"을 누를 때까지 마지막 값 유지)
    this.emit({ loading: false, error, failures, retryInMs: retry ? delay : null });
    if (retry) this.schedule(delay, "retry");
  }
}
