import copy from "@/content/copy.ko.json";

/** 항목 이름 옆 표지: "신규"(최근 1분 안에 조건 결과에 들어옴)와 "일봉"(시세를 못 받아 일봉 값을 그대로 쓴 항목). */
export function LiveItemMarks({ isNew, isDaily }: { isNew: boolean; isDaily: boolean }) {
  if (!isNew && !isDaily) return null;
  return (
    <span className="live-marks">
      {isNew && (
        <span className="live-mark live-mark--new">
          {copy.liveScreen.newBadge}
          <span className="sr-only"> ({copy.liveScreen.newBadgeSr})</span>
        </span>
      )}
      {isDaily && (
        <span className="live-mark live-mark--daily" title={copy.liveScreen.dailyMarkTitle}>
          {copy.liveScreen.dailyMark}
          <span className="sr-only"> ({copy.liveScreen.dailyMarkSr})</span>
        </span>
      )}
    </span>
  );
}
