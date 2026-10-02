import Link from "next/link";
import copy from "@/content/copy.ko.json";
import { ConditionStatusBadge } from "@/components/ConditionStatusBadge";
import { PATTERN_CONDITION_IDS } from "@/lib/patternApi";
import { conditionTitle, evidenceText } from "@/lib/patternFormat";
import type { PatternDefinition, PatternItem } from "@/lib/types";

/**
 * 결과 표(≥1024px, 03-ux-design.md §2-1·§8) — `<table>` + `<caption>`(sr-only) + 열 `scope="col"`,
 * 종목명 셀 `scope="row"`. 조건 열이 6개라 이 표는 1024px 이상에서만 쓰고 그보다 좁으면 카드
 * (`PatternResultsList`)로 바뀐다. 사이드 패널과 함께 있어 폭이 좁을 수 있으므로 표를 포커스 가능한
 * 스크롤 영역(`role="region"`)으로 감싸, 넘치더라도 페이지 가로 스크롤이 아니라 표 안에서만 스크롤한다.
 * 점수·순위 열은 없다(REQ-034) — 조건별 충족/미충족/산정 불가와 근거 수치만 보여 준다.
 */
interface PatternResultsTableProps {
  items: PatternItem[];
  definition: PatternDefinition;
}

export function PatternResultsTable({ items, definition }: PatternResultsTableProps) {
  return (
    <div
      className="pattern-table-wrap"
      role="region"
      aria-label={copy.pattern.tableCaption}
      tabIndex={0}
    >
      <table className="results-table pattern-table">
        <caption className="sr-only">{copy.pattern.tableCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{copy.pattern.stockColumnLabel}</th>
            {PATTERN_CONDITION_IDS.map((id) => (
              <th scope="col" key={id}>
                {conditionTitle(id)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.stock_code}>
              <th scope="row">
                <Link href={`/stocks/${item.stock_code}`} className="results-table__link">
                  {item.name} <span className="results-table__code">({item.stock_code})</span>
                </Link>
                <div>
                  <span className="market-badge">{item.market}</span>
                </div>
              </th>
              {PATTERN_CONDITION_IDS.map((id) => (
                <td key={id}>
                  <ConditionStatusBadge result={item.conditions[id]} />
                  <span className="pattern-evidence">{evidenceText(id, item, definition)}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
