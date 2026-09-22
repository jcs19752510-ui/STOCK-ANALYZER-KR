import copy from "@/content/copy.ko.json";
import {
  formatSignedPercent,
  percentDirectionLabel,
  percentValueClassName,
} from "@/lib/formatPercent";

/**
 * `GET /api/v1/screen` `matched_metrics`의 키(sort_by 허용값과 동일,
 * 03-system-design.md §4-2) -> 화면 표시 문구 변환. 04-ux-design.md §2-2/§2-6이
 * 정한 "무엇의 몇 배/몇 %인지 항상 명시한 완전한 문장형" 원칙을 그대로 따른다
 * (단순 숫자 나열 금지 — `/stocks/[code]` 종목 상세 화면의 표기 규칙과 동일).
 */
export const MATCHED_METRIC_DISPLAY_ORDER = [
  "return_pct",
  "market_cap",
  "per",
  "pbr",
  "ma5_gap_pct",
  "ma20_gap_pct",
  "volume_anomaly_score",
] as const;

export interface FormattedMetric {
  label: string;
  text: string;
  valueClassName?: string;
  srOnlyPrefix?: string;
}

export function formatMatchedMetric(key: string, value: number | null): FormattedMetric {
  switch (key) {
    case "return_pct":
      return {
        label: copy.screener.metricLabels.returnPct,
        text: value === null ? copy.stockDetail.missingDataText : formatSignedPercent(value),
        valueClassName: value === null ? undefined : percentValueClassName(value),
        srOnlyPrefix: value === null ? undefined : percentDirectionLabel(value),
      };
    case "market_cap":
      return {
        label: copy.screener.metricLabels.marketCap,
        text:
          value === null
            ? copy.stockDetail.missingDataText
            : `${copy.stockDetail.percentileUpPrefix} ${value}%`,
      };
    case "per":
      return {
        label: copy.screener.metricLabels.per,
        text:
          value === null
            ? copy.stockDetail.valuationUnavailableText
            : `${copy.stockDetail.percentileUpPrefix} ${value}%`,
      };
    case "pbr":
      return {
        label: copy.screener.metricLabels.pbr,
        text:
          value === null
            ? copy.stockDetail.valuationUnavailableText
            : `${copy.stockDetail.percentileUpPrefix} ${value}%`,
      };
    case "ma5_gap_pct":
      return {
        label: copy.screener.metricLabels.ma5GapPct,
        text: value === null ? copy.stockDetail.missingDataText : formatSignedPercent(value),
        valueClassName: value === null ? undefined : percentValueClassName(value),
        srOnlyPrefix: value === null ? undefined : percentDirectionLabel(value),
      };
    case "ma20_gap_pct":
      return {
        label: copy.screener.metricLabels.ma20GapPct,
        text: value === null ? copy.stockDetail.missingDataText : formatSignedPercent(value),
        valueClassName: value === null ? undefined : percentValueClassName(value),
        srOnlyPrefix: value === null ? undefined : percentDirectionLabel(value),
      };
    case "volume_anomaly_score":
      return {
        label: copy.screener.metricLabels.volumeAnomalyScore,
        text:
          value === null
            ? copy.stockDetail.missingDataText
            : `${value.toFixed(1)} ${copy.stockDetail.volumeAnomalySuffix}`,
      };
    default:
      return {
        label: key,
        text: value === null ? copy.stockDetail.missingDataText : String(value),
      };
  }
}

/** `matched_metrics`의 키 순서(객체 삽입 순서)에 의존하지 않고 항상 동일한
 * 순서로 표시하기 위한 정렬 헬퍼. */
export function orderMatchedMetricKeys(keys: string[]): string[] {
  const known = MATCHED_METRIC_DISPLAY_ORDER.filter((k) => keys.includes(k));
  const unknown = keys.filter((k) => !(MATCHED_METRIC_DISPLAY_ORDER as readonly string[]).includes(k));
  return [...known, ...unknown];
}
