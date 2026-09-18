import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §4 `EmptyState` 공통 컴포넌트. UNIT-06은 `no-data-yet`
 * (503 DATA_PIPELINE_STALE) 하나만 구현했고, UNIT-07이 `no-screen-conditions`
 * (설계 문서 명명 누락 보완, §2 참조)/`no-screen-result`를 추가했다. 이번
 * 유닛(UNIT-09, REQ-001)은 §1-3 Flow C가 서술한 두 빈 상태를 추가한다:
 * `no-query`(질의 전 초기 상태)와 `no-search-result`(검색 결과 없음).
 *
 * `no-search-result`는 다른 변형과 달리 문구에 사용자가 입력한 검색어를
 * 그대로 삽입해야 한다("'{검색어}'에 대한 검색 결과가 없습니다...", §1-3).
 * 그래서 이 변형만 정적 `VARIANT_MESSAGE` 맵이 아니라 `query` prop을 받아
 * 템플릿 문자열의 `{query}` 자리를 치환한다.
 */
export type EmptyStateVariant =
  | "no-data-yet"
  | "no-screen-conditions"
  | "no-screen-result"
  | "no-query"
  | "no-search-result";

interface EmptyStateProps {
  variant: EmptyStateVariant;
  /** `no-search-result` 전용 — 생략 시 빈 문자열로 치환된다. */
  query?: string;
}

const STATIC_VARIANT_MESSAGE: Record<
  Exclude<EmptyStateVariant, "no-search-result">,
  string
> = {
  "no-data-yet": copy.emptyState.noDataYetTitle,
  "no-screen-conditions": copy.emptyState.noScreenConditionsTitle,
  "no-screen-result": copy.emptyState.noScreenResultTitle,
  "no-query": copy.emptyState.noQueryTitle,
};

export function EmptyState({ variant, query }: EmptyStateProps) {
  const message =
    variant === "no-search-result"
      ? copy.emptyState.noSearchResultTemplate.replace("{query}", query ?? "")
      : STATIC_VARIANT_MESSAGE[variant];

  return (
    <div className="empty-state">
      <p>{message}</p>
    </div>
  );
}
