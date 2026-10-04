"use client";

import { useEffect, useRef, useState } from "react";
import copy from "@/content/copy.ko.json";
import { browserApiBase } from "@/lib/apiBase";
import {
  createWakeTracker,
  installWakeTracking,
  PAGE_LOADING_ATTR,
  WAKE_NOTICE_THRESHOLD_MS,
} from "@/lib/apiWake";
import {
  createCountdown,
  formatClockKst,
  formatRemaining,
  resetAutoReloads,
  tryConsumeAutoReload,
  WAKE_COUNTDOWN_SECONDS,
} from "@/lib/wakeCountdown";

/**
 * 무료 호스팅 베타용 "서버가 깨어나는 중" 팝업(DEC-063, DEC-066). 오래 걸릴 때만 화면 가운데에 뜨고
 * 요청 시각과 60초 카운트다운(60→00)을 보여 준다. 두 경우에 뜬다.
 *  1) 서버가 화면 데이터를 받아 오는 동안 보이는 로딩 폴백(`data-page-loading`)이 오래 남아 있을 때 → 0초에 아직 로딩 중이면 새로고침
 *     (같은 탭에서 연속 최대 2회). 그 전에 데이터가 오면 팝업만 닫고 새로고침하지 않는다.
 *  2) 브라우저가 보내는 API 요청이 오래 걸릴 때 → 0초에 팝업만 닫는다(입력한 조건이 사라지지 않게 새로고침하지 않는다).
 * 기능에는 영향이 없고 화면 읽기 프로그램에는 안내 문구를 상태로 전달한다(카운트다운 숫자는 매초 읽지 않는다).
 */
export function ApiWakeNotice() {
  const [requestStart, setRequestStart] = useState<number | null>(null);
  const [pageStart, setPageStart] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(WAKE_COUNTDOWN_SECONDS);
  const [expired, setExpired] = useState(false);
  const pageActiveRef = useRef(false);

  useEffect(() => {
    pageActiveRef.current = pageStart !== null;
  }, [pageStart]);

  useEffect(() => {
    const tracker = createWakeTracker((visible, startedAt) =>
      setRequestStart(visible ? (startedAt ?? Date.now()) : null),
    );
    const restore = installWakeTracking(window, browserApiBase(), tracker);
    return () => {
      restore();
      setRequestStart(null);
    };
  }, []);

  useEffect(() => {
    const selector = `[${PAGE_LOADING_ATTR}]`;
    let timer: number | undefined;
    let firstSync = true;
    let counterCleared = false;
    const sync = () => {
      const loading = document.querySelector(selector) !== null;
      if (loading && timer === undefined) {
        counterCleared = false;
        // 처음 열 때는 주소창에서 요청한 시각(timeOrigin)을, 화면 이동 중이면 지금을 요청 시각으로 본다.
        const start = firstSync ? Math.round(performance.timeOrigin) : Date.now();
        const wait = Math.max(0, WAKE_NOTICE_THRESHOLD_MS - (Date.now() - start));
        timer = window.setTimeout(() => setPageStart(start), wait);
      } else if (!loading) {
        if (timer !== undefined) {
          window.clearTimeout(timer);
          timer = undefined;
        }
        setPageStart(null);
        if (!counterCleared) {
          counterCleared = true;
          resetAutoReloads(window.sessionStorage); // 데이터가 도착했으니 새로고침 횟수를 지운다
        }
      }
      firstSync = false;
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (timer !== undefined) window.clearTimeout(timer);
      setPageStart(null);
    };
  }, []);

  const active = pageStart !== null || requestStart !== null;

  useEffect(() => {
    if (!active) return undefined;
    const countdown = createCountdown({
      seconds: WAKE_COUNTDOWN_SECONDS,
      onTick: setRemaining,
      onDone: () => {
        const stillLoadingPage =
          pageActiveRef.current && document.querySelector(`[${PAGE_LOADING_ATTR}]`) !== null;
        if (stillLoadingPage && tryConsumeAutoReload(window.sessionStorage)) {
          window.location.reload();
          return;
        }
        setExpired(true);
      },
    });
    return () => {
      countdown.stop();
      setExpired(false); // 느린 상태가 끝나면(또는 다시 시작되면) 다음 팝업이 다시 뜰 수 있게 한다
    };
  }, [active]);

  const visible = active && !expired;
  const requestedAt = Math.min(...[pageStart, requestStart].filter((v): v is number => v !== null));
  const percent = Math.round((remaining / WAKE_COUNTDOWN_SECONDS) * 100);
  const w = copy.wakeNotice;

  return (
    <div role="status" aria-live="polite">
      {visible ? (
        <>
          <span className="sr-only">
            {w.title} {w.body}
          </span>
          <div className="wake-dialog-layer">
            <div
              className="wake-dialog"
              role="dialog"
              aria-labelledby="wake-dialog-title"
              aria-describedby="wake-dialog-body"
            >
              <h2 id="wake-dialog-title" className="wake-dialog__title">
                {w.title}
              </h2>
              <p id="wake-dialog-body" className="wake-dialog__body">
                {w.body}
              </p>
              <dl className="wake-dialog__meta">
                <dt>{w.requestedAtLabel}</dt>
                <dd data-testid="wake-requested-at">{formatClockKst(requestedAt)}</dd>
              </dl>
              <p className="wake-dialog__label">{w.remainingLabel}</p>
              <div role="timer" aria-label={`${w.remainingLabel} ${formatRemaining(remaining)}${w.secondsUnit}`}>
                <span className="wake-dialog__count" data-testid="wake-remaining" aria-hidden="true">
                  {formatRemaining(remaining)}
                </span>
              </div>
              <div className="wake-dialog__bar" aria-hidden="true">
                <span style={{ width: `${percent}%` }} />
              </div>
              <p className="wake-dialog__note">
                {pageStart !== null ? w.reloadNote : w.autoCloseNote}
              </p>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
