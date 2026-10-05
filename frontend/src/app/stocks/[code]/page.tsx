import { notFound } from "next/navigation";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MetricCard } from "@/components/MetricCard";
import { PriceBasisNote } from "@/components/PriceBasisNote";
import { StockDetailTabs } from "@/components/StockDetailTabs";
import { StockQuoteHeader } from "@/components/StockQuoteHeader";
import { ValuationMetricCard } from "@/components/ValuationMetricCard";
import copy from "@/content/copy.ko.json";
import { requireMember } from "@/lib/auth/current";
import { mapApiErrorCodeToDisplay } from "@/lib/errorMapping";
import { formatSignedPercent, percentDirectionLabel, percentValueClassName } from "@/lib/formatPercent";
import { PRICE_EXPOSURE_ENABLED } from "@/lib/priceExposure";
import { fetchStockMetrics } from "@/lib/stockMetrics";
import { fetchStockPrices } from "@/lib/stockDetailApi";

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
  const session = await requireMember(date ? `/stocks/${code}?date=${date}` : `/stocks/${code}`); // 로그인 확인(프록시와 이중 방어)
  const isAdmin = session?.rl === "a"; // 관리자 전용 투자자 수급(DEC-074). 표시용 — API가 매 호출마다 DB에서 관리자 권한을 다시 확인한다
  // 서버 호출은 2건만(첫 화면에 필요한 것). 실적·조건 체크는 탭을 열 때 브라우저가 호출한다.
  // 시세 원값 비공개(DEC-048, 기본)면 일봉을 호출하지 않는다.
  const [result, pricesResult] = await Promise.all([
    fetchStockMetrics(code, date),
    PRICE_EXPOSURE_ENABLED ? fetchStockPrices(code) : Promise.resolve(null),
  ]);

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
  const prices = pricesResult?.kind === "success" ? pricesResult.data.prices : [];
  const latest = prices.length > 0 ? prices[prices.length - 1] : null;
  return (
    <section className="stock-detail-page">
      {latest ? (
        <StockQuoteHeader
          name={data.name}
          stockCode={data.stock_code}
          market={data.market}
          close={latest.close}
          change={latest.change}
          changePct={latest.change_pct}
          tradeDate={latest.trade_date}
        />
      ) : (
        <header className="stock-detail-header">
          <h1 className="stock-detail-header__title">
            {data.name} <span className="stock-detail-header__code">({data.stock_code})</span>
          </h1>
          <span className="market-badge">{data.market}</span>
        </header>
      )}
      {latest && (
        <p className="stock-quote__basis">
          <span className="market-badge">{data.market}</span> {data.stock_code} ·{" "}
          {copy.stockDetail.priceBasis.replace("{date}", latest.trade_date)} ·{" "}
          <PriceBasisNote />
        </p>
      )}

      <DataFreshnessBadge freshness={freshness} />

      {!PRICE_EXPOSURE_ENABLED ? (
        <>
          <p className="stock-quote__basis">{copy.stockDetail.pricesHiddenNote}</p>
          <StockDetailTabs stockCode={data.stock_code} stockName={data.name} prices={[]} showPrices={false} isAdmin={isAdmin} />
        </>
      ) : pricesResult?.kind === "success" && prices.length > 0 ? (
        <StockDetailTabs stockCode={data.stock_code} stockName={data.name} prices={prices} isAdmin={isAdmin} />
      ) : (
        <p className="stock-tabs__pending">
          {pricesResult?.kind === "success"
            ? copy.stockDetail.pricesEmpty
            : copy.stockDetail.pricesUnavailable}
        </p>
      )}

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
          perReason={data.per_unavailable_reason}
          pbrReason={data.pbr_unavailable_reason}
        />
      </div>
    </section>
  );
}
