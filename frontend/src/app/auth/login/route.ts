import { apiLogin } from "@/lib/auth/apiClient";
import { authConfigProblem, authEnabled, sessionSecret } from "@/lib/auth/config";
import { endUserIp } from "@/lib/auth/endUserIp";
import { json, nowSeconds, setSessionCookie } from "@/lib/auth/http";
import { isSameOriginRequest } from "@/lib/auth/origin";
import { safeNextPath } from "@/lib/auth/redirect";
import { newSession, remainingSeconds, signSession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

const MAX_BODY_CHARS = 4096;

/** 로그인(DEC-067). 같은 사이트 화면에서 온 JSON 요청만 받는다. 실패는 틀림·시도 많음·서버 문제와, 비밀번호가 맞은 경우에만 "승인 대기"·"사용 중지"(DEC-074)로 알린다. */
export async function POST(request: Request) {
  if (!authEnabled()) return json({ ok: false, code: "NOT_FOUND" }, 404);
  if (authConfigProblem()) return json({ ok: false, code: "MISCONFIGURED" }, 503);
  if (!isSameOriginRequest(request.headers)) return json({ ok: false, code: "FORBIDDEN" }, 403);
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
  const { username, password, remember } = body;
  if (
    typeof username !== "string" ||
    typeof password !== "string" ||
    username.length < 1 ||
    username.length > 64 ||
    password.length < 1 ||
    password.length > 1024 ||
    (remember !== undefined && typeof remember !== "boolean") // "로그인 상태 유지"는 참/거짓만 받는다
  ) {
    return json({ ok: false, code: "BAD_REQUEST" }, 400);
  }

  const result = await apiLogin(username, password, endUserIp(request.headers), remember === true);
  if (result.kind === "invalid") return json({ ok: false, code: "INVALID_CREDENTIALS" }, 401);
  if (result.kind === "pending") return json({ ok: false, code: "PENDING_APPROVAL" }, 403);
  if (result.kind === "disabled") return json({ ok: false, code: "ACCOUNT_DISABLED" }, 403);
  if (result.kind === "rate_limited") return json({ ok: false, code: "LOGIN_RATE_LIMITED" }, 429);
  if (result.kind !== "ok") return json({ ok: false, code: "SERVICE_UNAVAILABLE" }, 503);

  const now = nowSeconds();
  const session = newSession(result.user, now, { sessionId: result.sessionId, remember: remember === true, lifetimeSeconds: result.expiresInSeconds });
  const response = json({ ok: true, next: safeNextPath(body.next) });
  setSessionCookie(response, signSession(session, sessionSecret()), remainingSeconds(session, now));
  return response;
}
