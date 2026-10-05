/**
 * 웹 서버가 회원 대신 API로 전달해도 되는 **조회(GET) 경로 허용 목록**(DEC-067). 목록에 없는 경로는 404.
 * 헬스체크, 내부 로그인·관리 경로(`/api/v1/internal/auth|admin/members|admin/action`)는 의도적으로 뺐다 — 브라우저가 부를 이유가 없다.
 * 개인 로컬 모드(`/api/v1/local/*`, DEC-052)는 **내 PC에서 `NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true`로 띄운 웹에서만** 열린다(DEC-075).
 * 운영 빌드는 그 값을 설정하지 않으므로 계속 404다. 로컬도 로그인을 켜면 브라우저가 API를 직접 부를 수 없어 이 대행 경로를 거친다.
 */
const ALLOWED: readonly RegExp[] = [
  /^\/api\/v1\/screen$/,
  /^\/api\/v1\/screen\/pattern$/,
  /^\/api\/v1\/stocks$/,
  /^\/api\/v1\/stocks\/quotes$/,
  /^\/api\/v1\/stocks\/[0-9A-Za-z]{6}\/(metrics|prices|earnings|pattern-check)$/,
  /^\/api\/v1\/market-summary$/,
  // 관리자 전용 투자자 수급(DEC-074): 경로는 열어 두되 API가 매 호출마다 DB에서 관리자 권한을 확인해 일반 사용자는 403.
  /^\/api\/v1\/internal\/admin\/stocks\/[0-9A-Za-z]{6}\/investor$/,
];

const LOCAL_ALLOWED: readonly RegExp[] = [
  /^\/api\/v1\/local\/status$/,
  /^\/api\/v1\/local\/stocks\/[0-9A-Za-z]{6}\/(minutes|ticks|orderbook|investor)$/,
];

/** 투자자 수급은 관리자만(DEC-074) — 로컬 모드의 투자자 경로도 같은 규칙을 따른다. */
const LOCAL_ADMIN_ONLY: readonly RegExp[] = [/^\/api\/v1\/local\/stocks\/[0-9A-Za-z]{6}\/investor$/];

type Env = Record<string, string | undefined>;

export function localIntradayBffEnabled(env: Env = process.env): boolean {
  return (env.NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED ?? "").trim().toLowerCase() === "true";
}

export function isAllowedBffPath(pathname: string, env: Env = process.env): boolean {
  if (ALLOWED.some((re) => re.test(pathname))) return true;
  return localIntradayBffEnabled(env) && LOCAL_ALLOWED.some((re) => re.test(pathname));
}

export function isAdminOnlyBffPath(pathname: string): boolean {
  return LOCAL_ADMIN_ONLY.some((re) => re.test(pathname));
}

/** 쿼리 문자열 길이 상한(비정상적으로 긴 요청을 API에 넘기지 않는다). */
export const MAX_QUERY_LENGTH = 2048;
