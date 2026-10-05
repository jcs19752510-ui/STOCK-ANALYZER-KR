/**
 * 로그인(회원 인증) 설정 (DEC-067, 설계서 §2·§4). 운영(Render)에서만 켠다 — 로컬은 `AUTH_REQUIRED`를 설정하지 않아 지금처럼 로그인 없이 동작한다.
 *
 * 켜졌는데 설정이 약하면(비밀 값이 없거나 짧음) **조용히 허용하지 않고** 모든 요청을 503으로 막는다(`authConfigProblem`).
 * 이 값들은 모두 서버 전용 환경변수다(`NEXT_PUBLIC_` 접두어 금지 — 브라우저 코드에 들어간다).
 */
export const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60; // 절대 만료 8시간
export const REMEMBER_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // "로그인 상태 유지" 절대 만료 30일(DEC-070)
export const SESSION_FRESH_SECONDS = 5 * 60; // 5분이 지나면 API에 회원이 아직 활성인지 다시 확인
export const SECRET_MIN_LENGTH = 32;

type Env = Record<string, string | undefined>;

function truthy(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

export function authEnabled(env: Env = process.env): boolean {
  return truthy(env.AUTH_REQUIRED);
}

/** 로컬 시험(http)에서만 `AUTH_COOKIE_INSECURE=true`. 운영은 항상 Secure. */
export function cookieSecure(env: Env = process.env): boolean {
  return !truthy(env.AUTH_COOKIE_INSECURE);
}

/** `__Host-` 접두어는 Secure 쿠키에서만 쓸 수 있다(도메인 고정, 하위 도메인이 덮어쓰지 못함). */
export function sessionCookieName(env: Env = process.env): string {
  return cookieSecure(env) ? "__Host-session" : "session";
}

export function sessionSecret(env: Env = process.env): string {
  return (env.SESSION_SECRET ?? "").trim();
}

/** 설정이 안전하지 않으면 사용자에게 보일 수 있는 설명(값은 포함하지 않음), 괜찮으면 null. */
export function authConfigProblem(env: Env = process.env): string | null {
  if (!authEnabled(env)) return null;
  if (sessionSecret(env).length < SECRET_MIN_LENGTH) {
    return `SESSION_SECRET이 없거나 ${SECRET_MIN_LENGTH}자보다 짧습니다.`;
  }
  if ((env.PUBLIC_API_INTERNAL_TOKEN ?? "").trim().length < SECRET_MIN_LENGTH) {
    return `PUBLIC_API_INTERNAL_TOKEN이 없거나 ${SECRET_MIN_LENGTH}자보다 짧습니다.`;
  }
  if (!(env.NEXT_PUBLIC_API_BASE_URL ?? "").trim()) {
    return "NEXT_PUBLIC_API_BASE_URL이 설정되지 않았습니다.";
  }
  // 브라우저가 API를 직접 부르면 내부 토큰이 없어 막히고(화면이 깨지고), 반대로 직접 부르게 두면 보호가 약해진다 → 대행 경로를 쓰도록 빌드되어야 한다.
  if ((env.NEXT_PUBLIC_BROWSER_API_BASE_URL ?? "").trim() !== "same-origin") {
    return "NEXT_PUBLIC_BROWSER_API_BASE_URL=same-origin 으로 빌드되지 않았습니다.";
  }
  if ((env.NEXT_PUBLIC_AUTH_ENABLED ?? "").trim().toLowerCase() !== "true") {
    return "NEXT_PUBLIC_AUTH_ENABLED=true 로 빌드되지 않았습니다.";
  }
  return null;
}
