import { cookies } from "next/headers";
import { apiAdminAction, apiSessionCheck, type AdminActionName, type Role } from "@/lib/auth/apiClient";
import { authConfigProblem, authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { clearSessionCookie, json, nowSeconds } from "@/lib/auth/http";
import { isSameOriginRequest } from "@/lib/auth/origin";
import { verifySession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

const MAX_BODY_CHARS = 4096;
const ACTIONS: readonly AdminActionName[] = ["create", "approve", "reject", "enable", "disable", "set_role", "rename", "reset_password", "revoke_sessions", "delete"];

/**
 * 관리자 화면의 작업(DEC-074): 회원 추가·승인·거절·활성/비활성·권한 변경·이름 수정·비밀번호 초기화·세션 취소·삭제.
 * 같은 사이트 화면에서 온 JSON 요청만 받고, 로그인 쿠키가 있어야 하며, **권한 판단은 API가 매번 DB에서** 한다(쿠키의 권한 표시는 믿지 않는다).
 * 관리자가 아니면 403. 쿠키가 무효(세션 취소 등)면 쿠키를 지우고 401.
 */
export async function POST(request: Request) {
  if (!authEnabled()) return json({ ok: false, code: "NOT_FOUND" }, 404);
  if (authConfigProblem()) return json({ ok: false, code: "MISCONFIGURED" }, 503);
  if (!isSameOriginRequest(request.headers)) return json({ ok: false, code: "FORBIDDEN" }, 403);
  const store = await cookies();
  const session = verifySession(store.get(sessionCookieName())?.value, sessionSecret(), nowSeconds());
  if (!session) return json({ ok: false, code: "AUTH_REQUIRED" }, 401);
  if (!(request.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    return json({ ok: false, code: "UNSUPPORTED_MEDIA_TYPE" }, 415);
  }
  const text = await request.text();
  if (text.length > MAX_BODY_CHARS) return json({ ok: false, code: "PAYLOAD_TOO_LARGE" }, 413);
  let body: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(text);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("shape");
    body = parsed as Record<string, unknown>;
  } catch {
    return json({ ok: false, code: "BAD_REQUEST" }, 400);
  }
  const { action, username, role, displayName, password } = body;
  if (
    typeof action !== "string" || !(ACTIONS as readonly string[]).includes(action) ||
    typeof username !== "string" || username.length < 1 || username.length > 64 ||
    (role !== undefined && role !== "user" && role !== "admin") ||
    (displayName !== undefined && (typeof displayName !== "string" || displayName.length > 100)) ||
    (password !== undefined && (typeof password !== "string" || password.length > 1024))
  ) {
    return json({ ok: false, code: "BAD_REQUEST" }, 400);
  }
  const result = await apiAdminAction(session.uid, session.sid, {
    action: action as AdminActionName,
    username,
    role: role as Role | undefined,
    displayName: displayName as string | undefined,
    password: password as string | undefined,
  });
  if (result.kind === "ok") {
    // 본인의 비밀번호를 초기화하면 서버가 이 기기 로그인도 끊으므로 쿠키를 지운다.
    const selfEnded = action === "reset_password" && username.trim().toLowerCase() === session.un;
    const response = json({ ok: true, result: result.result, ...(selfEnded ? { reauth: true } : {}) });
    if (selfEnded) clearSessionCookie(response);
    return response;
  }
  if (result.kind === "rejected") return json({ ok: false, code: result.code, message: result.message }, result.status);
  if (result.kind === "forbidden") {
    // 쿠키는 유효하지만 서버가 관리자로 보지 않는다 → 권한이 바뀌었거나 세션이 취소됨. 최신 상태를 확인해 안내한다.
    const check = await apiSessionCheck(session.uid, session.sid);
    if (check.kind === "inactive") {
      const response = json({ ok: false, code: "AUTH_REQUIRED" }, 401);
      clearSessionCookie(response);
      return response;
    }
    return json({ ok: false, code: "FORBIDDEN" }, 403);
  }
  return json({ ok: false, code: "SERVICE_UNAVAILABLE" }, 503);
}
