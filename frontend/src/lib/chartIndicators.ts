/**
 * 차트 지표 계산(DEC-041, UNIT-21). 순수 함수 — React·DOM·경로 별칭에 의존하지 않아 Node로 그대로 검증된다
 * (`scripts/check-chart-indicators.mjs`). 계산식의 단일 출처이며, 서버는 원자료(일봉)만 내려준다.
 *
 * 결측 원칙: 계산에 필요한 기간이 모자라면 0이 아니라 `null`(지어내지 않는다).
 */

export interface Candle {
  trade_date: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type Timeframe = "D" | "W" | "M";

function assertPeriod(period: number): void {
  if (!Number.isInteger(period) || period < 1) throw new RangeError("period는 1 이상의 정수");
}

/** 단순 이동평균. 처음 `period-1`개는 null. */
export function sma(values: readonly number[], period: number): (number | null)[] {
  assertPeriod(period);
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

/**
 * 지수 이동평균(첫 값 시드, 평활계수 2/(period+1) — pandas `ewm(adjust=False)`와 같은 정의).
 * 입력은 null을 포함할 수 있으며, 첫 non-null부터 계산하고 그 앞은 null.
 */
export function ema(values: readonly (number | null)[], period: number): (number | null)[] {
  assertPeriod(period);
  const alpha = 2 / (period + 1);
  const out: (number | null)[] = [];
  let prev: number | null = null;
  for (const v of values) {
    if (v === null) {
      out.push(null);
      continue;
    }
    prev = prev === null ? v : alpha * v + (1 - alpha) * prev;
    out.push(prev);
  }
  return out;
}

export interface MacdSeries {
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
}

/**
 * MACD(fast−slow), 시그널(MACD의 EMA), 히스토그램. 기본 12·26·9.
 * 지수평균이 안정되기 전 구간(앞 `slow-1`개)은 null로 둔다(워밍업).
 */
export function macd(
  closes: readonly number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9,
): MacdSeries {
  const fastEma = ema(closes, fast);
  const slowEma = ema(closes, slow);
  const line = closes.map((_, i) =>
    i < slow - 1 || fastEma[i] === null || slowEma[i] === null
      ? null
      : (fastEma[i] as number) - (slowEma[i] as number),
  );
  const signalRaw = ema(line, signalPeriod);
  // 시그널도 `signalPeriod-1`개 이후부터만 의미 있다.
  const firstLine = line.findIndex((v) => v !== null);
  const signal = signalRaw.map((v, i) =>
    firstLine < 0 || i < firstLine + signalPeriod - 1 ? null : v,
  );
  const histogram = line.map((v, i) =>
    v === null || signal[i] === null ? null : v - (signal[i] as number),
  );
  return { macd: line, signal, histogram };
}

/** 그 주의 월요일 날짜(키). 로컬 시간대 영향을 받지 않도록 UTC로 계산한다. */
function weekKey(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  const day = (t.getUTCDay() + 6) % 7; // 월=0
  t.setUTCDate(t.getUTCDate() - day);
  return t.toISOString().slice(0, 10);
}

/** 일봉을 주봉/월봉으로 묶는다(시가=첫날, 종가=마지막날, 고가/저가=극값, 거래량=합). 날짜는 마지막 거래일. */
export function aggregate(candles: readonly Candle[], timeframe: Timeframe): Candle[] {
  if (timeframe === "D") return candles.map((c) => ({ ...c }));
  const key = (c: Candle) => (timeframe === "W" ? weekKey(c.trade_date) : c.trade_date.slice(0, 7));
  const out: Candle[] = [];
  let currentKey: string | null = null;
  for (const c of candles) {
    const k = key(c);
    if (k !== currentKey) {
      out.push({ ...c });
      currentKey = k;
      continue;
    }
    const last = out[out.length - 1];
    last.high = Math.max(last.high, c.high);
    last.low = Math.min(last.low, c.low);
    last.close = c.close;
    last.volume += c.volume;
    last.trade_date = c.trade_date;
  }
  return out;
}

/** 값 범위에 여유를 둔 [min, max]. 모든 값이 같으면 0으로 나누지 않도록 ±1%를 준다. */
export function paddedExtent(
  values: readonly (number | null)[],
  padRatio = 0.05,
): [number, number] {
  const nums = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (nums.length === 0) return [0, 1];
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  if (lo === hi) return [lo * 0.99, hi * 1.01 || 1];
  const pad = (hi - lo) * padRatio;
  return [lo - pad, hi + pad];
}

export interface VolumeProfileBin {
  lo: number; // 구간 하한(가격)
  hi: number; // 구간 상한(가격)
  volume: number;
  share: number; // 전체 거래량 대비 비중(%), 구간 합계 = 100(거래량이 0이면 모두 0)
}

/**
 * 매물대(가격대별 거래량 분포, 증권사 앱의 "매물대(7)"): 보이는 구간의 최저가~최고가를 `bins`개 같은 폭으로 나누고,
 * 각 봉의 거래량을 **종가가 속한 구간**에 더한다(봉 안의 체결 가격 분포는 일봉만으로 알 수 없어 종가 기준으로 근사).
 * 결과는 낮은 가격 구간부터 정렬된다. 가격 범위가 0이면 빈 배열.
 */
export function volumeProfile(candles: readonly Candle[], bins = 7): VolumeProfileBin[] {
  if (candles.length === 0 || !Number.isInteger(bins) || bins < 1) return [];
  const lo = Math.min(...candles.map((c) => c.low));
  const hi = Math.max(...candles.map((c) => c.high));
  if (!(hi > lo)) return [];
  const width = (hi - lo) / bins;
  const out: VolumeProfileBin[] = Array.from({ length: bins }, (_, i) => ({
    lo: lo + width * i,
    hi: lo + width * (i + 1),
    volume: 0,
    share: 0,
  }));
  let total = 0;
  for (const c of candles) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((c.close - lo) / width)));
    out[idx].volume += c.volume;
    total += c.volume;
  }
  if (total > 0) for (const b of out) b.share = (b.volume / total) * 100;
  return out;
}

export interface MacdCross {
  index: number;
  kind: "golden" | "dead"; // golden: MACD가 시그널을 아래→위로 돌파, dead: 위→아래
}

/** MACD선과 시그널선의 교차 지점. 두 값이 같은 봉은 직전의 부호를 이어 받아 한 번만 센다. */
export function macdCrosses(
  macdLine: readonly (number | null)[],
  signal: readonly (number | null)[],
): MacdCross[] {
  const out: MacdCross[] = [];
  let prevSign = 0;
  for (let i = 0; i < macdLine.length; i++) {
    const a = macdLine[i];
    const b = signal[i];
    if (a === null || b === null || a === undefined || b === undefined) continue;
    const sign = Math.sign(a - b);
    if (sign === 0) continue;
    if (prevSign !== 0 && sign !== prevSign) {
      out.push({ index: i, kind: sign > 0 ? "golden" : "dead" });
    }
    prevSign = sign;
  }
  return out;
}

/** 보기 좋은 눈금값(1·2·2.5·5 × 10^k). [lo, hi] 안의 값만 오름차순으로 반환한다. */
export function niceTicks(lo: number, hi: number, target = 5): number[] {
  if (!(hi > lo) || target < 1) return [];
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) {
    out.push(Number((Math.round(v / step) * step).toPrecision(12))); // 부동소수 오차 제거
  }
  return out;
}
