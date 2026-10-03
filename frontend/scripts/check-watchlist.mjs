#!/usr/bin/env node
/**
 * 관심종목 상태 변환·검증(DEC-055). 실행:
 *   node --experimental-strip-types --test scripts/check-watchlist.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import * as w from "../src/lib/watchlist.ts";

const it = (code, name = code) => ({ code, name, market: "KOSPI" });

test("기본 상태는 그룹 하나, 비어 있음", () => {
  const s = w.emptyState();
  assert.equal(s.groups.length, 1);
  assert.equal(s.groups[0].items.length, 0);
});

test("추가: 첫 그룹에 들어가고, 중복·잘못된 코드·가득 참은 변경 없음", () => {
  let r = w.addToDefault(w.emptyState(), it("005930", "삼성전자"));
  assert.equal(r.result, "added");
  assert.equal(w.isWatched(r.state, "005930"), true);
  assert.equal(w.addToDefault(r.state, it("005930")).result, "exists");
  assert.equal(w.addToDefault(r.state, it("12")).result, "invalid");
  assert.equal(w.addToDefault(r.state, { code: "<script>", name: "x", market: "" }).result, "invalid");
  let s = w.emptyState();
  for (let i = 0; i < w.MAX_PER_GROUP; i++) s = w.addToDefault(s, it(String(100000 + i))).state;
  const full = w.addToDefault(s, it("999999"));
  assert.equal(full.result, "full");
  assert.equal(full.state, s);
});

test("제거·순서 이동·그룹 이동", () => {
  let s = w.emptyState();
  for (const c of ["000001", "000002", "000003"]) s = w.addToDefault(s, it(c)).state;
  const g1 = s.groups[0].id;
  s = w.moveWithinGroup(s, g1, "000003", -1);
  assert.deepEqual(s.groups[0].items.map((i) => i.code), ["000001", "000003", "000002"]);
  s = w.moveWithinGroup(s, g1, "000001", -1); // 맨 위에서 더 못 올림
  assert.deepEqual(s.groups[0].items.map((i) => i.code), ["000001", "000003", "000002"]);
  s = w.createGroup(s, "양자컴퓨터 관련주");
  const g2 = s.groups[1].id;
  s = w.moveToGroup(s, g1, g2, "000002");
  assert.deepEqual(s.groups[1].items.map((i) => i.code), ["000002"]);
  assert.equal(s.groups[0].items.some((i) => i.code === "000002"), false);
  assert.deepEqual(w.mergedItems(s).map((i) => i.code), ["000001", "000003", "000002"]);
  s = w.removeEverywhere(s, "000002");
  assert.equal(w.isWatched(s, "000002"), false);
  s = w.removeFromGroup(s, g1, "000001");
  assert.equal(w.isWatched(s, "000001"), false);
});

test("그룹: 이름 정리·길이 제한·최대 개수·마지막 그룹은 삭제 불가", () => {
  let s = w.createGroup(w.emptyState(), "  가나다   라마바  ");
  assert.equal(s.groups[1].name, "가나다 라마바");
  s = w.renameGroup(s, s.groups[1].id, "x".repeat(50));
  assert.equal(s.groups[1].name.length, w.MAX_NAME_LENGTH);
  s = w.renameGroup(s, s.groups[1].id, "   "); // 빈 이름은 이전 이름 유지
  assert.equal(s.groups[1].name.length, w.MAX_NAME_LENGTH);
  for (let i = 0; i < 20; i++) s = w.createGroup(s, `g${i}`);
  assert.equal(s.groups.length, w.MAX_GROUPS);
  const only = w.emptyState();
  assert.equal(w.deleteGroup(only, only.groups[0].id), only);
  assert.equal(w.deleteGroup(s, s.groups[1].id).groups.length, w.MAX_GROUPS - 1);
});

test("읽기: 깨진·악의적 저장값을 바로잡는다", () => {
  assert.equal(w.parseState(null).groups.length, 1);
  assert.equal(w.parseState("not json").groups.length, 1);
  assert.equal(w.parseState('{"groups":"x"}').groups.length, 1);
  const messy = JSON.stringify({
    groups: [
      { id: "a", name: "<b>x</b>", items: [{ code: "005930", name: "삼성전자", market: "KOSPI" }, { code: "005930" }, { code: "bad" }, 5] },
      { id: "a", name: 7, items: "no" },
    ],
  });
  const s = w.parseState(messy);
  assert.equal(s.groups.length, 2);
  assert.notEqual(s.groups[0].id, s.groups[1].id);
  assert.equal(s.groups[0].items.length, 1);
  assert.equal(s.groups[1].name, w.DEFAULT_GROUP_NAME);
  assert.equal(w.parseState(w.serialize(s)).groups[0].items[0].code, "005930");
});
