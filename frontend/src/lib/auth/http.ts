import { NextResponse } from "next/server";
import { REMEMBER_MAX_AGE_SECONDS, cookieSecure, sessionCookieName } from "@/lib/auth/config";

/** 인증 관련 응답 공통: 캐시 금지 + JSON. 오류 본문에는 이유를 길게 쓰지 않는다. */
export function json(body: Record<string, unknown>, status = 200): NextResponse {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export function setSessionCookie(response: NextResponse, token: string, maxAgeSeconds: number): void {
  response.cookies.set(sessionCookieName(), token, {
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: Math.min(Math.max(0, Math.floor(maxAgeSeconds)), REMEMBER_MAX_AGE_SECONDS),
  });
}

export function clearSessionCookie(response: NextResponse): void {
  response.cookies.set(sessionCookieName(), "", {
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}
