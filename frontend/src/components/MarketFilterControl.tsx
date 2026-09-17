import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §4 `MarketFilterControl` — 상장시장 구분 필터(전체/코스피/
 * 코스닥), 종목검색(칩)·스크리닝(세그먼트 버튼) 공통 컴포넌트. 이번 유닛은
 * 스크리닝(`/screener`)의 세그먼트 버튼 용법만 구현한다 — 종목검색(`/stocks`)
 * 은 REQ-001 프론트엔드 담당 유닛(UNIT-09) 범위이며, 이 컴포넌트를 그대로
 * 재사용해야 한다(임의로 새 필터 컴포넌트를 만들지 않는다, `unit-05-note.md`
 * §8과 동일한 재사용 원칙).
 */
export type ScreenMarketOption = "ALL" | "KOSPI" | "KOSDAQ";

interface MarketFilterControlProps {
  value: ScreenMarketOption;
  onChange: (value: ScreenMarketOption) => void;
}

const OPTIONS: Array<{ value: ScreenMarketOption; label: string }> = [
  { value: "ALL", label: copy.screener.marketOptionAll },
  { value: "KOSPI", label: copy.screener.marketOptionKospi },
  { value: "KOSDAQ", label: copy.screener.marketOptionKosdaq },
];

export function MarketFilterControl({ value, onChange }: MarketFilterControlProps) {
  return (
    <div className="market-filter-control" role="group" aria-label={copy.screener.marketLabel}>
      {OPTIONS.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            className={
              active
                ? "market-filter-control__button market-filter-control__button--active"
                : "market-filter-control__button"
            }
            aria-pressed={active}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
