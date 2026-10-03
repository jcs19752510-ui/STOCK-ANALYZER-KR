#!/usr/bin/env node
/**
 * "서버 깨우는 중" 안내 로직 검증(DEC-063). 실행:
 *   node --experimental-strip-types --test scripts/check-api-wake.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { createWakeTracker, installWakeTracking, isApiRequest } from "../src/lib/apiWake.ts";

/** 가짜 타이머: advance(ms)로 시간을 흘려보낸다. */
function fakeTimers() {
  let now = 0, seq = 0;
  const jobs = new Map();
  return {
    setTimeout: (fn, ms) => { const id = ++seq; jobs.set(id, { at: now + ms, fn }); return id; },
    clearTimeout: (id) => { jobs.delete(id); },
    advance(ms) {
      now += ms;
      for (const [id, j] of [...jobs]) if (j.at <= now) { jobs.delete(id); j.fn(); }
    },
    count: () => jobs.size,
  };
}

test("isApiRequest: 우리 API(/api/ 경로, 같은 출처)만 센다", () => {
  const base = "https://api.example.com";
  assert.equal(isApiRequest("https://api.example.com/api/v1/screen", base), true);
  assert.equal(isApiRequest("/api/v1/screen", base), true); // 상대경로는 API 기준
  assert.equal(isApiRequest("https://api.example.com/other", base), false);
  assert.equal(isApiRequest("https://evil.example.com/api/v1/x", base), false);
  assert.equal(isApiRequest("https://api.example.com.evil.com/api/v1/x", base), false);
  assert.equal(isApiRequest("https://api.example.com/api/v1/x", undefined), false);
  assert.equal(isApiRequest("::bad::", base), false);
});

test("임계값 전에 끝나면 안내를 띄우지 않는다", () => {
  const t = fakeTimers(); const events = [];
  const tr = createWakeTracker((v) => events.push(v), 4500, t);
  const end = tr.begin();
  t.advance(4000); end(); t.advance(10000);
  assert.deepEqual(events, []);
  assert.equal(t.count(), 0); // 타이머 정리됨
});

test("임계값을 넘기면 안내를 띄우고, 끝나면 내린다", () => {
  const t = fakeTimers(); const events = [];
  const tr = createWakeTracker((v) => events.push(v), 4500, t);
  const end = tr.begin();
  t.advance(4500);
  assert.deepEqual(events, [true]); assert.equal(tr.isVisible(), true);
  end();
  assert.deepEqual(events, [true, false]);
});

test("여러 요청: 모두 끝나야 내린다, 같은 값은 중복 통지하지 않는다", () => {
  const t = fakeTimers(); const events = [];
  const tr = createWakeTracker((v) => events.push(v), 4500, t);
  const a = tr.begin(); const b = tr.begin();
  t.advance(5000);
  assert.deepEqual(events, [true]);
  a(); assert.deepEqual(events, [true]); // b가 아직 느림
  b(); assert.deepEqual(events, [true, false]);
});

test("end 두 번 호출은 안전하다", () => {
  const t = fakeTimers(); const events = [];
  const tr = createWakeTracker((v) => events.push(v), 4500, t);
  const end = tr.begin(); end(); end();
  assert.equal(tr.pendingCount(), 0);
});

test("installWakeTracking: API 요청만 감싸고 결과/오류를 그대로 전달, 복원 가능", async () => {
  const t = fakeTimers(); const events = [];
  const tr = createWakeTracker((v) => events.push(v), 100, t);
  let release; const calls = [];
  const target = {
    fetch: (input) => { calls.push(String(input)); return new Promise((res, rej) => { release = { res, rej }; }); },
  };
  const original = target.fetch;
  const restore = installWakeTracking(target, "https://api.example.com", tr);

  // 외부 요청은 추적하지 않는다
  const p0 = target.fetch("https://cdn.example.com/a.js"); release.res("cdn");
  assert.equal(await p0, "cdn"); assert.equal(tr.pendingCount(), 0);

  // API 요청: 느리면 안내, 성공하면 내림
  const p1 = target.fetch("https://api.example.com/api/v1/screen");
  assert.equal(tr.pendingCount(), 1);
  t.advance(100); assert.deepEqual(events, [true]);
  release.res("ok"); assert.equal(await p1, "ok");
  assert.deepEqual(events, [true, false]);

  // 실패해도 내리고 오류는 그대로 전달
  const p2 = target.fetch("https://api.example.com/api/v1/screen");
  t.advance(100);
  release.rej(new Error("boom"));
  await assert.rejects(p2, /boom/);
  assert.equal(tr.isVisible(), false); assert.equal(tr.pendingCount(), 0);

  restore(); assert.equal(target.fetch, original);
});
