"use client";

import { useEffect, useMemo, useState } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent } from "react";
import { LocalModeNotice } from "@/components/LocalModeNotice";
import copy from "@/content/copy.ko.json";
import { buildChartSummary, type SummaryGroup } from "@/lib/chartSummary";
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
import {
  MAX_DRAWINGS,
  addDrawing,
  describeDrawing,
  isValidPrice,
  priceFromY,
  removeDrawing,
  snapIndex,
  type DrawPoint,
} from "@/lib/chartDrawings";
import { useChartDrawings } from "@/lib/useChartDrawings";
import { useIntradayPoll } from "@/lib/useIntradayPoll";
import { setIntradayFlag } from "@/lib/viewBasis";
import type { IntradayMinutesData, IntradayTicksData } from "@/lib/types";

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
const VOL_H = 70;
const MACD_H = 122;
const AXIS_H = 26;

const UP = "#d9342b"; // 상승(빨강) — 한국 시장 관례. 색 외에 ▲▼·텍스트로도 구분한다
const DOWN = "#1a6fc9";
const DRAW_COLOR = "#0f766e"; // 사용자가 직접 그린 선(이동평균선 색과 겹치지 않게)
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
  /** 종목코드 — 개인 로컬 모드 분·틱 조회에 쓴다. */
  stockCode?: string;
  /** 개인 로컬 모드(DEC-052)가 켜져 있으면 분·틱 버튼이 동작한다. */
  localMode?: boolean;
}

type IntraSpec = { mode: "minute" | "tick"; n: number };
type PanelId = "volume" | "macd";
const MINUTE_OPTIONS = [1, 3, 5, 10, 15, 30, 60];
const TICK_OPTIONS = [1, 3, 5, 10, 30];

