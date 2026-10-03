/**
 * 서버 렌더 호출에 실을 "최종 사용자 IP" 선택 로직(DEC-045, R1). 프레임워크 의존 없는 순수 함수라 단위 테스트한다.
 *
 * `X-Forwarded-For`는 클라이언트가 임의로 채울 수 있어, 신뢰하는 프록시가 몇 단인지(`trustedHops`)를 알 때만 쓴다.
 * 신뢰 프록시는 자기가 본 상대 주소를 목록 **오른쪽 끝**에 덧붙이므로, 오른쪽에서 `trustedHops`번째 값이 실제
 * 클라이언트 주소다(왼쪽 값은 스푸핑 가능해 절대 쓰지 않는다). 프록시 신뢰가 꺼져 있거나(0) 값이 모자라거나
 * IP 형식이 아니면 null — 이때 API는 내부 공용 버킷(넉넉한 한도)으로 처리한다(fail closed).
 */
const IPV4 = /^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$/;
const IPV6 = /^[0-9a-fA-F:]+(?:%[0-9A-Za-z]+)?$/;

export function isIpLiteral(value: string): boolean {
  if (IPV4.test(value)) return true;
  return value.includes(":") && value.length <= 45 && IPV6.test(value);
}

export function pickClientIp(forwardedFor: string | null, trustedHops: number): string | null {
  if (!forwardedFor || !Number.isInteger(trustedHops) || trustedHops < 1) return null;
  const parts = forwardedFor
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  if (parts.length < trustedHops) return null;
  const candidate = parts[parts.length - trustedHops];
  return isIpLiteral(candidate) ? candidate : null;
}
