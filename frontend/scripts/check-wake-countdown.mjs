#!/usr/bin/env node
/**
 * "서버 깨우는 중" 카운트다운 팝업 로직 검증(DEC-066). 실행:
 *   node --experimental-strip-types --test scripts/check-wake-countdown.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { createWakeTracker } from "../src/lib/apiWake.ts";
import {
  AUTO_RELOAD_KEY,
  MAX_AUTO_RELOADS,
  createCountdown,
  formatClockKst,
  formatRemaining,
  parseCountdownSeconds,
  readAutoReloads,
  resetAutoReloads,
  tryConsumeAutoReload,
} from "../src/lib/wakeCountdown.ts";

/** 가짜 시계: advance(ms)로 시간을 흘려보내며 setInterval 콜백을 부른다. */
function fakeClock(start = 1_000_000) {
  let t = start, seq = 0;
  const jobs = new Map();
  return {
    now: () => t,
    setInterval: (fn, ms) => { const id = ++seq; jobs.set(id, { fn, ms, next: t + ms }); return id; },
    clearInterval: (id) => { jobs.delete(id); },
    advance(ms) {
      const end = t + ms;
      while (true) {
        let due = null;
        for (const [id, j] of jobs) if (j.next <= end && (due === null || j.next < jobs.get(due).next)) due = id;
        if (due === null) break;
        const j = jobs.get(due); t = j.next; j.next += j.ms; j.fn();
      }
      t = end;
    },
    jump(ms) { t += ms; }, // 탭이 멈췄다 깨어난 상황: 인터벌 호출 없이 시간만 흐름
    tick() { for (const j of [...jobs.values()]) j.fn(); },
    count: () => jobs.size,
  };
}
function fakeStore(initial = {}) {
  const m = new Map(Object.entries(initial));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    dump: () => Object.fromEntries(m),
  };
}

test("parseCountdownSeconds: 숫자 5~120만 허용, 그 외는 기본 60", () => {
  assert.equal(parseCountdownSeconds(undefined), 60);
  assert.equal(parseCountdownSeconds(""), 60);
  assert.equal(parseCountdownSeconds("8"), 8);
  assert.equal(parseCountdownSeconds(" 45 "), 45);
  assert.equal(parseCountdownSeconds("120"), 120);
  for (const bad of ["4", "121", "0", "-5", "abc", "6.5", "1e2", "60s", "9999"]) {
    assert.equal(parseCountdownSeconds(bad), 60, bad);
  }
});

test("formatRemaining: 두 자리(59, 08, 00), 음수·소수는 보정", () => {
  assert.equal(formatRemaining(59), "59");
  assert.equal(formatRemaining(8), "08");
  assert.equal(formatRemaining(0), "00");
  assert.equal(formatRemaining(-3), "00");
  assert.equal(formatRemaining(7.9), "07");
});

test("formatClockKst: 한국 시간 HH:MM:SS, 자정은 00", () => {
  assert.equal(formatClockKst(Date.UTC(2026, 9, 4, 15, 0, 0)), "00:00:00"); // UTC 15:00 = KST 다음날 00:00
  assert.equal(formatClockKst(Date.UTC(2026, 9, 5, 3, 4, 5)), "12:04:05");
});

test("createCountdown: 시작 즉시 60, 이후 59…0, 0에서 onDone 정확히 한 번", () => {
  const c = fakeClock(); const ticks = []; let done = 0;
  createCountdown({ seconds: 60, onTick: (r) => ticks.push(r), onDone: () => { done += 1; }, clock: c });
  assert.deepEqual(ticks, [60]);
  c.advance(1000); assert.deepEqual(ticks.slice(-1), [59]);
  c.advance(1000); assert.deepEqual(ticks.slice(-1), [58]);
  c.advance(58_000);
  assert.deepEqual(ticks.slice(-3), [2, 1, 0]);
  assert.equal(ticks[0], 60); assert.equal(ticks.at(-1), 0);
  assert.equal(done, 1);
  // 중복 없이 60→0 모든 값을 한 번씩
  assert.equal(new Set(ticks).size, 61); assert.equal(ticks.length, 61);
  c.advance(10_000); assert.equal(done, 1); assert.equal(c.count(), 0); // 인터벌 정리됨
});

