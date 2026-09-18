import type { DataFreshness, Envelope, StockMetricsData } from "@/lib/types";

/**
 * 종목 상세(REQ-002) 서버 컴포넌트 전용 fetch 클라이언트. 04-ux-design.md
 * §1-4 Flow D 에러 매핑을 그대로 따를 수 있도록, 원본 HTTP 상태 대신
 * 서버가 내려준 `error.code`를 결과에 그대로 실어 반환한다(프론트가 코드
 * 목록을 다시 판단하지 않고 서버가 준 값을 신뢰 — §3-4 원칙과 동일한 정신).
 */
export type StockMetricsResult =
  | { kind: "success"; data: StockMetricsData; freshness: DataFreshness }
  | { kind: "not_found" }
  | { kind: "error"; code: string; message: string };

export async function fetchStockMetrics(
  code: string,
  date?: string
): Promise<StockMetricsResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    return {
      kind: "error",
      code: "CONFIG_ERROR",
      message: "NEXT_PUBLIC_API_BASE_URL 환경변수가 설정되지 않았습니다.",
    };
  }

  const url = new URL(`/api/v1/stocks/${encodeURIComponent(code)}/metrics`, baseUrl);
  if (date) {
    url.searchParams.set("date", date);
  }

  let response: Response;
  try {
    // 지연 데이터 기반 배치 서비스라 캐시하면 안 됨(§3-4 "자체 계산하지 않는다"와
    // 같은 취지 — 매 요청마다 서버가 계산한 최신 신선도 값을 그대로 신뢰).
    response = await fetch(url.toString(), { cache: "no-store" });
  } catch {
    return { kind: "error", code: "NETWORK_ERROR", message: "네트워크 오류가 발생했습니다." };
  }

  let body: Envelope<StockMetricsData>;
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
    if (body.error?.code === "STOCK_NOT_FOUND") {
      return { kind: "not_found" };
    }
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
