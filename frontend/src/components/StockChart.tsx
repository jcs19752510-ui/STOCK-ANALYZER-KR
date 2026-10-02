"use client";

import { useEffect, useMemo, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import copy from "@/content/copy.ko.json";
import {
  aggregate,
  macd,
  macdCrosses,
  niceTicks,
  paddedExtent,
  sma,
  volumeProfile,
  type Candle,
  type Timeframe,
} from "@/lib/chartIndicators";

/**
 * 종목 일봉 차트(DEC-041, DEC-051): 증권사 앱 "차트" 화면 구성을 따른다 — 가격(캔들·이동평균 5/10/20/60·
 * 매물대 7구간·최고/최저 표기·현재가 배지) · 거래량(이동평균 5/20/60/200) · MACD(12,26)+Signal(9)(교차 화살표).
 * 새 라이브러리 없이 SVG로 직접 그린다. 지표 계산은 `chartIndicators.ts`가 단일 출처.
 *
 * 접근성: 색(상승 빨강·하락 파랑)에만 의존하지 않도록 선택한 봉의 값을 텍스트로 읽을 수 있게 하고(포인터·←→ 키),
 * 같은 데이터는 "일자별 시세" 탭에 표로 제공된다. 일 단위 종가 기준이며 실시간 시세가 아니다.
 */

const MA_PERIODS = [5, 10, 20, 60] as const;
const VOL_MA_PERIODS = [5, 20, 60, 200] as const;
const MA_COLORS: Record<number, string> = {
  5: "#52b04a",
  10: "#d9534f",
  20: "#f5a623",
  60: "#8b3df5",
};
const VOL_MA_COLORS: Record<number, string> = {
  5: "#52b04a",
  20: "#d9534f",
  60: "#f5a623",
  200: "#8b3df5",
};
const MACD_COLOR = "#f28c1b";
const SIGNAL_COLOR = "#f6b042";
const VISIBLE_BARS: Record<Timeframe, number> = { D: 61, W: 52, M: 24 };
const PROFILE_BINS = 7;

// viewBox 단위 ≈ 360dp 폭 휴대폰 화면(참고 화면과 같은 비율).
const W = 360;
const PAD_R = 62; // 오른쪽 가격축·배지 영역
const PLOT_W = W - PAD_R;
const LEGEND_H = 24;
const PRICE_TOP = LEGEND_H;
const PRICE_H = 226;
const VOL_TOP = PRICE_TOP + PRICE_H;
const VOL_H = 70;
const MACD_TOP = VOL_TOP + VOL_H;
const MACD_H = 122;
const AXIS_H = 26;
const H = MACD_TOP + MACD_H + AXIS_H;

const UP = "#d9342b"; // 상승(빨강) — 한국 시장 관례. 색 외에 ▲▼·텍스트로도 구분한다
const DOWN = "#1a6fc9";
const GRID = "#e6e8eb";
const AXIS_TEXT = "#9aa0a8";

const nf = new Intl.NumberFormat("ko-KR");

function fmtPrice(v: number): string {
  return nf.format(Math.round(v));
}

/** 증권사 앱 표기: 1,000만 이상은 천 단위(K), 그 미만은 전체 숫자. */
function fmtVolume(v: number): string {
  return v >= 10_000_000 ? `${nf.format(Math.round(v / 1000))}K` : nf.format(Math.round(v));
}

/** 소수 둘째 자리까지, 끝의 0은 지우되 최소 한 자리는 남긴다(12.70→12.7, 12.00→12.0, 1.72). */
function fmtShare(v: number): string {
  const s = v.toFixed(2);
  return s.endsWith("0") ? v.toFixed(1) : s;
}

function shortDate(d: string): string {
  return `${d.slice(5, 7)}.${d.slice(8, 10)}`;
}

function yyMmDd(d: string): string {
  return `${d.slice(2, 4)}.${d.slice(5, 7)}.${d.slice(8, 10)}`;
}

interface StockChartProps {
  candles: Candle[]; // 일봉, 오름차순
  stockName: string;
}

interface Layers {
  ma: Record<number, boolean>;
  profile: boolean;
  volMa: boolean;
}

const DEFAULT_LAYERS: Layers = {
  ma: { 5: true, 10: true, 20: true, 60: true },
  profile: true,
  volMa: true,
};

export function StockChart({ candles, stockName }: StockChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>("D");
  const [hover, setHover] = useState<number | null>(null);
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [expanded]);

  const model = useMemo(() => {
    const series = aggregate(candles, timeframe);
    const closes = series.map((c) => c.close);
    const volumes = series.map((c) => c.volume);
    const mas = MA_PERIODS.map((p) => ({ period: p, values: sma(closes, p) }));
    const volMas = VOL_MA_PERIODS.map((p) => ({ period: p, values: sma(volumes, p) }));
    const m = macd(closes);
    const n = Math.min(VISIBLE_BARS[timeframe], series.length);
    const start = series.length - n;
    return { series, mas, volMas, m, start, n };
  }, [candles, timeframe]);

  const { series, mas, volMas, m, start, n } = model;
  if (n === 0) return null;

  const view = series.slice(start);
  const step = PLOT_W / n;
  const bodyW = Math.max(2, Math.min(10, step * 0.86));
  const x = (i: number) => step * (i + 0.5);

  const visibleMas = mas.filter((s) => layers.ma[s.period]);
  const [rawLo, rawHi] = paddedExtent(
    [
      ...view.flatMap((c) => [c.high, c.low]),
      ...visibleMas.flatMap((s) => s.values.slice(start)),
    ],
    0,
  );
  const span = rawHi - rawLo || 1;
  // 위쪽은 최고가 표기 글자, 아래쪽은 최저가 표기 글자가 들어갈 여백.
  const pHi = rawHi + span * 0.1;
  const pLo = rawLo - span * 0.07;
  const py = (v: number) => PRICE_TOP + 8 + ((pHi - v) / (pHi - pLo)) * (PRICE_H - 16);
  const priceTicks = niceTicks(pLo, pHi, 5);

  // 구간 최고·최저(증권사 앱의 화살표 표기): 마지막 종가 대비 등락률.
  let hiIdx = 0;
  let loIdx = 0;
  view.forEach((c, i) => {
    if (c.high > view[hiIdx].high) hiIdx = i;
    if (c.low < view[loIdx].low) loIdx = i;
  });
  const lastBar = view[n - 1];
  const lastAbs = start + n - 1;
  const lastPrev = lastAbs > 0 ? series[lastAbs - 1].close : null;
  const lastChange = lastPrev === null ? null : lastBar.close - lastPrev;
  const lastPct = lastPrev ? ((lastBar.close - lastPrev) / lastPrev) * 100 : null;
  const lastUp = lastChange === null ? lastBar.close >= lastBar.open : lastChange >= 0;
  const extremeText = (price: number, i: number) =>
    `${fmtPrice(price)}(${yyMmDd(view[i].trade_date)}), ${(
      ((price - lastBar.close) / (lastBar.close || 1)) *
      100
    ).toFixed(2)}%`;

  const profile = layers.profile ? volumeProfile(view, PROFILE_BINS) : [];
  const maxShare = Math.max(0, ...profile.map((b) => b.share));

  // 거래량 패널
  const volBase = VOL_TOP + VOL_H - 2;
  const volTop = VOL_TOP + 18;
  const visibleVolMas = layers.volMa
    ? volMas.filter((s) => s.values.slice(start).some((v) => v !== null))
    : [];
  const maxVol = Math.max(
    1,
    ...view.map((c) => c.volume),
    ...visibleVolMas.flatMap((s) =>
      s.values.slice(start).filter((v): v is number => v !== null),
    ),
  );
  const vy = (v: number) => volBase - (v / maxVol) * (volBase - volTop);
  const volTicks = niceTicks(0, maxVol, 2).filter((v) => v > 0);

  // MACD 패널
  const visMacd = [...m.macd.slice(start), ...m.signal.slice(start)];
  const finiteMacd = visMacd.filter((v): v is number => v !== null);
  const [mLo, mHi] = paddedExtent(finiteMacd.length ? [...finiteMacd, 0] : [0], 0.08);
  const macdTop = MACD_TOP + 22;
  const macdBottom = MACD_TOP + MACD_H - 8;
  const my = (v: number) => macdTop + ((mHi - v) / (mHi - mLo)) * (macdBottom - macdTop);
  const macdTicks = niceTicks(mLo, mHi, 3);
  const crosses = macdCrosses(m.macd.slice(start), m.signal.slice(start));
  const lastMacd = m.macd[start + n - 1];

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

  // X축: 20봉 간격 4개(참고 화면과 같은 간격), 오른쪽 끝이 마지막 봉.
  const xTickIdx = [3, 2, 1, 0]
    .map((k) => n - 1 - 20 * k)
    .filter((i) => i >= 0)
    .filter((v, i, a) => a.indexOf(v) === i);
  const clampX = (v: number) => Math.max(18, Math.min(PLOT_W - 18, v));

  const selected = hover ?? n - 1;
  const sel = view[selected];
  const selAbs = start + selected;
  const prevClose = selAbs > 0 ? series[selAbs - 1].close : null;
  const selChange = prevClose === null ? null : sel.close - prevClose;

  const indexFromPointer = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    return Math.max(0, Math.min(n - 1, Math.floor(vx / step)));
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

  const badgeColor = lastUp ? UP : DOWN;
  const badgeY = Math.max(PRICE_TOP + 14, Math.min(PRICE_TOP + PRICE_H - 14, py(lastBar.close)));
  const volBadgeY = Math.max(VOL_TOP + 26, Math.min(VOL_TOP + VOL_H - 10, vy(lastBar.volume)));
  const macdBadgeY =
    lastMacd === null || lastMacd === undefined
      ? null
      : Math.max(MACD_TOP + 30, Math.min(MACD_TOP + MACD_H - 10, my(lastMacd)));

  const hiRight = hiIdx > n / 2;
  const loRight = loIdx > n / 2;

  return (
    <div className={`stock-chart${expanded ? " stock-chart--expanded" : ""}`}>
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
          <button
            type="button"
            className="chart-seg__btn chart-seg__btn--disabled"
            disabled
            title={copy.stockDetail.minuteDisabled}
          >
            {copy.stockDetail.timeframeMinute}
            <span aria-hidden="true" className="chart-seg__caret" />
          </button>
          <button
            type="button"
            className="chart-seg__btn chart-seg__btn--disabled"
            disabled
            title={copy.stockDetail.tickDisabled}
          >
            {copy.stockDetail.timeframeTick}
            <span aria-hidden="true" className="chart-seg__caret" />
          </button>
        </div>
        <div className="chart-tools">
          <button
            type="button"
            className="chart-tools__btn"
            aria-label={copy.stockDetail.settingsLabel}
            aria-expanded={settingsOpen}
            aria-controls="chart-settings-panel"
            onClick={() => setSettingsOpen((v) => !v)}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Zm8 4.6v-2.2l-2-.6a6.6 6.6 0 0 0-.6-1.4l1-1.8-1.6-1.6-1.8 1a6.600 6.600 0 0 0-1.4-.6l-.6-2h-2.2l-.6 2c-.5.1-1 .3-1.400.6l-1.800-1-1.600 1.600 1 1.800c-.3.4-.5.900-.6 1.400l-2 .6v2.200l2 .6c.1.500.3 1 .6 1.400l-1 1.800 1.600 1.600 1.800-1c.4.300.9.500 1.400.6l.6 2h2.200l.6-2c.5-.1 1-.3 1.400-.6l1.800 1 1.600-1.600-1-1.800c.3-.4.500-.9.600-1.400l2-.6Z"
              />
            </svg>
          </button>
          <button
            type="button"
            className="chart-tools__btn"
            disabled
            aria-label={copy.stockDetail.drawDisabled}
            title={copy.stockDetail.drawDisabled}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                d="m14.500 6.500 3 3M4 20l1-4 10.500-10.500a2.100 2.100 0 0 1 3 3L8 19l-4 1Z"
              />
            </svg>
          </button>
        </div>
      </div>

      {settingsOpen && (
        <fieldset id="chart-settings-panel" className="chart-settings">
          <legend>{copy.stockDetail.settingsLabel}</legend>
          {MA_PERIODS.map((p) => (
            <label key={p} className="chart-settings__item">
              <input
                type="checkbox"
                checked={layers.ma[p]}
                onChange={(e) =>
                  setLayers((l) => ({ ...l, ma: { ...l.ma, [p]: e.target.checked } }))
                }
              />
              {copy.stockDetail.settingsMa.replace("{n}", String(p))}
            </label>
          ))}
          <label className="chart-settings__item">
            <input
              type="checkbox"
              checked={layers.profile}
              onChange={(e) => setLayers((l) => ({ ...l, profile: e.target.checked }))}
            />
            {copy.stockDetail.profileLabel}
          </label>
          <label className="chart-settings__item">
            <input
              type="checkbox"
              checked={layers.volMa}
              onChange={(e) => setLayers((l) => ({ ...l, volMa: e.target.checked }))}
            />
            {copy.stockDetail.settingsVolMa}
          </label>
        </fieldset>
      )}

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
          {/* 범례: 가격 이동평균 · 매물대 · 표시 봉 수 */}
          <g fontSize="11" fill="#1f2937">
            <text x={2} y={15}>
              {copy.stockDetail.legendPrice}
            </text>
            {MA_PERIODS.map((p, i) => (
              <g key={p} opacity={layers.ma[p] ? 1 : 0.35}>
                <circle cx={46 + i * 38} cy={11} r={5} fill={MA_COLORS[p]} />
                <text x={54 + i * 38} y={15}>
                  {p}
                </text>
              </g>
            ))}
            <g opacity={layers.profile ? 1 : 0.35}>
              <circle cx={206} cy={11} r={5} fill="#c3c8d0" />
              <text x={214} y={15}>
                {copy.stockDetail.profileLabel}({PROFILE_BINS})
              </text>
            </g>
            <rect
              x={W - 40}
              y={1}
              width={38}
              height={20}
              rx={2}
              fill="none"
              stroke="#d5d9df"
              aria-hidden="true"
            />
            <text x={W - 21} y={15} textAnchor="middle">
              {n}
            </text>
          </g>

          {/* 세로 격자(날짜 눈금) — 세 패널을 가로지른다 */}
          {xTickIdx.map((i) => (
            <line
              key={`vg-${i}`}
              x1={x(i)}
              x2={x(i)}
              y1={PRICE_TOP}
              y2={MACD_TOP + MACD_H}
              stroke={GRID}
              strokeWidth="0.8"
            />
          ))}

          {/* 가격 가로 격자·축 */}
          {priceTicks.map((t) => (
            <g key={`pt-${t}`}>
              <line
                x1={0}
                x2={PLOT_W}
                y1={py(t)}
                y2={py(t)}
                stroke={GRID}
                strokeDasharray="1.5 3"
              />
              <text x={PLOT_W + 8} y={py(t) + 4} fontSize="11" fill={AXIS_TEXT}>
                {fmtPrice(t)}
              </text>
            </g>
          ))}
          <line x1={PLOT_W} x2={PLOT_W} y1={PRICE_TOP} y2={MACD_TOP + MACD_H} stroke={GRID} />

          {/* 매물대(가격대별 거래량 비중) — 캔들 뒤 */}
          {profile.map((b, i) => {
            if (b.share <= 0 || maxShare <= 0) return null;
            const yTop = py(b.hi);
            const yBot = py(b.lo);
            const h = (yBot - yTop) * 0.82;
            const y = yTop + (yBot - yTop) * 0.09;
            const len = Math.max(h, (b.share / maxShare) * PLOT_W);
            const isMax = b.share === maxShare;
            const tier = isMax ? "#8d96a3" : b.share >= maxShare * 0.5 ? "#c2c8d1" : "#e3e6ea";
            return (
              <g key={`vp-${i}`} aria-hidden="true">
                <rect x={0} y={y} width={len} height={h} rx={h / 2} fill={tier} opacity={0.92} />
                <text
                  x={Math.max(len - 8, 34)}
                  y={y + h / 2 + 4}
                  fontSize="11"
                  textAnchor="end"
                  fill={isMax ? "#ffffff" : "#6b7280"}
                >
                  {fmtShare(b.share)}%
                </text>
              </g>
            );
          })}

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
                  fill={color}
                />
              </g>
            );
          })}

          {/* 이동평균선 */}
          {visibleMas.map((s) => (
            <path
              key={s.period}
              d={line(s.values, py)}
              fill="none"
              stroke={MA_COLORS[s.period]}
              strokeWidth="1.1"
            />
          ))}

          {/* 구간 최고·최저 표기 */}
          <text
            x={hiRight ? x(hiIdx) - 6 : x(hiIdx) + 2}
            y={py(view[hiIdx].high) + 4}
            fontSize="11.5"
            fill={UP}
            textAnchor={hiRight ? "end" : "start"}
          >
            {hiRight ? `${extremeText(view[hiIdx].high, hiIdx)} ←` : `→${extremeText(view[hiIdx].high, hiIdx)}`}
          </text>
          <text
            x={loRight ? x(loIdx) - 6 : x(loIdx) + 2}
            y={Math.min(PRICE_TOP + PRICE_H - 4, py(view[loIdx].low) + 13)}
            fontSize="11.5"
            fill={DOWN}
            textAnchor={loRight ? "end" : "start"}
          >
            {loRight ? `${extremeText(view[loIdx].low, loIdx)} ←` : `→${extremeText(view[loIdx].low, loIdx)}`}
          </text>

          {/* 현재가 배지(가격축 위) */}
          <g aria-hidden="true">
            <path
              d={`M${PLOT_W + 1},${badgeY} l5,-13 h${PAD_R - 7} a2,2 0 0 1 2,2 v22 a2,2 0 0 1 -2,2 h-${PAD_R - 7} Z`}
              fill={badgeColor}
            />
            <text x={PLOT_W + 9} y={badgeY - 1} fontSize="11" fontWeight="600" fill="#ffffff">
              {fmtPrice(lastBar.close)}
            </text>
            {lastPct !== null && (
              <text x={PLOT_W + 9} y={badgeY + 11} fontSize="11" fill="#ffffff">
                {Math.abs(lastPct).toFixed(2)}%
              </text>
            )}
          </g>

          {/* 거래량 패널 */}
          <line x1={0} x2={W} y1={VOL_TOP} y2={VOL_TOP} stroke={GRID} />
          <g fontSize="11" fill="#1f2937">
            <text x={2} y={VOL_TOP + 14}>
              {copy.stockDetail.volumePanel}
            </text>
            {VOL_MA_PERIODS.map((p, i) => (
              <g key={p} opacity={layers.volMa ? 1 : 0.35}>
                <circle cx={58 + i * 40} cy={VOL_TOP + 10} r={5} fill={VOL_MA_COLORS[p]} />
                <text x={66 + i * 40} y={VOL_TOP + 14}>
                  {p}
                </text>
              </g>
            ))}
          </g>
          {volTicks.map((t) => (
            <g key={`vt-${t}`}>
              <line
                x1={0}
                x2={PLOT_W}
                y1={vy(t)}
                y2={vy(t)}
                stroke={GRID}
                strokeDasharray="1.5 3"
              />
              <text x={PLOT_W + 8} y={vy(t) + 4} fontSize="11" fill={AXIS_TEXT}>
                {fmtVolume(t)}
              </text>
            </g>
          ))}
          {view.map((c, i) => (
            <rect
              key={c.trade_date}
              x={x(i) - bodyW / 2}
              y={vy(c.volume)}
              width={bodyW}
              height={Math.max(0, volBase - vy(c.volume))}
              fill={c.close >= c.open ? UP : DOWN}
            />
          ))}
          {visibleVolMas.map((s) => (
            <path
              key={s.period}
              d={line(s.values, vy)}
              fill="none"
              stroke={VOL_MA_COLORS[s.period]}
              strokeWidth="1"
            />
          ))}
          <g aria-hidden="true">
            <path
              d={`M${PLOT_W + 1},${volBadgeY} l5,-10 h${PAD_R - 7} a2,2 0 0 1 2,2 v16 a2,2 0 0 1 -2,2 h-${PAD_R - 7} Z`}
              fill="#5f6b7a"
            />
            <text x={PLOT_W + 9} y={volBadgeY + 4} fontSize="10.5" fill="#ffffff">
              {fmtVolume(lastBar.volume)}
            </text>
          </g>

          {/* MACD 패널 */}
          <line x1={0} x2={W} y1={MACD_TOP} y2={MACD_TOP} stroke={GRID} />
          <g fontSize="11" fill="#1f2937">
            <circle cx={9} cy={MACD_TOP + 10} r={5} fill={MACD_COLOR} />
            <text x={18} y={MACD_TOP + 14}>
              MACD(12,26)
            </text>
            <circle cx={104} cy={MACD_TOP + 10} r={5} fill={SIGNAL_COLOR} />
            <text x={113} y={MACD_TOP + 14}>
              Signal(9)
            </text>
          </g>
          {macdTicks.map((t) => (
            <text key={`mt-${t}`} x={PLOT_W + 8} y={my(t) + 4} fontSize="11" fill={AXIS_TEXT}>
              {nf.format(t)}
            </text>
          ))}
          <line x1={0} x2={PLOT_W} y1={my(0)} y2={my(0)} stroke="#6b7280" strokeWidth="1" />
          <text x={2} y={my(0) - 3} fontSize="10.5" fill="#6b7280">
            0.0
          </text>
          <path d={line(m.macd, my)} fill="none" stroke={MACD_COLOR} strokeWidth="1.2" />
          <path d={line(m.signal, my)} fill="none" stroke={SIGNAL_COLOR} strokeWidth="1.2" />
          {crosses.map((c) => {
            const v = m.macd[start + c.index] ?? 0;
            return c.kind === "golden" ? (
              <text
                key={`gc-${c.index}`}
                x={x(c.index)}
                y={my(v) + 14}
                fontSize="12"
                fontWeight="700"
                textAnchor="middle"
                fill={UP}
              >
                ↑
              </text>
            ) : (
              <text
                key={`dc-${c.index}`}
                x={x(c.index)}
                y={my(v) - 6}
                fontSize="12"
                fontWeight="700"
                textAnchor="middle"
                fill={DOWN}
              >
                ↓
              </text>
            );
          })}
          {macdBadgeY !== null && lastMacd !== null && lastMacd !== undefined && (
            <g aria-hidden="true">
              <path
                d={`M${PLOT_W + 1},${macdBadgeY} l5,-10 h${PAD_R - 7} a2,2 0 0 1 2,2 v16 a2,2 0 0 1 -2,2 h-${PAD_R - 7} Z`}
                fill={MACD_COLOR}
              />
              <text x={PLOT_W + 9} y={macdBadgeY + 4} fontSize="10.5" fill="#ffffff">
                {lastMacd.toFixed(2)}
              </text>
            </g>
          )}

          {/* X축 날짜 */}
          {xTickIdx.map((i) => (
            <text
              key={`xt-${i}`}
              x={clampX(x(i))}
              y={H - 8}
              fontSize="11.5"
              fill={AXIS_TEXT}
              textAnchor="middle"
            >
              {shortDate(view[i].trade_date)}
            </text>
          ))}

          {/* 선택선 */}
          {hover !== null && (
            <line
              x1={x(selected)}
              x2={x(selected)}
              y1={PRICE_TOP}
              y2={MACD_TOP + MACD_H}
              stroke="#111827"
              strokeOpacity="0.4"
              strokeDasharray="3 3"
            />
          )}
        </svg>
        <button
          type="button"
          className="chart-expand"
          aria-label={expanded ? copy.stockDetail.collapseLabel : copy.stockDetail.expandLabel}
          aria-pressed={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
            <path
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              d={expanded ? "M9 4v5H4M15 20v-5h5M4 9l6-6M20 15l-6 6" : "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"}
            />
          </svg>
        </button>
      </div>

      <p className="stock-chart__readout" aria-live="polite">
        <strong>{sel.trade_date}</strong> {copy.stockDetail.readoutOpen} {fmtPrice(sel.open)} ·{" "}
        {copy.stockDetail.readoutHigh} {fmtPrice(sel.high)} · {copy.stockDetail.readoutLow}{" "}
        {fmtPrice(sel.low)} · {copy.stockDetail.readoutClose} {fmtPrice(sel.close)}
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
      <p className="stock-chart__hint">{copy.stockDetail.chartHint}</p>
      <p className="stock-chart__hint">{copy.stockDetail.profileNote}</p>
    </div>
  );
}
