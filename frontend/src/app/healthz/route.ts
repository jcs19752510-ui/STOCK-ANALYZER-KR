export const dynamic = "force-dynamic";

/**
 * 호스팅(Render) 상태 검사 전용 경로. 로그인 여부·설정과 무관하게 항상 200을 돌려주고 DB·API를 부르지 않는다(잠든 API를 깨우지 않는다).
 * 상태 검사를 특정 화면(`/login` 등)에 걸면 그 화면이 없는 커밋·설정에서는 검사가 실패해 배포가 취소된다(2026-10-05 실제 사례: 로그인 화면이 없는 옛 커밋을 배포하다 `/login` 검사 시간 초과). 프록시(`proxy.ts`)도 이 경로는 건드리지 않는다.
 */
export function GET() {
  return new Response("ok", { status: 200, headers: { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" } });
}
