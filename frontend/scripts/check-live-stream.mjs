#!/usr/bin/env node
/**
 * 실시간 스트림(DEC-084) 프론트 순수 로직 검증: 반영 규칙(reducer)·N분봉/N틱 묶기(aggregate)·묶음 갱신(store)·연결 수명(controller, 가짜 EventSource). 실행:
 *   node --experimental-strip-types scripts/check-live-stream.mjs
 * N분봉 기대값(GOLDEN)은 서버 `services/public_api/intraday/normalize.py`의 `aggregate_minutes`를 실제로 돌려 얻은 값이다.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { aggregateMinutes, ticksToBars } from "../src/lib/liveStream/aggregate.ts";
import { LiveStreamController } from "../src/lib/liveStream/controller.ts";
import { TICK_LIMIT, applyBar, applyQuote, applyTick, initialLiveData, reduceLive } from "../src/lib/liveStream/reducer.ts";
import { createLiveStore, effectiveState, INITIAL_META, liveMode } from "../src/lib/liveStream/store.ts";

// ── 도우미 ───────────────────────────────────────────────────────────
const tick = (time, price = 100, volume = 1, acml = null) => ({ time, price, change: 0, change_pct: 0, volume, strength: 100, acml_volume: acml });
const bar = (time, o = 100, h = 100, l = 100, c = 100, v = 1) => ({ time, open: o, high: h, low: l, close: c, volume: v });
const quote = (time, price = 100) => ({ time, price, change: 0, change_pct: 0, open: price, high: price, low: price, ask1: null, bid1: null, acml_volume: 1, acml_value: 1, strength: 100, halted: false, vi_price: null });
const snap = (o = {}) => ({ code: "005930", quote: null, book: null, ticks: [], bars: [], seeded: true, business_date: "20261006", connection: "connected", ...o });
const sec = (n) => `${String(9 + Math.floor(n / 3600)).padStart(2, "0")}:${String(Math.floor((n % 3600) / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;

class FakeTimers {
  constructor() { this.now = 0; this.items = []; this.seq = 0; }
  setTimeout = (fn, ms) => { const id = ++this.seq; this.items.push({ id, at: this.now + ms, fn }); return id; };
  clearTimeout = (id) => { this.items = this.items.filter((x) => x.id !== id); };
  advance(ms) {
    const end = this.now + ms;
    for (;;) {
      const due = this.items.filter((x) => x.at <= end).sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) break;
      this.items = this.items.filter((x) => x !== due);
      this.now = due.at;
      due.fn();
    }
    this.now = end;
  }
  get pending() { return this.items.length; }
}

// ── reducer ──────────────────────────────────────────────────────────
test("빈 snapshot: 빈 화면이 되고 오류가 나지 않는다", () => {
  const d = reduceLive(initialLiveData("005930"), { type: "snapshot", data: snap({ business_date: null, seeded: false }) });
  assert.deepEqual([d.ticks, d.bars, d.quote, d.book, d.businessDate, d.seeded], [[], [], null, null, null, false]);
  const d2 = reduceLive(initialLiveData("005930"), { type: "snapshot", data: { code: "005930", quote: null, book: null, ticks: [], bars: [], seeded: false, business_date: null } });
  assert.equal(d2.ticks.length, 0);
});

test("snapshot: 분봉은 시간 오름차순·같은 분 중복은 나중 것, 체결 중복은 제거(최신이 앞 유지)", () => {
  const d = reduceLive(initialLiveData("x"), {
    type: "snapshot",
    data: snap({
      bars: [bar("09:02", 1, 1, 1, 1, 5), bar("09:01"), bar("09:02", 2, 2, 2, 2, 9)],
      ticks: [tick("09:02:05", 10, 1, 7), tick("09:02:05", 10, 1, 7), tick("09:02:01", 9)],
    }),
  });
  assert.deepEqual(d.bars.map((b) => [b.time, b.volume]), [["09:01", 1], ["09:02", 9]]);
  assert.deepEqual(d.ticks.map((t) => t.time), ["09:02:05", "09:02:01"]);
});

test("snapshot이 다시 오면 통째로 교체(재연결): 이전 체결·분봉·호가가 남지 않는다", () => {
  let d = reduceLive(initialLiveData("x"), { type: "snapshot", data: snap({ ticks: [tick("09:00:01")], bars: [bar("09:00")], quote: quote("09:00:01") }) });
  d = reduceLive(d, { type: "snapshot", data: snap({ ticks: [tick("09:05:00")], bars: [bar("09:05")], quote: null }) });
  assert.deepEqual([d.ticks.map((t) => t.time), d.bars.map((b) => b.time), d.quote], [["09:05:00"], ["09:05"], null]);
});

test("거래일 변경: business_date가 다른 snapshot은 어제 값을 전부 버린다", () => {
  let d = reduceLive(initialLiveData("x"), { type: "snapshot", data: snap({ business_date: "20261005", ticks: [tick("15:29:59")], bars: [bar("15:29")] }) });
  d = reduceLive(d, { type: "snapshot", data: snap({ business_date: "20261006", ticks: [], bars: [] }) });
  assert.deepEqual([d.businessDate, d.ticks.length, d.bars.length], ["20261006", 0, 0]);
});

test("거래일 변경: 연결을 유지한 채 다음 날이 되어 체결 시각이 30분 넘게 과거로 가면 어제 값을 버린다", () => {
  let d = { ...initialLiveData("x"), ticks: [tick("19:59:59")], bars: [bar("19:59")], quote: quote("19:59:59") };
  d = applyTick(d, tick("08:00:01", 50));
  assert.deepEqual([d.ticks.map((t) => t.time), d.bars.length, d.quote], [["08:00:01"], 0, null]);
});

test("순서가 조금 뒤바뀐 체결(30분 이내)은 버리지 않고 시각 순서 자리에 끼운다", () => {
  let d = initialLiveData("x");
  for (const t of ["10:00:05", "10:00:07", "10:00:03", "10:00:06"]) d = applyTick(d, tick(t, 100, 1, Number(t.slice(-2))));
  assert.deepEqual(d.ticks.map((t) => t.time), ["10:00:07", "10:00:06", "10:00:05", "10:00:03"]);
});

test("같은 시각의 서로 다른 체결은 나중에 온 것이 앞", () => {
  let d = initialLiveData("x");
  d = applyTick(d, tick("10:00:00", 100, 1, 1));
  d = applyTick(d, tick("10:00:00", 101, 2, 3));
  assert.deepEqual(d.ticks.map((t) => t.price), [101, 100]);
});

test("중복 체결(시각·가격·수량·누적거래량 같음)은 무시하고 같은 객체를 돌려준다", () => {
  let d = applyTick(initialLiveData("x"), tick("10:00:00", 100, 5, 50));
  const again = applyTick(d, tick("10:00:00", 100, 5, 50));
  assert.equal(again, d);
  assert.equal(again.ticks.length, 1);
  // 누적거래량이 다르면 다른 체결
  d = applyTick(d, tick("10:00:00", 100, 5, 55));
  assert.equal(d.ticks.length, 2);
});

test(`체결 버퍼 상한 ${TICK_LIMIT}: 가장 오래된 것부터 버린다`, () => {
  let d = initialLiveData("x");
  for (let i = 0; i < TICK_LIMIT + 50; i++) d = applyTick(d, tick(sec(i), 100 + i, 1, i + 1));
  assert.equal(d.ticks.length, TICK_LIMIT);
  assert.equal(d.ticks[0].price, 100 + TICK_LIMIT + 49);
  assert.equal(d.ticks[TICK_LIMIT - 1].price, 100 + 50);
  // snapshot이 상한보다 길어도 잘라 낸다
  const big = Array.from({ length: TICK_LIMIT + 20 }, (_, i) => tick(sec(TICK_LIMIT + 20 - i), i, 1, i));
  assert.equal(reduceLive(initialLiveData("x"), { type: "snapshot", data: snap({ ticks: big }) }).ticks.length, TICK_LIMIT);
});

test("분봉: 같은 분은 교체, 새 분은 끝에 추가, 늦게 온 이전 분은 순서 자리에", () => {
  let d = { ...initialLiveData("x"), bars: [bar("09:00"), bar("09:02")] };
  d = applyBar(d, bar("09:02", 1, 9, 1, 5, 77));
  assert.deepEqual(d.bars.map((b) => [b.time, b.volume]), [["09:00", 1], ["09:02", 77]]);
  d = applyBar(d, bar("09:03"));
  d = applyBar(d, bar("09:01"));
  assert.deepEqual(d.bars.map((b) => b.time), ["09:00", "09:01", "09:02", "09:03"]);
  assert.equal(applyBar(initialLiveData("x"), bar("09:00")).bars.length, 1);
});

test("시세: 더 이른 시각(순서 뒤바뀜)은 무시, 같거나 늦은 시각은 반영", () => {
  let d = applyQuote(initialLiveData("x"), quote("10:00:05", 105));
  const same = applyQuote(d, quote("10:00:03", 103));
  assert.equal(same, d);
  d = applyQuote(d, quote("10:00:05", 106));
  assert.equal(d.quote.price, 106);
  d = applyQuote(d, quote("10:00:09", 109));
  assert.equal(d.quote.price, 109);
  // 새 거래일(30분 넘게 과거)은 받아들인다
  d = applyQuote(d, quote("08:00:01", 50));
  assert.equal(d.quote.price, 50);
});

test("알 수 없는 이벤트는 상태를 바꾸지 않는다", () => {
  const d = initialLiveData("x");
  assert.equal(reduceLive(d, { type: "nope", data: {} }), d);
});

// ── aggregate ────────────────────────────────────────────────────────
const GOLDEN_TIMES = ["08:59", "09:00", "09:01", "09:02", "09:03", "09:04", "09:05", "09:06", "10:29", "10:30", "15:29", "15:30"];
const GOLDEN_INPUT = GOLDEN_TIMES.map((t, i) => bar(t, 100 + i, 110 + i * 2, 90 - i, 101 + i, 10 * (i + 1)));
// 아래 값은 서버 aggregate_minutes를 실제로 실행해 얻은 결과다([시각, 시가, 고가, 저가, 종가, 거래량]).
const GOLDEN = {
  1: [["08:59",100,110,90,101,10],["09:00",101,112,89,102,20],["09:01",102,114,88,103,30],["09:02",103,116,87,104,40],["09:03",104,118,86,105,50],["09:04",105,120,85,106,60],["09:05",106,122,84,107,70],["09:06",107,124,83,108,80],["10:29",108,126,82,109,90],["10:30",109,128,81,110,100],["15:29",110,130,80,111,110],["15:30",111,132,79,112,120]],
  3: [["08:57",100,110,90,101,10],["09:00",101,116,87,104,90],["09:03",104,122,84,107,180],["09:06",107,124,83,108,80],["10:27",108,126,82,109,90],["10:30",109,128,81,110,100],["15:27",110,130,80,111,110],["15:30",111,132,79,112,120]],
  5: [["08:55",100,110,90,101,10],["09:00",101,120,85,106,200],["09:05",106,124,83,108,150],["10:25",108,126,82,109,90],["10:30",109,128,81,110,100],["15:25",110,130,80,111,110],["15:30",111,132,79,112,120]],
  10: [["08:50",100,110,90,101,10],["09:00",101,124,83,108,350],["10:20",108,126,82,109,90],["10:30",109,128,81,110,100],["15:20",110,130,80,111,110],["15:30",111,132,79,112,120]],
  15: [["08:45",100,110,90,101,10],["09:00",101,124,83,108,350],["10:15",108,126,82,109,90],["10:30",109,128,81,110,100],["15:15",110,130,80,111,110],["15:30",111,132,79,112,120]],
  30: [["08:30",100,110,90,101,10],["09:00",101,124,83,108,350],["10:00",108,126,82,109,90],["10:30",109,128,81,110,100],["15:00",110,130,80,111,110],["15:30",111,132,79,112,120]],
  60: [["08:00",100,110,90,101,10],["09:00",101,124,83,108,350],["10:00",108,128,81,110,190],["15:00",110,132,79,112,230]],
};

for (const n of Object.keys(GOLDEN).map(Number)) {
  test(`N분봉 ${n}분: 서버 aggregate_minutes와 같은 결과(09:00 기준 구간 경계 포함)`, () => {
    const got = aggregateMinutes(GOLDEN_INPUT, n).map((b) => [b.time, b.open, b.high, b.low, b.close, b.volume]);
    assert.deepEqual(got, GOLDEN[n]);
  });
}

test("N분봉: 입력 순서가 뒤섞여도 같은 결과, 간격 0·음수·소수는 1분봉과 같다(서버 interval<=1)", () => {
  const shuffled = [...GOLDEN_INPUT].reverse();
  assert.deepEqual(aggregateMinutes(shuffled, 5), aggregateMinutes(GOLDEN_INPUT, 5));
  for (const n of [0, -3, 1]) assert.deepEqual(aggregateMinutes(shuffled, n).map((b) => b.time), GOLDEN_TIMES);
  assert.deepEqual(aggregateMinutes([], 5), []);
});

test("N분봉: 경계 — 09:04는 09:00 구간, 09:05는 다음 구간(5분)", () => {
  const r = aggregateMinutes([bar("09:04", 1, 5, 1, 4, 3), bar("09:05", 4, 6, 2, 5, 4)], 5);
  assert.deepEqual(r.map((b) => [b.time, b.volume]), [["09:00", 3], ["09:05", 4]]);
});

test("N틱 묶음: 가장 오래된 체결부터 n개씩, 마지막 묶음은 모자라도 봉으로(차트 기존 규칙)", () => {
  const latestFirst = [7, 6, 5, 4, 3, 2, 1].map((i) => tick(`09:00:0${i}`, 100 + (i % 3) * 10, i));
  const r = ticksToBars(latestFirst, 3);
  assert.equal(r.length, 3);
  assert.deepEqual(r.map((b) => [b.time, b.volume]), [["09:00:01", 6], ["09:00:04", 15], ["09:00:07", 7]]);
  assert.equal(r[0].open, 110); // i=1 → 100+10
  assert.equal(r[0].close, 100); // 마지막(i=3): 100 + 0
  assert.equal(r[0].high, 120);
  assert.equal(ticksToBars(latestFirst, 1).length, 7);
  assert.deepEqual(ticksToBars([], 5), []);
  assert.equal(ticksToBars(latestFirst, 0).length, 7); // 잘못된 값은 1틱으로
});

// ── store ────────────────────────────────────────────────────────────
test("store: 이벤트가 폭주해도 화면 알림은 100ms에 한 번(묶음 갱신)", () => {
  const timers = new FakeTimers();
  const store = createLiveStore("x", { timers, now: () => timers.now });
  let notified = 0;
  store.subscribe(() => (notified += 1));
  for (let i = 0; i < 1000; i++) store.dispatch({ type: "tick", data: tick(sec(i), 100, 1, i + 1) });
  assert.equal(notified, 0);
  assert.equal(store.getData().ticks.length, 0, "공개된 상태는 알림 전까지 그대로");
  timers.advance(99);
  assert.equal(notified, 0);
  timers.advance(1);
  assert.equal(notified, 1);
  assert.equal(store.getData().ticks.length, TICK_LIMIT);
  timers.advance(1000);
  assert.equal(notified, 1, "새 이벤트가 없으면 더 알리지 않는다");
});

test("store: 알림 사이에 같은 객체를 돌려주고, 마지막 수신 시각은 초당 1회만 바뀐다", () => {
  const timers = new FakeTimers();
  const store = createLiveStore("x", { timers, now: () => timers.now });
  store.dispatch({ type: "snapshot", data: snap() });
  timers.advance(100);
  const m1 = store.getMeta();
  assert.equal(store.getMeta(), m1);
  assert.equal(m1.lastReceivedAt, 0);
  assert.equal(m1.hasSnapshot, true);
  timers.advance(300);
  store.dispatch({ type: "tick", data: tick("09:00:01") });
  timers.advance(100);
  assert.equal(store.getMeta().lastReceivedAt, 0, "1초 안에는 그대로");
  timers.advance(900);
  store.dispatch({ type: "tick", data: tick("09:00:02") });
  timers.advance(100);
  assert.equal(store.getMeta().lastReceivedAt, 1400);
});

test("store: 증권사 연결 상태(status 이벤트)와 브라우저 연결 상태를 합쳐 판단", () => {
  const live = { ...INITIAL_META, status: "live", hasSnapshot: true };
  assert.equal(effectiveState({ ...live, serverConnection: "connected", everConnected: true }), "live");
  assert.equal(effectiveState({ ...live, serverConnection: null }), "live");
  assert.equal(effectiveState({ ...live, serverConnection: "reconnecting", everConnected: true }), "reconnecting");
  assert.equal(effectiveState({ ...live, serverConnection: "reconnecting", everConnected: true, down: true }), "down");
  assert.equal(effectiveState({ ...live, serverConnection: "connecting", everConnected: false }), "connecting");
  assert.equal(effectiveState({ ...live, serverConnection: "connecting", everConnected: true }), "reconnecting");
  assert.equal(effectiveState({ ...INITIAL_META, status: "reconnecting" }), "reconnecting");
  assert.equal(effectiveState({ ...INITIAL_META, status: "off" }), "off");
  assert.equal(effectiveState({ ...INITIAL_META, status: "error" }), "error");
  assert.equal(effectiveState({ ...INITIAL_META, status: "ended" }), "ended");
});

test("store: 재연결이 30초 넘게 이어지면 '끊김'으로, 복구되면 되돌린다", () => {
  const timers = new FakeTimers();
  const store = createLiveStore("x", { timers, now: () => timers.now });
  store.setStatus("live");
  store.dispatch({ type: "snapshot", data: snap({ connection: "connected" }) });
  timers.advance(100);
  store.setServerConnection("reconnecting");
  assert.equal(effectiveState(store.getMeta()), "reconnecting");
  timers.advance(29_000);
  assert.equal(effectiveState(store.getMeta()), "reconnecting");
  timers.advance(1_000);
  assert.equal(effectiveState(store.getMeta()), "down");
  store.setServerConnection("connected");
  assert.equal(effectiveState(store.getMeta()), "live");
  assert.equal(store.getMeta().down, false);
});

test("liveMode: 스트림이 열리지 않으면 폴링(fallback), 첫 snapshot 전에는 pending, 받은 뒤에는 끊겨도 live(마지막 값 유지)", () => {
  const m = (o) => ({ ...INITIAL_META, ...o });
  assert.equal(liveMode(m({ status: "off" })), "fallback");
  assert.equal(liveMode(m({ status: "connecting" })), "pending");
  assert.equal(liveMode(m({ status: "live" })), "pending");
  assert.equal(liveMode(m({ status: "error", errorCode: "NOT_FOUND" })), "fallback");
  assert.equal(liveMode(m({ status: "ended" })), "fallback");
  assert.equal(liveMode(m({ status: "live", hasSnapshot: true })), "live");
  assert.equal(liveMode(m({ status: "reconnecting", hasSnapshot: true })), "live");
  assert.equal(liveMode(m({ status: "error", hasSnapshot: true })), "live");
});

// ── controller(가짜 EventSource) ────────────────────────────────────────
class FakeES {
  static all = [];
  constructor(url) { this.url = url; this.readyState = 0; this.onopen = null; this.onerror = null; this.handlers = {}; this.closed = false; FakeES.all.push(this); }
  addEventListener(type, fn) { (this.handlers[type] ??= []).push(fn); }
  close() { this.closed = true; this.readyState = 2; }
  // 시험 도우미
  open() { this.readyState = 1; this.onopen?.({}); }
  emit(type, data) { for (const fn of this.handlers[type] ?? []) fn({ data: typeof data === "string" ? data : JSON.stringify(data) }); }
  failRetry() { this.readyState = 0; this.onerror?.({}); } // 브라우저가 알아서 다시 연결하는 오류
  failClosed() { this.readyState = 2; this.onerror?.({}); } // HTTP 오류 등으로 연결이 거절됨
}

function setup(fetchFn, o = {}) {
  FakeES.all = [];
  const timers = new FakeTimers();
  const store = createLiveStore("005930", { timers, now: () => timers.now });
  const controller = new LiveStreamController({ url: "http://x/api/v1/local/stocks/005930/stream", store, createEventSource: (u) => new FakeES(u), fetchFn, timers, ...o });
  return { timers, store, controller };
}
const jsonRes = (status, body, type = "application/json") => ({ ok: status >= 200 && status < 300, status, headers: { get: () => type }, json: async () => body });
const flushMicro = () => new Promise((r) => setImmediate(r));

test("controller: 연결은 하나만 열고, 연결·snapshot·이벤트가 상태에 반영되며, stop하면 닫는다", () => {
  const { timers, store, controller } = setup(null);
  controller.start();
  controller.start(); // 두 번 불러도 하나
  assert.equal(FakeES.all.length, 1);
  assert.equal(store.getMeta().status, "connecting");
  const es = FakeES.all[0];
  es.open();
  es.emit("snapshot", snap({ ticks: [tick("09:00:01")], quote: quote("09:00:01", 77), connection: "connected" }));
  es.emit("tick", tick("09:00:02", 78, 1, 9));
  es.emit("bar", bar("09:00", 1, 2, 1, 2, 10));
  es.emit("quote", quote("09:00:02", 78));
  es.emit("book", { stock_code: "005930", time: null, asks: [], bids: [], total_ask_quantity: 0, total_bid_quantity: 0, expected: null, source: "ws" });
  timers.advance(100);
  const d = store.getData();
  assert.deepEqual([d.ticks.length, d.bars.length, d.quote.price, d.book !== null, store.getMeta().status, store.getMeta().hasSnapshot], [2, 1, 78, true, "live", true]);
  controller.stop();
  assert.equal(es.closed, true);
});

test("controller: 깨진 JSON·모양이 다른 이벤트는 무시(화면이 깨지지 않음)", () => {
  const { timers, store, controller } = setup(null);
  controller.start();
  const es = FakeES.all[0];
  es.open();
  es.emit("snapshot", "{not json");
  es.emit("snapshot", { foo: 1 });
  es.emit("tick", { price: "abc", time: "09:00:00" });
  es.emit("quote", null);
  timers.advance(200);
  assert.equal(store.getMeta().hasSnapshot, false);
  assert.equal(store.getData().ticks.length, 0);
});

test("controller: status 이벤트로 증권사 연결 상태를 반영", () => {
  const { store, controller } = setup(null);
  controller.start();
  const es = FakeES.all[0];
  es.open();
  es.emit("snapshot", snap({ connection: "connected" }));
  es.emit("status", { connection: "reconnecting", detail: "x" });
  assert.equal(effectiveState(store.getMeta()), "reconnecting");
  es.emit("status", { connection: "connected", detail: null });
  assert.equal(effectiveState(store.getMeta()), "live");
});

test("controller: end 이벤트 후에는 다시 연결하지 않는다(오류가 이어져도·시간이 지나도)", () => {
  const { timers, store, controller } = setup(null);
  controller.start();
  const es = FakeES.all[0];
  es.open();
  es.emit("snapshot", snap());
  es.emit("end", { reason: "forbidden" });
  assert.deepEqual([store.getMeta().status, store.getMeta().errorCode, es.closed], ["ended", "forbidden", true]);
  es.onerror?.({});
  timers.advance(120_000);
  assert.equal(FakeES.all.length, 1);
  assert.equal(store.getMeta().status, "ended");
});

test("controller: 브라우저가 재연결하는 동안 '재연결 중', 다시 열리면 '연결됨'(새 snapshot으로 교체)", () => {
  const { timers, store, controller } = setup(null);
  controller.start();
  const es = FakeES.all[0];
  es.open();
  es.emit("snapshot", snap({ ticks: [tick("09:00:01")] }));
  es.failRetry();
  assert.equal(store.getMeta().status, "reconnecting");
  assert.equal(liveMode(store.getMeta()), "live", "끊겨도 마지막 값은 유지");
  assert.equal(FakeES.all.length, 1, "연결을 새로 만들지 않는다(브라우저가 재연결)");
  es.open();
  es.emit("snapshot", snap({ ticks: [tick("09:00:09")] }));
  timers.advance(100);
  assert.equal(store.getMeta().status, "live");
  assert.deepEqual(store.getData().ticks.map((t) => t.time), ["09:00:09"]);
});

for (const [status, bodyCode, expected] of [
  [404, "FEATURE_DISABLED", "FEATURE_DISABLED"],
  [404, undefined, "NOT_FOUND"],
  [403, "FORBIDDEN", "FORBIDDEN"],
  [429, "REALTIME_CAPACITY", "REALTIME_CAPACITY"],
  [503, "LOCAL_INTRADAY_NOT_CONFIGURED", "LOCAL_INTRADAY_NOT_CONFIGURED"],
  [503, undefined, "LOCAL_INTRADAY_NOT_CONFIGURED"],
]) {
  test(`controller: 연결이 거절(HTTP ${status})되면 같은 주소를 fetch로 열어 이유(${expected})를 읽고 폴링으로 되돌아간다`, async () => {
    const calls = [];
    const fetchFn = async (url) => { calls.push(url); return jsonRes(status, bodyCode ? { data: null, error: { code: bodyCode, message: "x" } } : { detail: "x" }); };
    const { store, controller } = setup(fetchFn);
    controller.start();
    FakeES.all[0].failClosed();
    await flushMicro();
    assert.deepEqual(calls, ["http://x/api/v1/local/stocks/005930/stream"]);
    assert.deepEqual([store.getMeta().status, store.getMeta().errorCode, liveMode(store.getMeta())], ["error", expected, "fallback"]);
    assert.equal(FakeES.all.length, 1, "다시 연결하지 않는다");
  });
}

test("controller: 진단 fetch가 스트림(text/event-stream)을 열면 읽지 않고 취소한 뒤 3초 후 정상 경로로 다시 연결", async () => {
  let aborted = false;
  const fetchFn = async (_url, init) => { init.signal.addEventListener("abort", () => (aborted = true)); return jsonRes(200, null, "text/event-stream; charset=utf-8"); };
  const { timers, store, controller } = setup(fetchFn);
  controller.start();
  FakeES.all[0].failClosed();
  await flushMicro();
  assert.equal(aborted, true);
  assert.equal(store.getMeta().status, "connecting");
  assert.equal(FakeES.all.length, 1);
  timers.advance(3000);
  assert.equal(FakeES.all.length, 2);
});

test("controller: 서버 5xx·네트워크 오류는 간격을 늘려 재시도하다가 처음부터 계속 실패하면 포기(NETWORK_ERROR → 폴링)", async () => {
  const fetchFn = async () => { throw new TypeError("network"); };
  const { timers, store, controller } = setup(fetchFn);
  controller.start();
  FakeES.all[0].failClosed();
  await flushMicro();
  assert.equal(store.getMeta().status, "connecting");
  timers.advance(3000);
  assert.equal(FakeES.all.length, 2);
  FakeES.all[1].failClosed();
  await flushMicro();
  timers.advance(6000);
  assert.equal(FakeES.all.length, 3);
  FakeES.all[2].failClosed();
  await flushMicro();
  assert.deepEqual([store.getMeta().status, store.getMeta().errorCode, liveMode(store.getMeta())], ["error", "NETWORK_ERROR", "fallback"]);
});

test("controller: 데이터를 받은 뒤의 오류는 포기하지 않고 계속 재연결(마지막 값 유지)", async () => {
  const fetchFn = async () => jsonRes(502, { error: { code: "BAD_GATEWAY" } });
  const { timers, store, controller } = setup(fetchFn);
  controller.start();
  FakeES.all[0].open();
  FakeES.all[0].emit("snapshot", snap({ ticks: [tick("09:00:01")] }));
  for (let i = 0; i < 5; i++) {
    FakeES.all.at(-1).failClosed();
    await flushMicro();
    assert.equal(store.getMeta().status, "reconnecting");
    timers.advance(30_000);
  }
  assert.equal(FakeES.all.length, 6);
  assert.equal(liveMode(store.getMeta()), "live");
});

test("controller: stop 뒤에는 진단·재시도가 아무것도 하지 않는다", async () => {
  let resolve;
  const fetchFn = () => new Promise((r) => (resolve = r));
  const { timers, store, controller } = setup(fetchFn);
  controller.start();
  FakeES.all[0].failClosed();
  controller.stop();
  resolve(jsonRes(404, { error: { code: "NOT_FOUND" } }));
  await flushMicro();
  timers.advance(60_000);
  assert.equal(FakeES.all.length, 1);
  assert.notEqual(store.getMeta().status, "error");
});
