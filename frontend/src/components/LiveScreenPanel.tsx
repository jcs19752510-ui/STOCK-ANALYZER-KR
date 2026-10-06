"use client";

import { useEffect, useRef, useState } from "react";
import copy from "@/content/copy.ko.json";
import type { LiveScreenView } from "@/lib/liveScreen/view";
import {
  bannerNotices,
  changeRows,
  dataAgeSeconds,
  isDelayed,
  statusKey,
} from "@/lib/liveScreen/logic";
import { useNowSeconds } from "@/lib/liveScreen/react";
import type { LiveError, LiveErrorKind } from "@/lib/liveScreen/types";
import { fillTemplate } from "@/lib/patternFormat";
import { formatHms } from "@/lib/psearch/logic";

/**
 * 장중 기준(DEC-089) 결과 위 영역: 기준 배너(계산 시각·시세 수신·기준 일봉·경고)·조작(일시정지·새로 계산)·오류 안내·낭독 한 곳.
 * 낭독은 상태가 **바뀔 때만** 한다(`statusKey`): 10초마다 목록이 바뀌어도 읽지 않고, 초 단위로 바뀌는 "N초 전"은 낭독 영역 밖이다.
 * 이 컴포넌트는 장중 기준이 켜졌을 때만 그려진다(켜기 전에는 이 컴포넌트도 요청도 없다).
 */
type AnyView = LiveScreenView<{ items: unknown[]; page: number }>;

interface Props {
  view: AnyView;
  /** 조건을 적용해 요청이 시작된 상태인가(아직 조건 적용 전이면 배너 없이 조작만 숨김) */
  hasQuery: boolean;
  onPause: () => void;
  onResume: () => void;
  onRefresh: () => void;
  onRevert: () => void;
}

const errorText = (kind: LiveErrorKind): { title: string; body: string } => {
  const [title, body] = (copy.liveScreen.errors as Record<string, string[]>)[kind] ?? copy.liveScreen.errors.server;
  return { title, body };
};

function announcement(prev: string, next: string, error: LiveError | null): string {
  if (next.startsWith("error:")) {
    return fillTemplate(copy.liveScreen.announceError, { title: errorText(error?.kind ?? "server").title });
  }
  if (next === "loading") return copy.liveScreen.announceLoading;
  const has = (key: string, s: string) => s.split("+").includes(key);
  if (has("expired", next) && !has("expired", prev)) return copy.liveScreen.announceExpired;
  if (has("paused", next) !== has("paused", prev)) return has("paused", next) ? copy.liveScreen.announcePaused : copy.liveScreen.announceResumed;
  if (has("delayed", next) !== has("delayed", prev)) return has("delayed", next) ? copy.liveScreen.announceDelayed : copy.liveScreen.announceRecovered;
  if (has("quotes-stale", next) && !has("quotes-stale", prev)) return copy.liveScreen.announceQuotesStale;
  if (has("fill-running", next) && !has("fill-running", prev)) return copy.liveScreen.announceFill;
  if (prev === "" || prev === "loading" || prev.startsWith("error:")) return copy.liveScreen.announceLoaded;
  return "";
}

function ErrorBlock({ error, onRefresh, onRevert }: { error: LiveError; onRefresh: () => void; onRevert: () => void }) {
  const { title, body } = errorText(error.kind);
  const p = error.progress;
  return (
    <div className="live-error" data-live-error={error.kind}>
      <h2 className="live-error__title">{title}</h2>
      <p>{body}</p>
      {error.kind === "base_filling" && p && p.total > 0 && (
        <p className="live-error__progress">
          <progress value={p.done} max={p.total} aria-label={fillTemplate(copy.liveScreen.fillRunning, { done: p.done, total: p.total })} />{" "}
          <span>
            {p.done}/{p.total}
          </span>
        </p>
      )}
      {error.message && error.kind !== "snapshot_expired" && (
        <p className="live-error__server">{fillTemplate(copy.liveScreen.serverMessage, { message: error.message })}</p>
      )}
      <div className="live-controls">
        <button type="button" className="live-button" onClick={onRefresh}>
          {copy.liveScreen.retry}
        </button>
        <button type="button" className="live-button live-button--primary" onClick={onRevert}>
          {copy.liveScreen.revert}
        </button>
      </div>
    </div>
  );
}

