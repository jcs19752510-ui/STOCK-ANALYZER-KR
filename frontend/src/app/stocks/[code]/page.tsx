import { notFound } from "next/navigation";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MetricCard } from "@/components/MetricCard";
import { ValuationMetricCard } from "@/components/ValuationMetricCard";
import copy from "@/content/copy.ko.json";
import { mapApiErrorCodeToDisplay } from "@/lib/errorMapping";
import { formatSignedPercent, percentDirectionLabel, percentValueClassName } from "@/lib/formatPercent";
import { fetchStockMetrics } from "@/lib/stockMetrics";

interface StockDetailPageProps {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ date?: string }>;
}

/**
 * 종목 상세 — 가공 지표 요약 (`/stocks/[code]`, REQ-002, REQ-006).
 * 04-ux-design.md §2-4를 그대로 구현한다: 원본 캔들차트/시세표 없이
 * `MetricCard` 5종(등락률 순위 / 5일·20일 이평 괴리율 / 거래량 이상치
 * 스코어 / PER·PBR·시가총액 백분위)만 카드형으로 노출한다(§4-3 데이터
 * 가공 원칙).
 */
export default async function StockDetailPage({ params, searchParams }: StockDetailPageProps) {
  const { code } = await params;
  const { date } = await searchParams;
  const result = await fetchStockMetrics(code, date);

  if (result.kind === "not_found") {
    notFound();
  }

  const retryHref = date ? `/stocks/${code}?date=${date}` : `/stocks/${code}`;

  if (result.kind === "error") {
    const display = mapApiErrorCodeToDisplay(result.code);
    if (display.kind === "empty") {
      return <EmptyState variant={display.variant} />;
    }
    return <ErrorState variant={display.variant} retryHref={retryHref} />;
  }

  const { data, freshness } = result;

  return (
    <section>
      <header className="stock-detail-header">
        <h1 className="stock-detail-header__title">
          {data.name} <span className="stock-detail-header__code">({data.stock_code})</span>
        </h1>
        <span className="market-badge">{data.market}</span>
      </header>

      <DataFreshnessBadge freshness={freshness} />

      <div className="metric-card-grid">
        <MetricCard
          label={copy.stockDetail.returnRankLabel}
          value={
            data.return_rank_pct === null
              ? null
              : `${copy.stockDetail.percentileUpPrefix} ${data.return_rank_pct}%`
          }
        />
        <MetricCard
          label={copy.stockDetail.ma5Label}
          value={data.ma5_gap_pct === null ? null : formatSignedPercent(data.ma5_gap_pct)}
          valueClassName={data.ma5_gap_pct === null ? undefined : percentValueClassName(data.ma5_gap_pct)}
          srOnlyPrefix={data.ma5_gap_pct === null ? undefined : percentDirectionLabel(data.ma5_gap_pct)}
        />
        <MetricCard
          label={copy.stockDetail.ma20Label}
          value={data.ma20_gap_pct === null ? null : formatSignedPercent(data.ma20_gap_pct)}
          valueClassName={data.ma20_gap_pct === null ? undefined : percentValueClassName(data.ma20_gap_pct)}
          srOnlyPrefix={
            data.ma20_gap_pct === null ? undefined : percentDirectionLabel(data.ma20_gap_pct)
          }
        />
        <MetricCard
          label={copy.stockDetail.volumeAnomalyLabel}
          value={
            data.volume_anomaly_score === null
              ? null
              : `${data.volume_anomaly_score.toFixed(1)} ${copy.stockDetail.volumeAnomalySuffix}`
          }
          helperText={copy.stockDetail.volumeAnomalyHelper}
        />
        <ValuationMetricCard
          perPercentile={data.per_percentile}
          pbrPercentile={data.pbr_percentile}
          marketCapPercentile={data.market_cap_percentile}
        />
      </div>
    </section>
  );
}
