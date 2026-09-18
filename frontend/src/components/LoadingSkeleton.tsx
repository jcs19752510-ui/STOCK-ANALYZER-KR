/**
 * 04-ux-design.md §4 `LoadingSkeleton` 공통 컴포넌트. 이번 유닛은 `card`
 * 변형만 사용한다(`table-row`/`text-line`은 이 화면에 해당 사항 없음 —
 * UNIT-07/08이 필요할 때 추가).
 */
interface LoadingSkeletonProps {
  variant?: "card";
  count?: number;
}

export function LoadingSkeleton({ variant = "card", count = 1 }: LoadingSkeletonProps) {
  return (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={`skeleton-${index}`}
          className={`loading-skeleton loading-skeleton--${variant}`}
          aria-hidden="true"
        />
      ))}
    </>
  );
}
