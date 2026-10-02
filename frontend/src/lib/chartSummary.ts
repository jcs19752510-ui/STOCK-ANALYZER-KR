import {
  macd,
  macdCrosses,
  sma,
  volumeProfile,
  type Candle,
} from "./chartIndicators.ts";

/**
 * 사실 서술형 차트 요약(DEC-052). 화면에 보이는 차트의 수치를 문장으로 옮길 뿐, 전망·평가·행동 제안은 하지 않는다.
 * 순수 함수라 DOM·React에 의존하지 않고 Node로 검증된다(`scripts/check-chart-summary.mjs`).
 *
 * - 모든 문장은 `copy.ko.json`의 템플릿(`stockDetail.summary`)에서 오며(금지표현 검사 대상), 이 파일은 숫자를 계산해
 *   `{이름}` 자리표시자에 채운다. 숫자는 한 문장에 값 하나씩, 입력에서 계산 가능한 것만 쓴다(결측이면 그 문장을 만들지 않는다).
 * - "높다/낮다/위/아래/배열 순서" 같은 위치 관계만 서술한다. 강세·약세·지지·저항·돌파 임박 같은 해석 어휘는 쓰지 않는다.
 */
export type SummaryGroup = "ma" | "momentum" | "range" | "volume" | "profile";

export interface SummaryFact {
  id: string;
  group: SummaryGroup;
  text: string;
}

export type SummaryTemplates = Record<string, string>;

const MA_PERIODS = [5, 10, 20, 60] as const;
const RANGE_BARS = 61;
const nf = new Intl.NumberFormat("ko-KR");

function fill(tpl: string, values: Record<string, string | number>): string {
  return tpl.replace(/\{(\w+)\}/g, (_, k: string) => String(values[k] ?? ""));
}

const price = (v: number) => nf.format(Math.round(v));
const pct = (v: number) => Math.abs(v).toFixed(2);

function dateLabel(c: Candle): string {
  return c.time ?? c.trade_date.slice(5).replace("-", ".");
}

/**
 * @param candles 선택한 봉 단위(일/주/월/분/틱)로 이미 묶인 시계열(오름차순)
 * @param unit 봉 단위 표기("일", "주", "개월", "분", "틱" 등) — 이동평균·직전 N개 봉 문장에 쓴다
 */
