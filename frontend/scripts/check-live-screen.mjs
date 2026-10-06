#!/usr/bin/env node
/**
 * 장중 기준 재계산 화면(DEC-089/090) 프론트 순수 로직 검증: 응답 정리·오류 매핑·지연 판정·편입/이탈 기록(logic) +
 * 조회 수명(controller: 가짜 시계·가짜 요청·가짜 가시성). 실행:
 *   node --experimental-strip-types scripts/check-live-screen.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EMPTY_CHANGE_LOG, MAX_BACKOFF_MS, NEW_WINDOW_SEC, TOGGLE_STORAGE_KEY, applyChanges, bannerNotices, buildLiveUrl, changeRows, clampRefreshSeconds,
  clearsData, dataAgeSeconds, isDelayed, mapLiveError, mergeNames, newCodes, nextBackoffMs, nextNewExpiryMs, parseLiveMeta, parseLiveSuccess,
  readStoredToggle, retryPolicy, statusKey, stripLiveParams, writeStoredToggle,
} from "../src/lib/liveScreen/logic.ts";
import { LiveScreenController } from "../src/lib/liveScreen/controller.ts";
import { MAX_QUERY_LENGTH } from "../src/lib/auth/bffPaths.ts";

// ── 공통 데이터 ──────────────────────────────────────────────────────
const fill = (o = {}) => ({ gap_days: 0, state: "none", done: 0, total: 0, filled: 0, excluded: 0, mismatched: 0, pending: 0, source: null, ...o });
const liveMeta = (o = {}) => ({
  snapshot_id: "snap-1", as_of: 1000, basis_trade_date: "2026-10-05", expected_trade_date: "2026-10-05", today: "2026-10-06",
  quotes_covered: 2700, quotes_total: 2800, coverage_ratio: 0.964, oldest_quote_age_seconds: 4, stale: false, volume_partial: true,
  recomputed: ["return_pct"], fixed_daily: ["per"], return_rank_policy: "live", compute_ms: 120, refresh_seconds: 10, priority_codes: 50,
  priority_cycle_seconds: 3, base_fill: fill(), changes: null, ...o,
});
const item = (code, basis = "live") => ({ stock_code: code, name: `이름${code}`, market: "KOSPI", matched_metrics: {}, basis });
const okBody = ({ meta = {}, items = [item("A"), item("B", "daily")], page = 1, total = 2, generated = null } = {}) => ({
  data: { items, total_count: total, page },
  meta: { data_freshness: null, disclaimer: "", generated_at: generated ?? new Date(1010 * 1000).toISOString(), live: liveMeta(meta) },
  error: null,
});
const ok = (o) => ({ status: 200, body: okBody(o) });
const err = (status, code, extra = {}) => ({ status, body: { data: null, meta: {}, error: { code, message: `m-${code}`, ...extra } } });
const Q = { kind: "screen", params: "market=ALL&sort_by=return_pct&sort_dir=desc" };

// ── logic ────────────────────────────────────────────────────────────
test("clampRefreshSeconds: 5~60초로 보정, 숫자가 아니면 기본 10초", () => {
  assert.equal(clampRefreshSeconds(10), 10); assert.equal(clampRefreshSeconds(3), 5); assert.equal(clampRefreshSeconds(5), 5);
  assert.equal(clampRefreshSeconds(60), 60); assert.equal(clampRefreshSeconds(120), 60); assert.equal(clampRefreshSeconds(7.4), 7);
  for (const bad of [undefined, null, "10", NaN, Infinity, {}]) assert.equal(clampRefreshSeconds(bad), 10, String(bad));
});

test("nextBackoffMs: 기본 간격부터 두 배씩, 상한 30초", () => {
  assert.deepEqual([1, 2, 3, 4, 5, 20].map((n) => nextBackoffMs(10000, n)), [10000, 20000, 30000, 30000, 30000, 30000]);
  assert.deepEqual([1, 2, 3, 4].map((n) => nextBackoffMs(5000, n)), [5000, 10000, 20000, 30000]);
  assert.equal(nextBackoffMs(60000, 1), MAX_BACKOFF_MS); // 상한을 넘는 기본 간격도 30초를 넘지 않는다
  assert.equal(nextBackoffMs(10000, 0), 10000);
});

test("isDelayed: 마지막 성공이 refresh_seconds의 3배를 넘으면 지연(경계 포함 안 함), 성공 전은 지연 아님", () => {
  assert.equal(isDelayed(1030, 1000, 10), false); // 정확히 30초 = 3배: 지연 아님
  assert.equal(isDelayed(1030.1, 1000, 10), true);
  assert.equal(isDelayed(1010, 1000, 10), false);
  assert.equal(isDelayed(1015.1, 1000, 5), true); // 5초 갱신이면 15초 초과
  assert.equal(isDelayed(1100, null, 10), false);
  assert.equal(isDelayed(1031, 1000, 3), true); // 3은 5로 보정 → 15초 기준
  assert.equal(isDelayed(1031, 1000, 120), false); // 120은 60으로 보정 → 180초 기준
});

test("dataAgeSeconds: 서버 시각 기준으로 받은 시점의 나이를 구해 브라우저 시계 어긋남에 흔들리지 않는다", () => {
  // 서버는 as_of 1000에 계산, 1003에 응답. 브라우저 시계는 5000(수천 초 어긋남)에 받았다.
  assert.equal(dataAgeSeconds(1000, 5000, 5000, 1003), 3);
  assert.equal(dataAgeSeconds(1000, 5000, 5007, 1003), 10);
  assert.equal(dataAgeSeconds(1000, 1004, 1009, null), 9); // 서버 시각을 모르면 브라우저 시계
  assert.equal(dataAgeSeconds(1000, 1004, 900, 990), 0); // 음수는 0
});

test("parseLiveMeta: 정상·기본값·필수 필드 누락", () => {
  const m = parseLiveMeta(liveMeta({ base_fill: fill({ state: "running", gap_days: 2, done: 10, total: 100, pending: 90 }), changes: { entered: ["A", "A", "B"], left: ["C"] } }));
  assert.equal(m.snapshot_id, "snap-1"); assert.equal(m.base_fill.pending, 90); assert.deepEqual(m.changes, { entered: ["A", "B"], left: ["C"] });
  assert.equal(parseLiveMeta({ ...liveMeta(), snapshot_id: undefined }), null);
  assert.equal(parseLiveMeta({ ...liveMeta(), snapshot_id: "" }), null);
  assert.equal(parseLiveMeta({ ...liveMeta(), as_of: "x" }), null);
  assert.equal(parseLiveMeta(null), null); assert.equal(parseLiveMeta([]), null);
  const d = parseLiveMeta({ snapshot_id: "s", as_of: 1 });
  assert.equal(d.refresh_seconds, 10); assert.equal(d.volume_partial, true); assert.equal(d.base_fill.state, "none"); assert.equal(d.changes, null);
  assert.equal(d.return_rank_policy, "daily"); assert.equal(d.coverage_ratio, 0);
  assert.equal(parseLiveMeta({ ...liveMeta(), volume_partial: false }).volume_partial, true); // 경고는 숨기지 않는다
  assert.equal(parseLiveMeta({ ...liveMeta(), refresh_seconds: 1 }).refresh_seconds, 5);
  assert.equal(parseLiveMeta({ ...liveMeta(), coverage_ratio: 7 }).coverage_ratio, 1);
  assert.equal(parseLiveMeta({ ...liveMeta(), base_fill: { state: "bogus", excluded: -3, done: "x" } }).base_fill.excluded, 0);
  assert.equal(parseLiveMeta({ ...liveMeta(), changes: { entered: new Array(300).fill(0).map((_, i) => `C${i}`), left: [] } }).changes.entered.length, 100);
});

test("parseLiveSuccess: 항목·총건수·쪽·meta.live가 모두 맞아야 성공", () => {
  assert.ok(parseLiveSuccess(okBody()));
  assert.equal(parseLiveSuccess(okBody()).generatedAt, 1010);
  for (const bad of [null, {}, { data: null, meta: {} }, { data: { items: [], total_count: 0, page: 1 }, meta: {} }, { data: { items: [], total_count: 0, page: 1 }, meta: { live: {} } },
    { data: { items: "x", total_count: 0, page: 1 }, meta: { live: liveMeta() } }, { data: { items: [], page: 1 }, meta: { live: liveMeta() } }, { data: { items: [], total_count: 0 }, meta: { live: liveMeta() } }]) {
    assert.equal(parseLiveSuccess(bad), null, JSON.stringify(bad).slice(0, 60));
  }
});

test("mapLiveError: 상태·코드 → 종류, 진행률, 재시도 정책", () => {
  const cases = [
    [410, "SNAPSHOT_EXPIRED", "snapshot_expired", "immediate"], [410, null, "snapshot_expired", "immediate"],
    [409, "LIVE_BASE_STALE", "base_stale", "none"], [503, "LIVE_BASE_FILLING", "base_filling", "fast"], [503, "LIVE_QUOTES_NOT_READY", "quotes_not_ready", "fast"],
    [403, "FORBIDDEN", "forbidden", "none"], [401, "UNAUTHORIZED", "forbidden", "none"], [404, "NOT_FOUND", "not_found", "none"],
    [400, "INVALID_PARAMETER", "invalid", "none"], [429, "RATE_LIMITED", "rate_limited", "backoff"],
    [503, "LOCAL_INTRADAY_NOT_CONFIGURED", "unavailable", "none"], [503, "FEATURE_DISABLED", "unavailable", "none"],
    [503, "SERVICE_UNAVAILABLE", "server", "backoff"], [503, null, "server", "backoff"], [502, "UPSTREAM", "server", "backoff"], [500, "INTERNAL", "server", "backoff"],
    [409, "OTHER", "server", "backoff"], [424, "CALENDAR_NOT_CONFIRMED", "server", "backoff"],
  ];
  for (const [status, code, kind, policy] of cases) {
    const e = mapLiveError(status, code ? { error: { code, message: "x" } } : null);
    assert.equal(e.kind, kind, `${status} ${code}`); assert.equal(retryPolicy(e.kind), policy, `${status} ${code}`); assert.equal(e.status, status);
  }
  assert.equal(mapLiveError(0, null).kind, "network"); assert.equal(retryPolicy("network"), "backoff");
  assert.equal(mapLiveError(200, {}).kind, "bad_response");
  // 코드가 상태보다 우선(대행 경로가 상태를 바꿔도 코드로 구분)
  assert.equal(mapLiveError(500, { error: { code: "LIVE_BASE_STALE" } }).kind, "base_stale");
  const f = mapLiveError(503, { error: { code: "LIVE_BASE_FILLING", message: "보충 중", details: { done: 120, total: 2800, gap_days: 2 } } });
  assert.deepEqual(f.progress, { done: 120, total: 2800, gap_days: 2 }); assert.equal(f.message, "보충 중");
  assert.deepEqual(mapLiveError(503, { error: { code: "LIVE_BASE_FILLING", details: { done: 5000, total: 100 } } }).progress, { done: 100, total: 100, gap_days: null }); // done은 total을 넘지 않는다
  assert.equal(mapLiveError(503, { error: { code: "LIVE_BASE_FILLING" } }).progress, null); // details는 선택
  assert.equal(mapLiveError(503, { error: { code: "LIVE_BASE_FILLING", details: "x" } }).progress, null);
  assert.equal(mapLiveError(500, { error: { message: "a".repeat(1000) } }).message.length, 300);
  assert.equal(clearsData("base_stale"), true); assert.equal(clearsData("network"), false); assert.equal(clearsData("base_filling"), false);
});

test("buildLiveUrl·stripLiveParams: 일봉 화면과 같은 조건 + page + 선택 snapshot_id", () => {
  assert.equal(stripLiveParams("market=ALL&page=3&snapshot_id=zz&sort_by=return_pct"), "market=ALL&sort_by=return_pct");
  assert.equal(stripLiveParams(new URLSearchParams("a=1&page=2")), "a=1");
  assert.equal(buildLiveUrl("http://x/", "screen", "market=ALL", 2, null), "http://x/api/v1/local/screen?market=ALL&page=2");
  assert.equal(buildLiveUrl("http://x", "pattern", "market=ALL&required=c1%2Cc2", 1, "snap-9"), "http://x/api/v1/local/screen/pattern?market=ALL&required=c1%2Cc2&page=1&snapshot_id=snap-9");
  assert.equal(buildLiveUrl("http://x", "screen", "", 0, null), "http://x/api/v1/local/screen?page=1");
});

test("긴 조건 쿼리도 웹 서버 대행 한도(MAX_QUERY_LENGTH) 안: 모든 조건 + 최대 길이 값 + snapshot_id", () => {
  const keys = ["market", "market_cap_min", "market_cap_max", "volume_min", "return_pct_min", "return_pct_max", "per_max", "pbr_max", "ma5_gap_pct_min", "ma5_gap_pct_max",
    "ma20_gap_pct_min", "ma20_gap_pct_max", "volume_anomaly_score_min", "volume_anomaly_score_max", "sort_by", "sort_dir"];
  const p = new URLSearchParams();
  for (const k of keys) p.set(k, "-123456789012345.123456789");
  p.set("required", "c1,c2,c3,c4,c5,c9"); p.set("page_size", "50");
  const url = buildLiveUrl("http://x", "pattern", stripLiveParams(p), 99999, "f".repeat(64));
  const search = url.slice(url.indexOf("?"));
  assert.ok(search.length < MAX_QUERY_LENGTH / 2, `쿼리 ${search.length}자`);
});

test("applyChanges: 첫 계산(null)은 신규 없음, 편입은 신규·변화 기록, 같은 스냅샷은 다시 반영하지 않음", () => {
  let log = applyChanges(EMPTY_CHANGE_LOG, "s1", 1000, null, 2000);
  assert.equal(log.appliedSnapshotId, "s1"); assert.deepEqual(log.entered, {}); assert.equal(log.recent.length, 0);
  log = applyChanges(log, "s2", 1010, { entered: ["A", "B"], left: ["C"] }, 2010);
  assert.deepEqual([...newCodes(log, 2010)].sort(), ["A", "B"]);
  assert.equal(log.recent.length, 1); assert.deepEqual(log.recent[0].left, ["C"]); assert.equal(log.recent[0].at, 1010);
  assert.equal(applyChanges(log, "s2", 1010, { entered: ["Z"], left: [] }, 2020), log); // 같은 스냅샷: 같은 객체
  const same = applyChanges(log, "s3", 1020, { entered: [], left: [] }, 2020); // 내용 없는 변화는 목록에 올리지 않음
  assert.equal(same.recent.length, 1); assert.equal(same.appliedSnapshotId, "s3");
  const out = applyChanges(log, "s4", 1030, { entered: [], left: ["A"] }, 2030); // 빠진 종목은 신규에서 제외
  assert.equal(out.entered.A, undefined); assert.ok(out.entered.B);
});

test("신규 표지는 약 60초(경계 포함), 만료 시점 계산, 기록은 10건·오래된 신규 정리", () => {
  const log = applyChanges(EMPTY_CHANGE_LOG, "s1", 1000, { entered: ["A"], left: [] }, 2000);
  assert.equal(newCodes(log, 2000 + NEW_WINDOW_SEC).has("A"), true);
  assert.equal(newCodes(log, 2000 + NEW_WINDOW_SEC + 0.1).has("A"), false);
  assert.equal(nextNewExpiryMs(log, 2000), 60000 + 250); assert.equal(nextNewExpiryMs(log, 2059), 1000 + 250);
  assert.equal(nextNewExpiryMs(log, 2061), null); assert.equal(nextNewExpiryMs(EMPTY_CHANGE_LOG, 1), null);
  let l = EMPTY_CHANGE_LOG;
  for (let i = 0; i < 15; i++) l = applyChanges(l, `s${i}`, 1000 + i, { entered: [`E${i}`], left: [] }, 2000 + i * 100);
  assert.equal(l.recent.length, 10); assert.equal(l.recent[0].snapshotId, "s14");
  assert.deepEqual(Object.keys(l.entered), ["E14"]); // 60초가 지난 신규는 정리된다
});

test("mergeNames·changeRows: 본 적 있는 이름으로 편입·이탈 표시, 종목은 5개까지 + 외 N", () => {
  const names = mergeNames({}, [{ stock_code: "A", name: "가" }, { stock_code: "B", name: null }, "x", null]);
  assert.deepEqual(names, { A: "가" });
  assert.equal(mergeNames(names, [{ stock_code: "A", name: "가" }]), names); // 바뀐 것 없으면 같은 객체
  const rows = changeRows([{ at: 1, snapshotId: "s", entered: ["A", "B"], left: ["C1", "C2", "C3", "C4", "C5", "C6", "C7"] }], names);
  assert.deepEqual(rows[0].entered, ["가(A)", "B"]); assert.equal(rows[0].left.length, 5); assert.equal(rows[0].leftMore, 2);
});

test("bannerNotices: stale·커버율 <90%·보충 상태·제외/보충 중/불일치를 구분", () => {
  const n = bannerNotices(parseLiveMeta(liveMeta({ coverage_ratio: 0.89, stale: true, return_rank_policy: "daily", base_fill: fill({ state: "running", gap_days: 1, excluded: 3, mismatched: 2, pending: 40 }) })));
  assert.deepEqual(n, { stale: true, lowCoverage: true, baseFillRunning: true, baseFillUsed: false, baseFillFailed: false, excluded: 3, mismatched: 2, pending: 40 });
  const g = bannerNotices(parseLiveMeta(liveMeta({ coverage_ratio: 0.9, base_fill: fill({ state: "ready", gap_days: 2, filled: 2700 }) })));
  assert.equal(g.lowCoverage, false); assert.equal(g.baseFillUsed, true); assert.equal(g.baseFillRunning, false);
  assert.equal(bannerNotices(parseLiveMeta(liveMeta({ coverage_ratio: 0.95, return_rank_policy: "daily" }))).lowCoverage, true); // 정책이 일봉이면 안내
  assert.equal(bannerNotices(parseLiveMeta(liveMeta({ base_fill: fill({ state: "none" }) }))).baseFillUsed, false);
});

test("statusKey: 값이 아니라 상태가 바뀔 때만 열쇠가 달라진다(10초마다 읽지 않음)", () => {
  const base = { hasData: true, paused: false, delayed: false, errorKind: null, baseFillState: "none", stale: false, expiredNotice: false };
  assert.equal(statusKey(base), statusKey({ ...base })); // 갱신마다 같은 열쇠
  const keys = new Set([base, { ...base, paused: true }, { ...base, delayed: true }, { ...base, errorKind: "network" }, { ...base, errorKind: "network", hasData: false },
    { ...base, hasData: false }, { ...base, baseFillState: "running" }, { ...base, stale: true }, { ...base, expiredNotice: true, paused: true }].map(statusKey));
  assert.equal(keys.size, 9);
});

test("localStorage 기억: 읽기·쓰기 실패(차단·사설 창)에도 던지지 않는다", () => {
  const mem = new Map();
  const good = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.equal(readStoredToggle(good), false);
  assert.equal(writeStoredToggle(good, true), true); assert.equal(mem.get(TOGGLE_STORAGE_KEY), "1"); assert.equal(readStoredToggle(good), true);
  writeStoredToggle(good, false); assert.equal(readStoredToggle(good), false);
  const bad = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("quota"); } };
  assert.equal(readStoredToggle(bad), false); assert.equal(writeStoredToggle(bad, true), false);
  assert.equal(readStoredToggle(null), false); assert.equal(readStoredToggle(undefined), false); assert.equal(writeStoredToggle(null, true), false);
  assert.equal(readStoredToggle({ getItem: () => "garbage", setItem() {} }), false);
});

// ── controller ───────────────────────────────────────────────────────
function harness({ hidden = false } = {}) {
  const h = { now: 1000, timers: [], seq: 0, requests: [], views: [], hidden, queue: [], aborted: [] };
  // 요청마다 큐의 응답을 쓴다. 함수면 호출해서 Promise를 얻는다(보류 중인 요청을 시험하려면 deferred 사용).
  const ctl = new LiveScreenController({
    baseUrl: "http://x",
    request: (url, signal) => {
      h.requests.push(url);
      signal.addEventListener("abort", () => h.aborted.push(url));
      const r = h.queue.length ? h.queue.shift() : ok();
      return typeof r === "function" ? r(signal) : r instanceof Error ? Promise.reject(r) : Promise.resolve(r);
    },
    onView: (v) => h.views.push(v),
    setTimeout: (fn, ms) => { const id = ++h.seq; h.timers.push({ id, at: h.now * 1000 + ms, fn }); return id; },
    clearTimeout: (id) => { h.timers = h.timers.filter((t) => t.id !== id); },
    isHidden: () => h.hidden,
    now: () => h.now,
  });
  h.ctl = ctl;
  h.settle = () => new Promise((r) => setImmediate(r));
  h.next = async () => { // 가장 이른 타이머 하나를 실행하고 응답 처리를 기다린다
    const t = h.timers.sort((a, b) => a.at - b.at)[0];
    if (!t) return null;
    h.timers = h.timers.filter((x) => x !== t); h.now = Math.max(h.now, t.at / 1000);
    t.fn(); await h.settle(); return t;
  };
  h.delay = () => { const t = h.timers[0]; return t ? t.at - h.now * 1000 : null; };
  h.v = () => ctl.current;
  return h;
}
const deferred = () => { let resolve; const p = new Promise((r) => { resolve = r; }); return { p, resolve }; };
const snap = (n, o = {}) => ok({ ...o, meta: { snapshot_id: `snap-${n}`, as_of: 1000 + n, ...(o.meta ?? {}) } });
const qs = (url) => new URL(url).searchParams;

test("시작: 첫 요청은 snapshot_id 없이 보내고 성공하면 값·메타를 채우고 refresh_seconds 뒤로 다음 요청을 예약", async () => {
  const h = harness(); h.queue.push(snap(1));
  h.ctl.setQuery(Q); assert.equal(h.v().loading, true); assert.equal(h.v().data, null);
  await h.settle();
  assert.equal(h.requests.length, 1);
  const p = qs(h.requests[0]);
  assert.equal(new URL(h.requests[0]).pathname, "/api/v1/local/screen"); assert.equal(p.get("page"), "1"); assert.equal(p.has("snapshot_id"), false); assert.equal(p.get("market"), "ALL");
  assert.equal(h.v().loading, false); assert.equal(h.v().data.items.length, 2); assert.equal(h.v().meta.snapshot_id, "snap-1"); assert.equal(h.v().receivedAt, 1000);
  assert.equal(h.delay(), 10000); assert.equal(h.v().refreshSeconds, 10);
  h.ctl.stop();
});

test("자동 갱신: 서버 refresh_seconds(5~60 보정)만큼 뒤에 다시 요청, 목록은 응답 전까지 이전 값 유지(제자리 교체)", async () => {
  const h = harness(); h.queue.push(snap(1, { meta: { refresh_seconds: 7 } }), snap(3, { meta: { refresh_seconds: 999 } }));
  h.ctl.setQuery(Q); await h.settle(); assert.equal(h.delay(), 7000);
  const hold = deferred(); h.queue.unshift(() => hold.p);
  await h.next(); assert.equal(h.requests.length, 2); assert.equal(h.v().loading, true);
  assert.deepEqual(h.v().data.items.map((i) => i.stock_code), ["A", "B"]); // 응답 전: 이전 목록 그대로
  hold.resolve(snap(2, { meta: { refresh_seconds: 3 }, items: [item("C")], total: 1 })); await h.settle();
  assert.deepEqual(h.v().data.items.map((i) => i.stock_code), ["C"]); assert.equal(h.delay(), 5000); // 3초 → 5초로 보정
  await h.next(); assert.equal(h.delay(), 60000); // 999초 → 60초
  h.ctl.stop();
});

test("탭이 가려지면 예약이 멈추고 진행 중 요청은 취소, 보이면 즉시 요청", async () => {
  const h = harness(); h.queue.push(snap(1));
  h.ctl.setQuery(Q); await h.settle();
  const hold = deferred(); h.queue.unshift(() => hold.p);
  await h.next(); assert.equal(h.requests.length, 2); // 진행 중
  h.hidden = true; h.ctl.visibilityChanged();
  assert.equal(h.aborted.length, 1); assert.equal(h.v().loading, false); assert.equal(h.timers.length, 0);
  hold.resolve(snap(9)); await h.settle(); assert.equal(h.v().meta.snapshot_id, "snap-1"); // 늦은 응답 버림
  await h.settle(); assert.equal(h.requests.length, 2);
  h.hidden = false; h.queue.push(snap(2)); h.ctl.visibilityChanged(); await h.settle();
  assert.equal(h.requests.length, 3); assert.equal(h.v().meta.snapshot_id, "snap-2"); assert.equal(h.delay(), 10000);
  h.ctl.stop();
});

test("가려진 동안 타이머가 이미 만료돼 있어도 요청하지 않는다(복귀 시에만)", async () => {
  const h = harness(); h.queue.push(snap(1));
  h.ctl.setQuery(Q); await h.settle();
  h.hidden = true; // visibilityChanged를 거치지 않고 가려진 경우(이벤트 누락)에도 타이머 실행이 요청을 만들지 않는다
  await h.next(); assert.equal(h.requests.length, 1);
  h.hidden = false; h.ctl.visibilityChanged(); await h.settle(); assert.equal(h.requests.length, 2);
  h.ctl.stop();
});

test("실패: 마지막 값 유지 + 10·20·30·30초 백오프, 성공하면 정상 간격으로 복귀", async () => {
  const h = harness(); h.queue.push(snap(1), err(500, "INTERNAL"), new Error("net"), { status: 200, body: { data: { items: [] } } }, err(502, "X"), snap(2));
  h.ctl.setQuery(Q); await h.settle();
  const delays = [];
  for (let i = 0; i < 4; i++) { await h.next(); delays.push(h.delay()); assert.equal(h.v().data.items.length, 2, "마지막 값 유지"); assert.ok(h.v().error); }
  assert.deepEqual(delays, [10000, 20000, 30000, 30000]);
  assert.equal(h.v().failures, 4); assert.equal(h.v().retryInMs, 30000);
  assert.deepEqual([500, 0, 200, 502].map((s) => s), [500, 0, 200, 502]);
  await h.next(); assert.equal(h.v().error, null); assert.equal(h.v().failures, 0); assert.equal(h.delay(), 10000);
  h.ctl.stop();
});

test("오류 종류: 네트워크 예외는 network, 모양 어긋난 200은 bad_response(성공으로 받아들이지 않음)", async () => {
  const h = harness(); h.queue.push(new Error("net"));
  h.ctl.setQuery(Q); await h.settle(); assert.equal(h.v().error.kind, "network"); assert.equal(h.v().data, null); assert.equal(h.delay(), 10000);
  h.queue.push({ status: 200, body: { data: { items: [], total_count: 0, page: 1 }, meta: {} } });
  await h.next(); assert.equal(h.v().error.kind, "bad_response"); assert.equal(h.v().data, null); assert.equal(h.delay(), 20000);
  h.ctl.stop();
});

test("LIVE_BASE_FILLING: 진행률 보관 + 5초 간격 자동 재시도(실패 횟수는 늘지 않음), 준비되면 정상", async () => {
  const h = harness();
  h.queue.push(err(503, "LIVE_BASE_FILLING", { details: { done: 10, total: 100, gap_days: 2 } }), err(503, "LIVE_BASE_FILLING", { details: { done: 60, total: 100, gap_days: 2 } }), snap(1));
  h.ctl.setQuery(Q); await h.settle();
  assert.equal(h.v().error.kind, "base_filling"); assert.deepEqual(h.v().error.progress, { done: 10, total: 100, gap_days: 2 }); assert.equal(h.delay(), 5000); assert.equal(h.v().failures, 0);
  await h.next(); assert.deepEqual(h.v().error.progress, { done: 60, total: 100, gap_days: 2 }); assert.equal(h.delay(), 5000);
  await h.next(); assert.equal(h.v().error, null); assert.equal(h.v().data.items.length, 2);
  h.ctl.stop();
});

test("LIVE_QUOTES_NOT_READY: 5초 간격 재시도", async () => {
  const h = harness(); h.queue.push(err(503, "LIVE_QUOTES_NOT_READY"), snap(1));
  h.ctl.setQuery(Q); await h.settle(); assert.equal(h.v().error.kind, "quotes_not_ready"); assert.equal(h.delay(), 5000);
  await h.next(); assert.equal(h.v().error, null);
  h.ctl.stop();
});

test("다시 묻지 않는 오류(LIVE_BASE_STALE·403·404·400): 이전 값을 지우고 멈춤, 탭 복귀로도 재시도하지 않고 '새로 계산'만 다시 시도", async () => {
  for (const [status, code, kind] of [[409, "LIVE_BASE_STALE", "base_stale"], [403, "FORBIDDEN", "forbidden"], [404, "NOT_FOUND", "not_found"], [400, "INVALID_PARAMETER", "invalid"], [503, "LOCAL_INTRADAY_NOT_CONFIGURED", "unavailable"]]) {
    const h = harness(); h.queue.push(snap(1), err(status, code));
    h.ctl.setQuery(Q); await h.settle(); await h.next();
    assert.equal(h.v().error.kind, kind, code); assert.equal(h.v().data, null, `${code}: 이전 값 삭제`); assert.equal(h.timers.length, 0, code);
    h.hidden = true; h.ctl.visibilityChanged(); h.hidden = false; h.ctl.visibilityChanged(); await h.settle();
    assert.equal(h.requests.length, 2, `${code}: 복귀로 재시도하지 않음`);
    h.queue.push(snap(2)); h.ctl.refreshNow(); await h.settle();
    assert.equal(h.requests.length, 3); assert.equal(h.v().error, null); assert.ok(h.v().data); // 수동 재시도는 가능
    h.ctl.stop();
  }
});

test("일시정지: 현재 snapshot_id로 고정·타이머 해제, 쪽 이동은 같은 snapshot_id, 해제하면 고정을 풀고 즉시 새로 계산", async () => {
  const h = harness(); h.queue.push(snap(1, { page: 1, total: 120 }), snap(1, { page: 2, total: 120, items: [item("P2")] }), snap(1, { page: 3, total: 120, items: [item("P3")] }), snap(5));
  h.ctl.setQuery(Q); await h.settle();
  assert.equal(h.ctl.pause(), true); assert.equal(h.v().paused, true); assert.equal(h.v().pinnedSnapshotId, "snap-1"); assert.equal(h.timers.length, 0);
  h.ctl.setPage(2); await h.settle();
  assert.equal(qs(h.requests[1]).get("snapshot_id"), "snap-1"); assert.equal(qs(h.requests[1]).get("page"), "2"); assert.equal(h.v().data.page, 2);
  h.ctl.setPage(3); await h.settle(); assert.equal(qs(h.requests[2]).get("snapshot_id"), "snap-1");
  assert.equal(h.timers.length, 0, "일시정지 중 자동 갱신 없음");
  h.now += 600; h.ctl.visibilityChanged(); await h.settle(); assert.equal(h.requests.length, 3, "일시정지 중 복귀해도 요청 없음");
  h.ctl.resume(); await h.settle();
  assert.equal(h.requests.length, 4); assert.equal(qs(h.requests[3]).has("snapshot_id"), false); assert.equal(qs(h.requests[3]).get("page"), "3");
  assert.equal(h.v().paused, false); assert.equal(h.v().pinnedSnapshotId, null); assert.equal(h.delay(), 10000);
  h.ctl.stop();
});

test("일시정지는 결과가 있어야 가능, 진행 중인 자동 갱신은 취소되고 늦은 응답은 버림", async () => {
  const h = harness();
  h.ctl.setQuery(Q); // 결과 전
  assert.equal(h.ctl.pause(), false);
  await h.settle(); h.ctl.stop();
  const g = harness(); g.queue.push(snap(1)); g.ctl.setQuery(Q); await g.settle();
  const hold = deferred(); g.queue.unshift(() => hold.p); await g.next();
  assert.equal(g.ctl.pause(), true); assert.equal(g.aborted.length, 1); assert.equal(g.v().loading, false);
  hold.resolve(snap(7)); await g.settle(); assert.equal(g.v().meta.snapshot_id, "snap-1"); assert.equal(g.v().pinnedSnapshotId, "snap-1");
  g.ctl.stop();
});

test("일시정지 중 410: 고정을 풀고 한 번 새로 계산, 일시정지 유지·새 스냅샷에 다시 고정·안내 표시, 같은 쪽 유지", async () => {
  const h = harness(); h.queue.push(snap(1, { total: 120 }), err(410, "SNAPSHOT_EXPIRED"), snap(2, { page: 2, total: 120, items: [item("N")] }));
  h.ctl.setQuery(Q); await h.settle(); h.ctl.pause();
  h.ctl.setPage(2); await h.settle();
  assert.equal(h.requests.length, 3); assert.equal(qs(h.requests[1]).get("snapshot_id"), "snap-1"); assert.equal(qs(h.requests[2]).has("snapshot_id"), false); assert.equal(qs(h.requests[2]).get("page"), "2");
  assert.equal(h.v().paused, true); assert.equal(h.v().pinnedSnapshotId, "snap-2"); assert.equal(h.v().expiredNotice, true); assert.equal(h.v().error, null); assert.equal(h.timers.length, 0);
  h.ctl.refreshNow(); assert.equal(h.v().expiredNotice, false); // 사용자 동작으로 안내 해제
  h.ctl.stop();
});

test("410이 새로 계산에서도 오면 무한 반복하지 않고 일반 오류로 취급", async () => {
  const h = harness(); h.queue.push(snap(1), err(410, "SNAPSHOT_EXPIRED"), err(410, "SNAPSHOT_EXPIRED"));
  h.ctl.setQuery(Q); await h.settle(); h.ctl.pause(); h.ctl.setPage(2); await h.settle();
  assert.equal(h.requests.length, 3); assert.equal(h.v().error.kind, "server"); assert.ok(h.v().data); assert.equal(h.timers.length, 0); // 일시정지 중이라 자동 재시도 없음
  h.ctl.stop();
});

test("자동 갱신 중(고정 없음) 410이 와도 즉시 새로 계산", async () => {
  const h = harness(); h.queue.push(snap(1), err(410, "SNAPSHOT_EXPIRED"), snap(2));
  h.ctl.setQuery(Q); await h.settle(); await h.next();
  assert.equal(h.requests.length, 3); assert.equal(h.v().meta.snapshot_id, "snap-2"); assert.equal(h.v().paused, false);
  h.ctl.stop();
});

test("일시정지 중 '새로 계산': 고정 없이 요청하고 새 스냅샷에 다시 고정, 실패하면 이전 고정 유지", async () => {
  const h = harness(); h.queue.push(snap(1), snap(4), err(500, "INTERNAL"));
  h.ctl.setQuery(Q); await h.settle(); h.ctl.pause();
  h.ctl.refreshNow(); await h.settle();
  assert.equal(qs(h.requests[1]).has("snapshot_id"), false); assert.equal(h.v().pinnedSnapshotId, "snap-4"); assert.equal(h.v().paused, true);
  h.ctl.refreshNow(); await h.settle();
  assert.equal(h.v().pinnedSnapshotId, "snap-4"); assert.equal(h.v().error.kind, "server"); assert.equal(h.timers.length, 0);
  h.ctl.stop();
});

test("같은 요청은 합치고(1건), 다른 요청이 오면 이전 요청을 취소하며 늦은 응답은 버림", async () => {
  const h = harness(); h.queue.push(snap(1));
  h.ctl.setQuery(Q); await h.settle();
  const d1 = deferred(); h.queue.unshift(() => d1.p);
  h.ctl.refreshNow(); h.ctl.refreshNow(); h.ctl.refreshNow(); assert.equal(h.requests.length, 2, "같은 요청 합침");
  const d2 = deferred(); h.queue.unshift(() => d2.p);
  h.ctl.setPage(2); assert.equal(h.requests.length, 3); assert.equal(h.aborted.length, 1);
  d1.resolve(snap(8, { items: [item("OLD")] })); await h.settle(); assert.equal(h.v().meta.snapshot_id, "snap-1");
  d2.resolve(snap(9, { page: 2, items: [item("NEW")] })); await h.settle();
  assert.equal(h.v().meta.snapshot_id, "snap-9"); assert.equal(h.v().data.page, 2); assert.equal(h.timers.length, 1);
  h.ctl.stop();
});

test("조건이 바뀌면 이전 결과를 비우고 진행 중 요청을 취소, 늦은 이전 조건 응답은 버림", async () => {
  const h = harness(); const d1 = deferred(); h.queue.push(() => d1.p);
  h.ctl.setQuery(Q);
  h.queue.push(snap(2, { items: [item("NEWQ")] })); h.ctl.setQuery({ kind: "screen", params: "market=KOSPI" }); await h.settle();
  d1.resolve(snap(1, { items: [item("OLDQ")] })); await h.settle();
  assert.equal(h.aborted.length, 1); assert.deepEqual(h.v().data.items.map((i) => i.stock_code), ["NEWQ"]); assert.equal(qs(h.requests[1]).get("market"), "KOSPI");
  // 결과가 있는 상태에서 조건을 바꾸면 이전 값이 비워진다
  const d3 = deferred(); h.queue.unshift(() => d3.p); h.ctl.setQuery({ kind: "screen", params: "market=KOSDAQ" });
  assert.equal(h.v().data, null); assert.equal(h.v().meta, null); assert.deepEqual(h.v().changeLog.recent, []);
  d3.resolve(snap(3)); await h.settle(); h.ctl.stop();
});

test("같은 조건으로 '조건 적용': 새로 계산(제자리), 같은 조건의 다른 쪽이면 쪽 이동", async () => {
  const h = harness(); h.queue.push(snap(1), snap(2), snap(2, { page: 4 }));
  h.ctl.setQuery(Q); await h.settle();
  h.ctl.setQuery(Q, 1); assert.ok(h.v().data); await h.settle(); assert.equal(h.requests.length, 2); assert.equal(h.v().meta.snapshot_id, "snap-2");
  h.ctl.setQuery(Q, 4); await h.settle(); assert.equal(qs(h.requests[2]).get("page"), "4");
  h.ctl.stop();
});

test("일시정지 중 조건을 바꾸면 일시정지는 유지하고 새 결과의 스냅샷에 고정", async () => {
  const h = harness(); h.queue.push(snap(1), snap(6));
  h.ctl.setQuery(Q); await h.settle(); h.ctl.pause();
  h.ctl.setQuery({ kind: "screen", params: "market=KOSPI" }); assert.equal(h.v().paused, true); await h.settle();
  assert.equal(qs(h.requests[1]).has("snapshot_id"), false); assert.equal(h.v().pinnedSnapshotId, "snap-6"); assert.equal(h.timers.length, 0);
  h.ctl.stop();
});

test("편입·이탈: changes를 스냅샷마다 한 번만 반영(재사용 스냅샷·쪽 이동에서 중복 없음), 60초 뒤 신규 만료", async () => {
  const h = harness();
  h.queue.push(snap(1), snap(2, { meta: { changes: { entered: ["B"], left: ["Z"] } } }), snap(2, { meta: { changes: { entered: ["B"], left: ["Z"] } } }), snap(3, { meta: { changes: { entered: [], left: ["A"] } } }));
  h.ctl.setQuery(Q); await h.settle();
  assert.equal(newCodes(h.v().changeLog, h.now).size, 0); // 첫 계산: changes null
  await h.next(); assert.deepEqual([...newCodes(h.v().changeLog, h.now)], ["B"]); assert.equal(h.v().changeLog.recent.length, 1);
  const enteredAt = h.v().changeLog.entered.B;
  await h.next(); assert.equal(h.v().changeLog.entered.B, enteredAt, "같은 스냅샷 재사용: 신규 시각이 늘어나지 않음"); assert.equal(h.v().changeLog.recent.length, 1);
  await h.next(); assert.equal(h.v().changeLog.recent.length, 2); assert.equal(h.v().changeLog.recent[0].left[0], "A");
  assert.equal(newCodes(h.v().changeLog, enteredAt + 61).size, 0);
  assert.equal(h.v().names.A, "이름A"); // 이탈 종목 이름은 본 적 있는 이름으로
  h.ctl.stop();
});

test("지연 판정은 마지막 성공 기준: 실패가 이어져 3×refresh를 넘으면 isDelayed", async () => {
  const h = harness(); h.queue.push(snap(1), err(500, "X"), err(500, "X"), err(500, "X"));
  h.ctl.setQuery(Q); await h.settle();
  const at = h.v().receivedAt;
  await h.next(); assert.equal(isDelayed(h.now, at, h.v().refreshSeconds), false); // 10초
  await h.next(); assert.equal(isDelayed(h.now, at, h.v().refreshSeconds), false); // 20초 지점
  await h.next(); assert.equal(isDelayed(h.now, at, h.v().refreshSeconds), true); // 40초(30초 초과)
  assert.ok(h.v().data);
  h.ctl.stop();
});

test("clearQuery·stop: 요청·타이머 정리, 이후 응답·타이머 무시", async () => {
  const h = harness(); h.queue.push(snap(1)); h.ctl.setQuery(Q); await h.settle();
  const d = deferred(); h.queue.unshift(() => d.p); await h.next();
  h.ctl.clearQuery(); assert.equal(h.aborted.length, 1); assert.equal(h.timers.length, 0); assert.equal(h.v().query, null); assert.equal(h.v().data, null);
  d.resolve(snap(5)); await h.settle(); assert.equal(h.v().data, null);
  h.ctl.visibilityChanged(); h.ctl.refreshNow(); h.ctl.setPage(3); await h.settle(); assert.equal(h.requests.length, 2); // 조건이 없으면 요청하지 않는다
  h.queue.push(snap(6)); h.ctl.setQuery(Q); await h.settle(); assert.equal(h.requests.length, 3); // 다시 켜면 처음부터
  h.ctl.stop(); h.ctl.refreshNow(); h.ctl.setQuery({ kind: "screen", params: "x=1" }); await h.settle(); assert.equal(h.requests.length, 3);
});

test("패턴 화면: 같은 컨트롤러가 /local/screen/pattern을 부른다", async () => {
  const h = harness(); h.queue.push(snap(1));
  h.ctl.setQuery({ kind: "pattern", params: "market=ALL&required=c1%2Cc2&page_size=50" }); await h.settle();
  assert.equal(new URL(h.requests[0]).pathname, "/api/v1/local/screen/pattern"); assert.equal(qs(h.requests[0]).get("required"), "c1,c2");
  h.ctl.stop();
});

test("뷰 번호(seq)는 상태가 바뀔 때마다 증가하고 가짜 시계 없이도 순서를 보장", async () => {
  const h = harness(); h.queue.push(snap(1)); h.ctl.setQuery(Q); await h.settle();
  const seqs = h.views.map((v) => v.seq); assert.deepEqual(seqs, [...seqs].sort((a, b) => a - b)); assert.equal(new Set(seqs).size, seqs.length);
  h.ctl.stop();
});
