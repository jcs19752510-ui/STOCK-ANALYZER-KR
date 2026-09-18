import type { ScreenFormField } from "@/lib/screenValidation";

/**
 * `ScreenFormValues` 필드 -> DOM id 매핑. `ConditionFilterPanel`(입력 렌더링)과
 * `/screener` 페이지(검증 실패 시 첫 오류 필드로 포커스 이동, 04-ux-design.md
 * §2-2)가 동일한 id를 참조해야 하므로 한 곳에 정의한다.
 */
export const SCREEN_FIELD_IDS: Partial<Record<ScreenFormField, string>> = {
  marketCapMin: "screen-market-cap-min",
  marketCapMax: "screen-market-cap-max",
  volumeMin: "screen-volume-min",
  returnPctMin: "screen-return-pct-min",
  returnPctMax: "screen-return-pct-max",
  perMax: "screen-per-max",
  pbrMax: "screen-pbr-max",
};
