/**
 * 장중 기준 재계산 화면(DEC-089/090) 순수 로직 — 계약서 `docs/stock-detail/10-intraday-rescreen-contract.md` §3·§4.
 * 시간·요청·화면 상태를 모르는 함수만 둔다(React 없음). `scripts/check-live-screen.mjs`가 가짜 시계로 시험한다.
 * 최상위 목표(실시간을 정확하게, 지연·불일치는 숨기지 않는다)에 따라: 모양이 어긋난 응답은 성공으로 받아들이지 않고, 오래된 값은 "지연"으로 드러낸다.
 */
import type { LiveBaseFill, LiveChanges, LiveError, LiveErrorKind, LiveMeta, LiveScreenKind } from "./types.ts";

export const DEFAULT_REFRESH_SECONDS = 10;
export const MIN_REFRESH_SECONDS = 5;
export const MAX_REFRESH_SECONDS = 60;
export const MAX_BACKOFF_MS = 30000;
/** 마지막 성공이 `refresh_seconds`의 이 배수를 넘으면 "지연". */
export const DELAYED_FACTOR = 3;
/** 시세 수신 비율이 이 값 미만이면 등락률 순위는 일봉 기준이라고 알린다(계약 §0-3). */
export const COVERAGE_MIN = 0.9;
export const NEW_WINDOW_SEC = 60;
export const MAX_RECENT_CHANGES = 10;
export const MAX_CHANGE_CODES = 100;
export const MAX_NAMES = 2000;
export const TOGGLE_STORAGE_KEY = "stock.liveScreen.on";

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);
const nonNegInt = (v: unknown): number => (finite(v) && v >= 0 ? Math.floor(v) : 0);

// ── 요청 주소 ────────────────────────────────────────────────────────────

export const LIVE_SCREEN_PATH: Record<LiveScreenKind, string> = {
  screen: "/api/v1/local/screen",
  pattern: "/api/v1/local/screen/pattern",
};

/** 조회 조건(쪽·스냅샷 제외) 문자열. 일봉 화면과 같은 파라미터를 쓰므로 기존 빌더의 결과에서 `page`·`snapshot_id`만 뺀다. */
export function stripLiveParams(search: string | URLSearchParams): string {
  const params = new URLSearchParams(typeof search === "string" ? search : search.toString());
  params.delete("page");
  params.delete("snapshot_id");
  return params.toString();
}

/** `base` 끝 슬래시는 무시. `snapshotId`가 있으면 그 스냅샷에 고정해 달라는 요청이다. */
export function buildLiveUrl(base: string, kind: LiveScreenKind, params: string, page: number, snapshotId: string | null): string {
  const qs = new URLSearchParams(params);
  qs.set("page", String(Math.max(1, Math.floor(page))));
  if (snapshotId) qs.set("snapshot_id", snapshotId);
  return `${base.replace(/\/$/, "")}${LIVE_SCREEN_PATH[kind]}?${qs.toString()}`;
}

// ── 간격·지연 ────────────────────────────────────────────────────────────

/** 서버가 알려 준 `refresh_seconds`를 5~60초로 보정. 숫자가 아니면 기본 10초. */
export function clampRefreshSeconds(v: unknown): number {
  if (!finite(v)) return DEFAULT_REFRESH_SECONDS;
  return Math.min(MAX_REFRESH_SECONDS, Math.max(MIN_REFRESH_SECONDS, Math.round(v)));
}

/** 연속 실패 `failures`(1부터)번째 재시도 간격(ms): 기본 간격에서 시작해 두 배씩, 상한 30초. */
export function nextBackoffMs(baseMs: number, failures: number): number {
  const n = Math.max(1, Math.floor(failures));
  return Math.min(MAX_BACKOFF_MS, Math.max(1, baseMs) * 2 ** Math.min(n - 1, 10));
}

/** 마지막 성공이 `refresh_seconds`의 3배보다 오래됐으면 지연. 아직 성공이 없으면 지연으로 보지 않는다(로딩 상태). */
export function isDelayed(nowSec: number, lastSuccessAt: number | null, refreshSeconds: number): boolean {
  if (lastSuccessAt === null) return false;
  return nowSec - lastSuccessAt > DELAYED_FACTOR * clampRefreshSeconds(refreshSeconds);
}

