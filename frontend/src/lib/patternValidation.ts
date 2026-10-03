import type { PatternConditionId } from "@/lib/types";

/**
 * 패턴 스크리닝 폼 클라이언트 검증(03-ux-design.md §5 "검증 오류") — 순수 함수라 DOM/네트워크 없이
 * 검증할 수 있다. 필수 조건을 모두 해제하면 요청을 보내지 않고 인라인 오류를 보여 준다(서버도 400).
 */
export interface PatternFormValues {
  market: "ALL" | "KOSPI" | "KOSDAQ";
  marketCapMin: string;
  volumeMin: string;
  required: PatternConditionId[];
}

export type PatternFormField = "required" | "marketCapMin" | "volumeMin";

export interface PatternFieldError {
  field: PatternFormField;
  message: string;
}

export interface PatternFormMessages {
  requiredError: string;
  numberError: string;
}

/** 빈 문자열은 "입력 안 함"(선택 입력)이라 오류가 아니다. 입력했다면 0 이상의 수여야 한다. */
function isInvalidNonNegative(raw: string): boolean {
  if (raw.trim() === "") return false;
  const value = Number(raw);
  return Number.isNaN(value) || value < 0;
}

export function validatePatternForm(
  values: PatternFormValues,
  messages: PatternFormMessages,
): PatternFieldError[] {
  const errors: PatternFieldError[] = [];
  if (values.required.length === 0) {
    errors.push({ field: "required", message: messages.requiredError });
  }
  if (isInvalidNonNegative(values.marketCapMin)) {
    errors.push({ field: "marketCapMin", message: messages.numberError });
  }
  if (isInvalidNonNegative(values.volumeMin)) {
    errors.push({ field: "volumeMin", message: messages.numberError });
  }
  return errors;
}

/** 필수 조건 체크 토글: 이미 있으면 제거, 없으면 추가(순서는 서버 전송 시 정규화). */
export function toggleRequired(
  current: PatternConditionId[],
  id: PatternConditionId,
): PatternConditionId[] {
  return current.includes(id) ? current.filter((c) => c !== id) : [...current, id];
}

/** 폼 필드 → DOM id. 검증 실패 시 첫 오류 필드로 포커스를 옮기는 데 쓴다. */
export const PATTERN_FIELD_IDS: Record<PatternFormField, string> = {
  required: "pattern-required-c1",
  marketCapMin: "pattern-market-cap-min",
  volumeMin: "pattern-volume-min",
};
