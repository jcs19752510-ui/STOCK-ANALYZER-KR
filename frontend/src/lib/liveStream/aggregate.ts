import type { LiveBar } from "./types.ts";

/** 서버 `intraday/normalize.py`의 `OPEN_MINUTE_OF_DAY`(09:00)와 같다. */
export const OPEN_MINUTE_OF_DAY = 9 * 60;

/**
 * 1분봉을 N분봉으로 묶는다. 서버 `aggregate_minutes`와 같은 규칙: 09:00 기준 구간, 시가=첫 시가, 고가=최대, 저가=최소,
 * 종가=마지막 종가, 거래량=합. 봉 시각은 구간 시작. 입력 순서와 상관없이 시간 오름차순으로 돌려준다.
 */
export function aggregateMinutes(bars: readonly LiveBar[], interval: number): LiveBar[] {
  const ordered = [...bars].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  if (!(interval > 1)) return ordered;
  const buckets = new Map<number, LiveBar[]>();
  for (const b of ordered) {
    const minute = Number(b.time.slice(0, 2)) * 60 + Number(b.time.slice(3, 5));
    const idx = Math.floor((minute - OPEN_MINUTE_OF_DAY) / interval); // 파이썬 `//`와 같은 내림(09:00 이전도 같은 규칙)
    const group = buckets.get(idx);
    if (group) group.push(b);
    else buckets.set(idx, [b]);
  }
  const out: LiveBar[] = [];
  for (const idx of [...buckets.keys()].sort((a, b) => a - b)) {
    const g = buckets.get(idx) as LiveBar[];
    const start = OPEN_MINUTE_OF_DAY + idx * interval;
    out.push({
      time: `${String(Math.floor(start / 60)).padStart(2, "0")}:${String(start % 60).padStart(2, "0")}`,
      open: g[0].open,
      high: Math.max(...g.map((x) => x.high)),
      low: Math.min(...g.map((x) => x.low)),
      close: g[g.length - 1].close,
      volume: g.reduce((a, x) => a + x.volume, 0),
    });
  }
  return out;
}

export interface TickLike {
  time: string;
  price: number;
  volume: number;
}

export interface TickBar {
  time: string; // 묶음의 첫 체결 시각
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/**
 * 최근 체결(최신이 앞)을 n틱씩 묶은 봉(오름차순). 차트의 기존 "틱▾" 규칙 그대로: 가장 오래된 체결부터 n개씩 자르고,
 * 마지막 묶음은 n개보다 적어도 봉으로 만든다. 시각은 묶음의 첫 체결.
 */
export function ticksToBars(ticksLatestFirst: readonly TickLike[], n: number): TickBar[] {
  const size = Math.max(1, Math.floor(n) || 1);
  const asc = [...ticksLatestFirst].reverse();
  const out: TickBar[] = [];
  for (let i = 0; i < asc.length; i += size) {
    const g = asc.slice(i, i + size);
    out.push({
      time: g[0].time,
      open: g[0].price,
      high: Math.max(...g.map((t) => t.price)),
      low: Math.min(...g.map((t) => t.price)),
      close: g[g.length - 1].price,
      volume: g.reduce((a, t) => a + t.volume, 0),
    });
  }
  return out;
}
