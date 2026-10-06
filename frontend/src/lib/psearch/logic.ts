/**
 * 증권사 조건검색 화면(DEC-088) 순수 로직 — 계약서 `docs/stock-detail/09-psearch-api-contract.md` §3·§4·§5.
 * 시간·요청·화면 상태를 모르는 함수만 둔다(가짜 시간으로 `scripts/check-psearch.mjs`가 시험).
 * - 조건 목록·결과 응답을 믿지 않고 한 번 걸러 쓴다(모양이 어긋난 응답은 `null` → 호출 실패로 취급).
 * - 시각은 모두 epoch 초. 서버(이 PC의 API)와 브라우저 시계가 달라도 "신규" 판정이 흔들리지 않게 서버 기준 현재 시각을 따로 계산한다.
 */
import type { StockQuote } from "../types.ts";

export const MIN_POLL_MS = 5000;
/** 서버 캐시 시간 상한(계약 §4: 최대 60초)보다 긴 값은 믿지 않는다. */
export const MAX_POLL_MS = 60000;
export const MAX_BACKOFF_MS = 30000;
export const NEW_WINDOW_SEC = 60;
export const MAX_CHANGES = 10;
export const MAX_NAMES_PER_CHANGE = 5;
export const MAX_ITEMS = 100;
export const MAX_NAME_BOOK = 500;

export interface PsearchCondition {
  seq: string;
  group: string;
  name: string;
}

export interface PsearchItem {
  code: string;
  name: string | null;
  market: string | null;
  /** 서버가 이 종목을 처음 본 시각. 응답에 없거나 숫자가 아니면 null(편입 시각 "-"). */
  entered_at: number | null;
}

export interface PsearchChange {
  at: number;
  added: string[];
  removed: string[];
}

export interface PsearchResults {
  seq: string;
  items: PsearchItem[];
  capped: boolean;
  empty: boolean;
  empty_message: string | null;
  changes: PsearchChange[];
  fetched_at: number | null;
  age_seconds: number;
  cache_ttl_seconds: number;
  stale: boolean;
}

export interface PsearchHttp {
  status: number;
  body: unknown;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);

/** 응답 봉투에서 오류 코드·문구를 꺼낸다(없으면 null). */
export function errorInfo(body: unknown): { code: string | null; message: string | null } {
  const err = isObj(body) && isObj(body.error) ? body.error : null;
  return { code: err ? str(err.code) : null, message: err ? str(err.message) : null };
}

// ── 응답 정리 ────────────────────────────────────────────────────────────

/** `GET .../psearch/conditions` 성공 본문 → 조건 목록. 모양이 다르면 null. 같은 seq는 처음 것만 쓴다. */
export function parseConditions(body: unknown): PsearchCondition[] | null {
  const data = isObj(body) && isObj(body.data) ? body.data : null;
  if (!data || !Array.isArray(data.conditions)) return null;
  const seen = new Set<string>();
  const out: PsearchCondition[] = [];
  for (const raw of data.conditions) {
    if (!isObj(raw)) continue;
    const seq = typeof raw.seq === "number" && Number.isFinite(raw.seq) ? String(raw.seq) : str(raw.seq);
    if (seq === null || seen.has(seq)) continue;
    seen.add(seq);
    out.push({ seq, group: str(raw.group) ?? "", name: str(raw.name) ?? seq });
  }
  return out;
}

/** 목록 표시용 글자 `group · name`(그룹이 비면 이름만). */
export function conditionLabel(c: PsearchCondition): string {
  return c.group ? `${c.group} · ${c.name}` : c.name;
}

