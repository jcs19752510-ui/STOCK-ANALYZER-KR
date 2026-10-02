import { DEFAULT_SCREEN_FORM_VALUES } from "@/lib/screenValidation";
import { PATTERN_CONDITION_IDS } from "@/lib/patternApi";
import type { PatternFormValues } from "@/lib/patternValidation";

/**
 * 패턴 화면 진입 시 자동 조회에 쓰는 기본값(03-ux-design.md §5 "초기").
 * 시장 전체, 최소 시가총액·최소 거래량은 기존 스크리너의 기본 프리셋 상수를 **재사용**하고
 * (같은 값이 두 곳에 따로 있지 않도록), 필수 조건은 6개 전부 선택한 상태다.
 */
export const DEFAULT_PATTERN_FORM_VALUES: PatternFormValues = {
  market: "ALL",
  marketCapMin: DEFAULT_SCREEN_FORM_VALUES.marketCapMin,
  volumeMin: DEFAULT_SCREEN_FORM_VALUES.volumeMin,
  required: [...PATTERN_CONDITION_IDS],
};
