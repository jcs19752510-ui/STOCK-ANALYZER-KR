"use client";

import { useId, useState } from "react";
import type { KeyboardEvent } from "react";
import { ConditionStatusBadge } from "@/components/ConditionStatusBadge";
import { StockChart } from "@/components/StockChart";
import copy from "@/content/copy.ko.json";
import { PATTERN_CONDITION_IDS } from "@/lib/patternApi";
import { conditionTitle, evidenceText } from "@/lib/patternFormat";
import type { PatternCheckData, StockEarningsData, StockPricePoint } from "@/lib/types";

/**
 * 종목 상세 탭(DEC-041): 차트 · 일자별 시세 · 투자자(준비 중) · 조건 체크.
 * 호가·체결은 실시간 데이터라 만들지 않고, 체결현황 자리는 **일 단위 종가 기준 일자별 시세 표**로 대체한다.
 * 점수·순위·충족 개수는 어디에도 두지 않는다.
 */
type TabId = "chart" | "daily" | "earnings" | "investor" | "check";
const TABS: { id: TabId; label: string }[] = [
  { id: "chart", label: copy.stockDetail.tabChart },
  { id: "daily", label: copy.stockDetail.tabDaily },
  { id: "earnings", label: copy.stockDetail.tabEarnings },
  { id: "investor", label: copy.stockDetail.tabInvestor },
  { id: "check", label: copy.stockDetail.tabCheck },
];

const nf = new Intl.NumberFormat("ko-KR");

function signedClass(v: number | null): string {
  if (v === null || v === 0) return "";
  return v > 0 ? "price-up" : "price-down";
}

function signedText(v: number | null, suffix = ""): string {
  if (v === null) return "–";
  const sign = v > 0 ? "▲" : v < 0 ? "▼" : "";
  return `${sign}${nf.format(Math.abs(v))}${suffix}`;
}

interface StockDetailTabsProps {
  stockName: string;
  prices: StockPricePoint[];
  patternCheck: PatternCheckData | null;
  earnings: StockEarningsData | null;
}

