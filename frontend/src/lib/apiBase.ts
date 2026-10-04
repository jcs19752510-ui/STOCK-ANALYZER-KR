/**
 * 브라우저가 API를 부를 때 쓰는 기준 주소(DEC-067). 로그인을 켠 운영에서는 브라우저가 API 서버가 아니라 **웹 서버 자신**(`same-origin`)을 부르고,
 * 웹 서버가 로그인 확인 뒤 API로 전달한다(`app/api/v1/[...path]/route.ts`). 값이 없으면 지금처럼 `NEXT_PUBLIC_API_BASE_URL`(API 주소)이다.
 *
 * `NEXT_PUBLIC_*`는 빌드 때 코드에 박힌다. 서버 컴포넌트가 API를 부를 때는 이 함수가 아니라 `NEXT_PUBLIC_API_BASE_URL`을 그대로 쓴다.
 */
export function browserApiBase(): string | undefined {
  const raw = process.env.NEXT_PUBLIC_BROWSER_API_BASE_URL?.trim();
  if (raw === "same-origin") return typeof window !== "undefined" ? window.location.origin : undefined;
  return raw || process.env.NEXT_PUBLIC_API_BASE_URL;
}
