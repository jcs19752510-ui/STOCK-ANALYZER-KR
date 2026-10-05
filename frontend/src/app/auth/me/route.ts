import { cookies } from "next/headers";
import { authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { json, nowSeconds } from "@/lib/auth/http";
import { verifySession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

/** 머리글의 회원 메뉴용: 쿠키만 확인해 이름을 돌려준다(API를 부르지 않는다). 로그인을 끈 환경은 404라 메뉴가 숨겨진다. */
export async function GET() {
  if (!authEnabled()) return json({ ok: false, code: "NOT_FOUND" }, 404);
  const store = await cookies();
  const session = verifySession(store.get(sessionCookieName())?.value, sessionSecret(), nowSeconds());
  if (!session) return json({ ok: false, code: "AUTH_REQUIRED" }, 401);
  return json({ ok: true, username: session.un, display_name: session.dn, role: session.rl === "a" ? "admin" : "user" });
}
