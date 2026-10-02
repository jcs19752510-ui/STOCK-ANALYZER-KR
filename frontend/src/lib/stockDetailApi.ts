import type { DataFreshness, Envelope, StockPricesData } from "@/lib/types";

/**
 * 종목 상세 일봉(DEC-041) 서버 컴포넌트 전용 fetch. `stockMetrics.ts`와 같은 원칙으로 서버가 준 `error.code`를
 * 그대로 실어 반환한다. 실적·조건 체크는 서버가 아니라 탭을 열 때 브라우저가 호출한다(`useLazyApi.ts`).
 */
export type StockPricesResult =
  | { kind: "success"; data: StockPricesData; freshness: DataFreshness | null }
  | { kind: "not_found" }
  | { kind: "error"; code: string; message: string };

async function getJson<T>(path: string): Promise<{ ok: boolean; body: Envelope<T> | null }> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) return { ok: false, body: null };
  try {
    const response = await fetch(new URL(path, baseUrl).toString(), { cache: "no-store" });
    const body = (await response.json()) as Envelope<T>;
    return { ok: response.ok, body };
  } catch {
    return { ok: false, body: null };
  }
}

export async function fetchStockPrices(code: string, days = 260): Promise<StockPricesResult> {
  const { ok, body } = await getJson<StockPricesData>(
    `/api/v1/stocks/${encodeURIComponent(code)}/prices?days=${days}`,
  );
  if (body === null) {
    return { kind: "error", code: "NETWORK_ERROR", message: "네트워크 오류가 발생했습니다." };
  }
  if (!ok) {
    if (body.error?.code === "STOCK_NOT_FOUND") return { kind: "not_found" };
    return {
      kind: "error",
      code: body.error?.code ?? "UNKNOWN_ERROR",
      message: body.error?.message ?? "알 수 없는 오류가 발생했습니다.",
    };
  }
  if (!body.data) {
    return { kind: "error", code: "INVALID_RESPONSE", message: "서버 응답 형식이 올바르지 않습니다." };
  }
  return { kind: "success", data: body.data, freshness: body.meta.data_freshness ?? null };
}