/**
 * 계산 시각 기준 경과 초. 서버·브라우저 시계가 어긋나도 흔들리지 않게, 응답을 받은 순간의 나이는 서버 시각(`generatedAtSec`, 응답 봉투)에서 `as_of`를 빼서 구하고
 * 그 뒤 브라우저에서 흐른 시간만 더한다. 서버 시각을 모르면 브라우저 시계로 계산한다.
 */
export function dataAgeSeconds(asOf: number, receivedAt: number, nowSec: number, generatedAtSec: number | null): number {
  const atReceipt = generatedAtSec !== null ? generatedAtSec - asOf : receivedAt - asOf;
  return Math.max(0, atReceipt) + Math.max(0, nowSec - receivedAt);
}

export function parseGeneratedAt(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms / 1000 : null;
}

// ── 응답 정리 ────────────────────────────────────────────────────────────

const FILL_STATES = new Set(["none", "running", "ready", "failed"]);

export function parseBaseFill(raw: unknown): LiveBaseFill {
  if (!isObj(raw)) return { gap_days: 0, state: "none", done: 0, total: 0, filled: 0, excluded: 0, mismatched: 0, pending: 0, source: null };
  const state = typeof raw.state === "string" && FILL_STATES.has(raw.state) ? (raw.state as LiveBaseFill["state"]) : "none";
  return {
    gap_days: nonNegInt(raw.gap_days),
    state,
    done: nonNegInt(raw.done),
    total: nonNegInt(raw.total),
    filled: nonNegInt(raw.filled),
    excluded: nonNegInt(raw.excluded),
    mismatched: nonNegInt(raw.mismatched),
    pending: nonNegInt(raw.pending),
    source: raw.source === "kis_daily_price" ? "kis_daily_price" : null,
  };
}

function codes(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return [...new Set(v.filter((x): x is string => typeof x === "string" && x !== ""))].slice(0, MAX_CHANGE_CODES);
}

export function parseChanges(raw: unknown): LiveChanges | null {
  if (!isObj(raw)) return null;
  return { entered: codes(raw.entered), left: codes(raw.left) };
}

/** `meta.live` → 정리한 값. 스냅샷 id·계산 시각이 없으면 null(성공으로 받아들이지 않는다). */
export function parseLiveMeta(raw: unknown): LiveMeta | null {
  if (!isObj(raw)) return null;
  const snapshotId = str(raw.snapshot_id);
  if (snapshotId === null || !finite(raw.as_of)) return null;
  const covered = nonNegInt(raw.quotes_covered);
  const total = nonNegInt(raw.quotes_total);
  const ratio = finite(raw.coverage_ratio) ? Math.min(1, Math.max(0, raw.coverage_ratio)) : total > 0 ? covered / total : 0;
  const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  return {
    snapshot_id: snapshotId,
    as_of: raw.as_of,
    basis_trade_date: str(raw.basis_trade_date) ?? "",
    expected_trade_date: str(raw.expected_trade_date) ?? "",
    today: str(raw.today) ?? "",
    quotes_covered: covered,
    quotes_total: total,
    coverage_ratio: ratio,
    oldest_quote_age_seconds: finite(raw.oldest_quote_age_seconds) ? raw.oldest_quote_age_seconds : null,
    stale: raw.stale === true,
    volume_partial: true, // 항상 true(계약 §3): 서버가 빠뜨려도 경고는 숨기지 않는다
    recomputed: strings(raw.recomputed),
    fixed_daily: strings(raw.fixed_daily),
    return_rank_policy: raw.return_rank_policy === "live" ? "live" : "daily",
    compute_ms: finite(raw.compute_ms) ? raw.compute_ms : 0,
    refresh_seconds: clampRefreshSeconds(raw.refresh_seconds),
    priority_codes: nonNegInt(raw.priority_codes),
    priority_cycle_seconds: finite(raw.priority_cycle_seconds) ? raw.priority_cycle_seconds : null,
    base_fill: parseBaseFill(raw.base_fill),
    changes: parseChanges(raw.changes),
  };
}

