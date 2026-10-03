/**
 * 서버 시작 시 1회 실행(Next.js instrumentation). 무료 호스팅에서 웹 서버가 깨어날 때 API 서버도 같이
 * 깨우기 위해 `/api/v1/live`(DB를 쓰지 않는 경로)를 한 번 부른다 — 두 서버가 순서대로가 아니라 동시에 깨어나
 * 첫 방문자의 대기 시간이 줄어든다(DEC-063). 응답을 기다리지 않고, 실패해도 무시하며 개발 모드에서는 하지 않는다.
 */
export function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs" || process.env.NODE_ENV !== "production") return;
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "");
  if (!base) return;
  void fetch(`${base}/api/v1/live`, { signal: AbortSignal.timeout(90_000) }).catch(() => undefined);
}
