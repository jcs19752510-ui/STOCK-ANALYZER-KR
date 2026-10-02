"use client";

import { useMemo, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import copy from "@/content/copy.ko.json";
import {
  aggregate,
  macd,
  paddedExtent,
  sma,
  type Candle,
  type Timeframe,
} from "@/lib/chartIndicators";

/**
 * 종목 일봉 차트(DEC-041, UNIT-21): 캔들 + 이동평균(5·10·20·60) + 최고·최저 표시 + 현재가 배지 +
 * 거래량(이동평균 5·20·60) + MACD.
 * 새 라이브러리 없이 SVG로 직접 그린다. 지표 계산은 `chartIndicators.ts`가 단일 출처.
 *
 * 접근성: 색(상승 빨강·하락 파랑)에만 의존하지 않도록 선택한 봉의 값을 텍스트로 읽을 수 있게 하고
 * (포인터·←→ 키), 같은 데이터는 "일자별 시세" 탭에 표로 제공된다. 이 차트는 일 단위 종가 기준이며
 * 실시간 시세가 아니다.
 */

const MA_PERIODS = [5, 10, 20, 60] as const;
const MA_COLORS: Record<number, string> = {
  5: "#15803d",
  10: "#be185d",
  20: "#b45309",
  60: "#6d28d9",
};
const VOL_MA_PERIODS = [5, 20, 60] as const;
const VISIBLE_BARS: Record<Timeframe, number> = { D: 60, W: 52, M: 24 };

const W = 720;
const PAD_L = 8;
const PAD_R = 64; // 오른쪽 가격축 라벨 영역
const PRICE_TOP = 8;
const PRICE_H = 280;
const VOL_TOP = PRICE_TOP + PRICE_H + 16;
const VOL_H = 80;
const MACD_TOP = VOL_TOP + VOL_H + 16;
const MACD_H = 100;
const AXIS_H = 22;
const H = MACD_TOP + MACD_H + AXIS_H;
const PLOT_W = W - PAD_L - PAD_R;

const UP = "#b91c1c"; // 상승(빨강) — 한국 시장 관례, 하락과는 색 외에 읽기 텍스트로도 구분
const DOWN = "#1d4ed8";

const nf = new Intl.NumberFormat("ko-KR");

function fmtPrice(v: number): string {
  return nf.format(Math.round(v));
}

function fmtVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

function shortDate(d: string): string {
  return `${d.slice(5, 7)}.${d.slice(8, 10)}`;
}

interface StockChartProps {
  candles: Candle[]; // 일봉, 오름차순
  stockName: string;
}

export function StockChart({ candles, stockName }: StockChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>("D");
  const [hover, setHover] = useState<number | null>(null);

  const model = useMemo(() => {
    const series = aggregate(candles, timeframe);
    const closes = series.map((c) => c.close);
    const mas = MA_PERIODS.map((p) => ({ period: p, values: sma(closes, p) }));
    const volMas = VOL_MA_PERIODS.map((p) => ({
      period: p,
      values: sma(
        series.map((c) => c.volume),
        p,
      ),
    }));
    const m = macd(closes);
    const n = Math.min(VISIBLE_BARS[timeframe], series.length);
    const start = series.length - n;
    return { series, mas, volMas, m, start, n };
  }, [candles, timeframe]);

  const { series, mas, volMas, m, start, n } = model;
  if (n === 0) return null;

  const view = series.slice(start);
  const step = PLOT_W / n;
  const bodyW = Math.max(2, Math.min(12, step * 0.6));
  const x = (i: number) => PAD_L + step * (i + 0.5);

  const [pLo, pHi] = paddedExtent([
    ...view.flatMap((c) => [c.high, c.low]),
    ...mas.flatMap((s) => s.values.slice(start)),
  ]);
  const py = (v: number) => PRICE_TOP + ((pHi - v) / (pHi - pLo)) * PRICE_H;

  // 구간 최고·최저(증권사 앱의 화살표 표기): 마지막 종가 대비 등락률을 함께 보여준다.
  let hiIdx = 0;
  let loIdx = 0;
  view.forEach((c, i) => {
    if (c.high > view[hiIdx].high) hiIdx = i;
    if (c.low < view[loIdx].low) loIdx = i;
  });
  const lastBar = view[n - 1];
  const lastPrev = start + n - 1 > 0 ? series[start + n - 2].close : null;
  const lastUp = lastPrev === null ? lastBar.close >= lastBar.open : lastBar.close >= lastPrev;
  const extremeLabel = (price: number, i: number) =>
    `${fmtPrice(price)} (${shortDate(view[i].trade_date)}), ${
      lastBar.close === 0 ? "" : `${price >= lastBar.close ? "+" : ""}${(((price - lastBar.close) / lastBar.close) * 100).toFixed(2)}%`
    }`;

  const maxVol = Math.max(
    1,
    ...view.map((c) => c.volume),
    ...volMas.flatMap((s) => s.values.slice(start).filter((v): v is number => v !== null)),
  );
  const vy = (v: number) => VOL_TOP + VOL_H - (v / maxVol) * VOL_H;

  const macdVals = [...m.macd, ...m.signal, ...m.histogram].slice(0).filter(
    (v): v is number => v !== null,
  );
  const visMacd = [
    ...m.macd.slice(start),
    ...m.signal.slice(start),
    ...m.histogram.slice(start),
  ];
  const [mLo, mHi] = paddedExtent(macdVals.length ? [...visMacd, 0] : [0]);
  const my = (v: number) => MACD_TOP + ((mHi - v) / (mHi - mLo)) * MACD_H;

  const line = (values: (number | null)[], yf: (v: number) => number) => {
    let d = "";
    let pen = false;
    values.slice(start).forEach((v, i) => {
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${yf(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  const priceTicks = [0, 1, 2, 3, 4].map((k) => pLo + ((pHi - pLo) * k) / 4);
  const xTickIdx = [0, Math.floor(n / 3), Math.floor((2 * n) / 3), n - 1].filter(
    (v, i, a) => a.indexOf(v) === i,
  );

  const selected = hover ?? n - 1;
  const sel = view[selected];
  const selAbs = start + selected;
  const prevClose = selAbs > 0 ? series[selAbs - 1].close : null;
  const selChange = prevClose === null ? null : sel.close - prevClose;

  const indexFromPointer = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    return Math.max(0, Math.min(n - 1, Math.floor((vx - PAD_L) / step)));
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowLeft") {
      setHover(Math.max(0, selected - 1));
      e.preventDefault();
    } else if (e.key === "ArrowRight") {
      setHover(Math.min(n - 1, selected + 1));
      e.preventDefault();
    } else if (e.key === "Escape") {
      setHover(null);
    }
  };

  return (
    <div className="stock-chart">
      <div className="stock-chart__toolbar">
        <div role="group" aria-label={copy.stockDetail.chartTimeframeLabel} className="chart-seg">
          {(["D", "W", "M"] as const).map((tf) => (
            <button
              key={tf}
              type="button"
              className="chart-seg__btn"
              aria-pressed={timeframe === tf}
              onClick={() => {
                setTimeframe(tf);
                setHover(null);
              }}
            >
              {tf === "D"
                ? copy.stockDetail.timeframeDay
                : tf === "W"
                  ? copy.stockDetail.timeframeWeek
                  : copy.stockDetail.timeframeMonth}
            </button>
          ))}
        </div>
        <ul className="chart-legend" aria-label={copy.stockDetail.chartLegendLabel}>
          {MA_PERIODS.map((p) => (
            <li key={p}>
              <span className="chart-legend__swatch" style={{ background: MA_COLORS[p] }} aria-hidden="true" />
              {p}
            </li>
          ))}
        </ul>
      </div>

      <p className="stock-chart__readout" aria-live="polite">
        <strong>{sel.trade_date}</strong>{" "}
        {copy.stockDetail.readoutOpen} {fmtPrice(sel.open)} · {copy.stockDetail.readoutHigh}{" "}
        {fmtPrice(sel.high)} · {copy.stockDetail.readoutLow} {fmtPrice(sel.low)} ·{" "}
        {copy.stockDetail.readoutClose} {fmtPrice(sel.close)}
        {selChange !== null && (
          <>
            {" "}
            (
            {selChange > 0
              ? copy.stockDetail.up
              : selChange < 0
                ? copy.stockDetail.down
                : copy.stockDetail.flat}{" "}
            {fmtPrice(Math.abs(selChange))})
          </>
        )}
        · {copy.stockDetail.readoutVolume} {nf.format(sel.volume)}
      </p>

      <div
        className="stock-chart__frame"
        tabIndex={0}
        role="group"
        aria-label={`${stockName} ${copy.stockDetail.chartAriaLabel}`}
        onKeyDown={onKey}
      >
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="stock-chart__svg"
          role="img"
          aria-label={`${stockName} ${copy.stockDetail.chartAriaLabel}`}
          onPointerMove={(e) => setHover(indexFromPointer(e))}
          onPointerLeave={() => setHover(null)}
          onPointerDown={(e) => setHover(indexFromPointer(e))}
        >
          {/* 가격 격자·축 */}
          {priceTicks.map((t) => (
            <g key={t}>
              <line x1={PAD_L} x2={W - PAD_R} y1={py(t)} y2={py(t)} stroke="#e5e7eb" strokeDasharray="3 3" />
              <text x={W - PAD_R + 6} y={py(t) + 4} fontSize="11" fill="#4b5563">
                {fmtPrice(t)}
              </text>
            </g>
          ))}

          {/* 캔들 */}
          {view.map((c, i) => {
            const up = c.close >= c.open;
            const color = up ? UP : DOWN;
            const top = py(Math.max(c.open, c.close));
            const bottom = py(Math.min(c.open, c.close));
            return (
              <g key={c.trade_date}>
                <line x1={x(i)} x2={x(i)} y1={py(c.high)} y2={py(c.low)} stroke={color} strokeWidth="1" />
                <rect
                  x={x(i) - bodyW / 2}
                  y={top}
                  width={bodyW}
                  height={Math.max(1, bottom - top)}
                  fill={up ? UP : DOWN}
                />
              </g>
            );
          })}

          {/* 이동평균선 */}
          {mas.map((s) => (
            <path key={s.period} d={line(s.values, py)} fill="none" stroke={MA_COLORS[s.period]} strokeWidth="1.4" />
          ))}

          {/* 구간 최고·최저 */}
          <text
            x={x(hiIdx)}
            y={Math.max(PRICE_TOP + 10, py(view[hiIdx].high) - 4)}
            fontSize="11"
            fontWeight="600"
            fill={UP}
            textAnchor={hiIdx > n / 2 ? "end" : "start"}
          >
            {hiIdx > n / 2 ? "" : "▼ "}
            {extremeLabel(view[hiIdx].high, hiIdx)}
            {hiIdx > n / 2 ? " ▼" : ""}
          </text>
          <text
            x={x(loIdx)}
            y={Math.min(PRICE_TOP + PRICE_H - 2, py(view[loIdx].low) + 13)}
            fontSize="11"
            fontWeight="600"
            fill={DOWN}
            textAnchor={loIdx > n / 2 ? "end" : "start"}
          >
            {loIdx > n / 2 ? "" : "▲ "}
            {extremeLabel(view[loIdx].low, loIdx)}
            {loIdx > n / 2 ? " ▲" : ""}
          </text>

          {/* 현재가 배지 */}
          <g aria-hidden="true">
            <line
              x1={PAD_L}
              x2={W - PAD_R}
              y1={py(lastBar.close)}
              y2={py(lastBar.close)}
              stroke={lastUp ? UP : DOWN}
              strokeOpacity="0.5"
              strokeDasharray="2 3"
            />
            <rect
              x={W - PAD_R + 2}
              y={py(lastBar.close) - 9}
              width={PAD_R - 4}
              height={18}
              rx={3}
              fill={lastUp ? UP : DOWN}
            />
            <text x={W - PAD_R + 6} y={py(lastBar.close) + 4} fontSize="11" fontWeight="700" fill="#ffffff">
              {fmtPrice(lastBar.close)}
            </text>
          </g>

          {/* 거래량 */}
          <text x={PAD_L} y={VOL_TOP - 4} fontSize="11" fill="#4b5563">
            {copy.stockDetail.volumePanel}
          </text>
          {view.map((c, i) => (
            <rect
              key={c.trade_date}
              x={x(i) - bodyW / 2}
              y={vy(c.volume)}
              width={bodyW}
              height={Math.max(0, VOL_TOP + VOL_H - vy(c.volume))}
              fill={c.close >= c.open ? UP : DOWN}
              opacity="0.7"
            />
          ))}
          {volMas.map((s) => (
            <path key={s.period} d={line(s.values, vy)} fill="none" stroke={MA_COLORS[s.period]} strokeWidth="1.2" />
          ))}
          <text x={W - PAD_R + 6} y={VOL_TOP + 10} fontSize="11" fill="#4b5563">
            {fmtVolume(maxVol)}
          </text>

          {/* MACD */}
          <text x={PAD_L} y={MACD_TOP - 4} fontSize="11" fill="#4b5563">
            MACD(12,26,9)
          </text>
          <line x1={PAD_L} x2={W - PAD_R} y1={my(0)} y2={my(0)} stroke="#9ca3af" />
          {m.histogram.slice(start).map((v, i) =>
            v === null ? null : (
              <rect
                key={i}
                x={x(i) - bodyW / 2}
                y={Math.min(my(v), my(0))}
                width={bodyW}
                height={Math.abs(my(v) - my(0))}
                fill={v >= 0 ? UP : DOWN}
                opacity="0.35"
              />
            ),
          )}
          <path d={line(m.macd, my)} fill="none" stroke="#b45309" strokeWidth="1.4" />
          <path d={line(m.signal, my)} fill="none" stroke="#6b7280" strokeWidth="1.4" />

          {/* X축 날짜 */}
          {xTickIdx.map((i) => (
            <text key={i} x={x(i)} y={H - 6} fontSize="11" fill="#4b5563" textAnchor="middle">
              {shortDate(view[i].trade_date)}
            </text>
          ))}

          {/* 선택선 */}
          <line
            x1={x(selected)}
            x2={x(selected)}
            y1={PRICE_TOP}
            y2={MACD_TOP + MACD_H}
            stroke="#111827"
            strokeOpacity="0.35"
            strokeDasharray="4 3"
          />
        </svg>
      </div>
      <p className="stock-chart__hint">{copy.stockDetail.chartHint}</p>
    </div>
  );
}
