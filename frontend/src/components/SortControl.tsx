import copy from "@/content/copy.ko.json";
import type { ScreenSortBy, ScreenSortDir } from "@/lib/screenApi";

/**
 * 04-ux-design.md §4 `SortControl` — 정렬 기준(드롭다운, 5개 값 고정) +
 * 정렬 방향(토글). §2-2: "PER/PBR도 `sort_dir=desc`는 항상 '원시값(배수)이
 * 큰 순'을 의미한다... 화면 토글 라벨도 '값이 큰 순/작은 순'처럼 원시값
 * 크기 기준으로 표기해 오해를 방지한다."
 */
interface SortControlProps {
  sortBy: ScreenSortBy;
  sortDir: ScreenSortDir;
  onSortByChange: (value: ScreenSortBy) => void;
  onSortDirChange: (value: ScreenSortDir) => void;
}

const SORT_BY_OPTIONS: Array<{ value: ScreenSortBy; label: string }> = [
  { value: "return_pct", label: copy.screener.sortByReturnPct },
  { value: "market_cap", label: copy.screener.sortByMarketCap },
  { value: "per", label: copy.screener.sortByPer },
  { value: "pbr", label: copy.screener.sortByPbr },
  { value: "ma5_gap_pct", label: copy.screener.sortByMa5GapPct },
  { value: "ma20_gap_pct", label: copy.screener.sortByMa20GapPct },
  { value: "volume_anomaly_score", label: copy.screener.sortByVolumeAnomalyScore },
];

export function SortControl({
  sortBy,
  sortDir,
  onSortByChange,
  onSortDirChange,
}: SortControlProps) {
  return (
    <div className="sort-control">
      <div className="condition-field">
        <label htmlFor="screen-sort-by" className="condition-field__label">
          {copy.screener.sortByLabel}
        </label>
        <select
          id="screen-sort-by"
          className="condition-field__input"
          value={sortBy}
          onChange={(event) => onSortByChange(event.target.value as ScreenSortBy)}
        >
          {SORT_BY_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="sort-control__direction">
        <span className="condition-field__label">{copy.screener.sortDirLabel}</span>
        <div className="sort-control__toggle" role="group" aria-label={copy.screener.sortDirLabel}>
          <button
            type="button"
            className={
              sortDir === "desc"
                ? "sort-control__toggle-button sort-control__toggle-button--active"
                : "sort-control__toggle-button"
            }
            aria-pressed={sortDir === "desc"}
            onClick={() => onSortDirChange("desc")}
          >
            {copy.screener.sortDirDesc}
          </button>
          <button
            type="button"
            className={
              sortDir === "asc"
                ? "sort-control__toggle-button sort-control__toggle-button--active"
                : "sort-control__toggle-button"
            }
            aria-pressed={sortDir === "asc"}
            onClick={() => onSortDirChange("asc")}
          >
            {copy.screener.sortDirAsc}
          </button>
        </div>
      </div>
    </div>
  );
}
