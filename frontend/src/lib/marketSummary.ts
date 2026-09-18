import type { DataFreshness, Envelope, MarketSummaryData } from "@/lib/types";

/**
 * 시장 동향 리포트(REQ-004) 서버 컴포넌트 전용 fetch 클라이언트. `/stocks/[code]`
 * (`stockMetrics.ts`)와 동일한 패턴 — 홈 화면은 사용자 상호작용으로 결과가
 * 바뀌지 않는 화면(04-ux-design.md §2-1)이라 서버 컴포넌트 fetch로 충분하다
 * (스크리닝처럼 "폼은 유지, 결과만 갱신"할 필요가 없음 — `screenApi.ts`와의
 * 차이).
 *
 * `market` 파라미터는 의도적으로 항상 생략한다 — 04-ux-design.md §2-1이
 * 확정한 단일 호출 패턴(`market` 생략 시 서버가 `ALL` 집계 + `by_market`
 * 세부를 한 번에 반환)을 그대로 따른다(03-system-design.md §4-2 Q7, DEC-016).
 */
export type MarketSummaryResult =
  | { kind: "success"; data: MarketSummaryData; freshness: DataFreshness }
  | { kind: "error"; code: string; message: string };

export async function fetchMarketSummary(date?: string): Promise<MarketSummaryResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    return {
      kind: "error",
      code: "CONFIG_ERROR",
      message: "NEXT_PUBLIC_API_BASE_URL 환경변수가 설정되지 않았습니다.",
    };
  }

  const url = new URL("/api/v1/market-summary", baseUrl);
  if (date) {
    url.searchParams.set("date", date);
  }

  let response: Response;
  try {
    // 배치 갱신 데이터라 캐시하지 않는다(§3-4 원칙 — 매 요청마다 서버가
    // 계산한 최신 신선도 값을 그대로 신뢰).
    response = await fetch(url.toString(), { cache: "no-store" });
  } catch {
    return { kind: "error", code: "NETWORK_ERROR", message: "네트워크 오류가 발생했습니다." };
  }

  let body: Envelope<MarketSummaryData>;
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
