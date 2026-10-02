import copy from "@/content/copy.ko.json";
import { fillTemplate } from "@/lib/patternFormat";
import type { PatternReadiness } from "@/lib/types";

/**
 * 평가 가능 종목 수 보조 안내(REQ-035 — 산정 불가 종목을 조용히 제외하지 않는다). `ready_ratio < 1`일 때만
 * 표시한다. 기존 CSS 클래스 `inline-notice--info`를 재사용한다.
 */
export function ReadinessNote({ readiness }: { readiness: PatternReadiness }) {
  if (readiness.ready_ratio >= 1) return null;
  return (
    <p className="inline-notice inline-notice--info pattern-readiness">
      {fillTemplate(copy.pattern.readinessNote, {
        evaluated: readiness.evaluated_count,
        total: readiness.total_count,
      })}
    </p>
  );
}
