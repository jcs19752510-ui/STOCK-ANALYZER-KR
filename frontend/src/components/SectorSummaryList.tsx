import copy from "@/content/copy.ko.json";
import { formatTradingValueKrw } from "@/lib/formatKrw";
import type { SectorSummary } from "@/lib/types";

/**
 * 04-ux-design.md §2-1/§4 `SectorSummaryList` — 업종별 거래대금 상위(최대
 * 5개, 막대바는 보조 시각 정보일 뿐 수치 텍스트가 항상 병기됨).
 *
 * 빈 배열이면 "부분 실패(업종 데이터만 없음)" 상태로 취급해 "업종 정보를
 * 준비 중입니다"를 대신 표시한다(§2-1) — `stock_master.sector` 출처가
 * 아직 확정되지 않아(03-system-design.md §8-2 항목8) 현재는 항상 빈
 * 배열이 될 수 있으며, 이는 결함이 아니라 알려진 데이터 공백이다.
 */
interface SectorSummaryListProps {
  sectors: SectorSummary[];
}

export function SectorSummaryList({ sectors }: SectorSummaryListProps) {
  if (sectors.length === 0) {
    return <p className="inline-notice inline-notice--info">{copy.home.sectorPreparingText}</p>;
  }

  const maxValue = sectors[0].trading_value_krw;

  return (
    <ul className="sector-summary-list">
      {sectors.map((item) => {
        const widthPct = maxValue > 0 ? Math.round((item.trading_value_krw / maxValue) * 100) : 0;
        return (
          <li key={item.sector} className="sector-summary-list__item">
            <div className="sector-summary-list__row">
              <span className="sector-summary-list__name">{item.sector}</span>
              <span className="sector-summary-list__value">
                {formatTradingValueKrw(item.trading_value_krw)}
              </span>
            </div>
            <div className="sector-summary-list__bar-track" aria-hidden="true">
              <div className="sector-summary-list__bar" style={{ width: `${widthPct}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
