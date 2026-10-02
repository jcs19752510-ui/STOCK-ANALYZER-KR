#!/usr/bin/env node
/**
 * 억 원 표기 검증(DEC-041, 실적 탭). 실행:
 *   node --experimental-strip-types --test scripts/check-format-eok.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatEok } from "../src/lib/formatEok.ts";

test("null·비정상 값은 '-'(0이 아님)", () => {
  assert.equal(formatEok(null), "-");
  assert.equal(formatEok(Number.NaN), "-");
  assert.equal(formatEok(Number.POSITIVE_INFINITY), "-");
});

test("원 → 억 원 환산과 천 단위 구분", () => {
  assert.equal(formatEok(333_605_938_000_000), "3,336,059"); // 삼성전자 2025 매출(실데이터 대조값)
  assert.equal(formatEok(100_000_000), "1");
  assert.equal(formatEok(0), "0");
});

test("반올림: 절반은 0에서 먼 쪽, 음수(적자)는 부호 유지", () => {
  assert.equal(formatEok(149_999_999), "1");
  assert.equal(formatEok(150_000_000), "2");
  assert.equal(formatEok(-150_000_000), "-2");
  assert.equal(formatEok(-436_011_000_000), "-4,360");
});

test("억 미만 음수는 '-0'이 아니라 '0'", () => {
  assert.equal(formatEok(-1_000_000), "0");
  assert.equal(formatEok(-49_999_999), "0");
});
