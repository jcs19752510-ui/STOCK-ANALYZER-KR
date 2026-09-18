import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §2-4 지표 카드 5번(밸류에이션) — PER/PBR/시가총액 백분위
 * 3개 값을 한 카드에 함께 표시한다(단일 값만 다루는 `MetricCard`와 구조가
 * 달라 별도 컴포넌트로 분리).
 *
 * PER/PBR이 `null`(적자기업 등 산정 불가)이면 "PER 산정 불가(적자기업 등)"로
 * 표시한다(§2-4 명시). 시가총액이 `null`인 경우의 문구는 설계서에 명시가
 * 없다 — "적자기업" 사유는 시가총액에 적용되지 않으므로, 일반적인 결측
 * 문구("데이터 부족")를 대신 사용한다(존재하지 않는 사유를 지어내지 않기
 * 위함, `unit-06-note.md` §2 참조). 현재 raw_fundamentals가 아직 적재되지
 * 않아(unit-02-note.md §0-3) 세 값 모두 항상 `null`이다 — 이는 결함이
 * 아니라 이 구현 시점의 알려진 데이터 공백이다(§3 참조).
 */
interface ValuationMetricCardProps {
  perPercentile: number | null;
  pbrPercentile: number | null;
  marketCapPercentile: number | null;
}

function formatPercentileOrUnavailable(value: number | null): string {
  if (value === null) {
    return copy.stockDetail.valuationUnavailableText;
  }
  return `${copy.stockDetail.percentileUpPrefix} ${value}%`;
}

export function ValuationMetricCard({
  perPercentile,
  pbrPercentile,
  marketCapPercentile,
}: ValuationMetricCardProps) {
  return (
    <div className="metric-card">
      <h2 className="metric-card__label">{copy.stockDetail.valuationLabel}</h2>
      <dl className="valuation-card__list">
        <div className="valuation-card__row">
          <dt>{copy.stockDetail.perLabel}</dt>
          <dd>{formatPercentileOrUnavailable(perPercentile)}</dd>
        </div>
        <div className="valuation-card__row">
          <dt>{copy.stockDetail.pbrLabel}</dt>
          <dd>{formatPercentileOrUnavailable(pbrPercentile)}</dd>
        </div>
        <div className="valuation-card__row">
          <dt>{copy.stockDetail.marketCapLabel}</dt>
          <dd>
            {marketCapPercentile === null
              ? copy.stockDetail.missingDataText
              : `${copy.stockDetail.percentileUpPrefix} ${marketCapPercentile}%`}
          </dd>
        </div>
      </dl>
      <p className="metric-card__helper">{copy.stockDetail.valuationHelper}</p>
    </div>
  );
}
