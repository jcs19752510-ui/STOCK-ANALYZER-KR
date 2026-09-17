import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §4 `EmptyState` 공통 컴포넌트. UNIT-06은 `no-data-yet`
 * (503 DATA_PIPELINE_STALE) 하나만 구현했다. 이번 유닛(REQ-003)은 §1-2
 * Flow B가 명시한 두 빈 상태를 추가한다: 조건 미적용 초기 상태와 조건
 * 결과 0건 상태. `no-search-result`(종목 검색, UNIT-06 검색 UI 확장)는
 * 여전히 이번 유닛 범위가 아니므로 추가하지 않는다(쓰지 않는 변형을
 * 미리 만들지 않는다는 unit-05/06 원칙을 그대로 승계).
 *
 * **04-ux-design.md §4의 변형 이름 표기 보완**: §4 표는 스크리닝 화면의
 * 빈 상태를 `no-screen-result`(조건 결과 0건) 하나만 명명했고, §1-2 Flow B가
 * 별도로 서술한 "초기(조건 미적용)" 상태에는 전용 변형 이름이 없었다(설계
 * 문서의 명명 누락 — 텍스트 자체는 §1-2/§2-2에 이미 확정되어 있다). 이
 * 유닛은 그 누락을 `no-screen-conditions`라는 이름으로 채워 넣었다 — 새
 * 기능이 아니라 이미 확정된 문구에 이름을 붙인 것뿐이다(`unit-07-note.md`
 * §2 참조).
 */
export type EmptyStateVariant = "no-data-yet" | "no-screen-conditions" | "no-screen-result";

interface EmptyStateProps {
  variant: EmptyStateVariant;
}

const VARIANT_MESSAGE: Record<EmptyStateVariant, string> = {
  "no-data-yet": copy.emptyState.noDataYetTitle,
  "no-screen-conditions": copy.emptyState.noScreenConditionsTitle,
  "no-screen-result": copy.emptyState.noScreenResultTitle,
};

export function EmptyState({ variant }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <p>{VARIANT_MESSAGE[variant]}</p>
    </div>
  );
}
