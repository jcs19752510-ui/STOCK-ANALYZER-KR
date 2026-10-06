import { NextResponse } from "next/server";
import { bffGate } from "@/lib/auth/bffGate";
import { MAX_QUERY_LENGTH, isAdminOnlyBffPath, isAllowedBffPath } from "@/lib/auth/bffPaths";
import { json, setSessionCookie } from "@/lib/auth/http";
import { fetchWithColdStartRetry } from "@/lib/serverFetch";

export const dynamic = "force-dynamic";

/**
 * 회원 대행 경로(BFF, DEC-067): 브라우저는 API 서버가 아니라 이 경로(`/api/v1/*`)를 부르고, 웹 서버가 **로그인 확인 → 허용 목록 확인 → 내부 토큰으로 API 전달**을 한다.
 * - 조회(GET)만, 목록에 있는 경로만(`bffPaths.ts`). 브라우저의 쿠키·인증 헤더는 API로 넘기지 않는다.
 * - 회원 확인이 5분 지났으면 이 자리에서 API로 활성 여부를 다시 확인하고 쿠키를 갱신한다.
 */
export async function GET(request: Request) {
  const gate = await bffGate(request, (session, url) => {
    if (!isAllowedBffPath(url.pathname)) {
      return json({ data: null, error: { code: "NOT_FOUND", message: "찾을 수 없습니다." } }, 404);
    }
    if (isAdminOnlyBffPath(url.pathname) && session.rl !== "a") {
      return json({ data: null, error: { code: "FORBIDDEN", message: "권한이 없습니다." } }, 403);
    }
    if (url.search.length > MAX_QUERY_LENGTH) {
      return json({ data: null, error: { code: "INVALID_PARAMETER", message: "요청 파라미터가 올바르지 않습니다." } }, 400);
    }
    return null;
  });
  if (!gate.ok) return gate.response;

  const url = new URL(request.url);
  let upstream: Response;
  try {
    upstream = await fetchWithColdStartRetry(`${gate.base}${url.pathname}${url.search}`, {
      headers: { ...gate.upstreamHeaders, Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    return json({ data: null, error: { code: "SERVICE_UNAVAILABLE", message: "일시적인 서비스 장애입니다." } }, 503);
  }

  // API가 돌려준 JSON 본문과 상태만 그대로 전달한다(그 밖의 헤더·쿠키는 전달하지 않는다).
  const body = await upstream.text();
  const response = new NextResponse(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
  if (gate.refreshedCookie) setSessionCookie(response, gate.refreshedCookie.token, gate.refreshedCookie.maxAge);
  return response;
}
