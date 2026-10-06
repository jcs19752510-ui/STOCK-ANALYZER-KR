#!/usr/bin/env node
/**
 * 증권사 조건검색(DEC-088) 프론트 순수 로직 검증: 응답 정리·간격·신규 판정·변화 목록·가격 병합(logic) + 주기 조회 수명(poller, 가짜 시간·가짜 요청). 실행:
 *   node --experimental-strip-types scripts/check-psearch.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MAX_BACKOFF_MS, MAX_CHANGES, MAX_ITEMS, MAX_NAME_BOOK, MAX_POLL_MS, MIN_POLL_MS, NEW_WINDOW_SEC,
  backoffMs, changeRows, conditionLabel, diffCodes, errorInfo, formatHms, hasPrice, intervalMs, isNewEntry, mergeNames,
  mergePrice, nextNewExpiryMs, normalizeChanges, normalizeResults, parseConditions, serverNow, stockLabel, updatePriceBook,
} from "../src/lib/psearch/logic.ts";
import { MIN_GAP_MS, PsearchPoller } from "../src/lib/psearch/poller.ts";

const item = (code, o = {}) => ({ code, name: `N${code}`, market: "KOSPI", entered_at: 1000, ...o });
const results = (items, o = {}) => ({
  data: {
    seq: "0", items, count: items.length, capped: false, empty: false, empty_message: null, changes: [], fields: [],
    fetched_at: 2000, age_seconds: 0, cache_ttl_seconds: 5, stale: false, ...o,
  },
  error: null,
});
const quote = (code, close = 1000, o = {}) => ({ stock_code: code, trade_date: "2026-10-06", close, change: 10, change_pct: 1, ...o });

// ── 응답 정리 ────────────────────────────────────────────────────────
test("조건 목록: 정상·빈 배열·모양 불량·중복 seq·그룹 없음", () => {
  const ok = parseConditions({ data: { conditions: [{ seq: "0", group: "내조건", name: "급등" }, { seq: "0", group: "x", name: "중복" }, { seq: 1, group: "", name: "B" }, { seq: "", name: "무시" }, "bad"], fetched_at: 1 } });
  assert.deepEqual(ok.map((c) => c.seq), ["0", "1"]);
  assert.equal(conditionLabel(ok[0]), "내조건 · 급등"); assert.equal(conditionLabel(ok[1]), "B");
  assert.deepEqual(parseConditions({ data: { conditions: [] } }), []);
  for (const bad of [null, {}, { data: null }, { data: { conditions: "x" } }, { data: [] }]) assert.equal(parseConditions(bad), null);
});
test("결과 정리: 필수 코드만 믿고 이름·시장·편입 시각은 없으면 null, 중복 코드 제거, 100건 상한", () => {
  const r = normalizeResults(results([item("A00001"), { code: "A00002" }, { code: "A00001", name: "dup" }, { name: "코드없음" }, { code: "A00003", entered_at: "x" }]), "0");
  assert.deepEqual(r.items.map((i) => i.code), ["A00001", "A00002", "A00003"]);
  assert.equal(r.items[1].name, null); assert.equal(r.items[1].market, null); assert.equal(r.items[1].entered_at, null); assert.equal(r.items[2].entered_at, null);
  const many = Array.from({ length: 130 }, (_, i) => item(`C${String(i).padStart(5, "0")}`));
  assert.equal(normalizeResults(results(many), "0").items.length, MAX_ITEMS);
});
test("결과 정리: 요청한 seq와 다르거나 모양이 어긋나면 null(늦게 온 다른 조건 응답 방어)", () => {
  assert.equal(normalizeResults(results([], { seq: "1" }), "0"), null);
  assert.equal(normalizeResults({ data: { seq: "0", items: "x" } }, "0"), null);
  assert.equal(normalizeResults(null, "0"), null);
  assert.equal(normalizeResults({ data: null, error: { code: "X" } }, "0"), null);
});
test("결과 정리: 플래그는 true일 때만 참, empty_message는 empty일 때만, cache_ttl 불량이면 5초, 나이 음수·불량은 0", () => {
  const r = normalizeResults(results([], { empty: true, empty_message: "조건 없음", capped: "yes", stale: 1, cache_ttl_seconds: -3, age_seconds: -5 }), "0");
  assert.equal(r.empty, true); assert.equal(r.empty_message, "조건 없음"); assert.equal(r.capped, false); assert.equal(r.stale, false);
  assert.equal(r.cache_ttl_seconds, 5); assert.equal(r.age_seconds, 0);
  assert.equal(normalizeResults(results([item("A00001")], { empty: false, empty_message: "남은 문구" }), "0").empty_message, null);
  assert.equal(normalizeResults(results([], { empty: true, empty_message: "가".repeat(500) }), "0").empty_message.length, 200);
  assert.equal(normalizeResults(results([], { empty: true }), "0").empty_message, null);
  assert.equal(normalizeResults(results([], { fetched_at: "x" }), "0").fetched_at, null);
});
test("errorInfo: 봉투에서 코드·문구, 없으면 null", () => {
  assert.deepEqual(errorInfo({ data: null, error: { code: "PSEARCH_NOT_CONFIGURED", message: "m" } }), { code: "PSEARCH_NOT_CONFIGURED", message: "m" });
  assert.deepEqual(errorInfo(null), { code: null, message: null }); assert.deepEqual(errorInfo({ error: "x" }), { code: null, message: null });
});

// ── 간격 ─────────────────────────────────────────────────────────────
test("조회 간격: max(5초, cache_ttl) · 서버 상한 60초 · 불량 값은 5초", () => {
  assert.equal(intervalMs(2), MIN_POLL_MS); assert.equal(intervalMs(5), 5000); assert.equal(intervalMs(5.5), 5500);
  assert.equal(intervalMs(30), 30000); assert.equal(intervalMs(60), MAX_POLL_MS); assert.equal(intervalMs(600), MAX_POLL_MS);
  for (const bad of [0, -1, NaN, undefined, null, Infinity]) assert.equal(intervalMs(bad), MIN_POLL_MS, String(bad));
});
test("실패 간격: 두 배씩 늘어 30초 상한, 기본 간격이 더 길면 그 아래로 내려가지 않음", () => {
  assert.deepEqual([1, 2, 3, 4, 5, 50].map((n) => backoffMs(5000, n)), [10000, 20000, 30000, 30000, 30000, 30000]);
  assert.equal(backoffMs(60000, 1), 60000); assert.equal(backoffMs(20000, 1), 30000); assert.equal(backoffMs(5000, 0), 10000);
});

// ── 시각·신규 ────────────────────────────────────────────────────────
test("formatHms: 한국 표준시 HH:MM:SS, 자정·날짜 경계, 값 없음은 '-'", () => {
  assert.equal(formatHms(0), "09:00:00"); // 1970-01-01T00:00Z = 09:00 KST
  assert.equal(formatHms(Date.UTC(2026, 9, 6, 15, 0, 0) / 1000), "00:00:00"); // 2026-10-07 00:00 KST
  assert.equal(formatHms(Date.UTC(2026, 9, 6, 14, 59, 59) / 1000), "23:59:59");
  assert.equal(formatHms(Date.UTC(2026, 9, 6, 0, 5, 7.9) / 1000), "09:05:07");
  for (const bad of [null, undefined, NaN, "x"]) assert.equal(formatHms(bad), "-");
  assert.equal(formatHms(-1), "08:59:59");
});
test("신규 판정 경계: 60초 이하는 신규, 61초부터 아님, 시각 없음은 신규 아님, 미래 시각(시계 오차)은 신규", () => {
  assert.equal(NEW_WINDOW_SEC, 60);
  assert.equal(isNewEntry(1000, 1059), true); assert.equal(isNewEntry(1000, 1060), true);
  assert.equal(isNewEntry(1000, 1060.5), false); assert.equal(isNewEntry(1000, 1061), false);
  assert.equal(isNewEntry(1000, 1000), true); assert.equal(isNewEntry(1005, 1000), true);
  assert.equal(isNewEntry(null, 1000), false);
});
test("서버 기준 현재 시각: 응답 시각+나이+브라우저에서 흐른 시간, 브라우저 시계가 어긋나도 같다", () => {
  const data = normalizeResults(results([], { fetched_at: 2000, age_seconds: 3 }), "0");
  assert.equal(serverNow(data, 500, 500), 2003);
  assert.equal(serverNow(data, 500, 510), 2013);
  assert.equal(serverNow(data, 500, 400), 2003); // 시계가 뒤로 가도 줄지 않는다
  const noTime = normalizeResults(results([], { fetched_at: null }), "0");
  assert.equal(serverNow(noTime, 500, 520), 520);
});
test("신규 표지 만료 시점: 가장 이른 만료까지 ms, 신규가 없으면 null", () => {
  const items = [item("A", { entered_at: 1000 }), item("B", { entered_at: 1030 }), item("C", { entered_at: null }), item("D", { entered_at: 900 })];
  assert.equal(nextNewExpiryMs(items, 1010), (1000 + 60 - 1010) * 1000 + 250);
  assert.equal(nextNewExpiryMs(items, 1061), (1030 + 60 - 1061) * 1000 + 250); // A는 이미 끝남
  assert.equal(nextNewExpiryMs(items, 1091), null);
  assert.equal(nextNewExpiryMs([], 1000), null);
  assert.ok(nextNewExpiryMs([item("A", { entered_at: 940 })], 1000) >= 250);
});

// ── 변화 목록 ────────────────────────────────────────────────────────
test("변화 정리: 최대 10건·앞이 최신, 빈 변화·중복·모양 불량 제거, 같은 코드 중복 제거", () => {
  const raw = Array.from({ length: 20 }, (_, i) => ({ at: 5000 - i, added: [`A${i}`, `A${i}`], removed: [] }));
  const out = normalizeChanges([{ at: 1, added: [], removed: [] }, raw[0], raw[0], { added: ["x"] }, "bad", ...raw.slice(1)]);
  assert.equal(out.length, MAX_CHANGES); assert.equal(out[0].at, 5000); assert.deepEqual(out[0].added, ["A0"]); assert.equal(out[9].at, 4991);
  assert.deepEqual(normalizeChanges("x"), []); assert.deepEqual(normalizeChanges(undefined), []);
});
test("변화 행: HH:MM:SS·이름(코드)·모르는 코드는 코드만·5개 넘으면 '외 N'", () => {
  const names = { A00001: "가나다" };
  const rows = changeRows([{ at: Date.UTC(2026, 9, 6, 1, 2, 3) / 1000, added: ["A00001", "Z99999"], removed: ["R1", "R2", "R3", "R4", "R5", "R6", "R7"] }], names);
  assert.equal(rows[0].time, "10:02:03"); assert.deepEqual(rows[0].added, ["가나다(A00001)", "Z99999"]);
  assert.equal(rows[0].removed.length, 5); assert.equal(rows[0].removedMore, 2); assert.equal(rows[0].addedMore, 0);
  assert.equal(stockLabel("Q", {}), "Q");
  assert.equal(changeRows(Array.from({ length: 15 }, (_, i) => ({ at: i, added: ["A"], removed: [] })), {}).length, MAX_CHANGES);
});
test("이름 장부: 새 이름만 추가·바뀐 게 없으면 같은 객체·상한 초과 시 오래된 것부터 버림", () => {
  const b0 = {};
  const b1 = mergeNames(b0, [item("A"), { code: "B", name: null }]);
  assert.deepEqual(b1, { A: "NA" }); assert.equal(mergeNames(b1, [item("A")]), b1);
  assert.equal(mergeNames(b1, [item("A", { name: "개명" })]).A, "개명");
  const big = mergeNames({}, Array.from({ length: MAX_NAME_BOOK + 20 }, (_, i) => item(`C${i}`)));
  assert.equal(Object.keys(big).length, MAX_NAME_BOOK); assert.equal(big.C0, undefined); assert.ok(big[`C${MAX_NAME_BOOK + 19}`]);
});
test("종목 집합 차이: 편입·이탈 개수", () => {
  assert.deepEqual(diffCodes([item("A"), item("B")], [item("B"), item("C"), item("D")]), { added: 2, removed: 1 });
  assert.deepEqual(diffCodes([], []), { added: 0, removed: 0 }); assert.deepEqual(diffCodes([item("A")], []), { added: 0, removed: 1 });
});

// ── 가격 병합 ────────────────────────────────────────────────────────
test("가격 있음 판정: 없음·0·음수·NaN은 '-'(0으로 채우지 않음)", () => {
  assert.equal(hasPrice(quote("A", 1)), true);
  for (const q of [undefined, quote("A", 0), quote("A", -5), quote("A", NaN), { ...quote("A"), close: null }]) assert.equal(hasPrice(q), false);
});
test("가격 병합: 이번 값 우선, 없으면 이전 값을 '지연'으로, 둘 다 없으면 undefined", () => {
  const live = quote("A", 1100, { live: { fetchedAt: 1, ageSec: 2, stale: false } });
  assert.equal(mergePrice(live, quote("A", 900)), live);
  const kept = mergePrice(undefined, live);
  assert.equal(kept.close, 1100); assert.equal(kept.live.stale, true); assert.equal(live.live.stale, false); // 원본은 건드리지 않음
  assert.equal(mergePrice(undefined, quote("A", 900)).close, 900); // 일 종가 값은 live 표지가 없다
  assert.equal(mergePrice(quote("A", 0), undefined), undefined); assert.equal(mergePrice(undefined, undefined), undefined);
  assert.equal(mergePrice(quote("A", 0), quote("A", 800)).close, 800); // 이번 값이 0이면 이전 값
});
test("가격 장부: 값 있는 종목 갱신·값 없는 종목은 이전 값 유지·목록에서 빠진 종목은 버림·변화 없으면 같은 객체", () => {
  const qa = quote("A", 100), qb = quote("B", 200);
  const b1 = updatePriceBook({}, { A: qa, B: qb }, ["A", "B"]);
  assert.deepEqual(Object.keys(b1), ["A", "B"]);
  assert.equal(updatePriceBook(b1, { A: qa, B: qb }, ["A", "B"]), b1);
  const b2 = updatePriceBook(b1, { A: qa }, ["A", "B"]); assert.equal(b2, b1); assert.equal(b2.B, qb);
  const b3 = updatePriceBook(b1, { A: qa }, ["A"]); assert.deepEqual(Object.keys(b3), ["A"]);
  const b4 = updatePriceBook(b1, { A: quote("A", 0), B: quote("B", 250) }, ["A", "B"]); assert.equal(b4.A, qa); assert.equal(b4.B.close, 250);
  assert.deepEqual(updatePriceBook(b1, {}, []), {});
});

// ── 주기 조회 ────────────────────────────────────────────────────────
function harness({ responses = [], hidden = false, startNow = 1000 } = {}) {
  const h = { now: startNow, timers: [], seq: 0, requests: [], views: [], hidden, queue: [...responses], aborted: 0, pending: [] };
  h.poller = new PsearchPoller({
    baseUrl: "http://x",
    request: (url, signal) => {
      h.requests.push(url);
      signal.addEventListener("abort", () => { h.aborted += 1; });
      const r = h.queue.length ? h.queue.shift() : { status: 200, body: results([item("A00001")]) };
      return Promise.resolve(typeof r === "function" ? r(url) : r);
    },
    onView: (v) => h.views.push(v),
    setTimeout: (fn, ms) => { const id = ++h.seq; h.timers.push({ id, at: h.now + ms, fn }); return id; },
    clearTimeout: (id) => { h.timers = h.timers.filter((t) => t.id !== id); },
    isHidden: () => h.hidden,
    now: () => h.now,
  });
  h.next = async () => {
    const t = h.timers.sort((a, b) => a.at - b.at)[0];
    if (!t) return null;
    h.timers = h.timers.filter((x) => x !== t); h.now = Math.max(h.now, t.at);
    t.fn(); await new Promise((r) => setImmediate(r)); return t;
  };
  h.delay = () => { const t = h.timers[0]; return t ? t.at - h.now : null; };
  h.flush = () => new Promise((r) => setImmediate(r));
  return h;
}
const ok = (items, o) => ({ status: 200, body: results(items, o) });
const fail = (status, code = "X", message = "m") => ({ status, body: { data: null, error: { code, message } } });
const tick = async (h, n = 1) => { for (let i = 0; i < n; i++) await h.next(); };

test("setSeq → 즉시 조회, 응답이 오면 값이 채워지고 max(5초, ttl) 간격으로 다음 조회(초 단위 환산)", async () => {
  const h = harness({ responses: [ok([item("A00001")], { cache_ttl_seconds: 2 }), ok([item("A00001")], { cache_ttl_seconds: 12 })] });
  h.poller.setSeq("0"); assert.equal(h.delay(), 0);
  await h.next();
  assert.match(h.requests[0], /\/api\/v1\/local\/psearch\/results\?seq=0$/);
  assert.equal(h.poller.current.data.items.length, 1); assert.equal(h.poller.current.receivedAt, 1000);
  assert.equal(h.delay(), 5000); assert.equal(h.poller.current.intervalMs, 5000);
  await h.next(); assert.equal(h.delay(), 12000);
});
test("seq는 주소에 안전하게 붙는다(특수문자 인코딩)", async () => {
  const h = harness(); h.poller.setSeq("a b&c"); await h.next();
  assert.match(h.requests[0], /seq=a%20b%26c$/);
});
test("12초 안에 조회는 3건 이하(5초 간격: 0·5·10초)", async () => {
  const h = harness();
  h.poller.setSeq("0");
  while (h.timers.length && h.timers[0].at - 1000 <= 12000) await h.next();
  assert.equal(h.requests.length, 3);
});
test("403/404/503/401은 이 화면을 쓸 수 없는 상태로 굳히고 다시 묻지 않는다(코드 보존, 조건을 바꿔도 같다)", async () => {
  for (const [status, code] of [[403, "FORBIDDEN"], [404, "NOT_FOUND"], [503, "PSEARCH_NOT_CONFIGURED"], [503, "LOCAL_INTRADAY_NOT_CONFIGURED"], [401, "AUTH_REQUIRED"]]) {
    const h = harness({ responses: [fail(status, code)] });
    h.poller.setSeq("0"); await h.next();
    const v = h.poller.current;
    assert.deepEqual([v.unavailable.status, v.unavailable.code], [status, code]); assert.equal(v.data, null);
    assert.equal(h.timers.length, 0, String(status));
    h.poller.setSeq("1"); assert.equal(h.timers.length, 0); assert.equal(h.poller.current.unavailable.status, status); // 다시 묻지 않음
    h.poller.visibilityChanged(); assert.equal(h.timers.length, 0); assert.equal(h.requests.length, 1);
  }
});
test("값을 받은 뒤에 403이 오면 결과를 비우고 멈춘다", async () => {
  const h = harness({ responses: [ok([item("A00001")]), fail(403, "FORBIDDEN")] });
  h.poller.setSeq("0"); await tick(h, 2);
  assert.equal(h.poller.current.data, null); assert.equal(h.poller.current.unavailable.status, 403); assert.equal(h.timers.length, 0);
});
test("400 INVALID_SEQ는 멈추고(fatal) 다른 조건을 고르면 다시 시작한다. 다른 400은 재시도", async () => {
  const h = harness({ responses: [fail(400, "INVALID_SEQ")] });
  h.poller.setSeq("bad!"); await h.next();
  assert.equal(h.poller.current.fatal.code, "INVALID_SEQ"); assert.equal(h.timers.length, 0);
  h.poller.setSeq("0"); assert.equal(h.poller.current.fatal, null); await h.next();
  assert.equal(h.poller.current.data.seq, "0");
  const h2 = harness({ responses: [fail(400, "OTHER")] });
  h2.poller.setSeq("0"); await h2.next(); assert.equal(h2.poller.current.fatal, null); assert.equal(h2.poller.current.failing, true); assert.equal(h2.timers.length, 1);
});
test("429·502·네트워크 오류·불량 응답은 간격을 늘려(상한 30초) 재시도하고 마지막 값은 유지, 복구되면 풀린다", async () => {
  const boom = () => { throw new Error("net"); };
  const h = harness({ responses: [ok([item("A00001")]), fail(429, "RATE_LIMITED"), fail(502, "UPSTREAM_UNAVAILABLE"), boom, { status: 200, body: { data: { items: "x" } } }, fail(502, "PSEARCH_REJECTED", "증권사 문구"), ok([item("A00001"), item("A00002")])] });
  h.poller.setSeq("0"); await tick(h, 2);
  let v = h.poller.current;
  assert.equal(v.failing, true); assert.equal(v.data.items.length, 1); assert.equal(v.lastError.code, "RATE_LIMITED"); assert.equal(v.retryInMs, 10000); assert.equal(h.delay(), 10000);
  const delays = [h.delay()];
  for (let i = 0; i < 4; i++) { await h.next(); delays.push(h.delay()); }
  assert.deepEqual(delays, [10000, 20000, 30000, 30000, 30000]);
  assert.ok(delays.every((d) => d <= MAX_BACKOFF_MS));
  assert.equal(h.poller.current.lastError.code, "PSEARCH_REJECTED"); assert.equal(h.poller.current.lastError.message, "증권사 문구");
  assert.equal(h.poller.current.data.items.length, 1);
  await h.next();
  v = h.poller.current;
  assert.equal(v.failing, false); assert.equal(v.failures, 0); assert.equal(v.data.items.length, 2); assert.equal(v.lastError, null); assert.equal(h.delay(), 5000);
});
test("불량 응답(200인데 모양 불량)은 BAD_RESPONSE 실패, 다른 조건의 응답(seq 불일치)도 버린다", async () => {
  const h = harness({ responses: [{ status: 200, body: null }, ok([item("A00001")], { seq: "9" })] });
  h.poller.setSeq("0"); await h.next();
  assert.equal(h.poller.current.lastError.code, "BAD_RESPONSE"); assert.equal(h.poller.current.data, null);
  await h.next(); assert.equal(h.poller.current.data, null); assert.equal(h.poller.current.failing, true);
});
test("서버 캐시가 길면(ttl 40초) 간격도 40초이고, 실패해도 그 아래로 내려가지 않는다", async () => {
  const h = harness({ responses: [ok([item("A00001")], { cache_ttl_seconds: 40 }), fail(429, "RATE_LIMITED")] });
  h.poller.setSeq("0"); await h.next(); assert.equal(h.delay(), 40000);
  await h.next(); assert.equal(h.delay(), 40000);
});
test("stale 응답은 성공으로 취급(값 갱신, 정상 간격)", async () => {
  const h = harness({ responses: [ok([item("A00001")], { stale: true })] });
  h.poller.setSeq("0"); await h.next();
  assert.equal(h.poller.current.data.stale, true); assert.equal(h.poller.current.failing, false); assert.equal(h.delay(), 5000);
});
test("탭이 가려져 있으면 조회하지 않고, 다시 보이면 바로 조회, 가리면 대기 중 타이머·진행 중 요청을 취소한다", async () => {
  const h = harness({ hidden: true });
  h.poller.setSeq("0"); assert.equal(h.timers.length, 0); await h.flush(); assert.equal(h.requests.length, 0);
  h.hidden = false; h.poller.visibilityChanged(); assert.equal(h.delay(), 0); await h.next(); assert.equal(h.requests.length, 1);
  assert.equal(h.timers.length, 1); // 다음 조회 대기 중
  h.hidden = true; h.poller.visibilityChanged(); assert.equal(h.timers.length, 0);
  h.now += 600; await h.flush(); assert.equal(h.requests.length, 1); // 가려져 있는 동안 0건
  h.hidden = false; h.poller.visibilityChanged(); assert.equal(h.delay(), 0); await h.next(); assert.equal(h.requests.length, 2);
  // 진행 중 요청은 가리는 순간 취소되고 응답은 버려진다
  let release; const slow = () => new Promise((r) => { release = () => r(ok([item("A00009")])); });
  const g = harness({ responses: [ok([item("A00001")]), slow] });
  g.poller.setSeq("0"); await g.next(); await g.next();
  g.hidden = true; g.poller.visibilityChanged(); assert.equal(g.aborted, 1);
  release(); await g.flush();
  assert.equal(g.poller.current.data.items[0].code, "A00001"); assert.equal(g.timers.length, 0);
});
test("가렸다 보였다를 빠르게 되풀이해도 요청 시작 간격은 1초 이상", async () => {
  const h = harness();
  h.poller.setSeq("0"); await h.next();
  h.hidden = true; h.poller.visibilityChanged(); h.hidden = false; h.now += 0.2; h.poller.visibilityChanged();
  assert.equal(Math.round(h.delay()), MIN_GAP_MS - 200);
  h.hidden = true; h.poller.visibilityChanged(); h.now += 5; h.hidden = false; h.poller.visibilityChanged(); assert.equal(h.delay(), 0);
});
test("조건이 바뀌면 진행 중 요청을 취소하고 늦게 온 이전 응답은 버린다(응답 순서가 뒤바뀌어도)", async () => {
  let releaseA;
  const slowA = () => new Promise((r) => { releaseA = () => r(ok([item("A00001")], { seq: "0" })); });
  const h = harness({ responses: [slowA, ok([item("B00002")], { seq: "1" })] });
  h.poller.setSeq("0");
  const t = h.timers[0]; h.timers = []; t.fn(); await h.flush();
  h.poller.setSeq("1"); assert.equal(h.aborted, 1); assert.equal(h.poller.current.seq, "1"); assert.equal(h.poller.current.data, null);
  await h.next();
  releaseA(); await h.flush();
  assert.equal(h.poller.current.data.seq, "1"); assert.equal(h.poller.current.data.items[0].code, "B00002");
  assert.equal(h.timers.length, 1); // 이전 응답이 다음 조회를 만들지 않았다
  assert.match(h.requests.at(-1), /seq=1$/);
});
test("조건이 바뀌면 이전 조건의 값·실패 상태·이름 장부가 사라지고 처음부터 시작한다", async () => {
  const h = harness({ responses: [ok([item("A00001")]), fail(429, "RATE_LIMITED"), ok([item("B00002")], { seq: "1" })] });
  h.poller.setSeq("0"); await tick(h, 2);
  assert.equal(h.poller.current.failing, true);
  h.poller.setSeq("1"); const v = h.poller.current;
  assert.equal(v.data, null); assert.equal(v.failing, false); assert.equal(v.failures, 0); assert.deepEqual(v.names, {}); assert.equal(h.delay(), 0);
  await h.next(); assert.equal(h.delay(), 5000); // 실패 횟수가 이어지지 않는다
});
test("같은 조건을 다시 넘겨도 추가 조회가 없고, stop() 뒤에는 아무것도 하지 않는다. null이면 조회하지 않는다", async () => {
  const h = harness(); h.poller.setSeq("0"); const n = h.timers.length;
  h.poller.setSeq("0"); assert.equal(h.timers.length, n);
  h.poller.setSeq(null); assert.equal(h.timers.length, 0); assert.equal(h.poller.current.data, null);
  h.poller.setSeq("0"); h.poller.stop(); assert.equal(h.timers.length, 0);
  h.poller.setSeq("Z"); h.poller.visibilityChanged(); assert.equal(h.timers.length, 0); assert.equal(h.requests.length, 0);
});
test("낭독 사건: 첫 조회=loaded, 집합 변화=changed(개수), 변화 없으면 그대로, 실패 시작=failing(한 번만), 복구=recovered", async () => {
  const h = harness({ responses: [ok([item("A00001"), item("A00002")]), ok([item("A00001"), item("A00002")]), ok([item("A00002"), item("A00003"), item("A00004")]), fail(429, "RATE_LIMITED"), fail(429, "RATE_LIMITED"), ok([item("A00002"), item("A00003"), item("A00004")])] });
  h.poller.setSeq("0");
  await h.next(); let e = h.poller.current.event; assert.deepEqual([e.id, e.kind, e.count], [1, "loaded", 2]);
  await h.next(); assert.equal(h.poller.current.event.id, 1); // 변화 없음 → 새 사건 없음
  await h.next(); e = h.poller.current.event; assert.deepEqual([e.id, e.kind, e.added, e.removed, e.count], [2, "changed", 2, 1, 3]);
  await h.next(); assert.deepEqual([h.poller.current.event.id, h.poller.current.event.kind], [3, "failing"]);
  await h.next(); assert.equal(h.poller.current.event.id, 3); // 실패가 이어져도 되풀이하지 않음
  await h.next(); assert.deepEqual([h.poller.current.event.id, h.poller.current.event.kind], [4, "recovered"]);
  const ids = h.views.map((v) => v.event?.id ?? 0); assert.deepEqual([...ids].sort((a, b) => a - b), ids); // 번호는 줄어들지 않는다
});
test("이름 장부는 이탈한 종목 이름도 남긴다(변화 목록 표시용)", async () => {
  const h = harness({ responses: [ok([item("A00001"), item("A00002")]), ok([item("A00002")])] });
  h.poller.setSeq("0"); await tick(h, 2);
  assert.equal(h.poller.current.names.A00001, "NA00001");
});
test("값 없는 결과(0건·empty)도 정상 응답으로 처리하고 이전 종목은 사라진 것으로 본다", async () => {
  const h = harness({ responses: [ok([item("A00001")]), ok([], { empty: true, empty_message: "조건 없음" })] });
  h.poller.setSeq("0"); await tick(h, 2);
  const v = h.poller.current; assert.equal(v.data.empty, true); assert.equal(v.data.items.length, 0); assert.equal(v.failing, false);
  assert.deepEqual([v.event.kind, v.event.removed], ["changed", 1]);
});

// 전환 항목 노출 판단(HTS ID 미설정 관리자 예외): 이 예외는 `src/lib/psearch/react.ts`의 NOT_CONFIGURED_CODE 상수와 같은 코드여야 한다.
test("전환 항목 노출 예외 코드는 계약서의 PSEARCH_NOT_CONFIGURED 하나뿐이다", async () => {
  const src = (await import("node:fs")).readFileSync(new URL("../src/lib/psearch/react.ts", import.meta.url), "utf8");
  assert.match(src, /const NOT_CONFIGURED_CODE = "PSEARCH_NOT_CONFIGURED";/);
  assert.ok(!/LOCAL_INTRADAY_NOT_CONFIGURED/.test(src.split("NOT_CONFIGURED_CODE")[1] ?? ""), "앱키 없음(LOCAL_INTRADAY_NOT_CONFIGURED)은 예외에 넣지 않는다");
});
