#!/usr/bin/env node
/**
 * 서버 호출 재시도(`fetchWithColdStartRetry`, DEC-065) 검증. 실행:
 *   node --experimental-strip-types --test scripts/check-server-fetch.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  COLD_START_ATTEMPTS,
  COLD_START_ATTEMPT_TIMEOUT_MS,
  COLD_START_DELAYS_MS,
  COLD_START_RETRY_STATUSES,
  fetchWithColdStartRetry,
} from "../src/lib/serverFetch.ts";

const res = (status) => new Response(JSON.stringify({ s: status }), { status });

/** 순서대로 결과를 내는 가짜 fetch. 값이 Error면 던지고, 숫자면 그 상태 코드의 응답을 낸다. */
function script(steps) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    const step = steps[Math.min(calls.length - 1, steps.length - 1)];
    if (step instanceof Error) throw step;
    return res(step);
  };
  return { impl, calls };
}
function sleeps() {
  const waited = [];
  return { fn: async (ms) => { waited.push(ms); }, waited };
}

test("기본값: 3회, 대기 3초·6초, 시도당 20초, 재시도 대상 502/503/504", () => {
  assert.equal(COLD_START_ATTEMPTS, 3);
  assert.deepEqual([...COLD_START_DELAYS_MS], [3000, 6000]);
  assert.equal(COLD_START_ATTEMPT_TIMEOUT_MS, 20000);
  assert.deepEqual([...COLD_START_RETRY_STATUSES].sort(), [502, 503, 504]);
});

test("첫 시도 성공: 1번만 호출, 기다리지 않음", async () => {
  const f = script([200]); const s = sleeps();
  const r = await fetchWithColdStartRetry("http://x/a", {}, { fetchImpl: f.impl, sleep: s.fn });
  assert.equal(r.status, 200); assert.equal(f.calls.length, 1); assert.deepEqual(s.waited, []);
});

test("503 두 번 뒤 성공: 3번 호출, 3초·6초 대기", async () => {
  const f = script([503, 503, 200]); const s = sleeps();
  const r = await fetchWithColdStartRetry("http://x/a", {}, { fetchImpl: f.impl, sleep: s.fn });
  assert.equal(r.status, 200); assert.equal(f.calls.length, 3); assert.deepEqual(s.waited, [3000, 6000]);
});

test("연결 오류(예외) 뒤 성공: 다시 시도", async () => {
  const f = script([new TypeError("fetch failed"), 200]); const s = sleeps();
  const r = await fetchWithColdStartRetry("http://x/a", {}, { fetchImpl: f.impl, sleep: s.fn });
  assert.equal(r.status, 200); assert.equal(f.calls.length, 2); assert.deepEqual(s.waited, [3000]);
});

test("502·504도 재시도 대상", async () => {
  for (const status of [502, 504]) {
    const f = script([status, 200]); const s = sleeps();
    const r = await fetchWithColdStartRetry("http://x/a", {}, { fetchImpl: f.impl, sleep: s.fn });
    assert.equal(r.status, 200); assert.equal(f.calls.length, 2, `status ${status}`);
  }
});

test("계속 503이면 3번 시도 후 마지막 503 응답을 그대로 돌려준다(오류 화면은 호출한 쪽이 처리)", async () => {
  const f = script([503]); const s = sleeps();
  const r = await fetchWithColdStartRetry("http://x/a", {}, { fetchImpl: f.impl, sleep: s.fn });
  assert.equal(r.status, 503); assert.equal(f.calls.length, 3); assert.deepEqual(s.waited, [3000, 6000]);
  assert.deepEqual(await r.json(), { s: 503 }); // 본문을 읽을 수 있어야 호출한 쪽이 error.code를 해석한다
});

test("계속 연결 오류면 마지막 오류를 던진다", async () => {
  const f = script([new TypeError("down")]); const s = sleeps();
  await assert.rejects(fetchWithColdStartRetry("http://x/a", {}, { fetchImpl: f.impl, sleep: s.fn }), /down/);
  assert.equal(f.calls.length, 3);
});

