#!/usr/bin/env node
/**
 * 차트 그리기(추세선·수평선) 상태 변환·검증(DEC-059). 실행:
 *   node --experimental-strip-types --test scripts/check-chart-drawings.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import * as d from "../src/lib/chartDrawings.ts";

const p = (date, price) => ({ date, price });

test("추가: 수평선·추세선 정상, 잘못된 값은 거절", () => {
  let r = d.addDrawing([], { kind: "hline", price: 12500 });
  assert.equal(r.result, "added");
  r = d.addDrawing(r.list, { kind: "trend", a: p("2026-07-15", 12300), b: p("2026-09-20", 13100) });
  assert.equal(r.result, "added");
  assert.equal(r.list.length, 2);
  for (const bad of [
    { kind: "hline", price: 0 }, { kind: "hline", price: -5 }, { kind: "hline", price: Number.NaN },
    { kind: "hline", price: 1e12 }, { kind: "trend", a: p("2026-07-15", 1), b: p("2026-07-15", 2) },
    { kind: "trend", a: p("2026-13-45", 1), b: p("2026-07-16", 2) }, { kind: "trend", a: p("2026-07-15", 1), b: p("x", 2) },
  ]) assert.equal(d.addDrawing([], bad).result, "invalid", JSON.stringify(bad));
});

test("최대 개수에서 가득 참 알림, 목록은 그대로", () => {
  let list = [];
  for (let i = 0; i < d.MAX_DRAWINGS; i++) list = d.addDrawing(list, { kind: "hline", price: 100 + i }).list;
  assert.equal(list.length, d.MAX_DRAWINGS);
  const r = d.addDrawing(list, { kind: "hline", price: 999 });
  assert.equal(r.result, "full");
  assert.equal(r.list.length, d.MAX_DRAWINGS);
});

test("삭제는 해당 id만, 없는 id는 변화 없음", () => {
  let r = d.addDrawing([], { kind: "hline", price: 10 });
  r = d.addDrawing(r.list, { kind: "hline", price: 20 });
  const [a, b] = r.list;
  assert.deepEqual(d.removeDrawing(r.list, a.id).map((x) => x.id), [b.id]);
  assert.equal(d.removeDrawing(r.list, "nope").length, 2);
});

test("저장·복원 왕복, 깨진·악의적 저장값 복구", () => {
  let r = d.addDrawing([], { kind: "trend", a: p("2026-07-15", 12300), b: p("2026-09-20", 13100) });
  r = d.addDrawing(r.list, { kind: "hline", price: 12500 });
  assert.deepEqual(d.parseDrawings(d.serializeDrawings(r.list)), r.list);
  assert.deepEqual(d.parseDrawings(null), []);
  assert.deepEqual(d.parseDrawings("not json"), []);
  assert.deepEqual(d.parseDrawings('{"items":"x"}'), []);
  const messy = JSON.stringify({ items: [
    { id: "a", kind: "hline", price: 5 }, { id: "a", kind: "hline", price: 6 }, { id: "<b>", kind: "hline", price: 7 },
    { kind: "hline", price: -1 }, { kind: "trend", a: p("2026-07-15", 1) }, 5, null, { kind: "evil", price: 3 },
  ] });
  const out = d.parseDrawings(messy);
  assert.equal(out.length, 3);
  assert.equal(new Set(out.map((x) => x.id)).size, 3); // 중복 id 해소
  assert.ok(out.every((x) => /^[A-Za-z0-9_-]{1,16}$/.test(x.id)));
  const many = JSON.stringify({ items: Array.from({ length: 50 }, (_, i) => ({ id: `i${i}`, kind: "hline", price: i + 1 })) });
  assert.equal(d.parseDrawings(many).length, d.MAX_DRAWINGS);
});

test("좌표 환산: 봉 번호는 범위 안으로, 가격은 위아래 8 여백을 반영", () => {
  assert.equal(d.snapIndex(0, 5, 61), 0);
  assert.equal(d.snapIndex(1000, 5, 61), 60);
  assert.equal(d.snapIndex(12, 5, 61), 2);
  assert.equal(d.snapIndex(10, 5, 0), 0);
  const range = { hi: 1000, lo: 0 };
  assert.equal(d.priceFromY(24 + 8, range, 24, 226), 1000); // 위쪽 끝
  assert.equal(Math.round(d.priceFromY(24 + 8 + 210, range, 24, 226)), 0); // 아래쪽 끝
  assert.equal(Math.round(d.priceFromY(24 + 8 + 105, range, 24, 226)), 500);
});

test("설명 문구와 날짜 검증", () => {
  assert.equal(d.describeDrawing({ id: "x", kind: "hline", price: 12500.4 }), "수평선 12,500원");
  assert.equal(
    d.describeDrawing({ id: "x", kind: "trend", a: p("2026-07-15", 12300), b: p("2026-09-20", 13100) }),
    "추세선 26.07.15 12,300원 → 26.09.20 13,100원",
  );
  assert.equal(d.isValidDate("2026-02-30"), false);
  assert.equal(d.isValidDate("2026-02-28"), true);
});
