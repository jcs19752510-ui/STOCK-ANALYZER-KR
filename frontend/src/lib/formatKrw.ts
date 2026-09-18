/**
 * 04-ux-design.md §2-1 총 거래대금 억/조 단위 변환 로직: "total_trading_value_krw
 * (KRW 정수)를 1억 단위로 나눈 값을 '억원'으로, 1조 이상이면 정수부는 '조',
 * 나머지는 '억'으로 나눠 '12.3조원'처럼 조 단위까지 소수 1자리로 결합
 * 표시(예: 12,300,000,000,000 KRW → 12.3조원)".
 *
 * 1조 미만은 예시가 명시되어 있지 않으나, 설계 원문의 "1억 단위로 나눈 값을
 * '억원'으로" 표현을 그대로 적용해 정수 억원으로 표시한다(예: 53,000,000,000
 * KRW → "530억원") — 없는 값을 지어내지 않고 설계 문구를 그대로 연장 적용한
 * 해석이다(`unit-08-note.md` 참조).
 */
const EOK = 100_000_000; // 1억
const JO = 1_000_000_000_000; // 1조

export function formatTradingValueKrw(krw: number): string {
  if (krw <= 0) {
    return "0원";
  }
  if (krw < EOK) {
    return "1억원 미만";
  }
  if (krw < JO) {
    return `${Math.floor(krw / EOK)}억원`;
  }
  return `${(krw / JO).toFixed(1)}조원`;
}
