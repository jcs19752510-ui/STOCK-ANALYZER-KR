import { headers } from "next/headers";
import { pickClientIp } from "@/lib/clientIp";
import { readSession } from "@/lib/auth/current";

/**
 * 서버 컴포넌트가 Public API를 호출할 때 붙일 헤더(DEC-045, R1). 토큰·IP 헤더는 서버에서만 만들며 브라우저로 나가지 않는다.
 *
 * - `PUBLIC_API_INTERNAL_TOKEN`(공개 변수 아님, `NEXT_PUBLIC_` 접두어 금지)이 없으면 아무 헤더도 붙이지 않는다 →
 *   API는 기존처럼 TCP peer(프론트 서버 IP) 기준으로 센다.
 * - 토큰이 있고 `FRONTEND_TRUSTED_PROXY_HOPS`(신뢰 프록시 단수, 기본 0)가 1 이상이면 `X-Forwarded-For`에서 최종 사용자 IP를
 *   골라 `X-End-User-IP`로 전달한다. 0이면 IP는 보내지 않고 API가 내부 공용 버킷으로 처리한다.
 */
export async function serverApiHeaders(): Promise<Record<string, string>> {
  const token = process.env.PUBLIC_API_INTERNAL_TOKEN?.trim();
  if (!token) return {};
  const result: Record<string, string> = { "X-Internal-Token": token };
  const hops = Number.parseInt(process.env.FRONTEND_TRUSTED_PROXY_HOPS ?? "0", 10);
  if (hops >= 1) {
    const ip = pickClientIp((await headers()).get("x-forwarded-for"), hops);
    if (ip) result["X-End-User-IP"] = ip;
  }
  // 로그인한 회원 id(DEC-067): API가 회원별로 호출 한도를 센다. 로그인을 끈 환경(로컬)에서는 쿠키를 읽지 않고 헤더도 붙이지 않는다.
  const session = await readSession();
  if (session) result["X-Auth-User"] = session.uid;
  return result;
}
