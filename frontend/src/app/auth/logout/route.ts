import { authEnabled } from "@/lib/auth/config";
import { clearSessionCookie, json } from "@/lib/auth/http";
import { isSameOriginRequest } from "@/lib/auth/origin";

export const dynamic = "force-dynamic";

/** 로그아웃: 쿠키를 지운다. 같은 사이트 화면에서 보낸 요청만 받는다(다른 사이트가 몰래 로그아웃시키는 것을 막는다). */
export async function POST(request: Request) {
  if (!authEnabled()) return json({ ok: false, code: "NOT_FOUND" }, 404);
  if (!isSameOriginRequest(request.headers)) return json({ ok: false, code: "FORBIDDEN" }, 403);
  const response = json({ ok: true });
  clearSessionCookie(response);
  return response;
}
