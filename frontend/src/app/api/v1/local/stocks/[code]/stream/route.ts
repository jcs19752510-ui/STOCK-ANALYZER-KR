import { NextResponse } from "next/server";
import { localIntradayBffEnabled } from "@/lib/auth/bffPaths";
import { bffGate } from "@/lib/auth/bffGate";
import { json, setSessionCookie } from "@/lib/auth/http";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * 본인 전용 실시간 시세 스트림 대행(SSE, DEC-084). 로그인한 **관리자**만, **개인 로컬 모드 빌드**(`NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true`)에서만 열린다.
 * 운영 빌드는 그 값이 없어 항상 404다. 브라우저의 `EventSource`가 이 경로를 부르고, 웹 서버가 로그인·권한을 확인한 뒤 내부 토큰으로 API 스트림을 이어 준다.
 * 브라우저가 연결을 닫으면 API 연결도 같이 닫는다(증권사 구독이 헛되이 남지 않게). 응답 본문은 그대로 흘려보낸다(버퍼링 없음).
 */
export async function GET(request: Request, context: { params: Promise<{ code: string }> }) {
  const { code } = await context.params;
  const gate = await bffGate(request, (session) => {
    if (!localIntradayBffEnabled() || !/^[0-9A-Za-z]{6}$/.test(code)) {
      return json({ data: null, error: { code: "NOT_FOUND", message: "찾을 수 없습니다." } }, 404);
    }
    if (session.rl !== "a") {
      return json({ data: null, error: { code: "FORBIDDEN", message: "권한이 없습니다." } }, 403);
    }
    return null;
  });
  if (!gate.ok) return gate.response;

  const upstreamAbort = new AbortController();
  request.signal.addEventListener("abort", () => upstreamAbort.abort(), { once: true });
  let upstream: Response;
  try {
    upstream = await fetch(`${gate.base}/api/v1/local/stocks/${code}/stream`, {
      headers: { ...gate.upstreamHeaders, Accept: "text/event-stream" },
      cache: "no-store",
      signal: upstreamAbort.signal,
    });
  } catch {
    return json({ data: null, error: { code: "SERVICE_UNAVAILABLE", message: "일시적인 서비스 장애입니다." } }, 503);
  }
  if (!upstream.ok || !upstream.body) {
    // API가 거절한 이유(한도 초과·앱키 없음 등)를 JSON 그대로 전달한다
    const body = await upstream.text();
    return new NextResponse(body, { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  }
  const response = new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
  if (gate.refreshedCookie) setSessionCookie(response, gate.refreshedCookie.token, gate.refreshedCookie.maxAge);
  return response;
}