export function LiveScreenPanel({ view, hasQuery, onPause, onResume, onRefresh, onRevert }: Props) {
  const now = useNowSeconds(hasQuery);
  const meta = view.meta;
  const delayed = !view.paused && isDelayed(now, view.receivedAt, view.refreshSeconds);
  const notices = meta ? bannerNotices(meta) : null;
  const key = statusKey({
    hasData: view.data !== null,
    paused: view.paused,
    delayed,
    errorKind: view.error?.kind ?? null,
    baseFillState: meta?.base_fill.state ?? null,
    stale: !!meta?.stale,
    expiredNotice: view.expiredNotice,
  });
  const [said, setSaid] = useState("");
  const prevKey = useRef("");
  useEffect(() => {
    if (!hasQuery) return;
    const text = announcement(prevKey.current, key, view.error);
    prevKey.current = key;
    if (text) setSaid(text);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 상태 열쇠가 바뀔 때만 낭독
  }, [key, hasQuery]);

  const announcer = (
    <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
      {said}
    </p>
  );
  if (!hasQuery) return announcer;

  const age = meta && view.receivedAt !== null ? Math.floor(dataAgeSeconds(meta.as_of, view.receivedAt, now, view.generatedAt)) : null;
  const failing = view.error !== null && view.data !== null;
  const retrySec = view.retryInMs === null ? null : Math.round(view.retryInMs / 1000);

  return (
    <div className="live-panel" data-live-state={key}>
      {announcer}
      {meta && view.data && (
        <section className="live-banner" aria-label={copy.liveScreen.bannerRegionLabel} data-snapshot-id={meta.snapshot_id} data-paused={view.paused ? "1" : "0"}>
          <p className="live-banner__main">
            <strong>{copy.liveScreen.basisHeading}</strong>
            <span className="live-banner__sep"> · </span>
            <span className="live-banner__time">{fillTemplate(copy.liveScreen.computedAt, { time: formatHms(meta.as_of), age: age ?? 0 })}</span>
            <span className="live-banner__sep"> · </span>
            <span>{fillTemplate(copy.liveScreen.quotesReceived, { covered: meta.quotes_covered, total: meta.quotes_total })}</span>
            <span className="live-banner__sep"> · </span>
            <span>{fillTemplate(copy.liveScreen.baseDaily, { date: meta.basis_trade_date || "-" })}</span>
            {delayed && <span className="live-badge live-badge--delayed">{copy.liveScreen.delayedBadge}</span>}
            {view.paused && <span className="live-badge live-badge--paused">{copy.liveScreen.pausedState}</span>}
          </p>
          <p className="live-banner__warn">{copy.liveScreen.volumeWarning}</p>
          {delayed && <p className="live-banner__notice live-banner__notice--warn">{fillTemplate(copy.liveScreen.delayedNotice, { age: age ?? 0 })}</p>}
          {failing && view.error && (
            <p className="live-banner__notice live-banner__notice--warn">
              {view.paused || retrySec === null
                ? copy.liveScreen.failingPausedNotice
                : fillTemplate(copy.liveScreen.failingNotice, { sec: retrySec })}{" "}
              {view.error.code || view.error.status
                ? fillTemplate(copy.liveScreen.failingDetail, { detail: [view.error.status || null, view.error.code].filter(Boolean).join(" ") })
                : ""}
            </p>
          )}
          {failing && view.error && (view.error.kind === "base_filling" || view.error.kind === "quotes_not_ready") && (
            <p className="live-banner__notice">{errorText(view.error.kind).title}</p>
          )}
          {notices?.stale && <p className="live-banner__notice live-banner__notice--warn">{copy.liveScreen.quotesStaleNotice}</p>}
          {notices?.lowCoverage && <p className="live-banner__notice">{copy.liveScreen.lowCoverageNotice}</p>}
          {notices?.baseFillRunning && meta && (
            <p className="live-banner__notice live-banner__notice--warn">
              {fillTemplate(copy.liveScreen.fillRunning, { done: meta.base_fill.done, total: meta.base_fill.total })}
              {meta.base_fill.total > 0 && (
                <>
                  {" "}
                  <progress value={meta.base_fill.done} max={meta.base_fill.total} aria-label={copy.liveScreen.fillRunning.split("(")[0]} />
                </>
              )}
            </p>
          )}
          {notices && notices.pending > 0 && <p className="live-banner__notice">{fillTemplate(copy.liveScreen.fillPending, { n: notices.pending })}</p>}
          {notices?.baseFillUsed && meta && (
            <p className="live-banner__notice">{fillTemplate(copy.liveScreen.fillUsed, { gap: meta.base_fill.gap_days, filled: meta.base_fill.filled })}</p>
          )}
          {notices?.baseFillFailed && <p className="live-banner__notice live-banner__notice--warn">{copy.liveScreen.fillFailed}</p>}
          {notices && (notices.excluded > 0 || notices.mismatched > 0) && (
            <p className="live-banner__notice live-banner__notice--warn" data-live-excluded={notices.excluded} data-live-mismatched={notices.mismatched}>
              {/* 불일치로 뺀 종목은 제외된 종목의 일부이므로 한 문장으로 알린다(서버: excluded ⊇ mismatched). */}
              {notices.excluded > 0 ? fillTemplate(copy.liveScreen.fillExcluded, { n: notices.excluded }) : null}
              {notices.mismatched > 0 && (
                <>
                  {notices.excluded > 0 ? " · " : ""}
                  {fillTemplate(notices.excluded > 0 ? copy.liveScreen.fillExcludedMismatch : copy.liveScreen.fillMismatched, notices.excluded > 0 ? { m: notices.mismatched } : { n: notices.mismatched })}
                </>
              )}
            </p>
          )}
          {view.paused && (
            <p className="live-banner__notice">{fillTemplate(copy.liveScreen.pausedNotice, { time: formatHms(meta.as_of) })}</p>
          )}
          {view.expiredNotice && (
            <p className="live-banner__notice live-banner__notice--warn">{fillTemplate(copy.liveScreen.expiredNotice, { time: formatHms(meta.as_of) })}</p>
          )}
          <div className="live-controls">
            <button type="button" className="live-button" aria-pressed={view.paused} onClick={view.paused ? onResume : onPause}>
              {copy.liveScreen.pause}
            </button>
            <button type="button" className="live-button" onClick={onRefresh} aria-busy={view.loading}>
              {copy.liveScreen.refresh}
            </button>
            {view.loading && <span className="live-controls__busy">{copy.liveScreen.refreshing}</span>}
            {!view.paused && <span className="live-controls__auto">{fillTemplate(copy.liveScreen.autoNote, { sec: view.refreshSeconds })}</span>}
          </div>
        </section>
      )}
      {view.error && !view.data && <ErrorBlock error={view.error} onRefresh={onRefresh} onRevert={onRevert} />}
    </div>
  );
}

