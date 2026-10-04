/**
 * 상태를 바꾸는 요청(로그인·로그아웃·세션 갱신)이 **우리 사이트 화면에서 보낸 것인지** 확인한다(CSRF 방어, DEC-067 설계서 §7).
 * 브라우저는 교차 사이트 POST에 `Origin`을 반드시 붙이고 값을 바꿀 수 없다. `Origin`의 호스트가 요청이 도착한 `Host`와 같을 때만 통과시키며,
 * `Origin`이 없으면 거부한다(fail closed). 쿠키의 SameSite=Lax와 함께 겹쳐서 막는다.
 */
export function isSameOriginRequest(headers: Pick<Headers, "get">): boolean {
  const origin = headers.get("origin");
  const host = (headers.get("x-forwarded-host") ?? headers.get("host") ?? "").split(",")[0].trim().toLowerCase();
  if (!origin || !host) return false;
  try {
    const parsed = new URL(origin);
    return parsed.host.toLowerCase() === host;
  } catch {
    return false;
  }
}
