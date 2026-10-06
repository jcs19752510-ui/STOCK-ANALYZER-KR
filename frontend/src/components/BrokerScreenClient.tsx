"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { BrokerResultsList, BrokerResultsTable, type BrokerRow } from "@/components/BrokerResults";
import { ScreeningModeNav } from "@/components/ScreeningModeNav";
import copy from "@/content/copy.ko.json";
import { fillTemplate } from "@/lib/patternFormat";
import {
  changeRows,
  conditionLabel,
  formatHms,
  isNewEntry,
  mergePrice,
  nextNewExpiryMs,
  serverNow,
  updatePriceBook,
  type ChangeRow,
} from "@/lib/psearch/logic";
import type { PsearchErrorInfo, PsearchEvent } from "@/lib/psearch/poller";
import { useConditions, usePsearchResults } from "@/lib/psearch/react";
import type { StockQuote } from "@/lib/types";
import { useIsDesktopViewport } from "@/lib/useIsDesktopViewport";
import { useQuotes } from "@/lib/useQuotes";

const NO_CODES: readonly string[] = [];

function Panel({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="broker-panel">
      <h2 className="broker-panel__title">{title}</h2>
      {children}
      {action}
    </div>
  );
}

/** 이 화면을 쓸 수 없는 이유별 안내(403·404·503 포함). 시세·조회는 시도하지 않는다. */
function UnavailablePanel({ error }: { error: PsearchErrorInfo }) {
  if (error.code === "PSEARCH_NOT_CONFIGURED") {
    return (
      <Panel title={copy.broker.notConfiguredTitle}>
        <p>{copy.broker.notConfiguredBody}</p>
      </Panel>
    );
  }
  if (error.code === "LOCAL_INTRADAY_NOT_CONFIGURED") {
    return (
      <Panel title={copy.broker.appKeyMissingTitle}>
        <p>{copy.broker.appKeyMissingBody}</p>
      </Panel>
    );
  }
  if (error.code === "LOCAL_MODE_REQUIRED") {
    return (
      <Panel title={copy.broker.localRequiredTitle}>
        <p>{copy.broker.localRequiredBody}</p>
      </Panel>
    );
  }
  return (
    <Panel title={copy.broker.unavailableTitle}>
      <p>{copy.broker.unavailableBody}</p>
    </Panel>
  );
}

function announcementText(event: PsearchEvent | null): string {
  if (!event) return "";
  const time = formatHms(event.at);
  switch (event.kind) {
    case "loaded":
      return fillTemplate(copy.broker.announceLoaded, { time, count: event.count });
    case "changed":
      return fillTemplate(copy.broker.announceChanged, { time, added: event.added, removed: event.removed, count: event.count });
    case "failing":
      return fillTemplate(copy.broker.announceFailing, { time });
    case "recovered":
      return fillTemplate(copy.broker.announceRecovered, { time });
  }
}

function errorDetail(error: PsearchErrorInfo | null): string | null {
  if (!error) return null;
  if (error.code === "PSEARCH_REJECTED" && error.message) return fillTemplate(copy.broker.brokerMessage, { message: error.message.slice(0, 200) });
  return error.code ? fillTemplate(copy.broker.failingDetail, { detail: error.status ? `${error.status} ${error.code}` : error.code }) : null;
}

