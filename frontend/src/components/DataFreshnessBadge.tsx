import copy from "@/content/copy.ko.json";
import { formatKstDateTime } from "@/lib/formatKst";
import type { DataFreshness } from "@/lib/types";

interface DataFreshnessBadgeProps {
  /**
   * `null`은 아직 `meta.data_freshness`를 받지 못한 상태(로딩 중 등)를 뜻한다.
   * 424(CALENDAR_NOT_CONFIRMED) 같은 완전 실패는 이 컴포넌트가 아니라
   * 화면 전체를 대체하는 `ErrorState`(04-ux-design.md §1-4)가 담당한다 —
   * 이 컴포넌트는 "데이터 자체는 있으나 표시할 기준시각이 아직 없는" 좁은
   * 경우만 `unavailable` 변형으로 다룬다.
   */
  freshness: DataFreshness | null;
}

/** REQ-006 — 데이터 기준시각 표기 공통 컴포넌트(04-ux-design.md §2-0/§4). */
export function DataFreshnessBadge({ freshness }: DataFreshnessBadgeProps) {
  if (freshness === null) {
    return (
      <p className="data-freshness-badge data-freshness-badge--unavailable">
        {copy.dataFreshness.unavailableText}
      </p>
    );
  }

  const closedAtText = freshness.session_close_at
    ? formatKstDateTime(freshness.session_close_at)
    : freshness.trade_date;
  const updatedAtText = formatKstDateTime(freshness.generated_at);

  return (
    <div className="data-freshness-badge">
      <p className="data-freshness-badge__text">
        {copy.dataFreshness.sessionLabelPrefix}({freshness.market}) 기준 {closedAtText}{" "}
        {copy.dataFreshness.closedSuffix} · {updatedAtText} {copy.dataFreshness.updatedSuffix}
      </p>
      {!freshness.is_latest_trading_day && (
        <p className="data-freshness-badge__warning" role="status">
          <span aria-hidden="true">⚠</span>{" "}
          {freshness.staleness_note ?? copy.dataFreshness.staleFallbackWarning}
        </p>
      )}
    </div>
  );
}