export interface ParsedLiveData<T> {
  data: T;
  meta: LiveMeta;
  generatedAt: number | null;
}

/** 목록 응답의 최소 모양 확인(항목 배열·총건수·쪽). 화면이 쓰는 필드가 없으면 성공으로 받아들이지 않는다. */
export function isListData(data: unknown): data is { items: unknown[]; total_count: number; page: number } {
  return isObj(data) && Array.isArray(data.items) && finite(data.total_count) && finite(data.page);
}

/** 200 응답 본문 → 데이터·`meta.live`. 어긋나면 null. */
export function parseLiveSuccess<T>(body: unknown): ParsedLiveData<T> | null {
  if (!isObj(body) || !isObj(body.data) || !isObj(body.meta)) return null;
  if (!isListData(body.data)) return null;
  const meta = parseLiveMeta(body.meta.live);
  if (!meta) return null;
  return { data: body.data as T, meta, generatedAt: parseGeneratedAt(body.meta.generated_at) };
}

// ── 오류 매핑 ────────────────────────────────────────────────────────────

/** 503이어도 일시 장애가 아니라 설정·기능 문제로 보는 코드(다시 묻지 않음). */
const UNAVAILABLE_CODES = new Set(["FEATURE_DISABLED", "LOCAL_INTRADAY_NOT_CONFIGURED", "LOCAL_INTRADAY_MISCONFIGURED", "LOCAL_MODE_REQUIRED", "INTRADAY_AUTH_FAILED"]);

function errorParts(body: unknown): { code: string | null; message: string | null; details: unknown } {
  const err = isObj(body) && isObj(body.error) ? body.error : null;
  return { code: err ? str(err.code) : null, message: err ? (str(err.message)?.slice(0, 300) ?? null) : null, details: err ? err.details : null };
}

function progressOf(details: unknown): { done: number; total: number; gap_days: number | null } | null {
  if (!isObj(details)) return null;
  const done = finite(details.done) ? Math.max(0, Math.floor(details.done)) : null;
  const total = finite(details.total) ? Math.max(0, Math.floor(details.total)) : null;
  if (done === null || total === null) return null;
  return { done: total > 0 ? Math.min(done, total) : done, total, gap_days: finite(details.gap_days) ? Math.max(0, Math.floor(details.gap_days)) : null };
}

/** 상태 코드와 응답 본문 → 화면이 구분하는 오류. `status` 0은 연결 실패. */
export function mapLiveError(status: number, body: unknown): LiveError {
  const { code, message, details } = errorParts(body);
  const make = (kind: LiveErrorKind, progress: LiveError["progress"] = null): LiveError => ({ kind, status, code, message, progress });
  // 코드가 가장 정확한 단서다(웹 서버 대행이 상태를 그대로 전달하지만 코드부터 본다).
  if (code === "SNAPSHOT_EXPIRED" || status === 410) return make("snapshot_expired");
  if (code === "LIVE_BASE_STALE") return make("base_stale");
  if (code === "LIVE_BASE_FILLING") return make("base_filling", progressOf(details));
  if (code === "LIVE_QUOTES_NOT_READY") return make("quotes_not_ready");
  if (status === 0) return make("network");
  if (status === 401 || status === 403) return make("forbidden");
  if (status === 404) return make("not_found");
  if (status === 400) return make("invalid");
  if (status === 429 || code === "RATE_LIMITED") return make("rate_limited");
  if (status === 503 && code !== null && UNAVAILABLE_CODES.has(code)) return make("unavailable");
  if (status === 200) return make("bad_response");
  return make("server");
}

/** 오류 종류별 재시도 방식: none=다시 묻지 않음, fast=짧은 고정 간격(진행 중 상태), backoff=간격을 늘려 재시도, immediate=바로 새로 계산. */
export type RetryPolicy = "none" | "fast" | "backoff" | "immediate";

