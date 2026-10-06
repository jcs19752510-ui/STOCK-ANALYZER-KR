import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiSessionCheck } from "@/lib/auth/apiClient";
import { authConfigProblem, authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { endUserIp } from "@/lib/auth/endUserIp";
import { clearSessionCookie, json, nowSeconds } from "@/lib/auth/http";
import { isFresh, refreshed, remainingSeconds, signSession, verifySession, type SessionPayload } from "@/lib/auth/session";

/**
 * 회원 대행 경로(BFF) 공통 관문(DEC-067): 로그인 확인 → (경로별 검사) → 5분이 지났으면 API로 활성 여부 재확인 → 내부 토큰 붙은 API 호출 정보를 만든다.
 * 조회용 JSON 대행(`/api/v1/[...path]`)과 실시간 스트림 대행(`/api/v1/local/stocks/{code}/stream`)이 같은 규칙을 쓰도록 한 곳에 둔다.
 * 브라우저의 쿠키·인증 헤더는 API로 넘기지 않는다.
 */
const ENVELOPE_AUTH_REQUIRED = { data: null, error: { code: "AUTH_REQUIRED", message: "로그인이 필요합니다." } };
const ENVELOPE_UNAVAILABLE = { data: null, error: { code: "SERVICE_UNAVAILABLE", message: "일시적인 서비스 장애입니다." } };

export interface BffGateOk {
  ok: true;
  session: SessionPayload;
  upstreamHeaders: Record<string, string>;
  base: string;
  refreshedCookie: { token: string; maxAge: number } | null;
}
export type BffGateResult = BffGateOk | { ok: false; response: NextResponse };

/** `check`는 로그인 확인 직후(회원 활성 재확인 전)에 경로별 규칙(허용 목록·관리자 전용 등)을 적용한다. 거절하려면 응답을 돌려준다. */
export async function bffGate(
  request: Request,
  check: (session: SessionPayload, url: URL) => NextResponse | null,
): Promise<BffGateResult> {
  if (!authEnabled()) return { ok: false, response: json({ data: null, error: { code: "NOT_FOUND", message: "찾을 수 없습니다." } }, 404) };
  if (authConfigProblem()) return { ok: false, response: json(ENVELOPE_UNAVAILABLE, 503) };

  const store = await cookies();
  const now = nowSeconds();
  const session = verifySession(store.get(sessionCookieName())?.value, sessionSecret(), now);
  if (!session) return { ok: false, response: json(ENVELOPE_AUTH_REQUIRED, 401) };

  const url = new URL(request.url);
  const rejected = check(session, url);
  if (rejected) return { ok: false, response: rejected };

  let refreshedCookie: BffGateOk["refreshedCookie"] = null;
  if (!isFresh(session, now)) {
    const result = await apiSessionCheck(session.uid, session.sid);
    if (result.kind === "unavailable") return { ok: false, response: json(ENVELOPE_UNAVAILABLE, 503) };
    if (result.kind === "inactive") {
      const response = json(ENVELOPE_AUTH_REQUIRED, 401);
      clearSessionCookie(response);
      return { ok: false, response };
    }
    const next = refreshed(
      { ...session, un: result.user.username, dn: result.user.displayName, rl: result.user.role === "admin" ? "a" : "u" },
      now,
    );
    refreshedCookie = { token: signSession(next, sessionSecret()), maxAge: remainingSeconds(next, now) };
  }

  const ip = endUserIp(request.headers);
  const upstreamHeaders: Record<string, string> = {
    "X-Internal-Token": (process.env.PUBLIC_API_INTERNAL_TOKEN ?? "").trim(),
    "X-Auth-User": session.uid,
    "X-Auth-Session": session.sid, // 관리자 전용 경로가 API에서 "유효한 세션 + 관리자"를 DB로 다시 확인한다(DEC-074)
  };
  if (ip) upstreamHeaders["X-End-User-IP"] = ip;
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
  return { ok: true, session, upstreamHeaders, base, refreshedCookie };
}
