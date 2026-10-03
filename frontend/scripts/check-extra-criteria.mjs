#!/usr/bin/env node
/**
 * 선발 기준 ⑥⑦⑧ 판정 검증(DEC-055). 실행:
 *   node --experimental-strip-types --test scripts/check-extra-criteria.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { evaluateEarnings, evaluateInvestorFlow } from "../src/lib/extraCriteria.ts";

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
  const few = evaluateInvestorFlow(rows(9, 1, 1, 1));
  assert.equal(few.institutional.result.met, null);
  assert.equal(few.personal.result.met, null);
  const withNull = [...rows(8, 1, 1, 1), day(8, null, 1, 1), day(9, 1, null, 1)];
  assert.equal(evaluateInvestorFlow(withNull).institutional.result.met, null);
  assert.equal(evaluateInvestorFlow([]).personal.result.met, null);
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
