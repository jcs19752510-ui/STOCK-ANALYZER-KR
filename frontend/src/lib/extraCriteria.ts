/**
 * 선발 기준 ⑥⑦(수급)·⑧(실적)의 사실 기준 판정(DEC-055). 점수·순위 없이 충족/미충족/산정 불가만 돌려준다.
 * 판정 규칙(모두 숫자 조건이며 이후 주가를 예측하지 않는다):
 * - ⑥ 외국인·기관 수급: 최근 20거래일 외국인+기관 누적 순매수 > 0 (10거래일 미만이면 누적은 산정 불가)
 *   **또는** ⑪ 기관이 최근 3거래일 이상 연속 순매수(오늘 포함, 최신일부터 거슬러 세며 0·값 없음은 연속 중단).
 *   외국인이 팔고 있어도 기관이 연속 매수 중이면 충족(사용자 결정, DEC-061).
 * - ⑦ 개인 주도 아님: 같은 기간 개인 누적 순매수 ≤ 0(순매도 또는 중립).
 *   **예외**: ⑪(기관 연속 순매수)를 충족한 종목은 같은 기간 기관 누적 순매수가 개인 누적 순매수보다 크면 충족(DEC-061).
 * - ⑧ 실적: 최근 사업연도 영업이익이 흑자이고 전년보다 증가 (전년 값이 없거나 연도·기준이 다르면 산정 불가)
 */
import { formatEok } from "./formatEok.ts";
import type { EarningsYear, IntradayInvestorDay, PatternConditionResult } from "./types.ts";

export const FLOW_WINDOW_DAYS = 20;
export const FLOW_MIN_DAYS = 10;
/** ⑪ 기관 연속 순매수 기준 일수(DEC-061, 사용자 결정 "3일 연속"). */
export const INSTITUTION_STREAK_DAYS = 3;

export interface ExtraCriterion {
  result: PatternConditionResult;
  evidence: string;
}

const nf = new Intl.NumberFormat("ko-KR");

function signedShares(v: number): string {
  return `${v > 0 ? "+" : v < 0 ? "-" : ""}${nf.format(Math.abs(v))}주`;
}

function unavailable(evidence: string): ExtraCriterion {
  return { result: { met: null, reason: "INSUFFICIENT_HISTORY" }, evidence };
}

/**
 * ⑪ 기관 연속 순매수. `rows`는 최근 거래일이 앞. 최신일부터 기관 순매수 > 0인 날을 센다.
 * 0 이하인 날을 만나면 거기서 끊긴 것(확정), 값이 없는 날(null)을 만나면 확인할 수 없어 멈춘다.
 * 기준 일수에 도달하면 충족, 기준 전에 0 이하인 날로 끊기면 미충족, 값 없음·자료 부족으로 판단할 수 없으면 null.
 */
export function institutionStreak(rows: readonly IntradayInvestorDay[]): {
  days: number;
  met: boolean | null;
} {
  let days = 0;
  for (const r of rows) {
    const q = r.institution_quantity;
    if (q === null) return { days, met: days >= INSTITUTION_STREAK_DAYS ? true : null };
    if (q <= 0) return { days, met: days >= INSTITUTION_STREAK_DAYS };
    days += 1;
    if (days >= INSTITUTION_STREAK_DAYS) return { days, met: true };
  }
  return { days, met: days >= INSTITUTION_STREAK_DAYS ? true : null };
}

/** 세 값 논리합: 하나라도 true면 true, 둘 다 false면 false, 그 외(알 수 없음 포함)는 null. */
function orUnknown(a: boolean | null, b: boolean | null): boolean | null {
  if (a === true || b === true) return true;
  if (a === false && b === false) return false;
  return null;
}

function countStreakDays(rows: readonly IntradayInvestorDay[]): number {
  let n = 0;
  for (const r of rows) {
    if (r.institution_quantity !== null && r.institution_quantity > 0) n += 1;
    else break;
  }
  return n;
}

