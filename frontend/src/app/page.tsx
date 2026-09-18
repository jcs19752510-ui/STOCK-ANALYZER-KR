import Link from "next/link";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SectorSummaryList } from "@/components/SectorSummaryList";
import { StatSummaryGrid } from "@/components/StatSummaryGrid";
import copy from "@/content/copy.ko.json";
import { mapApiErrorCodeToDisplay } from "@/lib/errorMapping";
import { fetchMarketSummary } from "@/lib/marketSummary";

/**
 * 배치로 매일 갱신되는 데이터(REQ-011)를 보여주는 화면이라 빌드 시점에
 * 정적으로 구워지면 안 된다 — `cache: "no-store"` fetch만으로는 이
 * Next.js 버전(App Router "이전 모델")에서 라우트 자체를 동적 렌더링으로
 * 전환하지 못하고(Request-time API가 따로 없으면 여전히 정적 프리렌더링
 * 대상으로 분류됨, `node_modules/next/dist/docs/01-app/02-guides/
 * caching-without-cache-components.md` 참조), 실제로 `next build`에서
 * "○ Static"으로 분류되어 빌드 시점 스냅샷이 굳어지는 것을 직접 확인했다
 * (`unit-08-note.md` 참조). `force-dynamic`으로 매 요청마다 재실행되게
 * 강제한다.
 */
export const dynamic = "force-dynamic";

/**
 * 홈 — 시장 동향 리포트(`/`, REQ-004, REQ-006, 04-ux-design.md §2-1).
 * "어제 시장이 어땠는지"를 가공된 요약 통계로 보여준다 — 개별 종목 원본
 * 시세 나열 없음(§4-3 데이터 가공 원칙). UNIT-04가 남긴 임시 플레이스홀더를
 * 실제 화면으로 교체한다.
 *
 * 단일 API 호출(`GET /api/v1/market-summary`, `market` 생략 시 기본값
 * `ALL`)로 전체 합산(`data`)과 시장별 세부(`data.by_market`)를 함께 받는다
 * (§2-1 — v2까지의 "코스피/코스닥 각각 호출 후 프론트 합산" 방식은 폐기됨).
 */
export default async function HomePage() {
  const result = await fetchMarketSummary();

  if (result.kind === "error") {
    const display = mapApiErrorCodeToDisplay(result.code);
    if (display.kind === "empty") {
      return <EmptyState variant={display.variant} />;
    }
    return <ErrorState variant={display.variant} retryHref="/" />;
  }

  const { data, freshness } = result;

  return (
    <section>
      <h1 className="home-page__title">{copy.home.pageTitle}</h1>

      <DataFreshnessBadge freshness={freshness} />

      <StatSummaryGrid overall={data} byMarket={data.by_market} />

      <section className="home-page__section" aria-labelledby="home-sector-heading">
        <h2 id="home-sector-heading" className="home-page__section-title">
          {copy.home.sectorSectionTitle}
        </h2>
        <SectorSummaryList sectors={data.top_sectors_by_value} />
      </section>

      <nav className="home-page__entry-cards" aria-label={copy.home.entryCardsAriaLabel}>
        <Link href="/screener" className="home-page__entry-card">
          {copy.home.screenerEntryLabel}
        </Link>
        <Link href="/stocks" className="home-page__entry-card">
          {copy.home.stocksEntryLabel}
        </Link>
      </nav>
    </section>
  );
}
