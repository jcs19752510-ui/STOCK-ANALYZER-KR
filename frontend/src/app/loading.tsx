import { LoadingSkeleton } from "@/components/LoadingSkeleton";

/**
 * 서버가 데이터를 받아 오는 동안 즉시 보이는 공통 로딩 화면(DEC-065). 홈처럼 서버 컴포넌트가 API를 부르는 화면이 대상이며,
 * 종목 상세는 자체 `loading.tsx`가 있다. `data-page-loading` 표시를 `SlowPageReload`가 감시해서 오래 남아 있으면 자동으로 새로고침한다
 * (팝업은 없음, DEC-076).
 */
export default function RootLoading() {
  return (
    <section aria-busy="true" data-page-loading="true">
      <h1 className="sr-only">내용을 불러오는 중</h1>
      <p className="sr-only" role="status">
        로딩 중입니다
      </p>
      <div className="loading-skeleton loading-skeleton--header" aria-hidden="true" />
      <div className="metric-card-grid">
        <LoadingSkeleton variant="card" count={3} />
      </div>
    </section>
  );
}
