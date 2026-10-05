import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { authEnabled, sessionCookieName, sessionSecret } from "@/lib/auth/config";
import { nowSeconds } from "@/lib/auth/http";
import { isFresh, verifySession, type SessionPayload } from "@/lib/auth/session";

/** 서버 컴포넌트에서 현재 로그인 회원(서명·만료 확인). 로그인을 끈 환경(로컬)에서는 항상 null이고 쿠키를 읽지 않는다. */
export async function readSession(): Promise<SessionPayload | null> {
  if (!authEnabled()) return null;
  const store = await cookies();
  return verifySession(store.get(sessionCookieName())?.value, sessionSecret(), nowSeconds());
}

/**
 * 회원 전용 서버 화면의 입구(홈·종목 상세·회원 목록). 프록시(`proxy.ts`)가 먼저 막지만, 프록시만 믿지 않고 여기서도 확인한다(이중 방어).
 * 로그인을 끈 환경이면 null을 돌려주고 그대로 진행한다. 로그인이 없으면 로그인 화면으로, 확인한 지 5분이 지났으면 갱신 화면으로 보낸다.
 */
export async function requireMember(nextPath: string): Promise<SessionPayload | null> {
  if (!authEnabled()) return null;
  const session = await readSession();
  const encoded = encodeURIComponent(nextPath);
  if (!session) redirect(`/login?next=${encoded}`);
  if (!isFresh(session, nowSeconds())) redirect(`/auth/renew?next=${encoded}`);
  return session;
}

/**
 * 관리자 전용 화면의 입구(DEC-074). 로그인 확인 + 쿠키가 관리자 권한이면 통과, 아니면 홈으로 보낸다. 쿠키의 권한 표시는 **화면 안내용**이고(최대 5분 늦게 반영),
 * 실제 데이터와 작업은 API가 매번 DB에서 관리자 권한을 확인해 막는다. 로그인을 끈 환경(로컬)에는 이 화면이 없다.
 */
export async function requireAdmin(nextPath: string): Promise<SessionPayload> {
  const session = await requireMember(nextPath);
  if (!session) notFound();
  if (session.rl !== "a") redirect("/");
  return session;
}
