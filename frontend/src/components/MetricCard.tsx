import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §2-4/§4 `MetricCard` — 가공 지표 1개 표시.
 * `value === null`이면 결측(§3-2 결측치 처리 원칙 — 0/"-" 등 대체값으로
 * 채우지 않고 "데이터 부족"을 명시적으로 표시).
 */
interface MetricCardProps {
  label: string;
  value: string | null;
  missingText?: string;
  helperText?: string;
  /** 등락률류 값에 상승/하락 색상을 입힐 때만 지정(§3-1 — 색상 단독 의존 금지, 부호는 value 문자열에 이미 포함) */
  valueClassName?: string;
  /** 스크린리더 전용 접두 텍스트(예: "상승 ") — 색상과 무관하게 의미를 전달(§3-1) */
  srOnlyPrefix?: string;
}

export function MetricCard({
  label,
  value,
  missingText,
  helperText,
  valueClassName,
  srOnlyPrefix,
}: MetricCardProps) {
  return (
    <div className="metric-card">
      <h2 className="metric-card__label">{label}</h2>
      {value === null ? (
        <p className="metric-card__missing">{missingText ?? copy.stockDetail.missingDataText}</p>
      ) : (
        <p className={valueClassName ? `metric-card__value ${valueClassName}` : "metric-card__value"}>
          {srOnlyPrefix && <span className="sr-only">{srOnlyPrefix} </span>}
          {value}
        </p>
      )}
      {helperText && <p className="metric-card__helper">{helperText}</p>}
    </div>
  );
}
