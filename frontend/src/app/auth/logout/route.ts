import { cookies } from "next/headers";
import { apiLogout } from "@/lib/auth/apiClient";
import { authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { clearSessionCookie, json, nowSeconds } from "@/lib/auth/http";
import { isSameOriginRequest } from "@/lib/auth/origin";
import { verifySession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

/**
 * 로그아웃(DEC-070): 서버 쪽 세션을 취소하고(분실·탈취된 쿠키도 못 쓰게) 쿠키를 지운다. 같은 사이트 화면에서 보낸 요청만 받는다.
 * 취소 요청이 실패(서버가 잠들어 있거나 장애)해도 이 브라우저의 쿠키는 반드시 지우고 `revoked: false`로 알린다 — 이 경우 복사된 쿠키는
 * 수명(최대 30일) 안에서 5분마다의 활성 확인을 통과할 수 있으므로, 분실이 의심되면 관리자가 `manage_users.py revoke-sessions`로 끊는다.
 * 쿠키가 없거나 형식이 틀려도 같은 성공 응답이다(상태를 알려 주지 않는다).
 */
export async function POST(request: Request) {
  if (!authEnabled()) return json({ ok: false, code: "NOT_FOUND" }, 404);
  if (!isSameOriginRequest(request.headers)) return json({ ok: false, code: "FORBIDDEN" }, 403);
  const store = await cookies();
  // 만료 직전·확인이 오래된 쿠키여도 id만 있으면 취소할 수 있다(서명은 확인한다).
  const session = verifySession(store.get(sessionCookieName())?.value, sessionSecret(), nowSeconds());
  const revoked = session ? await apiLogout(session.uid, session.sid) : false;
  const response = json({ ok: true, revoked });
  clearSessionCookie(response);
  return response;
}
