import Link from "next/link";
import { QuoteText } from "@/components/QuoteText";
import copy from "@/content/copy.ko.json";
import { formatHms, hasPrice, type PsearchItem } from "@/lib/psearch/logic";
import type { StockQuote } from "@/lib/types";

/**
 * 증권사 조건검색 결과 표(≥768px)와 카드 목록(<768px). 표는 `<table>`+`<caption>`+`<th scope>`.
 * 현재가는 준실시간 시세(`QuoteText`)이고 값이 없으면 "-"(0으로 채우지 않는다). 신규 종목은 색이 아니라 "신규" 글자로 알린다.
 */
export interface BrokerRow {
  item: PsearchItem;
  isNew: boolean;
  quote: StockQuote | undefined;
}

function StockName({ item }: { item: PsearchItem }) {
  return (
    <Link href={`/stocks/${item.code}`} className="results-table__link">
      {item.name ? `${item.name} ` : ""}
      <span className="results-table__code">({item.code})</span>
    </Link>
  );
}

function NewBadge() {
  return (
    <span className="broker-new">
      {copy.broker.newBadge}
      <span className="sr-only"> ({copy.broker.newBadgeSr})</span>
    </span>
  );
}

function Price({ quote }: { quote: StockQuote | undefined }) {
  if (!hasPrice(quote)) {
    return (
      <span className="broker-noprice">
        <span aria-hidden="true">{copy.broker.noPrice}</span>
        <span className="sr-only">{copy.broker.noPriceSr}</span>
      </span>
    );
  }
  return <QuoteText quote={quote} />;
}

export function BrokerResultsTable({ rows }: { rows: BrokerRow[] }) {
  return (
    <div className="broker-table-wrap" role="region" aria-label={copy.broker.tableCaption} tabIndex={0}>
      <table className="results-table broker-table">
        <caption className="sr-only">{copy.broker.tableCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{copy.broker.stockColumn}</th>
            <th scope="col">{copy.broker.marketColumn}</th>
            <th scope="col">{copy.broker.priceColumn}</th>
            <th scope="col">{copy.broker.enteredColumn}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ item, isNew, quote }) => (
            <tr key={item.code}>
              <th scope="row">
                <StockName item={item} /> {isNew && <NewBadge />}
              </th>
              <td>{item.market ? <span className="market-badge">{item.market}</span> : copy.broker.noValue}</td>
              <td>
                <Price quote={quote} />
              </td>
              <td className="broker-time">{formatHms(item.entered_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BrokerResultsList({ rows }: { rows: BrokerRow[] }) {
  return (
    <ul className="results-list broker-list" aria-label={copy.broker.listAriaLabel}>
      {rows.map(({ item, isNew, quote }) => (
        <li key={item.code} className="results-list__item broker-list__item">
          <div className="results-list__header">
            <Link href={`/stocks/${item.code}`} className="broker-list__link">
              {item.name && <span className="results-list__name">{item.name} </span>}
              <span className="results-list__code">({item.code})</span>
            </Link>
            {item.market && <span className="market-badge">{item.market}</span>}
            {isNew && <NewBadge />}
          </div>
          <div className="results-list__quote">
            <Price quote={quote} />
          </div>
          <dl className="results-list__metrics">
            <div className="results-list__metric-row">
              <dt>{copy.broker.enteredColumn}</dt>
              <dd className="broker-time">{formatHms(item.entered_at)}</dd>
            </div>
          </dl>
        </li>
      ))}
    </ul>
  );
}