test("재시도하지 않는 상태: 404·400·429·500은 1번만 호출", async () => {
  for (const status of [404, 400, 429, 500, 401]) {
    const f = script([status, 200]); const s = sleeps();
    const r = await fetchWithColdStartRetry("http://x/a", {}, { fetchImpl: f.impl, sleep: s.fn });
    assert.equal(r.status, status); assert.equal(f.calls.length, 1, `status ${status}`); assert.deepEqual(s.waited, []);
  }
});

test("시도마다 새 시간 제한 신호가 붙고, 호출자의 헤더·캐시 옵션은 그대로 전달된다", async () => {
  const f = script([503, 200]); const s = sleeps();
  await fetchWithColdStartRetry("http://x/a", { cache: "no-store", headers: { "X-Internal-Token": "t" } }, { fetchImpl: f.impl, sleep: s.fn });
  assert.equal(f.calls.length, 2);
  for (const c of f.calls) {
    assert.ok(c.init.signal instanceof AbortSignal);
    assert.equal(c.init.cache, "no-store");
    assert.equal(c.init.headers["X-Internal-Token"], "t");
  }
  assert.notEqual(f.calls[0].init.signal, f.calls[1].init.signal);
});

test("시도 횟수·대기 시간을 바꿀 수 있고, 시도 1회면 재시도 없음", async () => {
  const f = script([503]); const s = sleeps();
  const r = await fetchWithColdStartRetry("http://x/a", {}, { attempts: 1, fetchImpl: f.impl, sleep: s.fn });
  assert.equal(r.status, 503); assert.equal(f.calls.length, 1);
  const g = script([503, 503, 503, 503]); const t = sleeps();
  await fetchWithColdStartRetry("http://x/a", {}, { attempts: 4, delaysMs: [100], fetchImpl: g.impl, sleep: t.fn });
  assert.deepEqual(t.waited, [100, 100, 100]);
});

test("실제 시간 제한: 응답이 없는 서버는 시도당 제한 시간에 끊긴다", async () => {
  const hang = async (_u, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason)));
  const s = sleeps();
  // AbortSignal.timeout의 타이머는 이벤트 루프를 붙잡지 않으므로(서버에서는 소켓이 붙잡는다) 시험에서는 직접 붙잡아 둔다.
  const keepAlive = setInterval(() => {}, 1000);
  try {
    await assert.rejects(
      fetchWithColdStartRetry("http://x/a", {}, { attempts: 2, attemptTimeoutMs: 50, fetchImpl: hang, sleep: s.fn }),
    );
  } finally {
    clearInterval(keepAlive);
  }
  assert.deepEqual(s.waited, [3000]);
});

test("내 PC(루프백·사설) 주소는 재시도 없이 한 번만 시도하고 곧바로 실패를 돌려준다(꺼진 API를 69초 기다리지 않음)", async () => {
  const { isLocalApiUrl } = await import("../src/lib/serverFetch.ts");
  for (const u of ["http://127.0.0.1:4001/x", "http://localhost:4001/x", "http://[::1]:4001/x", "http://192.168.0.5:4001/x", "http://10.1.2.3/x", "http://172.16.0.1/x"]) assert.equal(isLocalApiUrl(u), true, u);
  for (const u of ["https://api.example.com/x", "http://172.32.0.1/x", "http://8.8.8.8/x", "not a url"]) assert.equal(isLocalApiUrl(u), false, u);
  const fail = script([new Error("ECONNREFUSED")]);
  const waits = sleeps();
  await assert.rejects(() => fetchWithColdStartRetry("http://127.0.0.1:4001/api/v1/internal/auth/session-check", {}, { fetchImpl: fail.impl, sleep: waits.fn }));
  assert.equal(fail.calls.length, 1);
  assert.deepEqual(waits.waited, []);
  const r503 = script([503]);
  const out = await fetchWithColdStartRetry("http://localhost:4001/x", {}, { fetchImpl: r503.impl, sleep: waits.fn });
  assert.equal(out.status, 503);
  assert.equal(r503.calls.length, 1);
  // 원격(운영) 주소는 예전처럼 3회
  const remote = script([503, 503, 200]);
  const ok = await fetchWithColdStartRetry("https://api.example.com/x", {}, { fetchImpl: remote.impl, sleep: waits.fn });
  assert.equal(ok.status, 200);
  assert.equal(remote.calls.length, 3);
});
