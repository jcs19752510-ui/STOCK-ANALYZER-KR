const nf = new Intl.NumberFormat("ko-KR");

/**
 * 원 → 억 원(가장 가까운 정수로 반올림, 정확히 절반이면 0에서 먼 쪽), null은 "-"(0이 아님).
 * 반올림해서 0이 되는 음수는 "-0"이 아니라 "0".
 */
export function formatEok(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "-";
  const eok = Math.round(Math.abs(value) / 100_000_000) * Math.sign(value);
  return nf.format(eok === 0 ? 0 : eok);
}