/** 최근 체결(최근이 앞)을 n틱씩 묶은 봉으로 바꾼다(오름차순). */
function ticksToCandles(
  data: IntradayTicksData,
  n: number,
  date: string,
): Candle[] {
  const asc = [...data.ticks].reverse();
  const out: Candle[] = [];
  for (let i = 0; i < asc.length; i += n) {
    const g = asc.slice(i, i + n);
    out.push({
      trade_date: date,
      time: g[0].time,
      open: g[0].price,
      high: Math.max(...g.map((t) => t.price)),
      low: Math.min(...g.map((t) => t.price)),
      close: g[g.length - 1].price,
      volume: g.reduce((a, t) => a + t.volume, 0),
    });
  }
  return out;
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

export function StockChart({ candles, stockName, stockCode, localMode = false }: StockChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>("D");
  const [hover, setHover] = useState<number | null>(null);
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [bubbleDismissed, setBubbleDismissed] = useState(false);
  const [intra, setIntra] = useState<IntraSpec | null>(null);
  const [menu, setMenu] = useState<"minute" | "tick" | null>(null);
  // 거래량·MACD 패널 닫기(⊠)와 순서 바꾸기(≡). 닫은 패널은 설정(⚙)에서 다시 켠다.
  const [panelOrder, setPanelOrder] = useState<PanelId[]>(["volume", "macd"]);
  const [panelOn, setPanelOn] = useState<Record<PanelId, boolean>>({ volume: true, macd: true });
  // 개인 로컬 모드가 꺼진 상태에서 분·틱을 눌렀을 때 이유를 보여 주는 안내(눌러도 무반응으로 보이지 않게).
  const [unavailableNotice, setUnavailableNotice] = useState<"minute" | "tick" | null>(null);
  // 그리기 도구(✎, DEC-059): 일봉에서 추세선·수평선을 그린다. 선은 (거래일, 가격)으로 이 브라우저에만 저장한다.
  const [drawOpen, setDrawOpen] = useState(false);
  const [drawTool, setDrawTool] = useState<"trend" | "hline" | null>(null);
  const [pendingPoint, setPendingPoint] = useState<DrawPoint | null>(null);
  const [selectedDrawing, setSelectedDrawing] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [hlineInput, setHlineInput] = useState("");
  const [drawMessage, setDrawMessage] = useState("");
  const { drawings, update: updateDrawings } = useChartDrawings(stockCode);
  const intraPath =
    localMode && intra && stockCode
      ? intra.mode === "minute"
        ? `/api/v1/local/stocks/${encodeURIComponent(stockCode)}/minutes?interval=${intra.n}`
        : `/api/v1/local/stocks/${encodeURIComponent(stockCode)}/ticks?limit=300`
      : null;
  const poll = useIntradayPoll<IntradayMinutesData | IntradayTicksData>(
    intraPath,
    intra?.mode === "tick" ? 5000 : 10000,
  );
  const intradayOn = localMode && intra !== null;
  useEffect(() => {
    setIntradayFlag("chart", intradayOn);
    return () => setIntradayFlag("chart", false);
  }, [intradayOn]);
  const intraCandles = useMemo<Candle[] | null>(() => {
    if (!intra || !poll.data) return null;
    if (intra.mode === "minute") {
      const d = poll.data as IntradayMinutesData;
      return d.bars.map((b) => ({ ...b, trade_date: d.date }));
    }
    const today = new Date().toISOString().slice(0, 10);
    const t = poll.data as IntradayTicksData;
    return t.ticks.length > 0 ? ticksToCandles(t, intra.n, today) : [];
  }, [intra, poll.data]);

  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [expanded]);

  // 분·틱 메뉴와 차트 요약: Esc 로 닫고 포커스를 연 버튼으로 돌려준다. 메뉴는 바깥을 누르면 닫힌다(검수 QA-05).
  useEffect(() => {
    if (menu === null && !summaryOpen) return;
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (menu !== null) {
        document.querySelector<HTMLElement>('.chart-seg__btn[aria-expanded="true"]')?.focus();
        setMenu(null);
      } else {
        document.querySelector<HTMLElement>('[aria-controls="chart-summary-panel"]')?.focus();
        setSummaryOpen(false);
      }
    };
    const onPointerDown = (e: globalThis.PointerEvent) => {
      if (menu !== null && e.target instanceof Element && !e.target.closest(".chart-seg__wrap")) setMenu(null);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menu, summaryOpen]);

  const model = useMemo(() => {
    // 분·틱을 골랐으면 일봉으로 대체하지 않는다(불러오는 중에는 빈 차트 + 상태 문구).
    const series = intra ? (intraCandles ?? []) : aggregate(candles, timeframe);
    const closes = series.map((c) => c.close);
    const volumes = series.map((c) => c.volume);
    const mas = MA_PERIODS.map((p) => ({ period: p, values: sma(closes, p) }));
    const volMas = VOL_MA_PERIODS.map((p) => ({ period: p, values: sma(volumes, p) }));
    const m = macd(closes);
    const n = Math.min(VISIBLE_BARS[intra ? "D" : timeframe], series.length);
    const start = series.length - n;
    return { series, mas, volMas, m, start, n };
  }, [candles, timeframe, intra, intraCandles]);

  const { series, mas, volMas, m, start, n } = model;
  const summaryFacts = useMemo(
    () =>
      summaryOpen
        ? buildChartSummary(
            series,
            copy.stockDetail.summary,
            intra ? "봉" : timeframe === "D" ? "일" : timeframe === "W" ? "주" : "개월",
          )
        : [],
    [summaryOpen, series, timeframe, intra],
  );
  // 그리기는 일봉에서만 가능하다(점을 거래일로 저장하므로).
  const drawable = !intra && timeframe === "D";
  const activeTool = drawable ? drawTool : null;
  const commitDrawing = (draft: Parameters<typeof addDrawing>[1]) => {
    let result = "invalid";
    updateDrawings((list) => {
      const r = addDrawing(list, draft);
      result = r.result;
      return r.list;
    });
    setDrawMessage(
      result === "added"
        ? copy.stockDetail.drawAdded
        : result === "full"
          ? copy.stockDetail.drawFull.replace("{max}", String(MAX_DRAWINGS))
          : copy.stockDetail.drawInvalid,
    );
  };
  useEffect(() => {
    if (!drawTool) return;
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setDrawTool(null);
      setPendingPoint(null);
      setDrawMessage(copy.stockDetail.drawCanceled);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawTool]);

  const header = (
    <>
      <div className="stock-chart__toolbar">
        <div role="group" aria-label={copy.stockDetail.chartTimeframeLabel} className="chart-seg">
          {(["D", "W", "M"] as const).map((tf) => (
            <button
              key={tf}
              type="button"
              className="chart-seg__btn"
              aria-pressed={!intra && timeframe === tf}
              onClick={() => {
                setTimeframe(tf);
                setIntra(null);
                setMenu(null);
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
          {(["minute", "tick"] as const).map((mode) => {
            const label = mode === "minute" ? copy.stockDetail.timeframeMinute : copy.stockDetail.timeframeTick;
            const opts = mode === "minute" ? MINUTE_OPTIONS : TICK_OPTIONS;
            const active = intra?.mode === mode;
            if (!localMode) {
              return (
                <button
                  key={mode}
                  type="button"
                  className="chart-seg__btn chart-seg__btn--disabled"
                  aria-disabled="true"
                  aria-controls="chart-intraday-notice"
                  aria-expanded={unavailableNotice === mode}
                  title={mode === "minute" ? copy.stockDetail.minuteDisabled : copy.stockDetail.tickDisabled}
                  onClick={() => setUnavailableNotice((v) => (v === mode ? null : mode))}
                >
                  {label}
                  <span aria-hidden="true" className="chart-seg__caret" />
                </button>
              );
            }
            return (
              <span key={mode} className="chart-seg__wrap">
                <button
                  type="button"
                  className="chart-seg__btn"
                  aria-pressed={active}
                  aria-haspopup="menu"
                  aria-expanded={menu === mode}
                  aria-label={mode === "minute" ? copy.stockDetail.minuteMenuLabel : copy.stockDetail.tickMenuLabel}
                  onClick={() => setMenu((m) => (m === mode ? null : mode))}
                >
                  {active && intra ? `${intra.n}${label}` : label}
                  <span aria-hidden="true" className="chart-seg__caret" />
                </button>
                {menu === mode && (
                  <ul className="chart-seg__menu" role="menu">
                    {opts.map((n) => (
                      <li key={n} role="none">
                        <button
                          type="button"
                          role="menuitem"
                          aria-current={active && intra?.n === n ? "true" : undefined}
                          onClick={() => {
                            setIntra({ mode, n });
                            setMenu(null);
                            setHover(null);
                          }}
                        >
                          {(mode === "minute" ? copy.stockDetail.minuteOption : copy.stockDetail.tickOption).replace(
                            "{n}",
                            String(n),
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </span>
            );
          })}
        </div>
        <div className="chart-tools">
          <button
            type="button"
            className="chart-tools__btn chart-tools__btn--summary"
            aria-label={copy.stockDetail.summaryButton}
            aria-expanded={summaryOpen}
            aria-controls="chart-summary-panel"
            onClick={() => {
              setSummaryOpen((v) => !v);
              setBubbleDismissed(true);
            }}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path
                fill="currentColor"
                d="M12 2.500c.5 4.600 2.400 6.500 7 7-4.600.5-6.500 2.400-7 7-.5-4.600-2.400-6.500-7-7 4.600-.5 6.500-2.400 7-7Zm6.500 11c.3 2.300 1.200 3.200 3.500 3.500-2.300.3-3.200 1.200-3.500 3.500-.3-2.300-1.200-3.200-3.500-3.500 2.300-.3 3.200-1.200 3.500-3.500Z"
              />
            </svg>
          </button>
          {!bubbleDismissed && !summaryOpen && (
            <span className="chart-bubble" role="note">
              {copy.stockDetail.summaryBubble}
            </span>
          )}
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
            aria-controls="chart-draw-panel"
            aria-expanded={drawOpen}
            aria-label={drawOpen ? copy.stockDetail.drawToolClose : copy.stockDetail.drawToolOpen}
            title={drawOpen ? copy.stockDetail.drawToolClose : copy.stockDetail.drawToolOpen}
            onClick={() => {
              setDrawOpen((v) => !v);
              setDrawTool(null);
              setPendingPoint(null);
              setConfirmClear(false);
            }}
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

      {drawOpen && (
        <section id="chart-draw-panel" className="chart-draw" aria-label={copy.stockDetail.drawPanelTitle}>
          {!drawable ? (
            <p className="chart-draw__note">{copy.stockDetail.drawOnlyDaily}</p>
          ) : (
            <>
              <div className="chart-draw__tools" role="group" aria-label={copy.stockDetail.drawPanelTitle}>
                {(["trend", "hline"] as const).map((tool) => (
                  <button
                    key={tool}
                    type="button"
                    className="chart-draw__btn"
                    aria-pressed={drawTool === tool}
                    onClick={() => {
                      setDrawTool((t) => (t === tool ? null : tool));
                      setPendingPoint(null);
                      setConfirmClear(false);
                      setDrawMessage("");
                    }}
                  >
                    {tool === "trend" ? copy.stockDetail.drawTrend : copy.stockDetail.drawHline}
                  </button>
                ))}
              </div>
              {drawTool && (
                <p className="chart-draw__hint" role="status">
                  {drawTool === "hline"
                    ? copy.stockDetail.drawHintHline
                    : pendingPoint
                      ? copy.stockDetail.drawHintTrendEnd
                      : copy.stockDetail.drawHintTrendStart}
                </p>
              )}
              <form
                className="chart-draw__row"
                onSubmit={(e) => {
                  e.preventDefault();
                  const price = Number(hlineInput);
                  if (!isValidPrice(price)) {
                    setDrawMessage(copy.stockDetail.drawInvalid);
                    return;
                  }
                  commitDrawing({ kind: "hline", price });
                  setHlineInput("");
                }}
              >
                <label htmlFor="chart-hline-input">{copy.stockDetail.drawHlineInputLabel}</label>
                <input
                  id="chart-hline-input"
                  type="number"
                  inputMode="decimal"
                  value={hlineInput}
                  onChange={(e) => setHlineInput(e.target.value)}
                />
                <button type="submit" className="chart-draw__btn">
                  {copy.stockDetail.drawAdd}
                </button>
              </form>
              <p className="chart-draw__title">{copy.stockDetail.drawListTitle}</p>
              {drawings.length === 0 ? (
                <p className="chart-draw__note">{copy.stockDetail.drawListEmpty}</p>
              ) : (
                <ul className="chart-draw__list">
                  {drawings.map((d) => (
                    <li key={d.id} className={selectedDrawing === d.id ? "chart-draw__item--selected" : undefined}>
                      <span>{describeDrawing(d)}</span>
                      <button
                        type="button"
                        className="chart-draw__btn"
                        aria-label={`${describeDrawing(d)} ${copy.stockDetail.drawRemove}`}
                        onClick={() => {
                          updateDrawings((list) => removeDrawing(list, d.id));
                          setSelectedDrawing(null);
                          setDrawMessage(copy.stockDetail.drawRemoved);
                        }}
                      >
                        {copy.stockDetail.drawRemove}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {drawings.length > 0 && (
                <button
                  type="button"
                  className={`chart-draw__btn${confirmClear ? " chart-draw__btn--danger" : ""}`}
                  onClick={() => {
                    if (!confirmClear) {
                      setConfirmClear(true);
                      return;
                    }
                    updateDrawings(() => []);
                    setConfirmClear(false);
                    setSelectedDrawing(null);
                    setDrawMessage(copy.stockDetail.drawCleared);
                  }}
                >
                  {confirmClear ? copy.stockDetail.drawClearConfirm : copy.stockDetail.drawClearAll}
                </button>
              )}
            </>
          )}
          <p className="chart-draw__note">{copy.stockDetail.drawStorageNote}</p>
          <p className="sr-only" role="status">
            {drawMessage}
          </p>
          {drawMessage && (
            <p className="chart-draw__note" aria-hidden="true">
              {drawMessage}
            </p>
          )}
        </section>
      )}

      {!localMode && unavailableNotice && (
        <p id="chart-intraday-notice" className="stock-chart__status stock-chart__notice" role="status">
          {copy.stockDetail.intradayUnavailable}
        </p>
      )}

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
          {(["volume", "macd"] as const).map((id) => (
            <label key={id} className="chart-settings__item">
              <input
                type="checkbox"
                checked={panelOn[id]}
                onChange={(e) => setPanelOn((o) => ({ ...o, [id]: e.target.checked }))}
              />
              {id === "volume" ? copy.stockDetail.panelVolume : copy.stockDetail.panelMacd}
            </label>
          ))}
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

      {summaryOpen && (
        <section
          id="chart-summary-panel"
          className="chart-summary"
          aria-label={copy.stockDetail.summaryTitle}
        >
          <div className="chart-summary__head">
            <h2 className="chart-summary__title">{copy.stockDetail.summaryTitle}</h2>
            <button
              type="button"
              className="chart-summary__close"
              aria-label={copy.stockDetail.summaryClose}
              onClick={() => setSummaryOpen(false)}
            >
              ×
            </button>
          </div>
          <p className="chart-summary__basis">
            {copy.stockDetail.summaryBasis
              .replace(
                "{unit}",
                intra
                  ? `${intra.n}${intra.mode === "minute" ? "분" : "틱"}`
                  : timeframe === "D"
                    ? "일"
                    : timeframe === "W"
                      ? "주"
                      : "월",
              )
              .replace(
                "{date}",
                series.length > 0
                  ? (series[series.length - 1].time ?? series[series.length - 1].trade_date)
                  : "-",
              )}
          </p>
          {summaryFacts.length === 0 ? (
            <p>{copy.stockDetail.summaryEmpty}</p>
          ) : (
            (["ma", "momentum", "range", "volume", "profile"] as SummaryGroup[]).map((g) => {
              const items = summaryFacts.filter((f) => f.group === g);
              if (items.length === 0) return null;
              return (
                <div key={g} className="chart-summary__group">
                  <h3 className="chart-summary__group-title">{copy.stockDetail.summaryGroups[g]}</h3>
                  <ul>
                    {items.map((f) => (
                      <li key={f.id}>{f.text}</li>
                    ))}
                  </ul>
                </div>
              );
            })
          )}
          <p className="chart-summary__notice">{copy.stockDetail.summaryNotice}</p>
        </section>
      )}
      {intra && (
        <>
          <LocalModeNotice />
          {poll.error && poll.data && (
            <p className="stock-chart__status" role="status">
              {copy.stockDetail.intradayStale} {poll.error.message}
            </p>
          )}
        </>
      )}
    </>
  );

  if (n === 0) {
    if (!intra) return null;
    // 분·틱을 막 골랐거나 불러오는 중/실패: 도구 줄은 유지하고 상태만 보여 준다.
    return (
      <div className="stock-chart">
        {header}
        <p className="stock-chart__status" role="status">
          {poll.error ? poll.error.message : copy.stockDetail.intradayLoading}
        </p>
      </div>
    );
  }

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
    `${fmtPrice(price)}(${view[i].time ?? yyMmDd(view[i].trade_date)}), ${(
      ((price - lastBar.close) / (lastBar.close || 1)) *
      100
    ).toFixed(2)}%`;

  const profile = layers.profile ? volumeProfile(view, PROFILE_BINS) : [];
  const maxShare = Math.max(0, ...profile.map((b) => b.share));

  // 거래량 패널
  // 패널 배치: 켜진 패널을 정해진 순서대로 가격 패널 아래에 쌓는다.
  const panelTop: Record<PanelId, number> = { volume: 0, macd: 0 };
  let cursor = PRICE_TOP + PRICE_H;
  for (const id of panelOrder) {
    if (!panelOn[id]) continue;
    panelTop[id] = cursor;
    cursor += id === "volume" ? VOL_H : MACD_H;
  }
  const chartBottom = cursor;
  const svgH = chartBottom + AXIS_H;
  const volY = panelTop.volume;
  const macdY = panelTop.macd;
  const volBase = volY + VOL_H - 2;
  const volTop = volY + 18;
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
  const macdTop = macdY + 22;
  const macdBottom = macdY + MACD_H - 8;
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

  const idxByDate = new Map<string, number>();
  if (drawable) series.forEach((c, i) => idxByDate.set(c.trade_date, i));
  const xOfDate = (date: string): number | null => {
    const j = idxByDate.get(date);
    return j === undefined ? null : x(j - start);
  };
  const handleCanvasClick = (e: MouseEvent<SVGSVGElement>) => {
    if (!activeTool) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    const vy = ((e.clientY - rect.top) / rect.height) * svgH;
    if (vx > PLOT_W || vy < PRICE_TOP || vy > PRICE_TOP + PRICE_H) return; // 가격 패널 안쪽만
    const bar = view[snapIndex(vx, step, n)];
    const price = Math.round(priceFromY(vy, { hi: pHi, lo: pLo }, PRICE_TOP, PRICE_H));
    if (!bar || !isValidPrice(price)) return;
    const point: DrawPoint = { date: bar.trade_date, price };
    if (activeTool === "hline") {
      commitDrawing({ kind: "hline", price });
      setDrawTool(null);
      return;
    }
    if (!pendingPoint) {
      setPendingPoint(point);
      setDrawMessage(copy.stockDetail.drawPending);
      return;
    }
    if (pendingPoint.date === point.date) {
      setDrawMessage(copy.stockDetail.drawSameDate);
      return;
    }
    commitDrawing({ kind: "trend", a: pendingPoint, b: point });
    setPendingPoint(null);
    setDrawTool(null);
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
  const volBadgeY = Math.max(volY + 26, Math.min(volY + VOL_H - 10, vy(lastBar.volume)));
  const macdBadgeY =
    lastMacd === null || lastMacd === undefined
      ? null
      : Math.max(macdY + 30, Math.min(macdY + MACD_H - 10, my(lastMacd)));

  const hiRight = hiIdx > n / 2;
  const loRight = loIdx > n / 2;

  return (
    <div className={`stock-chart${expanded ? " stock-chart--expanded" : ""}`}>
      {header}

      <div
        className="stock-chart__frame"
        tabIndex={0}
        role="group"
        aria-label={`${stockName} ${copy.stockDetail.chartAriaLabel}`}
        onKeyDown={onKey}
      >
        <svg
          viewBox={`0 0 ${W} ${svgH}`}
          className={`stock-chart__svg${activeTool ? " stock-chart__svg--drawing" : ""}`}
          onClick={handleCanvasClick}
          role="img"
          aria-label={`${stockName} ${copy.stockDetail.chartAriaLabel}`}
          onPointerMove={(e) => setHover(indexFromPointer(e))}
          onPointerLeave={(e) => {
            // 터치는 손가락을 떼면 pointerleave 가 바로 따라오므로, 탭으로 고른 봉이 지워지지 않게 마우스일 때만 해제한다.
            if (e.pointerType === "mouse") setHover(null);
          }}
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
              y2={chartBottom}
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
          <line x1={PLOT_W} x2={PLOT_W} y1={PRICE_TOP} y2={chartBottom} stroke={GRID} />

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
              <g key={`${c.trade_date}-${c.time ?? ""}-${i}`}>
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

          {panelOn.volume && (
          <g>
          <line x1={0} x2={W} y1={volY} y2={volY} stroke={GRID} />
          <g fontSize="11" fill="#1f2937">
            <text x={2} y={volY + 14}>
              {copy.stockDetail.volumePanel}
            </text>
            {VOL_MA_PERIODS.map((p, i) => (
              <g key={p} opacity={layers.volMa ? 1 : 0.35}>
                <circle cx={58 + i * 40} cy={volY + 10} r={5} fill={VOL_MA_COLORS[p]} />
                <text x={66 + i * 40} y={volY + 14}>
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
              key={`${c.trade_date}-${c.time ?? ""}-${i}`}
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

          </g>
          )}

          {panelOn.macd && (
          <g>
          <line x1={0} x2={W} y1={macdY} y2={macdY} stroke={GRID} />
          <g fontSize="11" fill="#1f2937">
            <circle cx={9} cy={macdY + 10} r={5} fill={MACD_COLOR} />
            <text x={18} y={macdY + 14}>
              MACD(12,26)
            </text>
            <circle cx={104} cy={macdY + 10} r={5} fill={SIGNAL_COLOR} />
            <text x={113} y={macdY + 14}>
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

          </g>
          )}

          {/* X축 날짜 */}
          {xTickIdx.map((i) => (
            <text
              key={`xt-${i}`}
              x={clampX(x(i))}
              y={svgH - 8}
              fontSize="11.5"
              fill={AXIS_TEXT}
              textAnchor="middle"
            >
              {view[i].time ?? shortDate(view[i].trade_date)}
            </text>
          ))}

          {/* 사용자가 직접 그린 선(일봉) */}
          {drawable && (
            <g>
              <defs>
                <clipPath id="chart-draw-clip">
                  <rect x={0} y={PRICE_TOP} width={PLOT_W} height={PRICE_H} />
                </clipPath>
              </defs>
              <g clipPath="url(#chart-draw-clip)">
                {drawings.map((d) => {
                  const sel = selectedDrawing === d.id;
                  const sw = sel ? 2.6 : 1.5;
                  if (d.kind === "hline") {
                    const y = py(d.price);
                    return (
                      <g key={d.id} aria-hidden="true">
                        <line x1={0} x2={PLOT_W} y1={y} y2={y} stroke={DRAW_COLOR} strokeWidth={sw} strokeDasharray="6 4" />
                        <line
                          x1={0}
                          x2={PLOT_W}
                          y1={y}
                          y2={y}
                          stroke="transparent"
                          strokeWidth={16}
                          pointerEvents={activeTool ? "none" : "stroke"}
                          onClick={() => setSelectedDrawing(d.id)}
                        />
                      </g>
                    );
                  }
                  const xa = xOfDate(d.a.date);
                  const xb = xOfDate(d.b.date);
                  if (xa === null || xb === null) return null;
                  return (
                    <g key={d.id} aria-hidden="true">
                      <line x1={xa} y1={py(d.a.price)} x2={xb} y2={py(d.b.price)} stroke={DRAW_COLOR} strokeWidth={sw} />
                      <circle cx={xa} cy={py(d.a.price)} r={3.5} fill={DRAW_COLOR} />
                      <circle cx={xb} cy={py(d.b.price)} r={3.5} fill={DRAW_COLOR} />
                      <line
                        x1={xa}
                        y1={py(d.a.price)}
                        x2={xb}
                        y2={py(d.b.price)}
                        stroke="transparent"
                        strokeWidth={16}
                        pointerEvents={activeTool ? "none" : "stroke"}
                        onClick={() => setSelectedDrawing(d.id)}
                      />
                    </g>
                  );
                })}
                {activeTool === "trend" && pendingPoint && xOfDate(pendingPoint.date) !== null && (
                  <circle
                    cx={xOfDate(pendingPoint.date) ?? 0}
                    cy={py(pendingPoint.price)}
                    r={5}
                    fill="none"
                    stroke={DRAW_COLOR}
                    strokeWidth={2}
                  />
                )}
              </g>
              {drawings.map((d) => {
                if (d.kind !== "hline") return null;
                const y = py(d.price);
                if (y < PRICE_TOP || y > PRICE_TOP + PRICE_H) return null;
                return (
                  <text key={`dl-${d.id}`} x={PLOT_W + 9} y={y + 4} fontSize="10.5" fill={DRAW_COLOR} aria-hidden="true">
                    {fmtPrice(d.price)}
                  </text>
                );
              })}
            </g>
          )}

          {/* 선택선 */}
          {hover !== null && (
            <line
              x1={x(selected)}
              x2={x(selected)}
              y1={PRICE_TOP}
              y2={chartBottom}
              stroke="#111827"
              strokeOpacity="0.4"
              strokeDasharray="3 3"
            />
          )}
        </svg>
        {(["volume", "macd"] as const)
          .filter((id) => panelOn[id])
          .map((id) => {
            const label = id === "volume" ? copy.stockDetail.panelVolume : copy.stockDetail.panelMacd;
            const top = `${((panelTop[id] + 14) / svgH) * 100}%`;
            return (
              <span key={id}>
                <button
                  type="button"
                  className="chart-panel-btn"
                  style={{ left: "calc(100% - 66px)", top }}
                  aria-label={`${label} ${copy.stockDetail.panelMove}`}
                  disabled={panelOrder.filter((p) => panelOn[p]).length < 2}
                  onClick={() => setPanelOrder((o) => [o[1], o[0]])}
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                    <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="chart-panel-btn"
                  style={{ left: "calc(100% - 22px)", top }}
                  aria-label={`${label} ${copy.stockDetail.panelClose}`}
                  onClick={() => setPanelOn((o) => ({ ...o, [id]: false }))}
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                    <rect x="4" y="4" width="16" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                    <path d="m9 9 6 6M15 9l-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                </button>
              </span>
            );
          })}
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
        <strong>{sel.time ? `${sel.trade_date} ${sel.time}` : sel.trade_date}</strong>{" "}
        {copy.stockDetail.readoutOpen} {fmtPrice(sel.open)} ·{" "}
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
