import { apiSignup } from "@/lib/auth/apiClient";
import { authConfigProblem, authEnabled } from "@/lib/auth/config";
import { endUserIp } from "@/lib/auth/endUserIp";
import { json } from "@/lib/auth/http";
import { isSameOriginRequest } from "@/lib/auth/origin";

export const dynamic = "force-dynamic";

const MAX_BODY_CHARS = 4096;

/**
 * 회원가입 신청(DEC-074). 같은 사이트 화면에서 온 JSON 요청만 받는다. **승인 대기 계정만** 만들어지고 로그인은 관리자 승인 뒤에 가능하다.
 * 입력 오류·아이디 중복·신청 마감·횟수 제한은 API가 준 사용자용 문구를 그대로 알린다(비밀번호는 어디에도 되돌려 주지 않는다).
 */
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
  const { username, displayName, password, website } = body;
  if (
    typeof username !== "string" || username.length < 1 || username.length > 64 ||
    typeof displayName !== "string" || displayName.length < 1 || displayName.length > 100 ||
    typeof password !== "string" || password.length < 1 || password.length > 1024 ||
    (website !== undefined && (typeof website !== "string" || website.length > 200))
  ) {
    return json({ ok: false, code: "BAD_REQUEST" }, 400);
  }
  const result = await apiSignup({ username, displayName, password, website: typeof website === "string" ? website : "" }, endUserIp(request.headers));
  if (result.kind === "ok") return json({ ok: true });
  if (result.kind === "rejected") return json({ ok: false, code: result.code, message: result.message }, result.status);
  return json({ ok: false, code: "SERVICE_UNAVAILABLE" }, 503);
}
