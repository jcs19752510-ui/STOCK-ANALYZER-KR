/**
 * 장중 기준 재계산(DEC-089/090) 요청·응답 규칙 — 주소 만들기, 응답 정리, 오류 매핑, 켜짐 기억(localStorage).
 * 계약서 `docs/stock-detail/10-intraday-rescreen-contract.md` §3. 이 모듈은 컨트롤러(`controller.ts`)와 화면의 요청 쪽에서만 가져다 쓴다:
 * 운영 빌드에서는 쓰는 곳이 모두 제거되어 번들에 남지 않는다(운영 빌드 비노출). 표시용 로직은 `logic.ts`.
 */
import { MAX_CHANGE_CODES, clampRefreshSeconds } from "./logic.ts";
import type { LiveBaseFill, LiveChanges, LiveError, LiveErrorKind, LiveMeta, LiveScreenKind } from "./types.ts";

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

/** `base` 끝 슬래시는 무시. `snapshotId`가 있으면 그 스냅샷에 고정해 달라는 요청이다. */
export function buildLiveUrl(base: string, kind: LiveScreenKind, params: string, page: number, snapshotId: string | null): string {
  const qs = new URLSearchParams(params);
  qs.set("page", String(Math.max(1, Math.floor(page))));
  if (snapshotId) qs.set("snapshot_id", snapshotId);
  return `${base.replace(/\/$/, "")}${LIVE_SCREEN_PATH[kind]}?${qs.toString()}`;
}

export function parseGeneratedAt(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms / 1000 : null;
}


// ── 응답 정리 ────────────────────────────────────────────────────────────

const FILL_STATES = new Set(["none", "running", "ready", "failed"]);

export function parseBaseFill(raw: unknown): LiveBaseFill {
  if (!isObj(raw)) return { gap_days: 0, state: "none", done: 0, total: 0, filled: 0, from_cache: 0, excluded: 0, mismatched: 0, pending: 0, source: null };
  const state = typeof raw.state === "string" && FILL_STATES.has(raw.state) ? (raw.state as LiveBaseFill["state"]) : "none";
  return {
    gap_days: nonNegInt(raw.gap_days),
    state,
    done: nonNegInt(raw.done),
    total: nonNegInt(raw.total),
    filled: nonNegInt(raw.filled),
    from_cache: nonNegInt(raw.from_cache),
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

// ── 켜짐 상태 기억(localStorage, 실패해도 동작) ──────────────────────────

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** 저장된 값이 없으면 켜짐이 기본이다(DEC-097: 최신 기준이 기본). 사용자가 끄면 "0"이 저장돼 유지된다. 알 수 없는 값은 꺼짐으로 본다. */
export function readStoredToggle(storage: StorageLike | null | undefined): boolean {
  try {
    const v = storage?.getItem(TOGGLE_STORAGE_KEY);
    if (v === null || v === undefined) return true;
    return v === "1";
  } catch {
    return true;
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
