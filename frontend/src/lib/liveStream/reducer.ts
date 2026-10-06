import type { LiveBar, LiveBook, LiveData, LiveEvent, LiveQuote, LiveSnapshot, LiveTick } from "./types.ts";

/** 화면이 들고 있는 체결 상한(서버 보관 상한과 같다). */
export const TICK_LIMIT = 300;
/** 새 체결이 가장 최근 체결보다 이만큼(분) 이상 과거면 새 거래일로 보고 어제 값을 버린다(서버가 거래일 변경 안내를 따로 보내지 않는다). */
export const DAY_ROLLOVER_GAP_MIN = 30;

export function initialLiveData(code: string): LiveData {
  return { code, quote: null, book: null, ticks: [], bars: [], seeded: false, businessDate: null };
}

function toSeconds(t: string): number {
  const h = Number(t.slice(0, 2));
  const m = Number(t.slice(3, 5));
  const s = t.length >= 8 ? Number(t.slice(6, 8)) : 0;
  return h * 3600 + m * 60 + s;
}

/** "HH:MM[:SS]" 비교. 앞이 더 이르면 음수. */
function cmpTime(a: string, b: string): number {
  return toSeconds(a) - toSeconds(b);
}

function sameTick(a: LiveTick, b: LiveTick): boolean {
  return a.time === b.time && a.price === b.price && a.volume === b.volume && (a.acml_volume ?? null) === (b.acml_volume ?? null);
}

function sortBars(bars: LiveBar[]): LiveBar[] {
  const byTime = new Map<string, LiveBar>();
  for (const b of bars) byTime.set(b.time, b); // 같은 분이 겹치면 나중 것이 이긴다
  return [...byTime.values()].sort((x, y) => (x.time < y.time ? -1 : x.time > y.time ? 1 : 0));
}

/** `snapshot`으로 통째로 바꾼다. 빈 snapshot이면 빈 화면이 된다(거래일이 바뀌어도 같은 처리). */
export function applySnapshot(prev: LiveData, snap: LiveSnapshot): LiveData {
  const ticks: LiveTick[] = [];
  for (const t of snap.ticks ?? []) {
    if (!ticks.some((x) => sameTick(x, t))) ticks.push(t); // 서버가 보낸 순서(최신이 앞)를 유지하며 중복만 걷어 낸다
  }
  return {
    code: snap.code || prev.code,
    quote: snap.quote ?? null,
    book: snap.book ?? null,
    ticks: ticks.slice(0, TICK_LIMIT),
    bars: sortBars(snap.bars ?? []),
    seeded: Boolean(snap.seeded),
    businessDate: snap.business_date ?? null,
  };
}

/**
 * 체결 1건을 반영한다(최신이 앞). 같은 체결이 다시 오면 무시, 순서가 뒤바뀌어 도착하면 시각 순서 자리에 끼워 넣는다.
 * 같은 시각이면 나중에 도착한 것이 앞이다.
 */
export function applyTick(prev: LiveData, tick: LiveTick): LiveData {
  let ticks = prev.ticks;
  const head = ticks[0];
  if (head && cmpTime(head.time, tick.time) > DAY_ROLLOVER_GAP_MIN * 60) {
    // 새 거래일 시작: 어제 체결·분봉·시세를 버린다(호가는 다음 호가 이벤트가 바꾼다)
    return { ...prev, quote: null, ticks: [tick], bars: [], businessDate: null };
  }
  let at = 0;
  while (at < ticks.length && cmpTime(ticks[at].time, tick.time) > 0) at += 1; // 더 늦은 시각의 체결은 앞에 둔다
  for (let i = at; i < ticks.length && ticks[i].time === tick.time; i += 1) {
    if (sameTick(ticks[i], tick)) return prev; // 중복
  }
  ticks = [...ticks.slice(0, at), tick, ...ticks.slice(at)];
  if (ticks.length > TICK_LIMIT) ticks = ticks.slice(0, TICK_LIMIT);
  return { ...prev, ticks };
}

/** 바뀐 1분봉 1개: 같은 시각이면 교체, 없으면 시간 순서 자리에 넣는다. */
export function applyBar(prev: LiveData, bar: LiveBar): LiveData {
  const bars = prev.bars;
  const i = bars.findIndex((b) => b.time === bar.time);
  if (i >= 0) {
    const next = bars.slice();
    next[i] = bar;
    return { ...prev, bars: next };
  }
  const next = [...bars, bar];
  if (bars.length > 0 && bars[bars.length - 1].time > bar.time) next.sort((x, y) => (x.time < y.time ? -1 : 1));
  return { ...prev, bars: next };
}

/** 시세: 더 이른 시각(순서가 뒤바뀐 이벤트)이면 무시한다. 거래일이 바뀐 경우(30분 이상 과거)는 받아들인다. */
export function applyQuote(prev: LiveData, quote: LiveQuote): LiveData {
  const cur = prev.quote;
  if (cur && quote.time && cur.time) {
    const back = cmpTime(cur.time, quote.time);
    if (back > 0 && back <= DAY_ROLLOVER_GAP_MIN * 60) return prev;
  }
  return { ...prev, quote };
}

export function applyBook(prev: LiveData, book: LiveBook): LiveData {
  return { ...prev, book };
}

export function reduceLive(prev: LiveData, ev: LiveEvent): LiveData {
  switch (ev.type) {
    case "snapshot":
      return applySnapshot(prev, ev.data);
    case "tick":
      return applyTick(prev, ev.data);
    case "bar":
      return applyBar(prev, ev.data);
    case "quote":
      return applyQuote(prev, ev.data);
    case "book":
      return applyBook(prev, ev.data);
    default:
      return prev;
  }
}