export function StockDetailTabs({
  stockName,
  prices,
  patternCheck,
  earnings,
}: StockDetailTabsProps) {
  const [tab, setTab] = useState<TabId>("chart");
  const baseId = useId();

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = (index + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    setTab(TABS[next].id);
    document.getElementById(`${baseId}-tab-${TABS[next].id}`)?.focus();
    e.preventDefault();
  };

  const dailyRows = [...prices].reverse().slice(0, 60); // 최근 60거래일, 최신순

  return (
    <div className="stock-tabs">
      <div role="tablist" aria-label={copy.stockDetail.tabsLabel} className="stock-tabs__list">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            id={`${baseId}-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`${baseId}-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            className="stock-tabs__tab"
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {TABS.map((t) => (
        <div
          key={t.id}
          id={`${baseId}-panel-${t.id}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${t.id}`}
          hidden={tab !== t.id}
          className="stock-tabs__panel"
        >
          {t.id === "chart" && tab === "chart" && (
            <StockChart candles={prices} stockName={stockName} />
          )}

          {t.id === "daily" && tab === "daily" && (
            <div className="daily-table-wrap" role="region" tabIndex={0} aria-label={copy.stockDetail.dailyTableLabel}>
              <table className="daily-table">
                <caption className="sr-only">{copy.stockDetail.dailyTableLabel}</caption>
                <thead>
                  <tr>
                    <th scope="col">{copy.stockDetail.colDate}</th>
                    <th scope="col">{copy.stockDetail.colClose}</th>
                    <th scope="col">{copy.stockDetail.colChange}</th>
                    <th scope="col">{copy.stockDetail.colChangePct}</th>
                    <th scope="col">{copy.stockDetail.colVolume}</th>
                  </tr>
                </thead>
                <tbody>
                  {dailyRows.map((p) => (
                    <tr key={p.trade_date}>
                      <th scope="row">{p.trade_date}</th>
                      <td>{nf.format(p.close)}</td>
                      <td className={signedClass(p.change)}>{signedText(p.change)}</td>
                      <td className={signedClass(p.change_pct)}>
                        {p.change_pct === null
                          ? "–"
                          : `${p.change_pct > 0 ? "▲" : p.change_pct < 0 ? "▼" : ""}${Math.abs(p.change_pct).toFixed(2)}%`}
                      </td>
                      <td>{nf.format(p.volume)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="stock-tabs__note">{copy.stockDetail.dailyNote}</p>
            </div>
          )}

          {t.id === "earnings" && tab === "earnings" && <EarningsPanel data={earnings} />}

          {t.id === "investor" && tab === "investor" && (
            <div className="stock-tabs__pending">
              <h2 className="stock-tabs__pending-title">{copy.stockDetail.investorPendingTitle}</h2>
              <p>{copy.stockDetail.investorPendingBody}</p>
            </div>
          )}

          {t.id === "check" && tab === "check" && <PatternCheckPanel data={patternCheck} />}
        </div>
      ))}
    </div>
  );
}

function PatternCheckPanel({ data }: { data: PatternCheckData | null }) {
  if (data === null) {
    return <p className="stock-tabs__pending">{copy.stockDetail.checkUnavailable}</p>;
  }
  if (data.item === null) {
    return <p className="stock-tabs__pending">{copy.stockDetail.checkNotEvaluated}</p>;
  }
  const item = data.item;
  return (
    <div className="pattern-check">
      <p className="pattern-check__lead">
        {copy.stockDetail.checkLead} ({data.trade_date})
      </p>
      <dl className="pattern-list__conditions">
        {PATTERN_CONDITION_IDS.map((id) => (
          <div key={id} className="pattern-list__row">
            <dt>{conditionTitle(id)}</dt>
            <dd>
              <ConditionStatusBadge result={item.conditions[id]} />
              <span className="pattern-evidence">{evidenceText(id, item, data.definition)}</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="stock-tabs__note">{copy.pattern.proxyFootnote}</p>
      <p className="stock-tabs__note">{copy.pattern.scopeFootnote}</p>
      <p className="stock-tabs__note">{copy.stockDetail.checkNotice}</p>
    </div>
  );
}

/** 원 → 억 원(소수 첫째 자리에서 반올림한 정수), null은 '-'. */
export function formatEok(value: number | null): string {
  if (value === null) return "-";
  const eok = Math.round(value / 100_000_000);
  return nf.format(eok === 0 ? 0 : eok); // -0 방지
}

function EarningsPanel({ data }: { data: StockEarningsData | null }) {
  if (data === null) {
    return <p className="stock-tabs__pending">{copy.stockDetail.earningsUnavailable}</p>;
  }
  if (data.earnings.length === 0) {
    return <p className="stock-tabs__pending">{copy.stockDetail.earningsEmpty}</p>;
  }
  return (
    <div className="daily-table-wrap" role="region" tabIndex={0} aria-label={copy.stockDetail.earningsLabel}>
      <table className="daily-table">
        <caption className="sr-only">{copy.stockDetail.earningsLabel}</caption>
        <thead>
          <tr>
            <th scope="col">{copy.stockDetail.colYear}</th>
            <th scope="col">{copy.stockDetail.colRevenue}</th>
            <th scope="col">{copy.stockDetail.colOperating}</th>
            <th scope="col">{copy.stockDetail.colNetIncome}</th>
          </tr>
        </thead>
        <tbody>
          {[...data.earnings].reverse().map((e) => (
            <tr key={e.fiscal_year}>
              <th scope="row">
                {e.fiscal_year}
                <span className="earnings-basis">
                  {e.fs_div === "CFS"
                    ? copy.stockDetail.earningsBasisCfs
                    : copy.stockDetail.earningsBasisOfs}
                </span>
              </th>
              <td>{formatEok(e.revenue)}</td>
              <td className={signedClass(e.operating_income)}>{formatEok(e.operating_income)}</td>
              <td className={signedClass(e.net_income)}>{formatEok(e.net_income)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="stock-tabs__note">{copy.stockDetail.earningsSource}</p>
    </div>
  );
}
