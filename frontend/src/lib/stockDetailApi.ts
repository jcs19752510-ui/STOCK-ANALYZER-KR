import type {
  DataFreshness,
  Envelope,
  PatternCheckData,
  StockEarningsData,
  StockPricesData,
} from "@/lib/types";

/**
 * 종목 상세 확장(DEC-041) 서버 컴포넌트 전용 fetch. `stockMetrics.ts`와 같은 원칙으로 서버가 준 `error.code`를
 * 그대로 실어 반환한다. 보조 데이터(조건 체크)는 실패해도 화면 전체를 막지 않도록 호출부가 null로 처리한다.
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

/** 조건 체크표 — 실패·기능 꺼짐·미준비는 모두 null(탭에서 "표시할 수 없음" 안내). */
export async function fetchPatternCheck(code: string): Promise<PatternCheckData | null> {
  const { ok, body } = await getJson<PatternCheckData>(
    `/api/v1/stocks/${encodeURIComponent(code)}/pattern-check`,
  );
  return ok && body?.data ? body.data : null;
}

/** 연간 실적 — 실패·없음은 null(탭에서 안내). */
export async function fetchStockEarnings(code: string): Promise<StockEarningsData | null> {
  const { ok, body } = await getJson<StockEarningsData>(
    `/api/v1/stocks/${encodeURIComponent(code)}/earnings`,
  );
  return ok && body?.data ? body.data : null;
}
