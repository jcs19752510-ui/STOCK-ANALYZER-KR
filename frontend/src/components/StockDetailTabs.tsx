"use client";

import { useId, useState, useSyncExternalStore } from "react";
import type { KeyboardEvent } from "react";
import { ConditionStatusBadge } from "@/components/ConditionStatusBadge";
import { OrderBookPanel } from "@/components/OrderBookPanel";
import { StockChart } from "@/components/StockChart";
import { TickPanel } from "@/components/TickPanel";
import copy from "@/content/copy.ko.json";
import { localIntradayAvailable } from "@/lib/localIntraday";
import { PATTERN_CONDITION_IDS } from "@/lib/patternApi";
import { conditionTitle, evidenceText } from "@/lib/patternFormat";
import { useLazyApi, type LazyState } from "@/lib/useLazyApi";
import { formatEok } from "@/lib/formatEok";
import type { PatternCheckData, StockEarningsData, StockPricePoint } from "@/lib/types";

/**
 * 종목 상세 탭(DEC-041): 차트 · 일자별 시세 · 투자자(준비 중) · 조건 체크.
 * 호가·체결은 실시간 데이터라 만들지 않고, 체결현황 자리는 **일 단위 종가 기준 일자별 시세 표**로 대체한다.
 * 점수·순위·충족 개수는 어디에도 두지 않는다.
 */
type TabId = "book" | "chart" | "ticks" | "daily" | "earnings" | "investor" | "check";
const ALL_TABS: { id: TabId; label: string }[] = [
  { id: "book", label: copy.stockDetail.tabBook },
  { id: "chart", label: copy.stockDetail.tabChart },
  { id: "ticks", label: copy.stockDetail.tabTicks },
  { id: "daily", label: copy.stockDetail.tabDaily },
  { id: "earnings", label: copy.stockDetail.tabEarnings },
  { id: "investor", label: copy.stockDetail.tabInvestor },
  { id: "check", label: copy.stockDetail.tabCheck },
];

// 시세 원값 비공개(DEC-048)일 때는 차트·일자별 시세 탭을 뺀다.
const PRICE_TAB_IDS: TabId[] = ["chart", "daily"];
// 호가·체결은 개인 로컬 모드(DEC-052)에서만 보인다.
const LOCAL_TAB_IDS: TabId[] = ["book", "ticks"];

const noopSubscribe = () => () => {};

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
  stockCode: string;
  stockName: string;
  prices: StockPricePoint[];
  /** false면 시세 원값 탭(차트·일자별 시세)을 만들지 않는다(DEC-048). 기본 true. */
  showPrices?: boolean;
}

export function StockDetailTabs({
  stockCode,
  stockName,
  prices,
  showPrices = true,
}: StockDetailTabsProps) {
  // 브라우저 주소가 내 PC/사설망이고 스위치가 켜졌을 때만 true(서버 렌더·공개 도메인에서는 false).
  const localMode = useSyncExternalStore(noopSubscribe, localIntradayAvailable, () => false);
  const TABS = ALL_TABS.filter(
    (t) => (showPrices || !PRICE_TAB_IDS.includes(t.id)) && (localMode || !LOCAL_TAB_IDS.includes(t.id)),
  );
  const initialTab: TabId = TABS.some((t) => t.id === "chart") ? "chart" : TABS[0].id;
  const [tab, setTab] = useState<TabId>(initialTab);
  const [menuOpen, setMenuOpen] = useState(false);
  const initialId = initialTab;
  // 보조 정보는 해당 탭을 처음 열 때 브라우저가 호출한다(방문자별 rate limit 집계, `useLazyApi` 참조).
  const [opened, setOpened] = useState<Record<string, boolean>>({ [initialId]: true });
  const codePath = encodeURIComponent(stockCode);
  const earnings = useLazyApi<StockEarningsData>(
    `/api/v1/stocks/${codePath}/earnings`,
    opened.earnings === true,
  );
  const patternCheck = useLazyApi<PatternCheckData>(
    `/api/v1/stocks/${codePath}/pattern-check`,
    opened.check === true,
  );
  const baseId = useId();

  const selectTab = (id: TabId) => {
    setTab(id);
    setOpened((o) => (o[id] ? o : { ...o, [id]: true }));
  };

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = (index + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    setTab(TABS[next].id);
    setOpened((o) => (o[TABS[next].id] ? o : { ...o, [TABS[next].id]: true }));
    document.getElementById(`${baseId}-tab-${TABS[next].id}`)?.focus();
    e.preventDefault();
  };

  const dailyRows = [...prices].reverse().slice(0, 60); // 최근 60거래일, 최신순

  return (
    <div className="stock-tabs">
      <div className="stock-tabs__bar">
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
              onClick={() => selectTab(t.id)}
              onKeyDown={(e) => onKey(e, i)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="stock-tabs__more"
          aria-label={copy.stockDetail.moreTabsLabel}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {menuOpen && (
          <ul className="stock-tabs__menu">
            {TABS.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  className="stock-tabs__menu-item"
                  aria-current={tab === t.id ? "true" : undefined}
                  onClick={() => {
                    selectTab(t.id);
                    setMenuOpen(false);
                    document.getElementById(`${baseId}-tab-${t.id}`)?.focus();
                  }}
                >
                  {t.label}
                </button>
              </li>
            ))}
          </ul>
        )}
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
            <StockChart
              candles={prices}
              stockName={stockName}
              stockCode={stockCode}
              localMode={localMode}
            />
          )}

          {t.id === "book" && tab === "book" && <OrderBookPanel stockCode={stockCode} />}

          {t.id === "ticks" && tab === "ticks" && <TickPanel stockCode={stockCode} />}

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

          {t.id === "earnings" && tab === "earnings" && <EarningsPanel state={earnings} />}

          {t.id === "investor" && tab === "investor" && (
            <div className="stock-tabs__pending">
              <h2 className="stock-tabs__pending-title">{copy.stockDetail.investorPendingTitle}</h2>
              <p>{copy.stockDetail.investorPendingBody}</p>
            </div>
          )}

          {t.id === "check" && tab === "check" && <PatternCheckPanel state={patternCheck} />}
        </div>
      ))}
    </div>
  );
}

function PatternCheckPanel({ state }: { state: LazyState<PatternCheckData> }) {
  if (state.kind === "idle" || state.kind === "loading") {
    return <p className="stock-tabs__pending">{copy.stockDetail.tabLoading}</p>;
  }
  if (state.kind === "error") {
    return <p className="stock-tabs__pending">{copy.stockDetail.checkUnavailable}</p>;
  }
  const data = state.data;
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

function EarningsPanel({ state }: { state: LazyState<StockEarningsData> }) {
  if (state.kind === "idle" || state.kind === "loading") {
    return <p className="stock-tabs__pending">{copy.stockDetail.tabLoading}</p>;
  }
  if (state.kind === "error") {
    return <p className="stock-tabs__pending">{copy.stockDetail.earningsUnavailable}</p>;
  }
  const data = state.data;
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
