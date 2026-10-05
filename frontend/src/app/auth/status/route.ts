import { classifyApiProbe } from "@/lib/auth/loginFailure";
import { authConfigProblem, authEnabled } from "@/lib/auth/config";
import { json } from "@/lib/auth/http";

export const dynamic = "force-dynamic";

const PROBE_TIMEOUT_MS = 30_000; // 잠든 API가 깨어나는 시간을 기다린다

/**
 * 로그인 연결 점검(운영 설정 확인용). 로그인 없이 열 수 있고 **상태 이름만** 알려 준다(값·비밀·회원 정보 없음):
 * - `web`: 웹 쪽 설정이 안전한지(`ok` / `misconfigured` / `auth_off`)
 * - `api`: 웹→API 연결(`ok` / `token_mismatch` / `auth_not_configured` / `unreachable`)
 * 로그인이 이유 없이 실패하면 이 주소(`/auth/status`) 하나로 "토큰이 다른지, 회원 DB 설정이 없는지, API가 안 뜨는지"를 구분한다.
 */
export async function GET() {
  if (!authEnabled()) return json({ ok: false, web: "auth_off" }, 404);
  if (authConfigProblem()) return json({ ok: false, web: "misconfigured" }, 503);
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
  let status: number | null = null;
  try {
    const response = await fetch(`${base}/api/v1/internal/auth/session-check`, {
      method: "POST",
      headers: { "X-Internal-Token": (process.env.PUBLIC_API_INTERNAL_TOKEN ?? "").trim(), "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ user_id: "00000000-0000-4000-8000-000000000000", session_id: "00000000-0000-4000-8000-000000000000" }),
      cache: "no-store",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    status = response.status;
  } catch {
    status = null;
  }
  const api = classifyApiProbe(status);
  return json({ ok: api === "ok", web: "ok", api }, api === "ok" ? 200 : 503);
}
