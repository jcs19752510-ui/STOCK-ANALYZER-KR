import copy from "@/content/copy.ko.json";
import { conditionTitle, definitionRuleText } from "@/lib/patternFormat";
import { PATTERN_CONDITION_IDS } from "@/lib/patternApi";
import type { PatternDefinition } from "@/lib/types";

/**
 * 조건 정의와 기준값 패널(03-ux-design.md §3-3). 네이티브 `<details>`/`<summary>`(기본 접힘)라 키보드·
 * 스크린리더 지원이 기본으로 된다. 내용은 **API `definition`을 그대로 렌더**한다 — 하드코딩하지 않으므로
 * 서버 설정이 바뀌면 화면 문구가 자동으로 정확해진다. 하단에 대리 지표·미반영 범위 고지 2줄을 고정 표시한다.
 */
export function PatternDefinitionPanel({
  definition,
  basisNote = copy.pattern.definitionBasis,
}: {
  definition: PatternDefinition;
  /** 계산 기준 문구. 장중 기준이 켜진 동안은 그 기준을 알리는 문구로 바꾼다(DEC-089). */
  basisNote?: string;
}) {
  return (
    <details className="pattern-definition">
      <summary className="pattern-definition__summary">{copy.pattern.definitionHeading}</summary>
      <div className="pattern-definition__body">
        <dl className="pattern-definition__list">
          {PATTERN_CONDITION_IDS.map((id) => (
            <div key={id} className="pattern-definition__row">
              <dt>{conditionTitle(id)}</dt>
              <dd>{definitionRuleText(id, definition)}</dd>
            </div>
          ))}
        </dl>
        <p className="pattern-definition__note">{basisNote}</p>
        <p className="pattern-definition__note">{copy.pattern.proxyFootnote}</p>
        <p className="pattern-definition__note">{copy.pattern.scopeFootnote}</p>
        {definition.universe.excluded_types.length > 0 && (
          <p className="pattern-definition__note">{copy.pattern.universeFootnote}</p>
        )}
      </div>
    </details>
  );
}
