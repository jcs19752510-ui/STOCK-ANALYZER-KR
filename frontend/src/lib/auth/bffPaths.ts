/**
 * 웹 서버가 회원 대신 API로 전달해도 되는 **조회(GET) 경로 허용 목록**(DEC-067). 목록에 없는 경로는 404.
 * 개인 로컬 모드(`/api/v1/local/*`), 헬스체크, 내부 로그인·관리 경로(`/api/v1/internal/auth|admin/members|admin/action`)는 의도적으로 뺐다 — 브라우저가 부를 이유가 없다.
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

export function isAllowedBffPath(pathname: string): boolean {
  return ALLOWED.some((re) => re.test(pathname));
}

/** 쿼리 문자열 길이 상한(비정상적으로 긴 요청을 API에 넘기지 않는다). */
export const MAX_QUERY_LENGTH = 2048;
