import copy from "@/content/copy.ko.json";
import { reasonText, statusKind, type ConditionStatusKind } from "@/lib/patternFormat";
import type { PatternConditionResult } from "@/lib/types";

/**
 * 조건 충족 상태 배지(03-ux-design.md §3-1). **색에만 의존하지 않는다** — 글리프(✓/✕/–)와 텍스트
 * (충족/미충족/산정 불가)를 항상 함께 보여 준다. 글리프는 `aria-hidden`, 텍스트는 항상 보인다.
 * 산정 불가이면 사유(`reason`)를 배지 아래 보조 줄로 **항상 표시**한다(툴팁 의존 금지, REQ-035).
 * 상승/하락 색(`semantic.up/down`)은 쓰지 않는다 — 등락 표시가 아니므로 오독을 막는다.
 */
const GLYPH: Record<ConditionStatusKind, string> = { met: "✓", unmet: "✕", unavailable: "–" };

const LABEL: Record<ConditionStatusKind, string> = {
  met: copy.pattern.status.met,
  unmet: copy.pattern.status.unmet,
  unavailable: copy.pattern.status.unavailable,
};

interface ConditionStatusBadgeProps {
  result: PatternConditionResult;
}

export function ConditionStatusBadge({ result }: ConditionStatusBadgeProps) {
  const kind = statusKind(result);
  const reason = kind === "unavailable" ? reasonText(result.reason) : null;

  return (
    <span className="condition-status">
      <span className={`condition-status__badge condition-status__badge--${kind}`}>
        <span aria-hidden="true">{GLYPH[kind]}</span>
        <span>{LABEL[kind]}</span>
      </span>
      {reason && (
        <span className="condition-status__reason">
          <span className="sr-only">{copy.pattern.reasonLabel} </span>
          {reason}
        </span>
      )}
    </span>
  );
}
