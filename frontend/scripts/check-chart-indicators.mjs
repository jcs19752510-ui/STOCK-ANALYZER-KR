#!/usr/bin/env node
/**
 * 차트 지표 계산 검증(DEC-041, UNIT-21). 새 의존성 없이 Node 내장 테스트 러너로 실행한다:
 *   node --experimental-strip-types --test scripts/check-chart-indicators.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  aggregate,
  ema,
  macd,
  macdCrosses,
  niceTicks,
  paddedExtent,
  sma,
  volumeProfile,
} from "../src/lib/chartIndicators.ts";

const close = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;

test("sma: 손계산 값과 워밍업 null", () => {
  assert.deepEqual(sma([1, 2, 3, 4, 5], 3), [null, null, 2, 3, 4]);
  assert.deepEqual(sma([5], 1), [5]);
  assert.deepEqual(sma([1, 2], 5), [null, null]); // 기간 부족은 null, 0 아님
  assert.throws(() => sma([1], 0), RangeError);
});

test("ema: 첫 값 시드·평활계수 2/(n+1) (pandas adjust=False)", () => {
  const out = ema([10, 20, 30], 3); // alpha=0.5
  assert.equal(out[0], 10);
  assert.ok(close(out[1], 15));
  assert.ok(close(out[2], 22.5));
});

test("ema: null 입력은 건너뛰고 첫 값부터 시작", () => {
  const out = ema([null, null, 4, 8], 3);
  assert.deepEqual(out.slice(0, 2), [null, null]);
  assert.equal(out[2], 4);
  assert.ok(close(out[3], 6));
});

test("macd: 상수열이면 0, 워밍업 구간은 null", () => {
  const m = macd(Array(60).fill(100));
  assert.equal(m.macd.slice(0, 25).every((v) => v === null), true); // 앞 slow-1=25개
  assert.ok(close(m.macd[25], 0));
  assert.equal(m.signal.slice(0, 33).every((v) => v === null), true); // 25+9-1=33개
  assert.ok(close(m.signal[33], 0));
  assert.ok(close(m.histogram[59], 0));
  assert.equal(m.macd.length, 60);
});

test("macd: 상승 추세면 MACD>0 이고 히스토그램=MACD−시그널", () => {
  const closes = Array.from({ length: 80 }, (_, i) => 100 + i);
  const m = macd(closes);
  assert.ok(m.macd[79] > 0);
  assert.ok(close(m.histogram[79], m.macd[79] - m.signal[79]));
});

test("macd: 독립 계산(EMA12−EMA26)과 일치", () => {
  const closes = Array.from({ length: 50 }, (_, i) => 50 + Math.sin(i / 3) * 10 + i * 0.3);
  const e = (p) => {
    const a = 2 / (p + 1);
    const o = [closes[0]];
    for (let i = 1; i < closes.length; i++) o.push(a * closes[i] + (1 - a) * o[i - 1]);
    return o;
  };
  const e12 = e(12);
  const e26 = e(26);
  const m = macd(closes);
  for (let i = 25; i < closes.length; i++) assert.ok(close(m.macd[i], e12[i] - e26[i]), `i=${i}`);
});

const day = (d, o, h, l, c, v) => ({
  trade_date: d,
  open: o,
  high: h,
  low: l,
  close: c,
  volume: v,
});

test("aggregate W: 월요일 기준 묶음, 시가=첫날·종가=마지막날·고저=극값·거래량=합", () => {
  const days = [
    day("2026-09-17", 10, 12, 9, 11, 100), // 목
    day("2026-09-18", 11, 15, 10, 14, 200), // 금
    day("2026-09-21", 14, 16, 13, 15, 300), // 다음 주 월
  ];
  const w = aggregate(days, "W");
  assert.equal(w.length, 2);
  assert.deepEqual(w[0], day("2026-09-18", 10, 15, 9, 14, 300));
  assert.deepEqual(w[1], day("2026-09-21", 14, 16, 13, 15, 300));
});

test("aggregate M·D: 월 경계, D는 복사본(원본 불변)", () => {
  const days = [day("2026-08-31", 1, 2, 1, 2, 10), day("2026-09-01", 2, 3, 2, 3, 20)];
  assert.equal(aggregate(days, "M").length, 2);
  const d = aggregate(days, "D");
  d[0].close = 999;
  assert.equal(days[0].close, 2);
});

test("aggregate W: 연말 경계 — 12/31(목)·1/1(금)은 같은 주", () => {
  const days = [
    day("2026-12-31", 1, 1, 1, 1, 1),
    day("2027-01-01", 1, 2, 1, 2, 1),
    day("2027-01-04", 2, 2, 2, 2, 1),
  ];
  const w = aggregate(days, "W");
  assert.equal(w.length, 2);
  assert.equal(w[0].trade_date, "2027-01-01");
});

test("paddedExtent: 빈 값·동일 값에서도 0으로 나누지 않음", () => {
  assert.deepEqual(paddedExtent([]), [0, 1]);
  const [lo, hi] = paddedExtent([100, 100]);
  assert.ok(lo < 100 && hi > 100);
  const [a, b] = paddedExtent([0, 10], 0.1);
  assert.ok(close(a, -1) && close(b, 11));
});

const bar = (low, high, close, volume) => ({
  trade_date: "2026-01-01", open: close, high, low, close, volume,
});

test("volumeProfile: 7구간 같은 폭, 종가 기준 거래량 합산, 비중 합계 100", () => {
  // 가격 범위 0~70 → 구간 폭 10. 종가 5(0번), 15(1번), 15(1번), 65(6번), 70(마지막 구간으로 포함)
  const bars = [bar(0, 6, 5, 100), bar(10, 16, 15, 100), bar(10, 16, 15, 200), bar(60, 66, 65, 100), bar(64, 70, 70, 100)];
  const p = volumeProfile(bars, 7);
  assert.equal(p.length, 7);
  assert.deepEqual(p.map((b) => b.volume), [100, 300, 0, 0, 0, 0, 200]);
  assert.ok(close(p.reduce((a, b) => a + b.share, 0), 100, 1e-9));
  assert.ok(close(p[1].share, 50));
  assert.ok(close(p[0].lo, 0) && close(p[6].hi, 70));
});

test("volumeProfile: 빈 입력·가격 범위 0·거래량 0 처리", () => {
  assert.deepEqual(volumeProfile([], 7), []);
  assert.deepEqual(volumeProfile([bar(10, 10, 10, 5)], 7), []);
  const zero = volumeProfile([bar(0, 10, 5, 0), bar(0, 10, 9, 0)], 7);
  assert.equal(zero.every((b) => b.share === 0), true);
});

test("macdCrosses: 골든·데드 교차 지점(동값은 직전 부호 유지, null 건너뜀)", () => {
  const macdL = [null, -1, -0.5, 0.5, 1, 0.2, -0.3, -0.3, 0.4];
  const sig = [null, 0, 0, 0, 0, 0.5, 0, 0, 0];
  // diff: -, -, +, +, -, -, -, +  → 골든(3), 데드(5), 골든(8)
  assert.deepEqual(macdCrosses(macdL, sig), [
    { index: 3, kind: "golden" },
    { index: 5, kind: "dead" },
    { index: 8, kind: "golden" },
  ]);
  const flat = macdCrosses([1, 1, 1], [1, 1, 1]);
  assert.deepEqual(flat, []);
});

test("niceTicks: 범위 안의 보기 좋은 눈금, 범위 밖 제외·퇴화 입력은 빈 배열", () => {
  assert.deepEqual(niceTicks(6000, 14000, 4), [6000, 8000, 10000, 12000, 14000]);
  assert.deepEqual(niceTicks(0.0, 1, 5), [0, 0.2, 0.4, 0.6, 0.8, 1]);
  assert.ok(niceTicks(53500, 124800, 5).every((v) => v >= 53500 && v <= 124800));
  assert.deepEqual(niceTicks(5, 5), []);
  assert.deepEqual(niceTicks(10, 1), []);
});
