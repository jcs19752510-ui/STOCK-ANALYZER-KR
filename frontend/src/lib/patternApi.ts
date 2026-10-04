import { browserApiBase } from "@/lib/apiBase";
import type { DataFreshness, Envelope, PatternConditionId, PatternScreenData } from "@/lib/types";

/**
 * 패턴 스크리닝(REQ-032) 클라이언트 fetch — `screenApi.ts`와 같은 이유로 클라이언트 컴포넌트에서
 * 직접 호출한다(결과 영역만 갱신, 필터는 유지). 사용자는 임계값을 바꿀 수 없으므로 질의에는
 * 시장·필수 조건·최소 시가총액·최소 거래량·페이지만 담긴다.
 */

// 03-system-design.md §4-1 — 화면 입력은 "억원" 단위, API는 KRW 정수.
const KRW_PER_EOK = 100_000_000;

export const PATTERN_PAGE_SIZE = 50;

/** 서버가 허용하는 조건 ID의 정규 순서(필수 조건 파라미터도 이 순서로 보낸다). */
export const PATTERN_CONDITION_IDS: readonly PatternConditionId[] = [
  "c1",
  "c2",
  "c3",
  "c4",
  "c5",
  "c9",
];

export type PatternMarket = "ALL" | "KOSPI" | "KOSDAQ";

export interface PatternQuery {
  market: PatternMarket;
  marketCapMinEok?: number;
  volumeMin?: number;
  required: PatternConditionId[];
  page: number;
}

export type PatternApiResult =
  | { kind: "success"; data: PatternScreenData; freshness: DataFreshness }
  | { kind: "error"; code: string; message: string };

export function buildPatternSearchParams(query: PatternQuery): URLSearchParams {
  const params = new URLSearchParams();
  params.set("market", query.market);
  // 서버는 정규 순서만 받는다(중복·공백 금지). 순서를 정렬해서 보낸다.
  const ordered = PATTERN_CONDITION_IDS.filter((id) => query.required.includes(id));
  params.set("required", ordered.join(","));
  if (query.marketCapMinEok !== undefined) {
    params.set("market_cap_min", String(Math.round(query.marketCapMinEok * KRW_PER_EOK)));
  }
  if (query.volumeMin !== undefined) params.set("volume_min", String(query.volumeMin));
  params.set("page", String(query.page));
  params.set("page_size", String(PATTERN_PAGE_SIZE));
  return params;
}

export async function fetchPatternResults(query: PatternQuery): Promise<PatternApiResult> {
  const baseUrl = browserApiBase();
  if (!baseUrl) {
    return {
      kind: "error",
      code: "CONFIG_ERROR",
      message: "NEXT_PUBLIC_API_BASE_URL 환경변수가 설정되지 않았습니다.",
    };
  }

  const url = new URL("/api/v1/screen/pattern", baseUrl);
  url.search = buildPatternSearchParams(query).toString();

  let response: Response;
  try {
    response = await fetch(url.toString(), { cache: "no-store" });
  } catch {
    return { kind: "error", code: "NETWORK_ERROR", message: "네트워크 오류가 발생했습니다." };
  }

  let body: Envelope<PatternScreenData>;
  try {
    body = await response.json();
  } catch {
    return {
      kind: "error",
      code: "INVALID_RESPONSE",
      message: "서버 응답을 해석할 수 없습니다.",
    };
  }

  if (!response.ok) {
    return {
      kind: "error",
      code: body.error?.code ?? "UNKNOWN_ERROR",
      message: body.error?.message ?? "알 수 없는 오류가 발생했습니다.",
    };
  }

  if (!body.data || !body.meta.data_freshness) {
    return {
      kind: "error",
      code: "INVALID_RESPONSE",
      message: "서버 응답 형식이 올바르지 않습니다.",
    };
  }

  return { kind: "success", data: body.data, freshness: body.meta.data_freshness };
}
