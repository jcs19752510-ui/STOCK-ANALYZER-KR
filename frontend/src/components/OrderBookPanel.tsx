"use client";

import { LocalModeNotice } from "@/components/LocalModeNotice";
import copy from "@/content/copy.ko.json";
import { useLiveBook, useLiveMode } from "@/lib/liveStream/react";
import { useIntradayPoll } from "@/lib/useIntradayPoll";
import type { IntradayBookLevel, IntradayOrderBookData } from "@/lib/types";

/**
 * 호가 탭(개인 로컬 모드, DEC-052): 10단계 매도(파랑)·매수(빨강) 호가와 잔량 막대, 총잔량, 예상체결가.
 * 실시간 스트림이 열려 있으면(DEC-084) 그 데이터로 바뀔 때마다 갱신하고 폴링하지 않는다. 스트림을 쓸 수 없으면 2초마다 다시 불러온다. 색에만 의존하지 않도록 열 제목·"매도/매수" 라벨과 숫자를 항상 함께 보여준다.
 */
const nf = new Intl.NumberFormat("ko-KR");

function Bar({ qty, max, side }: { qty: number; max: number; side: "ask" | "bid" }) {
  const width = max > 0 ? Math.max(2, Math.round((qty / max) * 100)) : 0;
  return (
    <span className={`book-bar book-bar--${side}`} style={{ width: `${width}%` }} aria-hidden="true" />
  );
}

export function OrderBookPanel({ stockCode }: { stockCode: string }) {
  const mode = useLiveMode();
  if (mode === "fallback") return <PolledOrderBook stockCode={stockCode} />;
  return <LiveOrderBook pending={mode === "pending"} />;
}

function LiveOrderBook({ pending }: { pending: boolean }) {
  const book = useLiveBook();
  if (!book) {
    return (
      <div>
        <LocalModeNotice />
        <p className="stock-tabs__pending">{pending ? copy.stockDetail.tabLoading : copy.stockDetail.liveBookWaiting}</p>
      </div>
    );
  }
  return <BookView book={book} error={null} note={copy.stockDetail.liveBookNote} />;
}

function PolledOrderBook({ stockCode }: { stockCode: string }) {
  const state = useIntradayPoll<IntradayOrderBookData>(
    `/api/v1/local/stocks/${encodeURIComponent(stockCode)}/orderbook`,
    2000,
  );
  const book = state.data;

  if (!book) {
    return (
      <div>
        <LocalModeNotice />
        <p className="stock-tabs__pending">
          {state.error ? state.error.message : copy.stockDetail.tabLoading}
        </p>
      </div>
    );
  }
  return <BookView book={book} error={state.error} note={copy.stockDetail.bookNote} />;
}

function BookView({
  book,
  error,
  note,
}: {
  book: IntradayOrderBookData;
  error: { message: string } | null;
  note: string;
}) {
  const asks: IntradayBookLevel[] = [...book.asks].reverse(); // 위쪽이 높은 가격
  const max = Math.max(1, ...book.asks.map((l) => l.quantity), ...book.bids.map((l) => l.quantity));
  const totalAll = book.total_ask_quantity + book.total_bid_quantity;
  const askShare = totalAll > 0 ? (book.total_ask_quantity / totalAll) * 100 : 50;

  return (
    <div className="orderbook">
      <LocalModeNotice />
      {error && <p className="local-error">{error.message}</p>}
      <table className="orderbook__table">
        <caption className="sr-only">{copy.stockDetail.bookCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{copy.stockDetail.bookAskQty}</th>
            <th scope="col">{copy.stockDetail.bookPrice}</th>
            <th scope="col">{copy.stockDetail.bookBidQty}</th>
          </tr>
        </thead>
        <tbody>
          {asks.map((l) => (
            <tr key={`a-${l.price}`} className="orderbook__row orderbook__row--ask">
              <td className="orderbook__qty">
                <Bar qty={l.quantity} max={max} side="ask" />
                <span className="orderbook__num">{nf.format(l.quantity)}</span>
              </td>
              <th scope="row" className="orderbook__price orderbook__price--ask">
                {nf.format(l.price)}
              </th>
              <td />
            </tr>
          ))}
          {book.bids.map((l) => (
            <tr key={`b-${l.price}`} className="orderbook__row orderbook__row--bid">
              <td />
              <th scope="row" className="orderbook__price orderbook__price--bid">
                {nf.format(l.price)}
              </th>
              <td className="orderbook__qty orderbook__qty--bid">
                <Bar qty={l.quantity} max={max} side="bid" />
                <span className="orderbook__num">{nf.format(l.quantity)}</span>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td className="orderbook__total orderbook__total--ask">{nf.format(book.total_ask_quantity)}</td>
            <th scope="row">{copy.stockDetail.bookTotal}</th>
            <td className="orderbook__total orderbook__total--bid">{nf.format(book.total_bid_quantity)}</td>
          </tr>
        </tfoot>
      </table>
      <div className="orderbook__ratio" aria-hidden="true">
        <span className="orderbook__ratio-ask" style={{ width: `${askShare}%` }} />
        <span className="orderbook__ratio-bid" style={{ width: `${100 - askShare}%` }} />
      </div>
      {book.expected && (
        <p className="orderbook__expected">
          {copy.stockDetail.bookExpected} <strong>{nf.format(book.expected.price)}</strong>
          {book.expected.change_pct !== null && ` (${book.expected.change_pct.toFixed(2)}%)`}
        </p>
      )}
      <p className="stock-tabs__note">
        {book.time ? `${copy.stockDetail.bookTime} ${book.time} · ` : ""}
        {note}
      </p>
    </div>
  );
}
