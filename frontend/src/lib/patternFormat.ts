import copy from "@/content/copy.ko.json";
import { formatSignedPercent } from "@/lib/formatPercent";
import type {
  PatternConditionId,
  PatternConditionResult,
  PatternDefinition,
  PatternItem,
} from "@/lib/types";

/**
 * 패턴 스크리닝 표시 문구 생성(03-ux-design.md §3-2). 모든 값은 API `metrics`/`definition`에서 주입하며
 * 임계값을 하드코딩하지 않는다(설정이 바뀌면 화면 문구가 따라간다). 순수 함수 — DOM/네트워크 없음.
 * 값이 `null`이면 "—"를 표시한다.
 */

const EMPTY = copy.pattern.emptyValue;

/** `{name}` 자리표시자를 채운다. 값이 없으면 빈 문자열이 아니라 그대로 두지 않고 "—"로 대체한다. */
export function fillTemplate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) =>
    key in values ? String(values[key]) : EMPTY,
  );
}

function signedPct(value: number | null): string {
  return value === null ? EMPTY : formatSignedPercent(value);
}

function plainPct(value: number | null): string {
  return value === null ? EMPTY : `${value.toFixed(1)}%`;
}

function ratio(value: number | null): string {
  return value === null ? EMPTY : value.toFixed(2);
}

export function conditionTitle(id: PatternConditionId): string {
  return copy.pattern.conditions[id];
}

export function stageText(stage: string | null, crossDays: number | null): string {
  switch (stage) {
    case "BELOW_NEAR":
      return copy.pattern.stage.BELOW_NEAR;
    case "CROSS_EARLY":
      return crossDays === null
        ? copy.pattern.stage.CROSS_EARLY_NO_DAYS
        : fillTemplate(copy.pattern.stage.CROSS_EARLY, { days: crossDays });
    case "EXTENDED":
      return copy.pattern.stage.EXTENDED;
    case "BELOW_FAR":
      return copy.pattern.stage.BELOW_FAR;
    case "ABOVE_SETTLED":
      return copy.pattern.stage.ABOVE_SETTLED;
    default:
      return EMPTY;
  }
}

/** 조건별 근거 문장(표 셀·카드 행에 배지와 함께 표시). */
export function evidenceText(
  id: PatternConditionId,
  item: PatternItem,
  definition: PatternDefinition,
): string {
  const m = item.metrics;
  switch (id) {
    case "c1":
      return fillTemplate(copy.pattern.evidence.c1, {
        range: plainPct(m.sideways_range_pct),
        lookback: definition.calc.lookback_days,
        net: signedPct(m.sideways_net_change_pct),
      });
    case "c2":
      return fillTemplate(copy.pattern.evidence.c2, {
        conv: plainPct(m.ma_convergence_pct),
        ratio: ratio(m.volatility_contraction_ratio),
      });
    case "c3":
      return fillTemplate(copy.pattern.evidence.c3, {
        gap: signedPct(m.ma60_gap_pct),
        gap2: signedPct(m.ma20_vs_ma60_gap_pct),
      });
    case "c4":
      return stageText(item.ma60_stage, m.ma60_cross_up_days);
    case "c5":
      return fillTemplate(copy.pattern.evidence.c5, { vr: ratio(m.volume_ratio_5_60) });
    case "c9": {
      const flag = m.recent_surge_flag;
      const state =
        flag === null
          ? EMPTY
          : flag
            ? copy.pattern.evidence.c9Has
            : copy.pattern.evidence.c9None;
      return fillTemplate(copy.pattern.evidence.c9, {
        days: definition.calc.surge_lookback_days,
        state,
      });
    }
  }
}

export function reasonText(reason: string | null): string | null {
  if (reason === null) return null;
  const table = copy.pattern.reason as Record<string, string>;
  return table[reason] ?? copy.pattern.reason.METRIC_UNAVAILABLE;
}

export type ConditionStatusKind = "met" | "unmet" | "unavailable";

export function statusKind(result: PatternConditionResult): ConditionStatusKind {
  if (result.met === true) return "met";
  if (result.met === false) return "unmet";
  return "unavailable";
}

/** 조건 정의 패널의 규칙 문장 — API `definition`(서버 설정)을 그대로 주입한다. */
export function definitionRuleText(id: PatternConditionId, d: PatternDefinition): string {
  const t = d.thresholds;
  const c = d.calc;
  const rules = copy.pattern.definitionRules;
  switch (id) {
    case "c1":
      return fillTemplate(rules.c1, {
        lookback: c.lookback_days,
        range: t.range_max_pct,
        net: t.net_change_max_pct,
      });
    case "c2":
      return fillTemplate(rules.c2, {
        conv: t.convergence_max_pct,
        window: c.ma60_window,
        vc: t.volatility_contraction_max,
      });
    case "c3":
      return fillTemplate(rules.c3, { window: c.ma60_window, band: t.ma60_approach_band_pct });
    case "c4":
      return fillTemplate(rules.c4, {
        window: c.ma60_window,
        band: t.ma60_approach_band_pct,
        early: t.ma60_early_max_gap_pct,
        days: t.cross_early_max_days,
      });
    case "c5":
      return fillTemplate(rules.c5, {
        window: c.ma60_window,
        vmin: t.volume_ratio_min,
        vmax: t.volume_ratio_max,
        anom: t.volume_anomaly_max,
      });
    case "c9":
      return fillTemplate(rules.c9, {
        days: c.surge_lookback_days,
        ret: c.surge_return_pct,
        mult: c.surge_volume_mult,
      });
  }
}
