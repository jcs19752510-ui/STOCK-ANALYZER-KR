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
