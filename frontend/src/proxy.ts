import { NextResponse, type NextRequest } from "next/server";
import { authConfigProblem, authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { safeNextPath } from "@/lib/auth/redirect";
import { isFresh, verifySession } from "@/lib/auth/session";

/**
 * 회원 전용 접근 통제의 입구(DEC-067). 로그인을 켠 운영(`AUTH_REQUIRED=true`)에서만 동작하고, 꺼져 있으면(로컬) 아무것도 바꾸지 않는다.
 *
 * 쿠키 서명·만료만 확인하는 가벼운 검사다(API를 부르지 않는다 — 깨어나는 API를 기다리며 화면이 멈추는 것을 막는다).
 * 확인한 지 5분이 지난 쿠키는 화면 이동에 한해 `/auth/renew`(안내 화면이 있는 갱신 페이지)로 보낸다.
 * 이 검사가 전부가 아니다: 데이터를 주는 곳(서버 화면·`/api/v1/*` 대행 경로)이 각자 다시 확인한다.
 */
const SELF_CHECKING_PREFIXES = ["/auth/"]; // 각 핸들러/페이지가 스스로 쿠키를 확인한다(로그인 전에도 불러야 하므로)

function securityHeaders(response: NextResponse): NextResponse {
  response.headers.set("X-Robots-Tag", "noindex, nofollow");
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "same-origin");
  return response;
}

function unauthorized(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  if (pathname.startsWith("/api/") || pathname === "/admin/actions") {
    return securityHeaders(
      NextResponse.json(
        { data: null, error: { code: "AUTH_REQUIRED", message: "로그인이 필요합니다." } },
        { status: 401 },
      ),
    );
  }
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(`${pathname}${search}`)}`;
  return securityHeaders(NextResponse.redirect(url));
}

export function proxy(request: NextRequest): NextResponse {
  if (!authEnabled()) return NextResponse.next();
  if (authConfigProblem()) {
    // 설정이 약한 채로 열어 두지 않는다(fail closed). 이유는 값 없이 서버 로그에만 남긴다.
    console.error(`[auth] 설정 오류로 모든 요청을 차단합니다: ${authConfigProblem()}`);
    return securityHeaders(new NextResponse("서비스 설정 오류로 일시적으로 이용할 수 없습니다.", { status: 503 }));
  }

  const { pathname } = request.nextUrl;
  if (pathname === "/signup") {
    // 회원가입 신청 화면은 로그인 전 누구나 열 수 있다. 이미 로그인한 회원은 홈으로.
    const nowS = Math.floor(Date.now() / 1000);
    if (verifySession(request.cookies.get(sessionCookieName())?.value, sessionSecret(), nowS)) {
      const target = request.nextUrl.clone();
      target.pathname = "/";
      target.search = "";
      return securityHeaders(NextResponse.redirect(target));
    }
    return securityHeaders(NextResponse.next());
  }
  if (pathname === "/login") {
    // 이미 로그인한 회원이 로그인 화면을 열면 로그인 화면을 보여 주지 않고 바로 원래 가려던 곳으로 보낸다(깜빡임 없이).
    const nowS = Math.floor(Date.now() / 1000);
    if (verifySession(request.cookies.get(sessionCookieName())?.value, sessionSecret(), nowS)) {
      const target = request.nextUrl.clone();
      const next = safeNextPath(request.nextUrl.searchParams.get("next"));
      const parsed = new URL(next, request.nextUrl.origin);
      target.pathname = parsed.pathname;
      target.search = parsed.search;
      return securityHeaders(NextResponse.redirect(target));
    }
    return securityHeaders(NextResponse.next());
  }
  if (SELF_CHECKING_PREFIXES.some((p) => pathname.startsWith(p))) {
    return securityHeaders(NextResponse.next());
  }
  if (pathname.startsWith("/api/") || pathname === "/admin/actions") {
    // 대행 경로·관리 작업 경로가 직접 로그인·신선도를 확인한다(쿠키 갱신이 필요해서). 여기서는 쿠키가 아예 없는 요청만 걸러낸다.
    const has = request.cookies.get(sessionCookieName())?.value;
    return has ? securityHeaders(NextResponse.next()) : unauthorized(request);
  }

  const now = Math.floor(Date.now() / 1000);
  const session = verifySession(request.cookies.get(sessionCookieName())?.value, sessionSecret(), now);
  if (!session) return unauthorized(request);
  if (!isFresh(session, now)) {
    const url = request.nextUrl.clone();
    url.pathname = "/auth/renew";
    url.search = `?next=${encodeURIComponent(`${pathname}${request.nextUrl.search}`)}`;
    return securityHeaders(NextResponse.redirect(url));
  }
  return securityHeaders(NextResponse.next());
}

export const config = {
  // 정적 파일·아이콘·robots·상태 검사(/healthz)는 제외(로그인 화면도 이 파일들을 불러야 한다).
  matcher: ["/((?!_next/static|_next/image|icon.svg|favicon.ico|robots.txt|healthz$).*)"],
};
