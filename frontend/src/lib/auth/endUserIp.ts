import { pickClientIp } from "../clientIp.ts";

/**
 * 방문자 IP를 API에 알릴 때 쓰는 값(DEC-045와 같은 규칙). 신뢰하는 프록시 단수(`FRONTEND_TRUSTED_PROXY_HOPS`, 기본 0)를 알 때만
 * `X-Forwarded-For`의 오른쪽에서 N번째를 쓰고, 모르면 null(API가 내부 공용 버킷으로 처리).
 */
export function endUserIp(headers: Pick<Headers, "get">, env: Record<string, string | undefined> = process.env): string | null {
  const hops = Number.parseInt(env.FRONTEND_TRUSTED_PROXY_HOPS ?? "0", 10);
  return hops >= 1 ? pickClientIp(headers.get("x-forwarded-for"), hops) : null;
}
