/**
 * API 로그인 실패 응답을 사용자에게 보일 종류로 나눈다(DEC-074 보완).
 *
 * 401은 **두 가지 뜻**이다: ① `INVALID_CREDENTIALS`(아이디·비밀번호가 틀림) ② `AUTH_REQUIRED`(웹과 API의 내부 토큰이 서로 다름 = 서버 설정 오류).
 * 둘을 같은 "비밀번호 오류"로 보이면 설정 오류를 사용자가 비밀번호 탓으로 오해한다(실제로 운영 첫 배포에서 발생). 그래서 **오류 코드가 INVALID_CREDENTIALS일 때만** 비밀번호 오류로 본다.
 */
export type LoginFailureKind = "invalid" | "pending" | "disabled" | "rate_limited" | "unavailable";

export function classifyLoginFailure(status: number, errorCode: unknown): LoginFailureKind {
  if (status === 401) return errorCode === "INVALID_CREDENTIALS" ? "invalid" : "unavailable";
  if (status === 403) {
    if (errorCode === "PENDING_APPROVAL") return "pending";
    if (errorCode === "ACCOUNT_DISABLED") return "disabled";
    return "unavailable";
  }
  if (status === 429) return "rate_limited";
  return "unavailable";
}

/**
 * 웹 → API 연결 점검 결과(`GET /auth/status`). API의 가벼운 내부 경로(`session-check`, 존재하지 않는 id)를 부른 응답으로 판별한다:
 * 200 = 정상(토큰 일치·회원 DB 연결), 401 = **내부 토큰 불일치**, 404 = 회원 DB 설정 없음(`PUBLIC_API_AUTH_DATABASE_URL`/토큰 미설정), 그 밖·실패 = 연결 불가.
 */
export type ApiProbeKind = "ok" | "token_mismatch" | "auth_not_configured" | "unreachable";

export function classifyApiProbe(status: number | null): ApiProbeKind {
  if (status === 200) return "ok";
  if (status === 401) return "token_mismatch";
  if (status === 404) return "auth_not_configured";
  return "unreachable";
}
