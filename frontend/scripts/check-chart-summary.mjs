#!/usr/bin/env node
/**
 * 사실 서술형 차트 요약 검증(DEC-052). 실행:
 *   node --experimental-strip-types --test scripts/check-chart-summary.mjs
 * 검증 항목: 계산값(손계산 대조) · 결측 처리 · 문장에 금지표현/해석 어휘가 없음 · 모든 템플릿 자리표시자가 채워짐.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { buildChartSummary } from "../src/lib/chartSummary.ts";

const copy = JSON.parse(readFileSync(new URL("../src/content/copy.ko.json", import.meta.url), "utf-8"));
const TPL = copy.stockDetail.summary;

// 금지어 목록은 CI 검사 스크립트(lint-forbidden-copy.mjs)에서 읽어 와 단일 출처를 유지한다.
const lintSrc = readFileSync(new URL("./lint-forbidden-copy.mjs", import.meta.url), "utf-8");
const FORBIDDEN = [...lintSrc.match(/const FORBIDDEN_TERMS = \[([\s\S]*?)\];/)[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
// 요약 문장에서 추가로 금지하는 해석·예측 어휘(사실 서술 원칙)
const INTERPRETIVE = ["강세", "약세", "지지", "저항", "돌파 임박", "유망", "상승 예상", "하락 예상", "전망", "매수", "매도", "관망", "과열", "바닥", "급등 가능"];

function day(i) {
  const d = new Date(Date.UTC(2026, 0, 1 + i));
  return d.toISOString().slice(0, 10);
}
function series(closeFn, n = 130, volFn = () => 1000) {
  return Array.from({ length: n }, (_, i) => {
    const c = closeFn(i);
    return { trade_date: day(i), open: c, high: c * 1.01, low: c * 0.99, close: c, volume: volFn(i) };
  });
}
const by = (facts, id) => facts.find((f) => f.id === id);

test("상승 일변 추세: 정배열·이동평균 위·직전 봉 대비 값이 손계산과 일치", () => {
  const c = series((i) => 100 + i); // 종가 100..229
  const f = buildChartSummary(c, TPL, "일");
  assert.equal(by(f, "maOrder").text.includes("정배열"), true);
  const last = 229;
  const ma5 = (225 + 226 + 227 + 228 + 229) / 5; // 227
  const gap5 = ((last / ma5 - 1) * 100).toFixed(2);
  assert.equal(by(f, "ma5").text, `종가(229원)는 5일 이동평균(227원)보다 ${gap5}% 위에 있습니다.`);
  assert.equal(by(f, "prev").text, "최근 봉 종가는 229원으로, 직전 봉보다 1원(0.44%) 높습니다.");
});

test("하락 일변 추세: 역배열·아래 문장", () => {
  const c = series((i) => 300 - i);
  const f = buildChartSummary(c, TPL, "일");
  assert.equal(by(f, "maOrder").text.includes("역배열"), true);
  assert.equal(by(f, "ma20").text.includes("아래에 있습니다"), true);
  assert.equal(by(f, "prev").text.includes("낮습니다"), true);
});

test("MACD 교차: 마지막 교차의 종류와 몇 개 봉 전인지", () => {
  // 앞 60봉 하락 후 뒤 40봉 상승 → 상승 전환 구간에서 골든크로스가 존재
  const c = series((i) => (i < 60 ? 200 - i : 140 + (i - 60) * 2), 120);
  const f = buildChartSummary(c, TPL, "일");
  const cross = by(f, "macdCross").text;
  assert.ok(cross.includes("골든크로스"), cross);
  assert.match(cross, /\d+개 봉 전|최근 봉에서/);
});

test("거래량: 직전 20개 봉 평균 대비 배수", () => {
  const c = series(() => 100, 60, (i) => (i === 59 ? 3000 : 1000));
  const f = buildChartSummary(c, TPL, "일");
  assert.equal(by(f, "volRatio").text, "최근 봉 거래량은 3,000주로, 직전 20개 봉 평균(1,000주)의 3.00배입니다.");
});

test("매물대: 거래량이 가장 많은 가격대와 종가 위치", () => {
  // 가격 100(거래량 큼) 구간에 오래 머물다 마지막에 150
  const c = series((i) => (i < 55 ? 100 : 150), 61, (i) => (i < 55 ? 5000 : 100));
  const f = buildChartSummary(c, TPL, "일");
  assert.ok(by(f, "profile").text.includes("위에 있습니다"), by(f, "profile").text);
});

test("고가·저가 대비: 최근 61개 봉 기준", () => {
  const c = series((i) => 100 + (i % 10), 130);
  const f = buildChartSummary(c, TPL, "일");
  assert.ok(by(f, "fromHigh").text.startsWith("최근 61개 봉의 최고가는"));
  assert.ok(by(f, "fromLow").text.startsWith("같은 기간 최저가는"));
});

test("결측: 봉이 적으면 필요한 기간이 모자란 문장은 만들지 않는다(0으로 채우지 않음)", () => {
  const f = buildChartSummary(series((i) => 100 + i, 8), TPL, "일");
  assert.equal(by(f, "ma20"), undefined);
  assert.equal(by(f, "ma60"), undefined);
  assert.equal(by(f, "maOrder"), undefined);
  assert.equal(by(f, "macdVsSignal"), undefined);
  assert.equal(by(f, "volRatio"), undefined);
  assert.ok(by(f, "ma5")); // 5개 이상이면 5봉 평균은 계산 가능
  assert.deepEqual(buildChartSummary([], TPL, "일"), []);
  assert.deepEqual(buildChartSummary(series(() => 1, 1), TPL, "일"), []);
});

test("분·틱 봉은 표시 시각(time)을 날짜 대신 쓰고 단위 문구가 바뀐다", () => {
  const c = series((i) => 100 + (i % 7), 90).map((x, i) => ({ ...x, time: `09:${String(i % 60).padStart(2, "0")}` }));
  const f = buildChartSummary(c, TPL, "분");
  assert.ok(by(f, "ma20").text.includes("20분 이동평균"));
  assert.ok(/\(\d\d:\d\d\)/.test(by(f, "fromHigh").text), by(f, "fromHigh").text);
});

test("모든 문장: 자리표시자 미치환 없음, 금지표현·해석 어휘 없음, 숫자 NaN 없음", () => {
  const sets = [
    series((i) => 100 + i),
    series((i) => 300 - i),
    series((i) => 100 + 20 * Math.sin(i / 5), 150, (i) => 500 + (i % 9) * 100),
    series((i) => (i < 60 ? 200 - i : 140 + (i - 60) * 2), 120),
  ];
  for (const c of sets) {
    for (const f of buildChartSummary(c, TPL, "일")) {
      assert.equal(/\{\w+\}/.test(f.text), false, `미치환: ${f.text}`);
      assert.equal(/NaN|undefined|Infinity/.test(f.text), false, `비정상 값: ${f.text}`);
      const squashed = f.text.replace(/\s/g, "");
      for (const w of [...FORBIDDEN, ...INTERPRETIVE]) {
        assert.equal(squashed.includes(w.replace(/\s/g, "")), false, `금지/해석 어휘 '${w}': ${f.text}`);
      }
    }
  }
  // 템플릿 원문에도 같은 규칙을 적용한다
  for (const [k, t] of Object.entries(TPL)) {
    const squashed = t.replace(/\s/g, "");
    for (const w of [...FORBIDDEN, ...INTERPRETIVE]) {
      assert.equal(squashed.includes(w.replace(/\s/g, "")), false, `템플릿 ${k}에 '${w}'`);
    }
  }
});