/** `rows`는 최근 거래일이 앞. 누적은 세 투자자 수량이 모두 있는 날만 센다. */
export function evaluateInvestorFlow(rows: readonly IntradayInvestorDay[]): {
  institutional: ExtraCriterion;
  personal: ExtraCriterion;
} {
  const usable = rows
    .filter(
      (r) =>
        r.personal_quantity !== null && r.foreign_quantity !== null && r.institution_quantity !== null,
    )
    .slice(0, FLOW_WINDOW_DAYS);
  const streak = institutionStreak(rows);
  const streakDays = countStreakDays(rows);
  const streakText = `기관 연속 순매수 ${streakDays}일(기준 ${INSTITUTION_STREAK_DAYS}일 이상)`;
  const cumulativeReady = usable.length >= FLOW_MIN_DAYS;

  const sum = (pick: (r: IntradayInvestorDay) => number | null) =>
    usable.reduce((a, r) => a + (pick(r) ?? 0), 0);
  const foreign = cumulativeReady ? sum((r) => r.foreign_quantity) : 0;
  const inst = cumulativeReady ? sum((r) => r.institution_quantity) : 0;
  const personal = cumulativeReady ? sum((r) => r.personal_quantity) : 0;
  const days = usable.length;
  const cumulativeMet: boolean | null = cumulativeReady ? foreign + inst > 0 : null;

  const cumulativeText = cumulativeReady
    ? `최근 ${days}거래일 누적 순매수 외국인 ${signedShares(foreign)} · 기관 ${signedShares(inst)} (합계 ${signedShares(foreign + inst)})`
    : `누적은 수급 일수가 ${days}일뿐이라 점검할 수 없습니다(최소 ${FLOW_MIN_DAYS}거래일)`;

  const instMet = orUnknown(cumulativeMet, streak.met);
  let basis = "";
  if (instMet === true) {
    basis =
      cumulativeMet === true && streak.met === true
        ? " → 누적과 기관 연속 순매수 모두 충족"
        : cumulativeMet === true
          ? " → 누적 순매수로 충족"
          : " → 외국인이 팔아도 기관이 연속 순매수 중이라 충족";
  }
  const institutional: ExtraCriterion =
    instMet === null
      ? unavailable(`${cumulativeText} · ${streakText}, 판단할 자료가 부족합니다.`)
      : { result: { met: instMet, reason: null }, evidence: `${cumulativeText} · ${streakText}${basis}` };

  if (!cumulativeReady) {
    return {
      institutional,
      personal: unavailable(
        `수급 일수가 ${days}일뿐이라 점검할 수 없습니다(최소 ${FLOW_MIN_DAYS}거래일).`,
      ),
    };
  }

  const allowedByInstitution = streak.met === true && inst > personal;
  const personalMet = personal <= 0 || allowedByInstitution;
  let personalNote = "";
  if (personal > 0) {
    personalNote = allowedByInstitution
      ? ` · 기관 연속 순매수를 충족하고 기관 누적 ${signedShares(inst)}가 개인 누적보다 커서 개인 주도가 아닌 것으로 봅니다`
      : streak.met === true
        ? ` · 기관 누적 ${signedShares(inst)}가 개인 누적보다 크지 않아 예외를 적용하지 않습니다`
        : " · 기관 연속 순매수를 충족하지 못해 예외를 적용하지 않습니다";
  }
  return {
    institutional,
    personal: {
      result: { met: personalMet, reason: null },
      evidence: `최근 ${days}거래일 누적 순매수 개인 ${signedShares(personal)}${personalNote}`,
    },
  };
}

/** `earnings`는 연도 오름차순. */
export function evaluateEarnings(earnings: readonly EarningsYear[]): ExtraCriterion {
  if (earnings.length < 2) {
    return {
      result: { met: null, reason: "METRIC_UNAVAILABLE" },
      evidence: "비교할 연간 실적이 2개 연도 미만이라 점검할 수 없습니다.",
    };
  }
  const cur = earnings[earnings.length - 1];
  const prev = earnings[earnings.length - 2];
  if (
    cur.operating_income === null ||
    prev.operating_income === null ||
    cur.fiscal_year - prev.fiscal_year !== 1 ||
    cur.fs_div !== prev.fs_div
  ) {
    return {
      result: { met: null, reason: "METRIC_UNAVAILABLE" },
      evidence: "영업이익이 없거나 연도·재무제표 기준이 달라 전년과 비교할 수 없습니다.",
    };
  }
  const pct =
    prev.operating_income > 0
      ? ` (${cur.operating_income >= prev.operating_income ? "+" : ""}${(((cur.operating_income - prev.operating_income) / prev.operating_income) * 100).toFixed(1)}%)`
      : "";
  const revenue =
    cur.revenue !== null && prev.revenue !== null
      ? ` · 매출 ${formatEok(cur.revenue)}억 원(전년 ${formatEok(prev.revenue)}억 원)`
      : "";
  return {
    result: {
      met: cur.operating_income > 0 && cur.operating_income > prev.operating_income,
      reason: null,
    },
    evidence: `${cur.fiscal_year}년 영업이익 ${formatEok(cur.operating_income)}억 원(전년 ${formatEok(prev.operating_income)}억 원)${pct}${revenue}`,
  };
}
