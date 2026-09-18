import copy from "@/content/copy.ko.json";
import { formatTradingValueKrw } from "@/lib/formatKrw";
import type { MarketSummaryItem } from "@/lib/types";

/**
 * 04-ux-design.md §2-1/§4 `StatSummaryGrid` — "상승/하락/보합 종목 수 등
 * (전체 합산 + 시장별 세부)". 본문(§2-1)은 이를 "요약 통계 그리드"와
 * "총 거래대금 카드" 두 문단으로 서술하지만, §4의 공식 컴포넌트 목록은
 * 이 둘을 하나의 `StatSummaryGrid`로 묶어 정의한다 — 이 구현은 §4를
 * 우선해 카드 하나에 네 항목(상승/하락/보합/총 거래대금)을 모두 담는다.
 *
 * 코스피/코스닥 개별 세부는 "탭 또는 병기 카드" 중 **병기 카드(정적
 * 나열)**를 선택했다(§2-1이 두 방식을 모두 허용) — 탭 전환은 포커스 이동/
 * `role="tab"` 키보드 상호작용을 새로 도입해야 하는데, 이 화면에 그런
 * 인터랙티브 요소를 추가할 요구사항 근거가 없고(과설계 방지), UNIT-07이
 * 겪은 포커스 트랩류 결함(`unit-07-test.md` DEF-U07-01)의 위험 자체를
 * 구조적으로 피할 수 있다는 이점이 있어 더 단순한 대안을 택했다.
 */
interface StatSummaryGridProps {
  overall: MarketSummaryItem;
  byMarket: MarketSummaryItem[] | null;
}

const MARKET_LABEL: Record<string, string> = {
  KOSPI: copy.home.marketLabelKospi,
  KOSDAQ: copy.home.marketLabelKosdaq,
};

function StatCard({ item, label }: { item: MarketSummaryItem; label: string }) {
  return (
    <div className="stat-summary-card">
      <h2 className="stat-summary-card__title">{label}</h2>
      <dl className="stat-summary-card__list">
        <div className="stat-summary-card__row">
          <dt>{copy.home.advancersLabel}</dt>
          <dd className="metric-card__value--up">+{item.advancers_count}</dd>
        </div>
        <div className="stat-summary-card__row">
          <dt>{copy.home.declinersLabel}</dt>
          <dd className="metric-card__value--down">-{item.decliners_count}</dd>
        </div>
        <div className="stat-summary-card__row">
          <dt>{copy.home.unchangedLabel}</dt>
          <dd>{item.unchanged_count}</dd>
        </div>
        <div className="stat-summary-card__row">
          <dt>{copy.home.totalTradingValueLabel}</dt>
          <dd>{formatTradingValueKrw(item.total_trading_value_krw)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function StatSummaryGrid({ overall, byMarket }: StatSummaryGridProps) {
  return (
    <div className="stat-summary-grid">
      <StatCard item={overall} label={copy.home.marketLabelAll} />
      {byMarket?.map((item) => (
        <StatCard key={item.market} item={item} label={MARKET_LABEL[item.market] ?? item.market} />
      ))}
    </div>
  );
}
