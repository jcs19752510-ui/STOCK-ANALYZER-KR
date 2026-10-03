"use client";

import { LocalModeNotice } from "@/components/LocalModeNotice";
import copy from "@/content/copy.ko.json";
import { useIntradayPoll } from "@/lib/useIntradayPoll";
import type { IntradayInvestorData } from "@/lib/types";

/**
 * 투자자 탭(개인 로컬 모드): 일별 개인·외국인·기관 순매수(수량 주, 대금 백만원). 30초마다 갱신한다.
 * 값이 없으면 "–"(0이 아님). ▲ 순매수 / ▼ 순매도를 색과 기호로 함께 보여 준다.
 */
const nf = new Intl.NumberFormat("ko-KR");

function dirClass(v: number | null): string {
  if (v === null || v === 0) return "";
  return v > 0 ? "price-up" : "price-down";
}

function signed(v: number | null): string {
  if (v === null) return "–";
  return `${v > 0 ? "▲" : v < 0 ? "▼" : ""}${nf.format(Math.abs(v))}`;
}

function Cell({ qty, amount }: { qty: number | null; amount: number | null }) {
  return (
    <td>
      <span className={dirClass(qty)}>{signed(qty)}</span>
      <span className={`investor-amount ${dirClass(amount)}`}>{signed(amount)}</span>
    </td>
  );
}

export function InvestorPanel({ stockCode }: { stockCode: string }) {
  const state = useIntradayPoll<IntradayInvestorData>(
    `/api/v1/local/stocks/${encodeURIComponent(stockCode)}/investor`,
    30_000,
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
      {data.rows.length === 0 ? (
        <p className="stock-tabs__pending">{copy.stockDetail.investorEmpty}</p>
      ) : (
        <div className="daily-table-wrap" role="region" tabIndex={0} aria-label={copy.stockDetail.investorCaption}>
          <table className="daily-table">
            <caption className="sr-only">{copy.stockDetail.investorCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.stockDetail.investorDate}</th>
                <th scope="col">{copy.stockDetail.investorPersonal}</th>
                <th scope="col">{copy.stockDetail.investorForeign}</th>
                <th scope="col">{copy.stockDetail.investorInstitution}</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.date}>
                  <th scope="row">{r.date}</th>
                  <Cell qty={r.personal_quantity} amount={r.personal_amount_million} />
                  <Cell qty={r.foreign_quantity} amount={r.foreign_amount_million} />
                  <Cell qty={r.institution_quantity} amount={r.institution_amount_million} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="stock-tabs__note">{copy.stockDetail.investorNetBuyHint}</p>
      <p className="stock-tabs__note">{copy.stockDetail.investorNote}</p>
    </div>
  );
}
