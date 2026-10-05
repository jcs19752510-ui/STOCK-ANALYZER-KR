import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiSessionCheck } from "@/lib/auth/apiClient";
import { MAX_QUERY_LENGTH, isAdminOnlyBffPath, isAllowedBffPath } from "@/lib/auth/bffPaths";
import { authConfigProblem, authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { endUserIp } from "@/lib/auth/endUserIp";
import { clearSessionCookie, json, nowSeconds, setSessionCookie } from "@/lib/auth/http";
import { isFresh, refreshed, remainingSeconds, signSession, verifySession } from "@/lib/auth/session";
import { fetchWithColdStartRetry } from "@/lib/serverFetch";

export const dynamic = "force-dynamic";

const ENVELOPE_AUTH_REQUIRED = {
  data: null,
  error: { code: "AUTH_REQUIRED", message: "로그인이 필요합니다." },
};

/**
 * 회원 대행 경로(BFF, DEC-067): 브라우저는 API 서버가 아니라 이 경로(`/api/v1/*`)를 부르고, 웹 서버가 **로그인 확인 → 허용 목록 확인 → 내부 토큰으로 API 전달**을 한다.
 * - 조회(GET)만, 목록에 있는 경로만(`bffPaths.ts`). 브라우저의 쿠키·인증 헤더는 API로 넘기지 않는다.
 * - 회원 확인이 5분 지났으면 이 자리에서 API로 활성 여부를 다시 확인하고 쿠키를 갱신한다.
 */
export async function GET(request: Request) {
  if (!authEnabled()) return json({ data: null, error: { code: "NOT_FOUND", message: "찾을 수 없습니다." } }, 404);
  if (authConfigProblem()) return json({ data: null, error: { code: "SERVICE_UNAVAILABLE", message: "일시적인 서비스 장애입니다." } }, 503);

  const store = await cookies();
  const now = nowSeconds();
  const session = verifySession(store.get(sessionCookieName())?.value, sessionSecret(), now);
  if (!session) return json(ENVELOPE_AUTH_REQUIRED, 401);

  const url = new URL(request.url);
  if (!isAllowedBffPath(url.pathname)) {
    return json({ data: null, error: { code: "NOT_FOUND", message: "찾을 수 없습니다." } }, 404);
  }
  if (isAdminOnlyBffPath(url.pathname) && session.rl !== "a") {
    return json({ data: null, error: { code: "FORBIDDEN", message: "권한이 없습니다." } }, 403);
  }
  if (url.search.length > MAX_QUERY_LENGTH) {
    return json({ data: null, error: { code: "INVALID_PARAMETER", message: "요청 파라미터가 올바르지 않습니다." } }, 400);
  }

  let refreshedCookie: { token: string; maxAge: number } | null = null;
  if (!isFresh(session, now)) {
    const check = await apiSessionCheck(session.uid, session.sid);
    if (check.kind === "unavailable") {
      return json({ data: null, error: { code: "SERVICE_UNAVAILABLE", message: "일시적인 서비스 장애입니다." } }, 503);
    }
    if (check.kind === "inactive") {
      const response = json(ENVELOPE_AUTH_REQUIRED, 401);
      clearSessionCookie(response);
      return response;
    }
    const next = refreshed({ ...session, un: check.user.username, dn: check.user.displayName, rl: check.user.role === "admin" ? "a" : "u" }, now);
    refreshedCookie = { token: signSession(next, sessionSecret()), maxAge: remainingSeconds(next, now) };
  }

  const ip = endUserIp(request.headers);
  const upstreamHeaders: Record<string, string> = {
    "X-Internal-Token": (process.env.PUBLIC_API_INTERNAL_TOKEN ?? "").trim(),
    "X-Auth-User": session.uid,
    "X-Auth-Session": session.sid, // 관리자 전용 경로가 API에서 "유효한 세션 + 관리자"를 DB로 다시 확인한다(DEC-074)
    Accept: "application/json",
  };
  if (ip) upstreamHeaders["X-End-User-IP"] = ip;
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim().replace(/\/+$/, "");

  let upstream: Response;
  try {
    upstream = await fetchWithColdStartRetry(`${base}${url.pathname}${url.search}`, {
      headers: upstreamHeaders,
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
  if (refreshedCookie) setSessionCookie(response, refreshedCookie.token, refreshedCookie.maxAge);
  return response;
}
