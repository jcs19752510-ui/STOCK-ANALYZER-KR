/**
 * 브라우저 주소가 내 PC·사설망인지(개인 로컬 모드 UI를 보일 수 있는 곳인지) 판단하는 순수 함수(DEC-052).
 * 공개 도메인(예: stock.example.com)이나 공인 IP에서는 false. API 서버도 `Host` 헤더·접속 주소로 한 번 더 막는다.
 */
const PRIVATE_HOST =
  /^(localhost|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|\[?::1\]?|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})$/i;

export function isPrivateHostname(hostname: string): boolean {
  return PRIVATE_HOST.test(hostname);
}
