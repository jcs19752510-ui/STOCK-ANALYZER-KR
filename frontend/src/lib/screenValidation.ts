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
  ma5GapPctMin: string;
  ma5GapPctMax: string;
  ma20GapPctMin: string;
  ma20GapPctMax: string;
  volumeAnomalyScoreMin: string;
  volumeAnomalyScoreMax: string;
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
  ["ma5GapPctMin", "ma5GapPctMax", "5일 이동평균 이격도"],
  ["ma20GapPctMin", "ma20GapPctMax", "20일 이동평균 이격도"],
  ["volumeAnomalyScoreMin", "volumeAnomalyScoreMax", "거래량 이상치 스코어"],
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

/**
 * 시장 탭(전체/코스피/코스닥) 선택 시 자동으로 채워지는 기본 필터값(2026-09-22
 * 사용자 결정 — "유동성+대형주 중심" 프리셋). 아무 조건도 모르는 사용자가
 * 바로 [조건 적용]을 눌러도, 거래정지에 가까운 초소형·이상치 종목이 상위에
 * 섞이지 않고 바로 유의미한 결과를 보게 하는 것이 목적이다. `market`만 다르고
 * 나머지는 세 탭 공통이다 — 탭을 바꾸면 이 값 그대로(입력했던 다른 조건은
 * 초기화됨) 다시 채워진다(ScreenerClient.tsx `handleMarketChange` 참조).
 */
export const DEFAULT_SCREEN_FORM_VALUES: ScreenFormValues = {
  market: "ALL",
  marketCapMin: "500",
  marketCapMax: "",
  volumeMin: "100000",
  returnPctMin: "",
  returnPctMax: "",
  perMax: "",
  pbrMax: "",
  ma5GapPctMin: "",
  ma5GapPctMax: "",
  ma20GapPctMin: "",
  ma20GapPctMax: "",
  volumeAnomalyScoreMin: "",
  volumeAnomalyScoreMax: "",
  sortBy: "market_cap",
  sortDir: "desc",
};

/** 시장 탭 전환 시 폼 전체를 이 값으로 되돌린다(market만 교체). */
export function defaultScreenFormValuesFor(market: ScreenFormValues["market"]): ScreenFormValues {
  return { ...DEFAULT_SCREEN_FORM_VALUES, market };
}
