/**
 * 패턴 스크리닝 기능 스위치(docs/pattern-screening/02-system-design.md §9, DEC-033).
 *
 * `NEXT_PUBLIC_PATTERN_SCREEN_ENABLED === "false"`이면 전환 링크를 렌더하지 않고 `/screener/pattern`은
 * 404(`notFound()`)다. 법률 검토(Q4) 전에 코드만 먼저 배포할 수 있게 하기 위한 장치다.
 *
 * `NEXT_PUBLIC_*` 값은 **빌드 시점에** 번들에 인라인된다(Next.js 환경변수 규칙) — 값을 바꾸려면 다시
 * 빌드해야 한다. 인라인되려면 아래처럼 `process.env.NEXT_PUBLIC_PATTERN_SCREEN_ENABLED`를 그대로
 * 참조해야 하므로 변수에 담아 동적으로 접근하지 않는다.
 */
export const PATTERN_SCREEN_ENABLED = process.env.NEXT_PUBLIC_PATTERN_SCREEN_ENABLED !== "false";