function ChangeList({ rows }: { rows: ChangeRow[] }) {
  const part = (label: string, names: string[], more: number) =>
    names.length === 0 ? null : (
      <span className="broker-change__part">
        <strong>{label}</strong> {names.join(", ")}
        {more > 0 && ` ${fillTemplate(copy.broker.more, { n: more })}`}
      </span>
    );
  return (
    <section className="broker-changes" aria-labelledby="broker-changes-heading">
      <h2 id="broker-changes-heading" className="broker-section-heading">
        {copy.broker.changesHeading}
      </h2>
      <p className="broker-note">{copy.broker.changesNote}</p>
      {rows.length === 0 ? (
        <p>{copy.broker.changesNone}</p>
      ) : (
        <ul className="broker-changes__list">
          {rows.map((row) => (
            <li key={row.key} className="broker-change">
              <span className="broker-time">{row.time}</span>
              {part(copy.broker.added, row.added, row.addedMore)}
              {part(copy.broker.removed, row.removed, row.removedMore)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * 증권사 조건검색 `/screener/broker`(DEC-088, 계약서 `docs/stock-detail/09-psearch-api-contract.md` §5).
 * 로컬 모드 관리자만 쓴다 — 서버 렌더에는 내용이 없고(`checking`), 로컬 모드가 아니면 안내만 보이며 요청·시세 조회를 하지 않는다.
 * 현재가는 `useQuotes`(준실시간)로 채우고, 상태가 바뀔 때의 낭독은 보이지 않는 `role="status"` 한 곳에서만 한다(표 전체는 live 영역이 아님).
 */
export function BrokerScreenClient() {
  const { state, reload } = useConditions();
  const [chosen, setChosen] = useState<string | null>(null);
  const conditions = state.phase === "ready" ? state.conditions : null;
  const seq = conditions ? (conditions.find((c) => c.seq === chosen)?.seq ?? conditions[0]?.seq ?? null) : null;

  const view = usePsearchResults(seq);
  const current = seq !== null && view.seq === seq; // 선택한 조건과 같은 조건의 값일 때만 쓴다(바뀌는 중에는 이전 값을 보이지 않음)
  const data = current && !view.unavailable ? view.data : null;
  const codes = useMemo(() => (data ? data.items.map((i) => i.code) : NO_CODES), [data]);
  const quotes = useQuotes(codes);

  // 시세 조회가 다시 시작되며 잠깐 비는 동안 가격이 "-"로 깜박이지 않게 마지막 값을 "지연"으로 이어서 보인다.
  const [book, setBook] = useState<Record<string, StockQuote>>({});
  const nextBook = updatePriceBook(book, quotes, codes);
  if (nextBook !== book) setBook(nextBook);

  // 신규 표지가 끝날 시점에 한 번 다시 그린다(조회 간격보다 늦지 않게). 렌더 중에는 현재 시각을 읽지 않는다.
  const [clock, setClock] = useState(0);
  const receivedAt = view.receivedAt ?? 0;
  const refNow = data ? serverNow(data, receivedAt, Math.max(receivedAt, clock)) : 0;
  const itemsKey = data ? data.items.map((i) => `${i.code}:${i.entered_at}`).join(",") : "";
  useEffect(() => {
    if (!data) return;
    const ms = nextNewExpiryMs(data.items, serverNow(data, receivedAt, Date.now() / 1000));
    if (ms === null) return;
    const id = window.setTimeout(() => setClock(Date.now() / 1000), ms);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- itemsKey·receivedAt·clock이 바뀔 때만 다시 계산
  }, [itemsKey, receivedAt, clock]);

  const isDesktop = useIsDesktopViewport(768);

  const rows: BrokerRow[] = useMemo(
    () =>
      data
        ? data.items.map((item) => ({
            item,
            isNew: isNewEntry(item.entered_at, refNow),
            quote: mergePrice(quotes[item.code], book[item.code]),
          }))
        : [],
    [data, refNow, quotes, book],
  );
  const changes = useMemo(() => (data ? changeRows(data.changes, view.names) : []), [data, view.names]);

  let body: ReactNode;
  if (state.phase === "checking") {
    body = <p className="broker-note">{copy.broker.checking}</p>;
  } else if (state.phase === "local-required") {
    body = <UnavailablePanel error={{ status: 0, code: "LOCAL_MODE_REQUIRED", message: null }} />;
  } else if (state.phase === "unavailable") {
    body = <UnavailablePanel error={state.error} />;
  } else if (state.phase === "loading") {
    body = <p className="broker-note">{copy.broker.loading}</p>;
  } else if (state.phase === "error") {
    const detail = errorDetail(state.error);
    body = (
      <Panel
        title={copy.broker.errorTitle}
        action={
          <button type="button" className="broker-button" onClick={reload}>
            {copy.broker.reloadConditions}
          </button>
        }
      >
        <p>{copy.broker.errorBody}</p>
        {detail && <p className="broker-note">{detail}</p>}
      </Panel>
    );
  } else if (state.conditions.length === 0) {
    body = (
      <Panel
        title={copy.broker.noConditionsTitle}
        action={
          <button type="button" className="broker-button" onClick={reload}>
            {copy.broker.reloadConditions}
          </button>
        }
      >
        <p>{copy.broker.noConditionsBody}</p>
      </Panel>
    );
  } else if (view.unavailable) {
    body = <UnavailablePanel error={view.unavailable} />; // 안내만 보인다(선택 상자·결과 없음)
  } else {
    const retrySec = view.retryInMs ? Math.round(view.retryInMs / 1000) : 0;
    const detail = errorDetail(view.lastError);
    body = (
      <>
        <div className="broker-select">
          <label htmlFor="broker-condition" className="broker-select__label">
            {copy.broker.conditionLabel}
          </label>
          <select
            id="broker-condition"
            className="broker-select__control"
            value={seq ?? ""}
            onChange={(e) => setChosen(e.target.value)}
          >
            {state.conditions.map((c) => (
              <option key={c.seq} value={c.seq}>
                {conditionLabel(c)}
              </option>
            ))}
          </select>
        </div>

        {view.fatal ? (
          <p className="inline-notice inline-notice--info broker-notice">{copy.broker.fatalBody}</p>
        ) : !data ? (
          view.failing && current ? (
            <div className="broker-notice broker-notice--warn">
              <p>{fillTemplate(copy.broker.failingNoData, { sec: retrySec })}</p>
              {detail && <p className="broker-note">{detail}</p>}
            </div>
          ) : (
            <p className="broker-note">{copy.broker.resultsLoading}</p>
          )
        ) : (
          <>
            <p className="broker-status">
              <span>{fillTemplate(copy.broker.lastQuery, { time: formatHms(view.receivedAt) })}</span>
              <span>{fillTemplate(copy.broker.brokerReceived, { time: formatHms(data.fetched_at) })}</span>
              <span>{fillTemplate(copy.broker.intervalNote, { sec: Math.round(view.intervalMs / 1000) })}</span>
            </p>
            {view.failing && (
              <div className="broker-notice broker-notice--warn">
                <p>{fillTemplate(copy.broker.failingNotice, { sec: retrySec })}</p>
                {detail && <p className="broker-note">{detail}</p>}
              </div>
            )}
            {data.stale && <p className="broker-notice broker-notice--warn">{copy.broker.staleNotice}</p>}
            {data.capped && <p className="broker-notice broker-notice--warn">{copy.broker.cappedNotice}</p>}
            {data.empty && (
              <div className="broker-notice broker-notice--warn">
                <p>{copy.broker.emptyLead}</p>
                <p>
                  {data.empty_message ? (
                    <>
                      <strong>{copy.broker.emptyMessageLabel}</strong> {data.empty_message}
                    </>
                  ) : (
                    copy.broker.emptyNoMessage
                  )}
                </p>
              </div>
            )}
            {rows.length > 0 && (
              <>
                <h2 className="broker-section-heading">{fillTemplate(copy.broker.resultsHeading, { count: rows.length })}</h2>
                {isDesktop ? <BrokerResultsTable rows={rows} /> : <BrokerResultsList rows={rows} />}
              </>
            )}
            <ChangeList rows={changes} />
          </>
        )}
      </>
    );
  }

  return (
    <section className="screener-page broker-page">
      <ScreeningModeNav current="broker" />
      <h1>{copy.broker.label}</h1>
      <p className="inline-notice inline-notice--info broker-notice-top">{copy.broker.notice}</p>
      {body}
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announcementText(current && !view.unavailable ? view.event : null)}
      </p>
    </section>
  );
}
