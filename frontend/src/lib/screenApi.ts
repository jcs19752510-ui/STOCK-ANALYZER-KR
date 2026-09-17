import type { DataFreshness, Envelope, ScreenData } from "@/lib/types";

/**
 * 조건 스크리닝(REQ-003) 클라이언트 fetch. 04-ux-design.md §2-2가 "로딩:
 * 결과 영역만 스켈레톤, 조건 폼은 그대로 유지"를 요구하므로, 이 화면은
 * 서버 컴포넌트 fetch가 아니라 클라이언트 컴포넌트에서 직접 호출한다
 * (`/stocks/[code]`처럼 서버 컴포넌트 fetch를 쓰면 전체 라우트가 다시
 * 로딩되어 "폼은 유지"를 만족할 수 없다). `NEXT_PUBLIC_API_BASE_URL`은
 * Next.js가 빌드 시점에 클라이언트 번들에도 그대로 삽입하므로 브라우저에서도
 * 동일하게 사용 가능하다.
 */

// 03-system-design.md §4-1 — 화면 입력은 "억원" 단위, API는 KRW 정수.
export const KRW_PER_EOK = 100_000_000;

export function eokToKrw(eok: number): number {
  return Math.round(eok * KRW_PER_EOK);
}

export type ScreenSortBy = "return_pct" | "market_cap" | "per" | "pbr" | "volume_anomaly_score";
export type ScreenSortDir = "asc" | "desc";
export type ScreenMarket = "ALL" | "KOSPI" | "KOSDAQ";

export interface ScreenQuery {
  market: ScreenMarket;
  marketCapMinEok?: number;
  marketCapMaxEok?: number;
  volumeMin?: number;
  returnPctMin?: number;
  returnPctMax?: number;
  perMax?: number;
  pbrMax?: number;
  sortBy: ScreenSortBy;
  sortDir: ScreenSortDir;
  page: number;
}

export type ScreenApiResult =
  | { kind: "success"; data: ScreenData; freshness: DataFreshness }
  | { kind: "error"; code: string; message: string };

function buildSearchParams(query: ScreenQuery): URLSearchParams {
  const params = new URLSearchParams();
  params.set("market", query.market);
  if (query.marketCapMinEok !== undefined) {
    params.set("market_cap_min", String(eokToKrw(query.marketCapMinEok)));
  }
  if (query.marketCapMaxEok !== undefined) {
    params.set("market_cap_max", String(eokToKrw(query.marketCapMaxEok)));
  }
  if (query.volumeMin !== undefined) params.set("volume_min", String(query.volumeMin));
  if (query.returnPctMin !== undefined) params.set("return_pct_min", String(query.returnPctMin));
  if (query.returnPctMax !== undefined) params.set("return_pct_max", String(query.returnPctMax));
  if (query.perMax !== undefined) params.set("per_max", String(query.perMax));
  if (query.pbrMax !== undefined) params.set("pbr_max", String(query.pbrMax));
  params.set("sort_by", query.sortBy);
  params.set("sort_dir", query.sortDir);
  params.set("page", String(query.page));
  return params;
}

export async function fetchScreenResults(query: ScreenQuery): Promise<ScreenApiResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    return {
      kind: "error",
      code: "CONFIG_ERROR",
      message: "NEXT_PUBLIC_API_BASE_URL 환경변수가 설정되지 않았습니다.",
    };
  }

  const url = new URL("/api/v1/screen", baseUrl);
  url.search = buildSearchParams(query).toString();

  let response: Response;
  try {
    response = await fetch(url.toString(), { cache: "no-store" });
  } catch {
    return { kind: "error", code: "NETWORK_ERROR", message: "네트워크 오류가 발생했습니다." };
  }

  let body: Envelope<ScreenData>;
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
