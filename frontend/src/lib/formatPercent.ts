/**
 * 04-ux-design.md §3-1 "등락률에 관한 주의(접근성)" — 색상에만 의존하지 않고
 * "+"/"-" 부호와 상승/하락 텍스트(스크린리더용)를 항상 함께 제공한다.
 */

export type PercentDirection = "up" | "down" | "flat";

export function percentDirection(value: number): PercentDirection {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

const DIRECTION_LABEL: Record<PercentDirection, string> = {
  up: "상승",
  down: "하락",
  flat: "보합",
};

export function percentDirectionLabel(value: number): string {
  return DIRECTION_LABEL[percentDirection(value)];
}

/** 예: 3.2 -> "+3.2%", -0.5 -> "-0.5%", 0 -> "0.0%" */
export function formatSignedPercent(value: number, digits = 1): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}%`;
}

/** 상승/하락에 따른 색상 클래스명(§3-1 — 색상은 보조 수단, 부호/텍스트가 항상 함께 있어야 함). */
export function percentValueClassName(value: number): string | undefined {
  const direction = percentDirection(value);
  if (direction === "up") return "metric-card__value--up";
  if (direction === "down") return "metric-card__value--down";
  return undefined;
}
