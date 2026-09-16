import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §4 `EmptyState` 공통 컴포넌트. 이번 유닛(REQ-002)이 실제로
 * 쓰는 변형은 `no-data-yet`(503 DATA_PIPELINE_STALE) 하나뿐이다. §4가 정의한
 * 나머지 변형(`no-query`/`no-search-result`/`no-screen-result`)은 종목 검색·
 * 스크리닝 화면(UNIT-06 검색 UI 확장/UNIT-07)이 실제로 필요할 때 추가해야
 * 한다 — 쓰지 않는 변형을 미리 만들지 않는다(unit-05-test.md가 지적한
 * "임시 텍스트 패턴을 그대로 승격시키지 말 것" 원칙과 동일하게, 이 컴포넌트도
 * 실제로 쓰는 변형만 정식으로 구현한다).
 */
export type EmptyStateVariant = "no-data-yet";

interface EmptyStateProps {
  variant: EmptyStateVariant;
}

const VARIANT_MESSAGE: Record<EmptyStateVariant, string> = {
  "no-data-yet": copy.emptyState.noDataYetTitle,
};

export function EmptyState({ variant }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <p>{VARIANT_MESSAGE[variant]}</p>
    </div>
  );
}
