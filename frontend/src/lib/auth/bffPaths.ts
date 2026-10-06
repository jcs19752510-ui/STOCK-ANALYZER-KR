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

// 실시간 스트림(`/api/v1/local/stocks/{code}/stream`)은 이 목록이 아니라 전용 경로(`local/stocks/[code]/stream/route.ts`)가 맡는다(SSE는 JSON 대행과 처리 방식이 달라서).
const LOCAL_ALLOWED: readonly RegExp[] = [
  /^\/api\/v1\/local\/status$/,
  /^\/api\/v1\/local\/realtime\/status$/, // 실시간 연결 상태(관리자 전용, DEC-084)
  /^\/api\/v1\/local\/market\/(quotes|status)$/, // 전 종목 준실시간 시세(관리자 전용, DEC-084)
  /^\/api\/v1\/local\/psearch\/(conditions|results)$/, // 증권사 조건검색 결과(관리자 전용, DEC-088)
  /^\/api\/v1\/local\/screen(\/pattern)?$/, // 장중 기준 재계산 스크리닝(관리자 전용, DEC-089). 쿼리는 기존 /screen과 같고 snapshot_id가 더해진다
  /^\/api\/v1\/local\/stocks\/[0-9A-Za-z]{6}\/(minutes|ticks|orderbook|investor)$/,
];

/** 투자자 수급은 관리자만(DEC-074) — 로컬 모드의 투자자 경로도 같은 규칙을 따른다. */
const LOCAL_ADMIN_ONLY: readonly RegExp[] = [
  /^\/api\/v1\/local\/stocks\/[0-9A-Za-z]{6}\/investor$/,
  /^\/api\/v1\/local\/realtime\/status$/,
  /^\/api\/v1\/local\/market\/(quotes|status)$/,
  /^\/api\/v1\/local\/psearch\/(conditions|results)$/,
  /^\/api\/v1\/local\/screen(\/pattern)?$/,
];

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
