const KST_TIME_ZONE = "Asia/Seoul";

/** DEF-001(unit-04-test.md TC-018) 대응 — 유효하지 않은 입력의 안전한 폴백 문구. */
export const INVALID_DATE_FALLBACK_TEXT = "기준시각 확인 불가";

/**
 * ISO 8601 문자열을 "YYYY-MM-DD HH:MM"(KST)로 포맷한다. 입력 문자열에 이미
 * +09:00 오프셋이 있어야 한다는 서버 계약(03-system-design.md §4-1)을
 * 신뢰하지 않고, 항상 명시적으로 Asia/Seoul 타임존으로 재변환한다 — 렌더링
 * 환경(서버 SSR)의 로컬 타임존이 KST가 아닐 수 있기 때문이다.
 *
 * DEF-001 대응: 빈 문자열/형식이 깨진 값이 들어오면(스키마 드리프트, 직렬화
 * 버그 등) 예외를 던지지 않고 `INVALID_DATE_FALLBACK_TEXT`를 반환한다 — 이
 * 함수를 try/catch 없이 렌더 본문에서 직접 호출하는 컴포넌트가 크래시하지
 * 않도록 하기 위함.
 *
 * DEF-008 대응: `new Date(null)`/`new Date(0)`은 `Invalid Date`가 아니라
 * 1970-01-01(Unix epoch)이라는 "유효하지만 틀린" 날짜를 반환하므로, 위
 * `Number.isNaN` 검사만으로는 TS 타입 계약을 우회한 런타임 `null`/`0`
 * 입력을 걸러내지 못한다. `typeof` 가드를 Date 생성 이전에 두어, 문자열이
 * 아닌 값은 애초에 `new Date()`에 넘기지 않고 폴백을 반환한다.
 */
export function formatKstDateTime(iso: string): string {
  if (typeof iso !== "string") {
    return INVALID_DATE_FALLBACK_TEXT;
  }

  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return INVALID_DATE_FALLBACK_TEXT;
  }

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: KST_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);

  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}
