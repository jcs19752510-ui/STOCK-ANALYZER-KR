/**
 * 시세 원값 공개 스위치(DEC-048 → DEC-050). 기본 **켜짐** — 종목 상세의 현재가·차트·일자별 시세와 목록의 시세
 * 요약을 보여준다. 법률 검토(REQ-022)가 끝나기 전 외부 배포 환경에서는 `NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED="false"`로
 * 끄면 가공 지표·실적·조건 체크만 노출한다.
 *
 * `NEXT_PUBLIC_*`는 **빌드 시점에** 번들에 인라인된다(값을 바꾸면 다시 빌드). 인라인되려면 아래처럼
 * `process.env.NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED`를 그대로 참조해야 한다. API 쪽
 * `PUBLIC_API_PRICE_EXPOSURE_ENABLED`와 같은 값으로 맞춘다.
 */
export const PRICE_EXPOSURE_ENABLED = process.env.NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED !== "false";
