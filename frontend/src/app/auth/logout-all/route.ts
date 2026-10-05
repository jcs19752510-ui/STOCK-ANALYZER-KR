import { cookies } from "next/headers";
import { apiLogoutAll } from "@/lib/auth/apiClient";
import { authConfigProblem, authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { clearSessionCookie, json, nowSeconds } from "@/lib/auth/http";
import { isSameOriginRequest } from "@/lib/auth/origin";
import { verifySession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

/**
 * "모든 기기에서 로그아웃"(DEC-071): 이 회원의 서버 쪽 세션을 전부 취소하고(30일 유지 로그인 포함) 이 브라우저의 쿠키도 지운다.
 * 일반 로그아웃과 달리 **서버 취소가 확인된 경우에만** 쿠키를 지우고 성공을 알린다 — 실패했는데 성공처럼 보이면 다른 기기가 로그인된 채 남기 때문이다.
 * 서버 장애면 503(로그인은 그대로 두어 다시 시도할 수 있게 한다). 로그인하지 않았거나 이미 취소·만료된 세션이면 401.
 * 같은 사이트 화면에서 보낸 요청만 받는다.
 */
export async function POST(request: Request) {
  if (!authEnabled()) return json({ ok: false, code: "NOT_FOUND" }, 404);
  if (authConfigProblem()) return json({ ok: false, code: "MISCONFIGURED" }, 503);
  if (!isSameOriginRequest(request.headers)) return json({ ok: false, code: "FORBIDDEN" }, 403);
  const store = await cookies();
  const session = verifySession(store.get(sessionCookieName())?.value, sessionSecret(), nowSeconds());
  if (!session) return json({ ok: false, code: "AUTH_REQUIRED" }, 401);
  const count = await apiLogoutAll(session.uid, session.sid);
  if (count === "invalid") {
    const gone = json({ ok: false, code: "AUTH_REQUIRED" }, 401); // 이미 취소·만료된 로그인: 쿠키만 정리한다
    clearSessionCookie(gone);
    return gone;
  }
  if (count === null) return json({ ok: false, code: "SERVICE_UNAVAILABLE" }, 503);
  const response = json({ ok: true, revoked_count: count });
  clearSessionCookie(response);
  return response;
}
