/**
 * 개인 로컬 모드 장중 시세(분봉·호가·체결, DEC-052) 프론트 연동.
 *
 * - 스위치: `NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED === "true"`(빌드 시점, 기본 꺼짐) **그리고** 시세 공개 스위치가 켜져 있어야 하고,
 *   브라우저 주소가 내 PC/사설망(localhost·127.x·10.x·172.16~31.x·192.168.x)일 때만 화면에 나타난다(공개 도메인에서는 숨김).
 *   서버(API)도 허용 IP·환경변수로 한 번 더 막으므로 이 검사는 보조 방어선이다.
 * - 호출은 브라우저가 한다(서버 렌더 경로를 거치지 않음). 로그인을 끈 로컬은 API로 직접, 로그인을 켠 로컬은 웹 서버 대행 경로(`apiBase.ts`)로 간다. 앱키는 이 코드에 존재하지 않는다(API 서버 환경변수에만 있음).
 */
import { browserApiBase } from "@/lib/apiBase";
import { isPrivateHostname } from "@/lib/privateHost";
import { PRICE_EXPOSURE_ENABLED } from "@/lib/priceExposure";
import type { Envelope } from "@/lib/types";

export const LOCAL_INTRADAY_FLAG = process.env.NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED === "true";

/** 화면에 개인 로컬 모드 기능(호가·체결 탭, 분·틱)을 보일지. 서버 렌더 시점에는 false(브라우저에서만 판단). */
export function localIntradayAvailable(): boolean {
  if (!LOCAL_INTRADAY_FLAG || !PRICE_EXPOSURE_ENABLED) return false;
  if (typeof window === "undefined") return false;
  return isPrivateHostname(window.location.hostname);
}

export type IntradayResult<T> =
  | { kind: "success"; data: T }
  | { kind: "error"; code: string; message: string };

export function intradayErrorMessage(code: string): string {
  switch (code) {
    case "FEATURE_DISABLED":
      return "개인 로컬 모드가 꺼져 있습니다. API 서버의 LOCAL_INTRADAY_ENABLED 설정을 확인하세요.";
    case "LOCAL_INTRADAY_NOT_CONFIGURED":
      return "증권사 앱키가 설정되지 않았습니다. API 서버의 KIS_APP_KEY·KIS_APP_SECRET을 확인하세요.";
    case "LOCAL_INTRADAY_MISCONFIGURED":
      return "개인 로컬 모드 설정이 올바르지 않습니다. API 서버 로그를 확인하세요.";
    case "INTRADAY_AUTH_FAILED":
      return "증권사 인증에 실패했습니다. 앱키·시크릿을 확인하세요.";
    case "INTRADAY_RATE_LIMITED":
    case "RATE_LIMITED":
      return "증권사 호출 한도를 초과했습니다. 잠시 후 자동으로 다시 시도합니다.";
    case "NETWORK_ERROR":
      return "API 서버에 연결하지 못했습니다.";
    default:
      return "장중 시세를 불러오지 못했습니다. 잠시 후 다시 시도합니다.";
  }
}

export async function fetchIntraday<T>(path: string, signal?: AbortSignal): Promise<IntradayResult<T>> {
  // 로그인을 켠 로컬은 웹 서버(대행 경로)를 거치고(DEC-075), 로그인을 끈 로컬은 지금처럼 API를 직접 부른다.
  const baseUrl = browserApiBase();
  if (!baseUrl) return { kind: "error", code: "CONFIG_ERROR", message: intradayErrorMessage("CONFIG_ERROR") };
  try {
    const response = await fetch(new URL(path, baseUrl).toString(), { signal, cache: "no-store" });
    const body = (await response.json()) as Envelope<T>;
    if (!response.ok || !body.data) {
      const code = body.error?.code ?? "UNKNOWN_ERROR";
      return { kind: "error", code, message: intradayErrorMessage(code) };
    }
    return { kind: "success", data: body.data };
  } catch (e) {
    if (signal?.aborted) return { kind: "error", code: "ABORTED", message: "" };
    return { kind: "error", code: "NETWORK_ERROR", message: intradayErrorMessage("NETWORK_ERROR") };
  }
}
