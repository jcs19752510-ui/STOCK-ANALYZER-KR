/**
 * 목록 행의 하루짜리 미니 캔들(증권사 앱 관심종목 화면의 오른쪽 작은 봉). 당일 시가·고가·저가·종가로 그린다.
 * 장식 요소라 스크린리더에는 숨기고(`aria-hidden`), 같은 정보는 행의 종가·등락 텍스트로 이미 제공된다.
 */
interface MiniCandleProps {
  open: number;
  high: number;
  low: number;
  close: number;
}

const H = 36;
const W = 12;

export function MiniCandle({ open, high, low, close }: MiniCandleProps) {
  const range = high - low;
  if (!Number.isFinite(range) || range <= 0) {
    // 고가=저가(거래 변동 없음): 가운데 가로선 하나로 표시
    return (
      <svg className="mini-candle" viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
        <line x1={2} x2={W - 2} y1={H / 2} y2={H / 2} stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  const y = (v: number) => 2 + ((high - v) / range) * (H - 4);
  const bodyTop = y(Math.max(open, close));
  const bodyBottom = y(Math.min(open, close));
  const up = close >= open;
  return (
    <svg
      className={`mini-candle mini-candle--${up ? "up" : "down"}`}
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      aria-hidden="true"
    >
      <line x1={W / 2} x2={W / 2} y1={y(high)} y2={y(low)} stroke="currentColor" strokeWidth="1.4" />
      <rect
        x={2.5}
        y={bodyTop}
        width={W - 5}
        height={Math.max(1.5, bodyBottom - bodyTop)}
        fill="currentColor"
      />
    </svg>
  );
}