/** "최근 변화": 직전 계산 대비 조건 결과에 들어오고 빠진 종목(이 화면을 연 뒤 본 것만). */
export function LiveChangesList({ view }: { view: AnyView }) {
  const rows = changeRows(view.changeLog.recent, view.names);
  if (!view.data) return null;
  const more = (n: number) => (n > 0 ? ` ${fillTemplate(copy.liveScreen.more, { n })}` : "");
  return (
    <section className="live-changes" aria-labelledby="live-changes-heading">
      <h2 id="live-changes-heading" className="live-changes__heading">
        {copy.liveScreen.changesHeading}
      </h2>
      <p className="live-changes__note">{copy.liveScreen.changesNote}</p>
      {rows.length === 0 ? (
        <p>{copy.liveScreen.changesNone}</p>
      ) : (
        <ul className="live-changes__list">
          {rows.map((row) => (
            <li key={row.key} className="live-changes__row">
              <span className="live-changes__time">{formatHms(row.at)}</span>
              {row.entered.length > 0 && (
                <span>
                  <strong>{copy.liveScreen.entered}</strong> {row.entered.join(", ")}
                  {more(row.enteredMore)}
                </span>
              )}
              {row.left.length > 0 && (
                <span>
                  <strong>{copy.liveScreen.left}</strong> {row.left.join(", ")}
                  {more(row.leftMore)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
