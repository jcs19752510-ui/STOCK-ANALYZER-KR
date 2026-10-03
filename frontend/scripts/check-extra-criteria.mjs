#!/usr/bin/env node
/**
 * 선발 기준 ⑥⑦⑧ 판정 검증(DEC-055) + ⑪ 기관 연속 순매수 대안·⑦ 예외(DEC-061). 실행:
 *   node --experimental-strip-types --test scripts/check-extra-criteria.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { evaluateEarnings, evaluateInvestorFlow, institutionStreak } from "../src/lib/extraCriteria.ts";

const day = (i, p, f, o) => ({
  date: `2026-09-${String(30 - i).padStart(2, "0")}`,
  personal_quantity: p, foreign_quantity: f, institution_quantity: o,
  personal_amount_million: null, foreign_amount_million: null, institution_amount_million: null,
});
const rows = (n, p, f, o) => Array.from({ length: n }, (_, i) => day(i, p, f, o));
const year = (fy, op, rev = 1e12, fs = "CFS") => ({ fiscal_year: fy, fs_div: fs, revenue: rev, operating_income: op, net_income: null });

test("수급: 외국인·기관 순매수 + 개인 순매도 → 둘 다 충족, 20일까지만 합산", () => {
  const r = evaluateInvestorFlow(rows(30, -100, 60, 50));
  assert.equal(r.institutional.result.met, true);
  assert.equal(r.personal.result.met, true);
  assert.match(r.institutional.evidence, /최근 20거래일/);
  assert.match(r.institutional.evidence, /외국인 \+1,200주/);
  assert.match(r.personal.evidence, /개인 -2,000주/);
});

test("수급: 개인 주도(개인 순매수, 외국인·기관 순매도) → 둘 다 미충족", () => {
  const r = evaluateInvestorFlow(rows(20, 100, -60, -50));
  assert.equal(r.institutional.result.met, false);
  assert.equal(r.personal.result.met, false);
});

test("수급: 경계값 — 합계 0이면 ⑥ 미충족, 개인 0이면 ⑦ 충족", () => {
  const r = evaluateInvestorFlow(rows(20, 0, 50, -50));
  assert.equal(r.institutional.result.met, false);
  assert.equal(r.personal.result.met, true);
});

test("수급: 10거래일 미만이거나 값이 비면 산정 불가(0으로 채우지 않음)", () => {
  // 기관이 순매도라 연속 매수도 아님 → 누적도 연속도 판단 불가/미충족이면 ⑥은 null
  const few = evaluateInvestorFlow(rows(9, 1, 1, -1));
  assert.equal(few.institutional.result.met, null);
  assert.equal(few.personal.result.met, null);
  const withNull = [day(0, 1, 1, null), ...rows(8, 1, 1, 1), day(9, 1, null, 1)];
  assert.equal(evaluateInvestorFlow(withNull).institutional.result.met, null);
  assert.equal(evaluateInvestorFlow([]).personal.result.met, null);
  assert.equal(evaluateInvestorFlow([]).institutional.result.met, null);
});

test("⑪ 기관 연속 순매수: 3일 이상이면 충족, 0·순매도로 끊기면 거기까지", () => {
  const inst = (...q) => q.map((v, i) => day(i, 0, 0, v));
  assert.deepEqual(institutionStreak(inst(5, 4, 3, -1)), { days: 3, met: true });
  assert.deepEqual(institutionStreak(inst(5, 4, 0, 9, 9)), { days: 2, met: false }); // 0은 연속 중단
  assert.deepEqual(institutionStreak(inst(-1, 9, 9, 9)), { days: 0, met: false });   // 오늘이 순매도면 불충족
  assert.deepEqual(institutionStreak(inst(5, 4)), { days: 2, met: null });          // 자료가 모자라 판단 불가
  assert.equal(institutionStreak([]).met, null);
});

test("⑪ 값 없는 날을 만나면 멈춤: 기준 전이면 판단 불가, 기준 후면 충족", () => {
  const q = (v, i) => day(i, 0, 0, v);
  assert.equal(institutionStreak([q(5, 0), q(4, 1), q(null, 2), q(9, 3)]).met, null);
  assert.equal(institutionStreak([q(5, 0), q(4, 1), q(3, 2), q(null, 3)]).met, true);
});

test("⑥ 대안: 외국인이 팔아도 기관이 3일 연속 순매수면 충족 (누적은 미충족)", () => {
  const r = evaluateInvestorFlow([...rows(5, 0, -100, 30), ...rows(15, 0, -100, -10)]);
  assert.equal(r.institutional.result.met, true);
  assert.match(r.institutional.evidence, /합계 -/);
  assert.match(r.institutional.evidence, /기관 연속 순매수 5일\(기준 3일 이상\)/);
  assert.match(r.institutional.evidence, /외국인이 팔아도 기관이 연속 순매수 중이라 충족/);
});

test("⑥ 누적만 충족(기관 연속 아님)이면 누적 근거로 충족, 둘 다 아니면 미충족", () => {
  const cumOnly = evaluateInvestorFlow([...rows(2, 0, 50, -1), ...rows(18, 0, 60, 5)]);
  assert.equal(cumOnly.institutional.result.met, true);
  assert.match(cumOnly.institutional.evidence, /누적 순매수로 충족/);
  const none = evaluateInvestorFlow(rows(20, 0, -50, -10));
  assert.equal(none.institutional.result.met, false);
});

test("누적 일수 부족(<10)이어도 기관 3일 연속이면 ⑥ 충족, ⑦은 산정 불가", () => {
  const r = evaluateInvestorFlow(rows(5, 1, -1, 3));
  assert.equal(r.institutional.result.met, true);
  assert.match(r.institutional.evidence, /누적은 수급 일수가 5일뿐/);
  assert.equal(r.personal.result.met, null);
});

test("리노공업 사례(증권사 화면 값): 외국인 순매도에도 기관 4일 연속 순매수 → ⑥ 충족, 개인 누적이 +여도 기관이 더 커서 ⑦ 충족", () => {
  const screen = [
    [-29687, -745781, 725502], [-268372, -191981, 439558], [102379, -159171, 59373],
    [5706, -127995, 118067], [172275, -116155, -57139],
  ].map(([p, f, o], i) => day(i, p, f, o));
  const older = rows(15, 40000, -100000, 20000).map((r, i) => ({ ...r, date: `2026-09-${String(20 - i).padStart(2, "0")}` }));
  const r = evaluateInvestorFlow([...screen, ...older]);
  assert.equal(r.institutional.result.met, true);
  assert.match(r.institutional.evidence, /기관 연속 순매수 4일/);
  assert.equal(r.personal.result.met, true);
  assert.match(r.personal.evidence, /개인 주도가 아닌 것으로 봅니다/);
});

test("⑦ 예외는 ⑪을 충족하고 기관 누적이 개인 누적보다 클 때만 (그 외 개인 누적 +이면 미충족)", () => {
  // 기관 연속 매수는 충족하지만 기관 누적(3*10) < 개인 누적(20*100) → 예외 없음
  const small = evaluateInvestorFlow([...rows(3, 100, 0, 10), ...rows(17, 100, 0, -1)]);
  assert.equal(small.institutional.result.met, true);
  assert.equal(small.personal.result.met, false);
  assert.match(small.personal.evidence, /크지 않아 예외를 적용하지 않습니다/);
  // 기관 연속 매수가 아님 → 예외 없음
  const noStreak = evaluateInvestorFlow([day(0, 50, 0, -5), ...rows(19, 50, 0, 100)]);
  assert.equal(noStreak.personal.result.met, false);
  assert.match(noStreak.personal.evidence, /기관 연속 순매수를 충족하지 못해/);
  // 개인 누적이 0 이하이면 예외와 관계없이 충족
  assert.equal(evaluateInvestorFlow(rows(20, -1, 0, 0)).personal.result.met, true);
});

test("실적: 흑자이고 전년보다 증가 → 충족, 증감률 표기", () => {
  const e = evaluateEarnings([year(2024, 327_260e8, 3_008_709e8), year(2025, 436_011e8, 3_336_059e8)]);
  assert.equal(e.result.met, true);
  assert.match(e.evidence, /2025년 영업이익 436,011억 원\(전년 327,260억 원\) \(\+33\.2%\)/);
  assert.match(e.evidence, /매출 3,336,059억 원/);
});

test("실적: 흑자여도 감소하면 미충족, 적자면 미충족(전년 적자일 때 % 생략)", () => {
  assert.equal(evaluateEarnings([year(2024, 500e8), year(2025, 400e8)]).result.met, false);
  const loss = evaluateEarnings([year(2024, -100e8), year(2025, -50e8)]);
  assert.equal(loss.result.met, false);
  assert.doesNotMatch(loss.evidence, /%/);
  assert.equal(evaluateEarnings([year(2024, -100e8), year(2025, 50e8)]).result.met, true);
});

test("실적: 1개 연도·영업이익 없음·연도 건너뜀·기준 다름은 산정 불가", () => {
  assert.equal(evaluateEarnings([]).result.met, null);
  assert.equal(evaluateEarnings([year(2025, 1e8)]).result.met, null);
  assert.equal(evaluateEarnings([year(2024, null), year(2025, 1e8)]).result.met, null);
  assert.equal(evaluateEarnings([year(2023, 1e8), year(2025, 2e8)]).result.met, null);
  assert.equal(evaluateEarnings([year(2024, 1e8, 1e12, "OFS"), year(2025, 2e8, 1e12, "CFS")]).result.met, null);
});
