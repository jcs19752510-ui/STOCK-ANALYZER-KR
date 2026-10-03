"use client";

import { LocalModeNotice } from "@/components/LocalModeNotice";
import copy from "@/content/copy.ko.json";
import { useIntradayPoll } from "@/lib/useIntradayPoll";
import type { IntradayTicksData } from "@/lib/types";

/** 체결 탭(개인 로컬 모드, DEC-052): 최근 체결 120건(시각·체결가·체결량·등락·체결강도), 3초마다 갱신. */
const nf = new Intl.NumberFormat("ko-KR");

function dirClass(v: number | null): string {
  if (v === null || v === 0) return "";
  return v > 0 ? "price-up" : "price-down";
}

export function TickPanel({ stockCode }: { stockCode: string }) {
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
  return (
    <div>
      <LocalModeNotice />
      {state.error && <p className="local-error">{state.error.message}</p>}
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
            {data.ticks.map((t, i) => (
              <tr key={`${t.time}-${i}`}>
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
      <p className="stock-tabs__note">
        {data.truncated ? copy.stockDetail.tickTruncated : ""} {copy.stockDetail.tickNote}
      </p>
    </div>
  );
}
