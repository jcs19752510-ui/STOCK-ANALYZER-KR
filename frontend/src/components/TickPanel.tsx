"use client";

import { LocalModeNotice } from "@/components/LocalModeNotice";
import copy from "@/content/copy.ko.json";
import { useLiveMode, useLiveTicks } from "@/lib/liveStream/react";
import { useIntradayPoll } from "@/lib/useIntradayPoll";
import type { IntradayTick, IntradayTicksData } from "@/lib/types";

/**
 * 체결 탭(개인 로컬 모드, DEC-052): 최근 체결 120건(시각·체결가·체결량·등락·체결강도).
 * 실시간 스트림이 열려 있으면(DEC-084) 체결이 생길 때마다 갱신하고 폴링하지 않는다. 스트림을 쓸 수 없으면 3초마다 다시 불러온다.
 */
const nf = new Intl.NumberFormat("ko-KR");
const SHOWN = 120;

function dirClass(v: number | null): string {
  if (v === null || v === 0) return "";
  return v > 0 ? "price-up" : "price-down";
}

/** 같은 시각·가격·수량의 체결이 겹쳐도 키가 겹치지 않게(그리고 새 체결이 위에 붙어도 기존 행이 다시 그려지지 않게) 내용 기반 키를 만든다. */
function rowKeys(ticks: IntradayTick[]): string[] {
  const seen = new Map<string, number>();
  return ticks.map((t) => {
    const base = `${t.time}|${t.price}|${t.volume}|${t.acml_volume ?? ""}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base}#${n}`;
  });
}

export function TickPanel({ stockCode }: { stockCode: string }) {
  const mode = useLiveMode();
  if (mode === "fallback") return <PolledTicks stockCode={stockCode} />;
  return <LiveTicks pending={mode === "pending"} />;
}

function LiveTicks({ pending }: { pending: boolean }) {
  const ticks = useLiveTicks();
  if (pending) {
    return (
      <div>
        <LocalModeNotice />
        <p className="stock-tabs__pending">{copy.stockDetail.tabLoading}</p>
      </div>
    );
  }
  return <TickTable ticks={ticks.slice(0, SHOWN)} truncated={false} error={null} note={copy.stockDetail.liveTickNote} empty={copy.stockDetail.liveTicksWaiting} />;
}

function PolledTicks({ stockCode }: { stockCode: string }) {
  const state = useIntradayPoll<IntradayTicksData>(
    `/api/v1/local/stocks/${encodeURIComponent(stockCode)}/ticks?limit=120`,
    3000,
  );
  const data = state.data;
  if (!data) {
    return (
      <div>
        <LocalModeNotice />
        <p className="stock-tabs__pending">
          {state.error ? state.error.message : copy.stockDetail.tabLoading}
        </p>
      </div>
    );
  }
  return <TickTable ticks={data.ticks} truncated={data.truncated} error={state.error} note={copy.stockDetail.tickNote} empty={null} />;
}

function TickTable({
  ticks,
  truncated,
  error,
  note,
  empty,
}: {
  ticks: IntradayTick[];
  truncated: boolean;
  error: { message: string } | null;
  note: string;
  /** 체결이 하나도 없을 때 표 대신 보여 줄 문구(없으면 빈 표). */
  empty: string | null;
}) {
  const keys = rowKeys(ticks);
  return (
    <div>
      <LocalModeNotice />
      {error && <p className="local-error">{error.message}</p>}
      {empty !== null && ticks.length === 0 ? (
        <p className="stock-tabs__pending">{empty}</p>
      ) : (
        <div className="daily-table-wrap" role="region" tabIndex={0} aria-label={copy.stockDetail.tickCaption}>
          <table className="daily-table">
            <caption className="sr-only">{copy.stockDetail.tickCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.stockDetail.tickTime}</th>
                <th scope="col">{copy.stockDetail.tickPrice}</th>
                <th scope="col">{copy.stockDetail.tickChange}</th>
                <th scope="col">{copy.stockDetail.tickVolume}</th>
                <th scope="col">{copy.stockDetail.tickStrength}</th>
              </tr>
            </thead>
            <tbody>
              {ticks.map((t, i) => (
                <tr key={keys[i]}>
                  <th scope="row">{t.time}</th>
                  <td className={dirClass(t.change)}>{nf.format(t.price)}</td>
                  <td className={dirClass(t.change)}>
                    {t.change === null
                      ? "–"
                      : `${t.change > 0 ? "▲" : t.change < 0 ? "▼" : ""}${nf.format(Math.abs(t.change))}`}
                  </td>
                  <td>{nf.format(t.volume)}</td>
                  <td>{t.strength === null ? "–" : t.strength.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="stock-tabs__note">
        {truncated ? copy.stockDetail.tickTruncated : ""} {note}
      </p>
    </div>
  );
}
