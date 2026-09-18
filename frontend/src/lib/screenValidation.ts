/**
 * 조건 스크리닝 폼(REQ-003) 클라이언트 유효성 검증(04-ux-design.md §2-2 —
 * "클라이언트 유효성 검증(범위 오류 등) 실패 시: 해당 입력 필드 인라인 에러...
 * 포커스를 첫 오류 필드로 이동"). 순수 함수라 DOM/네트워크 없이 검증 가능하다.
 */

export interface ScreenFormValues {
  market: "ALL" | "KOSPI" | "KOSDAQ";
  marketCapMin: string;
  marketCapMax: string;
  volumeMin: string;
  returnPctMin: string;
  returnPctMax: string;
  perMax: string;
  pbrMax: string;
  sortBy: string;
  sortDir: "asc" | "desc";
}

export type ScreenFormField = keyof ScreenFormValues;

export interface FieldError {
  field: ScreenFormField;
  message: string;
}

const RANGE_PAIRS: Array<[ScreenFormField, ScreenFormField, string]> = [
  ["marketCapMin", "marketCapMax", "시가총액"],
  ["returnPctMin", "returnPctMax", "등락률"],
];

/** 빈 문자열은 "입력 안 함"이므로 오류 대상이 아니다(모든 필드는 선택 입력). */
function parseOptionalNumber(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isNaN(value) ? null : value;
}

export function validateScreenForm(values: ScreenFormValues): FieldError[] {
  const errors: FieldError[] = [];

  for (const [minField, maxField, label] of RANGE_PAIRS) {
    const min = parseOptionalNumber(values[minField]);
    const max = parseOptionalNumber(values[maxField]);
    if (min === null || max === null) continue;
    if (min > max) {
      errors.push({
        field: maxField,
        message: `${label} 최소값은 최대값보다 클 수 없습니다.`,
      });
    }
  }

  return errors;
}

export const DEFAULT_SCREEN_FORM_VALUES: ScreenFormValues = {
  market: "ALL",
  marketCapMin: "",
  marketCapMax: "",
  volumeMin: "",
  returnPctMin: "",
  returnPctMax: "",
  perMax: "",
  pbrMax: "",
  sortBy: "return_pct",
  sortDir: "desc",
};
