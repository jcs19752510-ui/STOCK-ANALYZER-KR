import type { Envelope, StockSearchItem } from "@/lib/types";

/**
 * 종목 검색(REQ-001) 클라이언트 fetch. 04-ux-design.md §1-3 Flow C가
 * "검색어 입력(2자 이상, 디바운스 300ms) → 로딩"을 요구하므로, `/screener`
 * (`screenApi.ts`)와 동일하게 클라이언트 컴포넌트에서 직접 호출한다 —
 * 사용자가 타이핑할 때마다 페이지 전체를 다시 내비게이션할 수 없다.
 *
 * `GET /api/v1/stocks`는 `meta.data_freshness`를 포함하지 않는다
 * (`unit-03-note.md` §1-4 — 종목 마스터는 REQ-006이 요구하는 "시세/스크리닝/
 * 리포트" 화면 범위 밖). 따라서 이 결과 타입에는 `freshness`가 없다.
 */
export type StockSearchMarket = "ALL" | "KOSPI" | "KOSDAQ";

export type StockSearchResult =
  | { kind: "success"; data: StockSearchItem[] }
  | { kind: "error"; code: string; message: string };

export async function fetchStockSearch(
  query: string,
  market: StockSearchMarket
): Promise<StockSearchResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    return {
      kind: "error",
      code: "CONFIG_ERROR",
      message: "NEXT_PUBLIC_API_BASE_URL 환경변수가 설정되지 않았습니다.",
    };
  }

  const url = new URL("/api/v1/stocks", baseUrl);
  url.searchParams.set("query", query);
  url.searchParams.set("market", market);

  let response: Response;
  try {
    response = await fetch(url.toString(), { cache: "no-store" });
  } catch {
    return { kind: "error", code: "NETWORK_ERROR", message: "네트워크 오류가 발생했습니다." };
  }

  let body: Envelope<StockSearchItem[]>;
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

  if (!body.data) {
    return {
      kind: "error",
      code: "INVALID_RESPONSE",
      message: "서버 응답 형식이 올바르지 않습니다.",
    };
  }

  return { kind: "success", data: body.data };
}
