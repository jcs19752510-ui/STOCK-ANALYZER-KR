/**
 * 시세 원값 공개 스위치(DEC-048, R3). 공공데이터포털 약관의 재배포 금지 조항에 대한 법률 검토(REQ-022)가
 * 끝나기 전에는 **기본 꺼짐**이다 — `NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED === "true"`일 때만 종목 상세의
 * 현재가·차트·일자별 시세와 목록의 시세 요약을 보여준다. 꺼져 있으면 가공 지표·실적·조건 체크만 노출한다.
 *
 * `NEXT_PUBLIC_*`는 **빌드 시점에** 번들에 인라인된다(값을 바꾸면 다시 빌드). 인라인되려면 아래처럼
 * `process.env.NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED`를 그대로 참조해야 한다. API 쪽 스위치
 * (`PUBLIC_API_PRICE_EXPOSURE_ENABLED`)와 **같은 값**으로 맞춘다(API가 꺼져 있으면 404라 어차피 비어 보인다).
 */
export const PRICE_EXPOSURE_ENABLED = process.env.NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED === "true";
