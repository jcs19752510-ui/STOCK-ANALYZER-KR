/**
 * 선발 기준 ⑥⑦(수급)·⑧(실적)의 사실 기준 판정(DEC-055). 점수·순위 없이 충족/미충족/산정 불가만 돌려준다.
 * 판정 규칙(모두 숫자 조건이며 이후 주가를 예측하지 않는다):
 * - ⑥ 외국인·기관 수급: 최근 20거래일 외국인+기관 누적 순매수 > 0 (10거래일 미만이면 산정 불가)
 * - ⑦ 개인 주도 아님: 같은 기간 개인 누적 순매수 ≤ 0 (순매도 또는 중립)
 * - ⑧ 실적: 최근 사업연도 영업이익이 흑자이고 전년보다 증가 (전년 값이 없거나 연도·기준이 다르면 산정 불가)
 */
import { formatEok } from "./formatEok.ts";
import type { EarningsYear, IntradayInvestorDay, PatternConditionResult } from "./types.ts";

export const FLOW_WINDOW_DAYS = 20;
export const FLOW_MIN_DAYS = 10;

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

/** `rows`는 최근 거래일이 앞. 세 투자자 수량이 모두 있는 날만 센다. */
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
  if (usable.length < FLOW_MIN_DAYS) {
    const msg = `수급 일수가 ${usable.length}일뿐이라 점검할 수 없습니다(최소 ${FLOW_MIN_DAYS}거래일).`;
    return { institutional: unavailable(msg), personal: unavailable(msg) };
  }
  const sum = (pick: (r: IntradayInvestorDay) => number | null) =>
    usable.reduce((a, r) => a + (pick(r) ?? 0), 0);
  const foreign = sum((r) => r.foreign_quantity);
  const inst = sum((r) => r.institution_quantity);
  const personal = sum((r) => r.personal_quantity);
  const days = usable.length;
  return {
    institutional: {
      result: { met: foreign + inst > 0, reason: null },
      evidence: `최근 ${days}거래일 누적 순매수 외국인 ${signedShares(foreign)} · 기관 ${signedShares(inst)} (합계 ${signedShares(foreign + inst)})`,
    },
    personal: {
      result: { met: personal <= 0, reason: null },
      evidence: `최근 ${days}거래일 누적 순매수 개인 ${signedShares(personal)}`,
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
