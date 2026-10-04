import { cookies } from "next/headers";
import { apiSessionCheck } from "@/lib/auth/apiClient";
import { authConfigProblem, authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { clearSessionCookie, json, nowSeconds, setSessionCookie } from "@/lib/auth/http";
import { isSameOriginRequest } from "@/lib/auth/origin";
import { refreshed, remainingSeconds, signSession, verifySession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

/**
 * 로그인 상태 갱신(DEC-067): 쿠키가 유효하면 API에 회원이 아직 활성인지 확인하고, 활성이면 "마지막 확인 시각"을 갱신한 쿠키를 다시 내려준다
 * (만료 시각은 그대로). 비활성·삭제된 회원이면 쿠키를 지우고 401. API가 응답하지 않으면 503만 돌려주고 **로그아웃시키지 않는다**(일시 장애).
 */
export async function POST(request: Request) {
  if (!authEnabled()) return json({ ok: false, code: "NOT_FOUND" }, 404);
  if (authConfigProblem()) return json({ ok: false, code: "MISCONFIGURED" }, 503);
  if (!isSameOriginRequest(request.headers)) return json({ ok: false, code: "FORBIDDEN" }, 403);
  const store = await cookies();
  const now = nowSeconds();
  const session = verifySession(store.get(sessionCookieName())?.value, sessionSecret(), now);
  if (!session) {
    const response = json({ ok: false, code: "AUTH_REQUIRED" }, 401);
    clearSessionCookie(response);
    return response;
  }
  const check = await apiSessionCheck(session.uid);
  if (check.kind === "unavailable") return json({ ok: false, code: "SERVICE_UNAVAILABLE" }, 503);
  if (check.kind === "inactive") {
    const response = json({ ok: false, code: "AUTH_REQUIRED" }, 401);
    clearSessionCookie(response);
    return response;
  }
  const next = refreshed({ ...session, un: check.user.username, dn: check.user.displayName }, now);
  const response = json({ ok: true });
  setSessionCookie(response, signSession(next, sessionSecret()), remainingSeconds(next, now));
  return response;
}
