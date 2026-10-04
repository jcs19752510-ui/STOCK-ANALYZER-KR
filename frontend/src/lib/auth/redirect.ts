/**
 * 로그인 뒤 돌아갈 경로 검사(열린 리다이렉트 방지, DEC-067 설계서 §7). **같은 사이트 안의 경로만** 허용한다.
 * 절대 주소(`https://…`), 프로토콜 상대(`//…`), 역슬래시·제어 문자(브라우저가 정규화하며 슬래시로 바꿔 우회하는 수법),
 * 로그인·인증 경로 자체(되돌아가기 반복)는 모두 기본 경로로 바꾼다.
 */
const MAX_LENGTH = 512;

export function safeNextPath(raw: unknown, fallback = "/"): string {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > MAX_LENGTH) return fallback;
  if (!raw.startsWith("/") || raw.startsWith("//")) return fallback;
  if (/[\\\u0000-\u001f\u007f]/.test(raw)) return fallback;
  let parsed: URL;
  try {
    parsed = new URL(raw, "http://internal.invalid");
  } catch {
    return fallback;
  }
  if (parsed.origin !== "http://internal.invalid") return fallback;
  const path = parsed.pathname;
  if (path === "/login" || path.startsWith("/login/") || path === "/auth" || path.startsWith("/auth/")) {
    return fallback;
  }
  return `${path}${parsed.search}`;
}
