import { LoadingSkeleton } from "@/components/LoadingSkeleton";

/**
 * 04-ux-design.md §2-4 "로딩: 헤더 + 카드 5개 스켈레톤" — Next.js `loading.tsx`
 * 관례를 사용해 비동기 서버 컴포넌트(`page.tsx`)가 fetch를 끝낼 때까지 자동으로
 * 이 폴백을 스트리밍한다(별도 클라이언트 상태 관리 불필요).
 */
export default function StockDetailLoading() {
  return (
    <section aria-busy="true">
      <p className="sr-only" role="status">
        로딩 중입니다
      </p>
      <div className="loading-skeleton loading-skeleton--header" aria-hidden="true" />
      <div className="metric-card-grid">
        <LoadingSkeleton variant="card" count={5} />
      </div>
    </section>
  );
}