test("createCountdown: stop() 뒤에는 onDone을 부르지 않는다(데이터가 먼저 도착한 경우)", () => {
  const c = fakeClock(); let done = 0;
  const cd = createCountdown({ seconds: 60, onTick: () => {}, onDone: () => { done += 1; }, clock: c });
  c.advance(20_000); cd.stop();
  c.advance(60_000); assert.equal(done, 0); assert.equal(c.count(), 0);
  cd.stop(); // 두 번 호출해도 안전
});

test("createCountdown: 탭이 멈췄다 깨어나도 마감 시각 기준으로 0에서 끝난다", () => {
  const c = fakeClock(); const ticks = []; let done = 0;
  createCountdown({ seconds: 60, onTick: (r) => ticks.push(r), onDone: () => { done += 1; }, clock: c });
  c.advance(5000); c.jump(70_000); c.tick(); // 75초가 한꺼번에 지남
  assert.equal(ticks.at(-1), 0); assert.equal(done, 1);
});

test("createCountdown: 시험용 짧은 시간(8초)", () => {
  const c = fakeClock(); const ticks = []; let done = 0;
  createCountdown({ seconds: 8, onTick: (r) => ticks.push(r), onDone: () => { done += 1; }, clock: c });
  c.advance(8000); assert.deepEqual(ticks, [8, 7, 6, 5, 4, 3, 2, 1, 0]); assert.equal(done, 1);
});

test("자동 새로고침 횟수: 최대 2회, 3번째는 거부", () => {
  const s = fakeStore();
  assert.equal(MAX_AUTO_RELOADS, 2);
  assert.equal(readAutoReloads(s), 0);
  assert.equal(tryConsumeAutoReload(s), true); assert.equal(readAutoReloads(s), 1);
  assert.equal(tryConsumeAutoReload(s), true); assert.equal(readAutoReloads(s), 2);
  assert.equal(tryConsumeAutoReload(s), false); assert.equal(readAutoReloads(s), 2);
});

test("데이터가 도착하면 횟수를 지워 다음에 다시 쓸 수 있다", () => {
  const s = fakeStore({ [AUTO_RELOAD_KEY]: "2" });
  assert.equal(tryConsumeAutoReload(s), false);
  resetAutoReloads(s);
  assert.equal(readAutoReloads(s), 0); assert.equal(tryConsumeAutoReload(s), true);
});

test("저장소를 못 쓰거나 값이 이상하면 새로고침하지 않는다(무한 반복 방지, fail closed)", () => {
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() { throw new Error("denied"); } };
  assert.equal(readAutoReloads(broken), MAX_AUTO_RELOADS);
  assert.equal(tryConsumeAutoReload(broken), false);
  assert.doesNotThrow(() => resetAutoReloads(broken));
  for (const bad of ["abc", "-1", "NaN", ""]) {
    assert.equal(tryConsumeAutoReload(fakeStore({ [AUTO_RELOAD_KEY]: bad })), false, `value=${JSON.stringify(bad)}`);
  }
  const writeFails = { getItem: () => "0", setItem() { throw new Error("quota"); }, removeItem() {} };
  assert.equal(tryConsumeAutoReload(writeFails), false);
});

test("createWakeTracker: 보이게 될 때 가장 오래된 느린 요청의 시작 시각을 함께 알린다", () => {
  let now = 5000; const events = [];
  const jobs = new Map(); let seq = 0;
  const timers = {
    setTimeout: (fn, ms) => { const id = ++seq; jobs.set(id, { at: now + ms, fn }); return id; },
    clearTimeout: (id) => { jobs.delete(id); },
  };
  const advance = (ms) => { now += ms; for (const [id, j] of [...jobs]) if (j.at <= now) { jobs.delete(id); j.fn(); } };
  const tr = createWakeTracker((v, at) => events.push([v, at]), 4500, timers, () => now);
  const first = tr.begin();           // 시작 5000
  advance(1000);
  const second = tr.begin();          // 시작 6000
  advance(4500);                      // 첫 요청이 4.5초를 넘김(10000-5000=5000>=4500)
  assert.deepEqual(events[0], [true, 5000]);
  first(); second();
  assert.deepEqual(events.at(-1), [false, undefined]);
});