export function normalizeChanges(raw: unknown): PsearchChange[] {
  if (!Array.isArray(raw)) return [];
  const out: PsearchChange[] = [];
  const seen = new Set<string>();
  for (const r of raw) {
    if (!isObj(r) || !finite(r.at)) continue;
    const codes = (v: unknown) => [...new Set(Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && x !== "") : [])];
    const added = codes(r.added);
    const removed = codes(r.removed);
    if (added.length === 0 && removed.length === 0) continue; // 내용 없는 변화는 목록에 올리지 않는다
    const key = `${r.at}|${added.join(",")}|${removed.join(",")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ at: r.at, added, removed });
    if (out.length >= MAX_CHANGES) break; // 서버는 최신이 앞이므로 앞에서 10건
  }
  return out;
}

/** `GET .../psearch/results` 성공 본문 → 정리한 결과. 요청한 seq와 다르거나 모양이 어긋나면 null. */
export function normalizeResults(body: unknown, expectedSeq: string): PsearchResults | null {
  const data = isObj(body) && isObj(body.data) ? body.data : null;
  if (!data || !Array.isArray(data.items)) return null;
  const seq = typeof data.seq === "number" ? String(data.seq) : str(data.seq);
  if (seq !== expectedSeq) return null;
  const seen = new Set<string>();
  const items: PsearchItem[] = [];
  for (const raw of data.items) {
    if (!isObj(raw)) continue;
    const code = str(raw.code);
    if (code === null || seen.has(code)) continue;
    seen.add(code);
    items.push({
      code,
      name: str(raw.name),
      market: str(raw.market),
      entered_at: finite(raw.entered_at) ? raw.entered_at : null,
    });
    if (items.length >= MAX_ITEMS) break;
  }
  const ttl = finite(data.cache_ttl_seconds) && data.cache_ttl_seconds > 0 ? data.cache_ttl_seconds : MIN_POLL_MS / 1000;
  const emptyFlag = data.empty === true;
  return {
    seq,
    items,
    capped: data.capped === true,
    empty: emptyFlag,
    empty_message: emptyFlag ? (str(data.empty_message)?.slice(0, 200) ?? null) : null,
    changes: normalizeChanges(data.changes),
    fetched_at: finite(data.fetched_at) ? data.fetched_at : null,
    age_seconds: finite(data.age_seconds) && data.age_seconds >= 0 ? data.age_seconds : 0,
    cache_ttl_seconds: ttl,
    stale: data.stale === true,
  };
}

// ── 조회 간격 ────────────────────────────────────────────────────────────

/** 다음 조회까지 기본 간격(ms): max(5초, 서버 캐시 시간), 서버 상한 60초. */
export function intervalMs(cacheTtlSeconds: number | null | undefined): number {
  const ttl = finite(cacheTtlSeconds) ? cacheTtlSeconds * 1000 : 0;
  return Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, ttl));
}

/** 연속 실패 `failures`(1부터)번째 재시도 간격: 기본 간격을 두 배씩, 상한 30초(기본 간격이 더 길면 기본 간격 아래로는 내려가지 않음). */
export function backoffMs(baseMs: number, failures: number): number {
  const n = Math.max(1, Math.floor(failures));
  return Math.max(baseMs, Math.min(MAX_BACKOFF_MS, baseMs * 2 ** Math.min(n, 10)));
}

/** 다시 묻지 않는 상태(이 화면을 쓸 수 없음): 로그인 없음·권한 없음·기능 꺼짐·설정 없음. */
export const UNAVAILABLE_STATUS: ReadonlySet<number> = new Set([401, 403, 404, 503]);

// ── 시각·신규 판정 ───────────────────────────────────────────────────────

/** epoch 초 → 한국 표준시 "HH:MM:SS". 값이 없으면 "-". (한국은 일광절약시간이 없어 +9시간 고정) */
export function formatHms(epochSec: number | null | undefined): string {
  if (!finite(epochSec)) return "-";
  const s = (((Math.floor(epochSec) + 9 * 3600) % 86400) + 86400) % 86400;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

/**
 * 서버 기준 현재 시각(epoch 초). 응답을 받은 순간의 서버 시각은 `fetched_at + age_seconds`이고, 그 뒤 브라우저에서 흐른 시간을 더한다.
 * 이렇게 하면 `entered_at`(서버 시계)과 브라우저 시계가 어긋나도 "신규" 판정이 흔들리지 않는다.
 */
export function serverNow(data: PsearchResults, receivedAt: number, clientNow: number): number {
  const elapsed = Math.max(0, clientNow - receivedAt);
  if (data.fetched_at === null) return clientNow; // 서버 시각을 모르면 브라우저 시계(어긋남이 있을 수 있음)
  return data.fetched_at + data.age_seconds + elapsed;
}

/** 편입 후 60초 이내(60초 포함)이면 신규. 시각을 모르면 신규로 보지 않고, 미래 시각(시계 오차)은 방금 편입으로 본다. */
export function isNewEntry(enteredAt: number | null, refNow: number): boolean {
  if (enteredAt === null) return false;
  return refNow - enteredAt <= NEW_WINDOW_SEC;
}

/** 지금 신규인 종목 중 가장 먼저 신규가 끝나는 때까지(ms). 신규 종목이 없으면 null. 화면을 한 번 다시 그릴 시점이다. */
export function nextNewExpiryMs(items: readonly PsearchItem[], refNow: number): number | null {
  let min: number | null = null;
  for (const it of items) {
    if (!isNewEntry(it.entered_at, refNow) || it.entered_at === null) continue;
    const ms = Math.ceil((it.entered_at + NEW_WINDOW_SEC - refNow) * 1000) + 250; // 60초가 지난 직후
    if (min === null || ms < min) min = ms;
  }
  return min === null ? null : Math.max(250, min);
}

// ── 이름·변화 목록 ───────────────────────────────────────────────────────

/** 본 적 있는 종목 이름 장부. 이탈한 종목도 이름으로 보여 주기 위해 쓴다. 바뀐 것이 없으면 같은 객체를 돌려준다. */
export function mergeNames(book: Record<string, string>, items: readonly PsearchItem[]): Record<string, string> {
  let next: Record<string, string> | null = null;
  for (const it of items) {
    if (it.name && book[it.code] !== it.name) {
      next ??= { ...book };
      next[it.code] = it.name;
    }
  }
  if (!next) return book;
  const keys = Object.keys(next);
  if (keys.length > MAX_NAME_BOOK) for (const k of keys.slice(0, keys.length - MAX_NAME_BOOK)) delete next[k];
  return next;
}

export function stockLabel(code: string, names: Record<string, string>): string {
  const name = names[code];
  return name ? `${name}(${code})` : code;
}

export interface ChangeRow {
  key: string;
  time: string;
  added: string[];
  addedMore: number;
  removed: string[];
  removedMore: number;
}

/** 변화 목록 표시용 행. 최대 10건, 한 줄에 종목은 5개까지 이름으로 보이고 나머지는 "외 N종목"으로 줄인다. */
export function changeRows(changes: readonly PsearchChange[], names: Record<string, string>): ChangeRow[] {
  return changes.slice(0, MAX_CHANGES).map((c) => ({
    key: `${c.at}|${c.added.join(",")}|${c.removed.join(",")}`,
    time: formatHms(c.at),
    added: c.added.slice(0, MAX_NAMES_PER_CHANGE).map((code) => stockLabel(code, names)),
    addedMore: Math.max(0, c.added.length - MAX_NAMES_PER_CHANGE),
    removed: c.removed.slice(0, MAX_NAMES_PER_CHANGE).map((code) => stockLabel(code, names)),
    removedMore: Math.max(0, c.removed.length - MAX_NAMES_PER_CHANGE),
  }));
}

/** 이전·새 결과의 종목 집합 차이(개수). */
export function diffCodes(prev: readonly PsearchItem[], next: readonly PsearchItem[]): { added: number; removed: number } {
  const a = new Set(prev.map((i) => i.code));
  const b = new Set(next.map((i) => i.code));
  let added = 0;
  let removed = 0;
  for (const c of b) if (!a.has(c)) added += 1;
  for (const c of a) if (!b.has(c)) removed += 1;
  return { added, removed };
}

// ── 가격 ─────────────────────────────────────────────────────────────────

/** 보여 줄 만한 가격이 있는가. 값이 없거나 0 이하·숫자가 아니면 "-"로 보인다(0으로 채우지 않는다). */
export function hasPrice(q: StockQuote | undefined): q is StockQuote {
  return !!q && finite(q.close) && q.close > 0;
}

/**
 * 가격 장부 갱신: 이번에 값이 있는 종목은 새 값으로, 값이 없는 종목은 장부의 이전 값을 그대로 둔다. 현재 목록에 없는 종목은 버린다.
 * 바뀐 것이 없으면 같은 객체를 돌려준다.
 */
export function updatePriceBook(
  book: Record<string, StockQuote>,
  quotes: Record<string, StockQuote>,
  codes: readonly string[],
): Record<string, StockQuote> {
  const next: Record<string, StockQuote> = {};
  let changed = false;
  for (const code of codes) {
    const q = quotes[code];
    if (hasPrice(q)) {
      next[code] = q;
      if (book[code] !== q) changed = true;
    } else if (book[code]) {
      next[code] = book[code];
    }
  }
  if (!changed && Object.keys(next).length === Object.keys(book).length && Object.keys(next).every((k) => book[k] === next[k])) return book;
  return next;
}

/**
 * 화면에 쓸 가격: 이번 시세에 값이 있으면 그것을, 없고 장부에 이전 값이 있으면 그 값을 "지연"으로 표시해 쓰고, 둘 다 없으면 undefined("-").
 * (조건 결과가 바뀔 때 시세 조회가 다시 시작되며 잠깐 비는 동안 가격이 깜박이지 않게 하되, 오래된 값을 신선한 값처럼 보이지 않게 한다.)
 */
export function mergePrice(quote: StockQuote | undefined, remembered: StockQuote | undefined): StockQuote | undefined {
  if (hasPrice(quote)) return quote;
  if (!hasPrice(remembered)) return undefined;
  return remembered.live ? { ...remembered, live: { ...remembered.live, stale: true } } : remembered;
}
