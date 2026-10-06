#!/usr/bin/env node
/**
 * 전 종목 준실시간 시세(DEC-084 B) 프론트 순수 로직 검증: 병합 규칙(merge)·조회 수명(poller, 가짜 시간·가짜 요청). 실행:
 *   node --experimental-strip-types scripts/check-live-market.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { EMPTY_LIVE_VIEW, STALE_AFTER_SEC, isValidLive, overlayAll, overlayQuote } from "../src/lib/liveMarket/merge.ts";
import { EMPTY_RETRY_MS, LiveMarketPoller, MARKET_CHUNK, MAX_BACKOFF_MS, MAX_POLL_MS, MIN_POLL_MS, nextDelayMs } from "../src/lib/liveMarket/poller.ts";

const daily = (code, close = 1000) => ({ stock_code: code, trade_date: "2026-10-05", close, change: 10, change_pct: 1, open: 990, high: 1010, low: 980, volume: 5 });
const live = (code, price = 1100, fetched = 1000) => ({ code, price, change: 100, change_pct: 10, volume: 77, open: 1000, high: 1120, low: 990, fetched_at: fetched });
const meta = (o = {}) => ({ cycle_seconds: 12, last_cycle_at: 1000, covered: 1, total: 1, stale: false, running: true, ...o });
const view = (quotes, o = {}) => ({ quotes, meta: meta(), unavailable: false, receivedAt: 1005, failing: false, ...o });

// ── merge ────────────────────────────────────────────────────────────
test("실시간 값이 일 종가 요약을 덮어쓰고 live 표지가 붙는다", () => {
  const q = overlayQuote(daily("A"), live("A"), false, 1005);
  assert.equal(q.close, 1100); assert.equal(q.change, 100); assert.equal(q.change_pct, 10);
  assert.equal(q.trade_date, "2026-10-05"); assert.deepEqual(q.live, { fetchedAt: 1000, ageSec: 5, stale: false });
  assert.equal(q.volume, 77);
});
test("실시간 값이 없거나 올바르지 않으면 덮어쓰지 않는다(0으로 채우지 않음)", () => {
  const d = daily("A");
  assert.equal(overlayQuote(d, undefined, false, 1), d);
  for (const bad of [{ ...live("A"), price: 0 }, { ...live("A"), price: NaN }, { ...live("A"), change: null }, { ...live("A"), fetched_at: undefined }]) {
    assert.equal(isValidLive(bad), false); assert.equal(overlayQuote(d, bad, false, 1), d);
  }
  assert.equal(overlayQuote(undefined, undefined, false, 1), undefined);
});
test("일 종가 요약이 없어도 실시간 값만으로 만든다", () => {
  const q = overlayQuote(undefined, live("A"), false, 1002);
  assert.equal(q.close, 1100); assert.equal(q.trade_date, ""); assert.equal(q.live.stale, false);
});
test("서버 stale·오래된 값·조회 실패 중이면 지연 표시, 값은 유지", () => {
  assert.equal(overlayQuote(daily("A"), live("A"), true, 1005).live.stale, true);
  assert.equal(overlayQuote(daily("A"), live("A", 1100, 1000), false, 1000 + STALE_AFTER_SEC + 1).live.stale, true);
  const out = overlayAll({ A: daily("A") }, view({ A: live("A") }, { failing: true }), ["A"]);
  assert.equal(out.A.live.stale, true); assert.equal(out.A.close, 1100);
});
test("시가·고가·저가가 0이면 null(미니 캔들을 그리지 않음)", () => {
  const q = overlayQuote(daily("A"), { ...live("A"), open: 0, high: 0, low: 0 }, false, 1001);
  assert.equal(q.open, null); assert.equal(q.high, null); assert.equal(q.low, null);
});
test("overlayAll: 요청한 코드만 덮고 나머지는 일 요약 유지, unavailable이면 그대로", () => {
  const d = { A: daily("A"), B: daily("B", 500) };
  const out = overlayAll(d, view({ A: live("A"), Z: live("Z") }), ["A", "B"]);
  assert.equal(out.A.close, 1100); assert.equal(out.B, d.B); assert.equal(out.Z, undefined);
  assert.equal(overlayAll(d, { ...EMPTY_LIVE_VIEW, unavailable: true }, ["A"]), d);
  assert.equal(overlayAll(d, EMPTY_LIVE_VIEW, ["A", "B"]).A.live, undefined); // 아직 응답 없음 → 일 요약
});

// ── poller ───────────────────────────────────────────────────────────
function harness({ responses = [], hidden = false } = {}) {
  const h = { now: 1000, timers: [], seq: 0, requests: [], views: [], hidden, queue: [...responses], aborted: 0 };
  const poller = new LiveMarketPoller({
    baseUrl: "http://x",
    request: (url, signal) => {
      h.requests.push(url);
      signal.addEventListener("abort", () => { h.aborted += 1; });
      const r = h.queue.length ? h.queue.shift() : { status: 200, body: { data: { quotes: [], missing: [], meta: meta() } } };
      return Promise.resolve(typeof r === "function" ? r() : r);
    },
    onView: (v) => h.views.push(v),
    setTimeout: (fn, ms) => { const id = ++h.seq; h.timers.push({ id, at: h.now + ms, fn }); return id; },
    clearTimeout: (id) => { h.timers = h.timers.filter((t) => t.id !== id); },
    isHidden: () => h.hidden,
    now: () => h.now,
  });
  h.poller = poller;
  h.next = async () => { // 가장 이른 타이머 하나를 실행하고 응답 처리를 기다린다
    const t = h.timers.sort((a, b) => a.at - b.at)[0];
    if (!t) return null;
    h.timers = h.timers.filter((x) => x !== t); h.now = Math.max(h.now, t.at);
    t.fn(); await new Promise((r) => setImmediate(r)); return t;
  };
  h.delay = () => { const t = h.timers[0]; return t ? t.at - h.now : null; };
  return h;
}
const ok = (quotes, m = meta()) => ({ status: 200, body: { data: { quotes, missing: [], meta: m } } });

test("setCodes → 즉시 조회, 응답이 오면 값이 채워지고 cycle/2(3~15초)로 다음 조회", async () => {
  const h = harness({ responses: [ok([live("A")])] });
  h.poller.setCodes(["A", "B"]);
  assert.equal(h.delay(), 0);
  await h.next();
  assert.equal(h.requests.length, 1); assert.match(h.requests[0], /codes=A,B$/);
  assert.equal(h.poller.current.quotes.A.price, 1100); assert.equal(h.poller.current.failing, false);
  assert.equal(h.delay(), 6000); // cycle 12초 → 6초
});
test("nextDelayMs 경계: 빈 응답 2초, cycle 2→3초 하한, 100→15초 상한, cycle 없음 10초", () => {
  assert.equal(nextDelayMs(meta(), false), EMPTY_RETRY_MS);
  assert.equal(nextDelayMs(meta({ cycle_seconds: 2 }), true), MIN_POLL_MS);
  assert.equal(nextDelayMs(meta({ cycle_seconds: 100 }), true), MAX_POLL_MS);
  assert.equal(nextDelayMs(meta({ cycle_seconds: null }), true), 10000);
  assert.equal(nextDelayMs(null, true), 10000);
});
test("첫 응답이 비어 있으면 2초 뒤 다시 묻는다", async () => {
  const h = harness({ responses: [ok([], meta({ cycle_seconds: null, stale: true }))] });
  h.poller.setCodes(["A"]); await h.next();
  assert.equal(h.delay(), EMPTY_RETRY_MS);
});
test("100개 초과는 100개씩 나눠 순서대로 조회", async () => {
  const codes = Array.from({ length: 230 }, (_, i) => `C${String(i).padStart(5, "0")}`);
  const h = harness(); h.poller.setCodes(codes); await h.next();
  assert.equal(MARKET_CHUNK, 100); assert.equal(h.requests.length, 3);
  assert.equal(h.requests[2].split("codes=")[1].split(",").length, 30);
});
test("403/404/503/401은 이 화면에서 쓸 수 없는 상태로 굳히고 다시 묻지 않는다", async () => {
  for (const status of [401, 403, 404, 503]) {
    const h = harness({ responses: [{ status, body: { error: { code: "X" } } }] });
    h.poller.setCodes(["A"]); await h.next();
    assert.equal(h.poller.current.unavailable, true, String(status));
    assert.equal(h.timers.length, 0); assert.deepEqual(h.poller.current.quotes, {});
    h.poller.setCodes(["B"]); assert.equal(h.timers.length, 0); // 코드가 바뀌어도 다시 묻지 않음
  }
});
test("429·네트워크 오류는 간격을 늘려 재시도(상한 30초)하고 값은 지연 표시로 유지, 복구되면 풀린다", async () => {
  const boom = () => { throw new Error("net"); };
  const h = harness({ responses: [ok([live("A")]), { status: 429, body: null }, boom, boom, boom, boom, ok([live("A", 1200)])] });
  h.poller.setCodes(["A"]); await h.next(); await h.next();
  assert.equal(h.poller.current.failing, true); assert.equal(h.poller.current.quotes.A.price, 1100);
  assert.equal(h.delay(), MIN_POLL_MS * 2);
  const delays = [];
  for (let i = 0; i < 4; i++) { await h.next(); delays.push(h.delay()); }
  assert.ok(delays.every((d) => d <= MAX_BACKOFF_MS)); assert.equal(delays.at(-1), MAX_BACKOFF_MS);
  await h.next();
  assert.equal(h.poller.current.failing, false); assert.equal(h.poller.current.quotes.A.price, 1200);
});
test("탭이 가려져 있으면 조회하지 않고, 다시 보이면 바로 조회", async () => {
  const h = harness({ hidden: true });
  h.poller.setCodes(["A"]); await h.next();
  assert.equal(h.requests.length, 0); assert.equal(h.timers.length, 0);
  h.hidden = false; h.poller.visibilityChanged(); await h.next();
  assert.equal(h.requests.length, 1);
});
test("코드가 바뀌면 진행 중 요청을 취소하고 이전 응답은 버린다", async () => {
  let release;
  const slow = () => new Promise((r) => { release = () => r(ok([live("A")])); });
  const h = harness({ responses: [slow] });
  h.poller.setCodes(["A"]);
  const t = h.timers[0]; h.timers = []; t.fn(); await new Promise((r) => setImmediate(r));
  h.poller.setCodes(["B"]);
  assert.equal(h.aborted, 1);
  release(); await new Promise((r) => setImmediate(r));
  assert.deepEqual(h.poller.current.quotes, {}); // 늦게 온 A 응답은 반영되지 않음
  await h.next(); assert.match(h.requests.at(-1), /codes=B$/);
});
test("같은 코드 목록을 다시 넘겨도 추가 조회를 만들지 않고, stop() 뒤에는 아무것도 하지 않는다", async () => {
  const h = harness(); h.poller.setCodes(["A"]); const n = h.timers.length;
  h.poller.setCodes(["A"]); assert.equal(h.timers.length, n);
  h.poller.stop(); assert.equal(h.timers.length, 0);
  h.poller.setCodes(["Z"]); assert.equal(h.timers.length, 0);
});
test("빈 코드 목록은 요청하지 않는다", async () => {
  const h = harness(); h.poller.setCodes(["A"]); await h.next(); h.poller.setCodes([]); await h.next();
  assert.equal(h.requests.length, 1);
});
