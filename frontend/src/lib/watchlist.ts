/**
 * 관심종목(DEC-055): 이 브라우저의 localStorage에만 저장한다. 계정·서버 저장 없음, 다른 기기와 공유되지 않는다.
 * 이 파일은 순수 함수(상태 변환·검증)만 둔다. 저장소 접근은 `useWatchlist.ts`.
 */
export const WATCHLIST_STORAGE_KEY = "watchlist.v1";
export const MAX_GROUPS = 10;
export const MAX_PER_GROUP = 50;
export const MAX_NAME_LENGTH = 20;
export const DEFAULT_GROUP_NAME = "관심종목";

export interface WatchItem {
  code: string;
  name: string;
  market: string;
}

export interface WatchGroup {
  id: string;
  name: string;
  items: WatchItem[]; // 사용자가 정한 순서
}

export interface WatchlistState {
  version: 1;
  groups: WatchGroup[];
}

const CODE_RE = /^[0-9A-Za-z]{6}$/;

export function emptyState(): WatchlistState {
  return { version: 1, groups: [{ id: "g1", name: DEFAULT_GROUP_NAME, items: [] }] };
}

function cleanName(raw: unknown, fallback: string): string {
  if (typeof raw !== "string") return fallback;
  const t = raw.replace(/\s+/g, " ").trim().slice(0, MAX_NAME_LENGTH);
  return t === "" ? fallback : t;
}

function cleanItem(raw: unknown): WatchItem | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.code !== "string" || !CODE_RE.test(r.code)) return null;
  return {
    code: r.code,
    name: cleanName(r.name, r.code),
    market: typeof r.market === "string" ? r.market.slice(0, 10) : "",
  };
}

/** 저장된 문자열을 믿지 않고 모양·개수·중복을 바로잡는다. 읽을 수 없으면 빈 상태. */
export function parseState(raw: string | null): WatchlistState {
  if (!raw) return emptyState();
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return emptyState();
  }
  if (typeof data !== "object" || data === null) return emptyState();
  const groupsRaw = (data as { groups?: unknown }).groups;
  if (!Array.isArray(groupsRaw)) return emptyState();
  const groups: WatchGroup[] = [];
  const ids = new Set<string>();
  for (const g of groupsRaw.slice(0, MAX_GROUPS)) {
    if (typeof g !== "object" || g === null) continue;
    const gr = g as Record<string, unknown>;
    let id = typeof gr.id === "string" && /^[A-Za-z0-9_-]{1,12}$/.test(gr.id) ? gr.id : `g${groups.length + 1}`;
    while (ids.has(id)) id = `${id}x`;
    ids.add(id);
    const seen = new Set<string>();
    const items: WatchItem[] = [];
    for (const it of Array.isArray(gr.items) ? gr.items : []) {
      const c = cleanItem(it);
      if (c && !seen.has(c.code) && items.length < MAX_PER_GROUP) {
        seen.add(c.code);
        items.push(c);
      }
    }
    groups.push({ id, name: cleanName(gr.name, DEFAULT_GROUP_NAME), items });
  }
  return groups.length === 0 ? emptyState() : { version: 1, groups };
}

export function serialize(state: WatchlistState): string {
  return JSON.stringify(state);
}

export function isWatched(state: WatchlistState, code: string): boolean {
  return state.groups.some((g) => g.items.some((i) => i.code === code));
}

/** 첫 번째 그룹에 추가한다. 이미 어느 그룹에든 있으면 그대로, 가득 찼으면 변경 없이 `full`을 알린다. */
export function addToDefault(
  state: WatchlistState,
  item: WatchItem,
): { state: WatchlistState; result: "added" | "exists" | "full" | "invalid" } {
  const clean = cleanItem(item);
  if (!clean) return { state, result: "invalid" };
  if (isWatched(state, clean.code)) return { state, result: "exists" };
  const first = state.groups[0];
  if (first.items.length >= MAX_PER_GROUP) return { state, result: "full" };
  const groups = state.groups.map((g, i) => (i === 0 ? { ...g, items: [...g.items, clean] } : g));
  return { state: { ...state, groups }, result: "added" };
}

/** 모든 그룹에서 제거한다(별표를 끄는 동작). */
export function removeEverywhere(state: WatchlistState, code: string): WatchlistState {
  return {
    ...state,
    groups: state.groups.map((g) => ({ ...g, items: g.items.filter((i) => i.code !== code) })),
  };
}

export function removeFromGroup(state: WatchlistState, groupId: string, code: string): WatchlistState {
  return {
    ...state,
    groups: state.groups.map((g) =>
      g.id === groupId ? { ...g, items: g.items.filter((i) => i.code !== code) } : g,
    ),
  };
}

export function moveWithinGroup(
  state: WatchlistState,
  groupId: string,
  code: string,
  delta: -1 | 1,
): WatchlistState {
  return {
    ...state,
    groups: state.groups.map((g) => {
      if (g.id !== groupId) return g;
      const i = g.items.findIndex((it) => it.code === code);
      const j = i + delta;
      if (i < 0 || j < 0 || j >= g.items.length) return g;
      const items = [...g.items];
      [items[i], items[j]] = [items[j], items[i]];
      return { ...g, items };
    }),
  };
}

/** 종목을 다른 그룹으로 옮긴다(대상이 가득 차면 변경 없음). */
export function moveToGroup(
  state: WatchlistState,
  fromId: string,
  toId: string,
  code: string,
): WatchlistState {
  if (fromId === toId) return state;
  const from = state.groups.find((g) => g.id === fromId);
  const to = state.groups.find((g) => g.id === toId);
  const item = from?.items.find((i) => i.code === code);
  if (!from || !to || !item || to.items.some((i) => i.code === code) || to.items.length >= MAX_PER_GROUP) {
    return state;
  }
  return {
    ...state,
    groups: state.groups.map((g) =>
      g.id === fromId
        ? { ...g, items: g.items.filter((i) => i.code !== code) }
        : g.id === toId
          ? { ...g, items: [...g.items, item] }
          : g,
    ),
  };
}

export function createGroup(state: WatchlistState, name: string): WatchlistState {
  if (state.groups.length >= MAX_GROUPS) return state;
  const id = `g${Date.now().toString(36)}${state.groups.length}`.slice(0, 12);
  return {
    ...state,
    groups: [...state.groups, { id, name: cleanName(name, `그룹 ${state.groups.length + 1}`), items: [] }],
  };
}

export function renameGroup(state: WatchlistState, groupId: string, name: string): WatchlistState {
  return {
    ...state,
    groups: state.groups.map((g) => (g.id === groupId ? { ...g, name: cleanName(name, g.name) } : g)),
  };
}

/** 그룹을 지운다. 마지막 하나는 지울 수 없고, 지운 그룹의 종목은 사라진다(다른 그룹에 있으면 유지). */
export function deleteGroup(state: WatchlistState, groupId: string): WatchlistState {
  if (state.groups.length <= 1) return state;
  return { ...state, groups: state.groups.filter((g) => g.id !== groupId) };
}

/** "통합" 보기: 모든 그룹의 종목을 중복 없이 합친다. */
export function mergedItems(state: WatchlistState): WatchItem[] {
  const seen = new Set<string>();
  const out: WatchItem[] = [];
  for (const g of state.groups) {
    for (const i of g.items) {
      if (!seen.has(i.code)) {
        seen.add(i.code);
        out.push(i);
      }
    }
  }
  return out;
}