export function retryPolicy(kind: LiveErrorKind): RetryPolicy {
  switch (kind) {
    case "base_stale":
    case "forbidden":
    case "not_found":
    case "unavailable":
    case "invalid":
      return "none";
    case "base_filling":
    case "quotes_not_ready":
      return "fast";
    case "snapshot_expired":
      return "immediate";
    default:
      return "backoff";
  }
}

/** 이 오류가 나면 더는 믿을 수 없는 이전 값을 지운다(다시 묻지 않는 종류). */
export function clearsData(kind: LiveErrorKind): boolean {
  return retryPolicy(kind) === "none";
}

// ── 편입·이탈 기록("신규" 표지·최근 변화) ────────────────────────────────

export interface ChangeRecord {
  /** 이 스냅샷의 계산 시각(서버 epoch 초) — 화면에 HH:MM:SS로 보인다 */
  at: number;
  snapshotId: string;
  entered: string[];
  left: string[];
}

export interface ChangeLog {
  /** 마지막으로 반영한 스냅샷 id. 같은 스냅샷이 다시 오면(최소 계산 간격 안 재사용·일시정지 중 페이지 이동) 다시 반영하지 않는다. */
  appliedSnapshotId: string | null;
  /** 코드 → 신규로 처음 본 시각(브라우저 epoch 초). 서버 시계와 무관하게 60초를 잰다. */
  entered: Record<string, number>;
  recent: ChangeRecord[];
}

export const EMPTY_CHANGE_LOG: ChangeLog = { appliedSnapshotId: null, entered: {}, recent: [] };

/**
 * 새 스냅샷의 `changes`를 기록에 반영한다. 첫 계산(`changes` null)은 신규 표지를 만들지 않는다.
 * 같은 스냅샷을 다시 받으면 같은 객체를 돌려준다. 내용 없는 변화는 목록에 올리지 않는다.
 */
export function applyChanges(log: ChangeLog, snapshotId: string, asOf: number, changes: LiveChanges | null, receivedAt: number): ChangeLog {
  if (log.appliedSnapshotId === snapshotId) return log;
  const entered = { ...log.entered };
  for (const [code, at] of Object.entries(entered)) if (receivedAt - at > NEW_WINDOW_SEC) delete entered[code];
  let recent = log.recent;
  if (changes && (changes.entered.length > 0 || changes.left.length > 0)) {
    for (const code of changes.entered) entered[code] = receivedAt;
    for (const code of changes.left) delete entered[code]; // 빠진 종목은 신규가 아니다
    recent = [{ at: asOf, snapshotId, entered: changes.entered, left: changes.left }, ...recent].slice(0, MAX_RECENT_CHANGES);
  }
  return { appliedSnapshotId: snapshotId, entered, recent };
}

/** 지금 "신규"로 보일 종목(편입 후 60초 이내). */
export function newCodes(log: ChangeLog, nowSec: number): Set<string> {
  const out = new Set<string>();
  for (const [code, at] of Object.entries(log.entered)) if (nowSec - at <= NEW_WINDOW_SEC) out.add(code);
  return out;
}

/** 가장 먼저 신규가 끝나는 때까지(ms). 신규 종목이 없으면 null. 그때 한 번 다시 그린다. */
export function nextNewExpiryMs(log: ChangeLog, nowSec: number): number | null {
  let min: number | null = null;
  for (const at of Object.values(log.entered)) {
    const remain = at + NEW_WINDOW_SEC - nowSec;
    if (remain < 0) continue;
    const ms = Math.ceil(remain * 1000) + 250;
    if (min === null || ms < min) min = ms;
  }
  return min;
}

/** 본 적 있는 종목 이름 장부(이탈 종목도 이름으로 보이게). 바뀐 것이 없으면 같은 객체. */
export function mergeNames(book: Record<string, string>, items: readonly unknown[]): Record<string, string> {
  let next: Record<string, string> | null = null;
  for (const raw of items) {
    if (!isObj(raw)) continue;
    const code = str(raw.stock_code);
    const name = str(raw.name);
    if (code && name && book[code] !== name) {
      next ??= { ...book };
      next[code] = name;
    }
  }
  if (!next) return book;
  const keys = Object.keys(next);
  if (keys.length > MAX_NAMES) for (const k of keys.slice(0, keys.length - MAX_NAMES)) delete next[k];
  return next;
}