export function buildChartSummary(
  candles: readonly Candle[],
  tpl: SummaryTemplates,
  unit: string,
): SummaryFact[] {
  const n = candles.length;
  if (n < 2) return [];
  const facts: SummaryFact[] = [];
  const add = (id: string, group: SummaryGroup, key: string, values: Record<string, string | number>) => {
    const t = tpl[key];
    if (t) facts.push({ id, group, text: fill(t, { unit, ...values }) });
  };

  const closes = candles.map((c) => c.close);
  const last = candles[n - 1];
  const prev = candles[n - 2];
  const maSeries = MA_PERIODS.map((p) => ({ p, v: sma(closes, p)[n - 1] }));
  const maOf = (p: number) => maSeries.find((m) => m.p === p)?.v ?? null;

  // 1) 직전 봉 대비
  if (prev.close) {
    const diff = last.close - prev.close;
    add("prev", "range", diff === 0 ? "prevFlat" : diff > 0 ? "prevUp" : "prevDown", {
      close: price(last.close),
      change: price(Math.abs(diff)),
      pct: pct((diff / prev.close) * 100),
    });
  }

  // 2) 이동평균 대비 종가 위치
  for (const { p, v } of maSeries) {
    if (v === null || v === 0) continue;
    const gap = (last.close / v - 1) * 100;
    add(`ma${p}`, "ma", gap >= 0 ? "maAbove" : "maBelow", {
      period: p,
      close: price(last.close),
      ma: price(v),
      pct: pct(gap),
    });
  }

  // 3) 이동평균 배열 순서
  const [m5, m10, m20, m60] = [5, 10, 20, 60].map(maOf);
  if (m5 !== null && m10 !== null && m20 !== null && m60 !== null) {
    const order = m5 > m10 && m10 > m20 && m20 > m60 ? "maAligned" : m5 < m10 && m10 < m20 && m20 < m60 ? "maReversed" : "maMixed";
    add("maOrder", "ma", order, {});
  }

  // 4) 5·20 이동평균 차이, 60 이동평균의 최근 5개 봉 변화
  if (m5 !== null && m20 !== null && m20 !== 0) {
    const gap = (m5 / m20 - 1) * 100;
    add("ma5vs20", "ma", gap >= 0 ? "ma5vs20Above" : "ma5vs20Below", { pct: pct(gap) });
  }
  const ma60s = sma(closes, 60);
  if (n >= 65 && ma60s[n - 1] !== null && ma60s[n - 6] !== null && ma60s[n - 6] !== 0) {
    const change = ((ma60s[n - 1] as number) / (ma60s[n - 6] as number) - 1) * 100;
    add("ma60slope", "ma", change >= 0 ? "ma60Up" : "ma60Down", { pct: pct(change), bars: 5 });
  }

  // 5) MACD(12,26,9)
  const m = macd(closes);
  const mv = m.macd[n - 1];
  const sv = m.signal[n - 1];
  if (mv !== null && sv !== null) {
    add("macdVsSignal", "momentum", mv >= sv ? "macdAboveSignal" : "macdBelowSignal", {
      macd: mv.toFixed(2),
      signal: sv.toFixed(2),
    });
    add("macdVsZero", "momentum", mv >= 0 ? "macdAboveZero" : "macdBelowZero", { macd: mv.toFixed(2) });
    const crosses = macdCrosses(m.macd, m.signal);
    const lastCross = crosses[crosses.length - 1];
    if (lastCross) {
      const barsAgo = n - 1 - lastCross.index;
      const golden = lastCross.kind === "golden";
      add(
        "macdCross",
        "momentum",
        barsAgo === 0 ? (golden ? "crossGoldenNow" : "crossDeadNow") : golden ? "crossGolden" : "crossDead",
        { bars: barsAgo },
      );
    } else {
      add("macdCross", "momentum", "crossNone", {});
    }
  }

  // 6) 최근 N개 봉의 고가·저가 대비 위치
  const view = candles.slice(Math.max(0, n - RANGE_BARS));
  let hi = view[0];
  let lo = view[0];
  for (const c of view) {
    if (c.high > hi.high) hi = c;
    if (c.low < lo.low) lo = c;
  }
  if (hi.high > 0 && lo.low > 0) {
    add("fromHigh", "range", "fromHigh", {
      bars: view.length,
      high: price(hi.high),
      date: dateLabel(hi),
      pct: pct((last.close / hi.high - 1) * 100),
    });
    add("fromLow", "range", "fromLow", {
      low: price(lo.low),
      date: dateLabel(lo),
      pct: pct((last.close / lo.low - 1) * 100),
    });
  }

  // 7) 거래량: 직전 20개 봉 평균 대비
  if (n >= 21) {
    const avg = candles.slice(n - 21, n - 1).reduce((a, c) => a + c.volume, 0) / 20;
    if (avg > 0) {
      add("volRatio", "volume", "volRatio", {
        volume: nf.format(Math.round(last.volume)),
        avg: nf.format(Math.round(avg)),
        ratio: (last.volume / avg).toFixed(2),
      });
    }
  }

  // 8) 매물대: 거래량이 가장 많이 쌓인 가격대와 종가의 위치
  const profile = volumeProfile(view, 7);
  const top = profile.reduce<(typeof profile)[number] | null>(
    (best, b) => (best === null || b.share > best.share ? b : best),
    null,
  );
  if (top && top.share > 0) {
    const where = last.close > top.hi ? "profileAbove" : last.close < top.lo ? "profileBelow" : "profileInside";
    add("profile", "profile", where, {
      lo: price(top.lo),
      hi: price(top.hi),
      share: top.share.toFixed(1),
      close: price(last.close),
    });
  }

  return facts;
}
