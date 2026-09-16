/**
 * API `error.code` -> 화면 표시 방식 매핑 (04-ux-design.md §1-4 Flow D).
 * `DATA_PIPELINE_STALE`(극단적 — 서빙 가능한 데이터 자체 없음)은 에러가
 * 아니라 빈 상태(`EmptyState`)로 취급한다(§1-4 표 참조). 이후 유닛(UNIT-07/08)도
 * 동일한 에러 코드 체계를 공유하므로 여기서 한 곳에 정의해 재사용한다.
 */

import type { ErrorStateVariant } from "@/components/ErrorState";

export type ApiErrorDisplay =
  | { kind: "empty"; variant: "no-data-yet" }
  | { kind: "error"; variant: ErrorStateVariant };

export function mapApiErrorCodeToDisplay(code: string): ApiErrorDisplay {
  switch (code) {
    case "DATA_PIPELINE_STALE":
      return { kind: "empty", variant: "no-data-yet" };
    case "CALENDAR_NOT_CONFIRMED":
      return { kind: "error", variant: "calendar-not-confirmed" };
    case "RATE_LIMITED":
      return { kind: "error", variant: "rate-limited" };
    default:
      // SERVICE_UNAVAILABLE, NETWORK_ERROR, INVALID_RESPONSE, CONFIG_ERROR,
      // UNKNOWN_ERROR 등 그 외 전부 — §1-4 "일시적인 오류가 발생했습니다" 공용 처리
      return { kind: "error", variant: "network" };
  }
}