export function stockLabel(code: string, names: Record<string, string>): string {
  return names[code] ? `${names[code]}(${code})` : code;
}

export interface ChangeRow {
  key: string;
  at: number;
  entered: string[];
  enteredMore: number;
  left: string[];
  leftMore: number;
}

export const MAX_NAMES_PER_ROW = 5;

export function changeRows(recent: readonly ChangeRecord[], names: Record<string, string>): ChangeRow[] {
  return recent.slice(0, MAX_RECENT_CHANGES).map((r) => ({
    key: r.snapshotId,
    at: r.at,
    entered: r.entered.slice(0, MAX_NAMES_PER_ROW).map((c) => stockLabel(c, names)),
    enteredMore: Math.max(0, r.entered.length - MAX_NAMES_PER_ROW),
    left: r.left.slice(0, MAX_NAMES_PER_ROW).map((c) => stockLabel(c, names)),
    leftMore: Math.max(0, r.left.length - MAX_NAMES_PER_ROW),
  }));
}

// ── 기준 배너 모델 ───────────────────────────────────────────────────────

export interface BannerNotices {
  stale: boolean;
  lowCoverage: boolean;
  /** 증권사 일봉 보충 진행 중 */
  baseFillRunning: boolean;
  /** 보충으로 이어 붙여 계산함(진행 끝남, 뒤처진 날이 있었음) */
  baseFillUsed: boolean;
  baseFillFailed: boolean;
  /** 보충이 안 되어 결과에서 제외된 종목 수 */
  excluded: number;
  mismatched: number;
  /** 아직 보충 결과가 정해지지 않은 종목 수("보충 중") */
  pending: number;
}

export function bannerNotices(meta: LiveMeta): BannerNotices {
  const f = meta.base_fill;
  return {
    stale: meta.stale,
    lowCoverage: meta.coverage_ratio < COVERAGE_MIN || meta.return_rank_policy === "daily",
    baseFillRunning: f.state === "running",
    baseFillUsed: f.state === "ready" && f.gap_days > 0,
    baseFillFailed: f.state === "failed",
    excluded: f.excluded,
    mismatched: f.mismatched,
    pending: f.pending,
  };
}

// ── 낭독(상태가 바뀔 때만) ───────────────────────────────────────────────

export interface StatusInput {
  hasData: boolean;
  paused: boolean;
  delayed: boolean;
  errorKind: LiveErrorKind | null;
  baseFillState: LiveBaseFill["state"] | null;
  stale: boolean;
  expiredNotice: boolean;
}

/**
 * 화면 낭독 영역(aria-live polite)에 알릴 상태의 열쇠. 열쇠가 바뀔 때만 낭독하므로 10초마다 목록이 바뀌어도 읽지 않는다.
 * 값(시각·건수)은 열쇠에 넣지 않는다.
 */
export function statusKey(s: StatusInput): string {
  if (s.errorKind) return `error:${s.errorKind}${s.hasData ? ":data" : ""}`;
  if (!s.hasData) return "loading";
  const parts = ["ok"];
  if (s.paused) parts.push("paused");
  if (s.delayed) parts.push("delayed");
  if (s.stale) parts.push("quotes-stale");
  if (s.baseFillState === "running") parts.push("fill-running");
  if (s.expiredNotice) parts.push("expired");
  return parts.join("+");
}

// ── 켜짐 상태 기억(localStorage, 실패해도 동작) ──────────────────────────

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function readStoredToggle(storage: StorageLike | null | undefined): boolean {
  try {
    return storage?.getItem(TOGGLE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeStoredToggle(storage: StorageLike | null | undefined, on: boolean): boolean {
  try {
    if (!storage) return false;
    storage.setItem(TOGGLE_STORAGE_KEY, on ? "1" : "0");
    return true;
  } catch {
    return false;
  }
}
