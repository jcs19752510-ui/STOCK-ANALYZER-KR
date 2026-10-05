"use client";

import { useEffect, useRef, useState } from "react";
import { PAGE_LOADING_ATTR, WAKE_NOTICE_THRESHOLD_MS } from "@/lib/apiWake";
import { createCountdown, resetAutoReloads, tryConsumeAutoReload, WAKE_COUNTDOWN_SECONDS } from "@/lib/wakeCountdown";

/**
 * 무료 호스팅 베타에서 서버가 쉬다 깨어나는 동안 화면 로딩이 멈춘 듯 길어질 때의 **자동 새로고침 안전장치**(DEC-063, DEC-066, DEC-076).
 * 예전에는 이때 "서버를 깨우는 중입니다" 팝업(요청 시각·카운트다운)을 띄웠으나 사용자 요청으로 **팝업은 없앴다**(DEC-076). 화면에는 아무것도 그리지 않는다.
 *
 * 동작(팝업 시절과 같은 시간표): 서버가 화면 데이터를 받아 오는 동안 보이는 로딩 폴백(`data-page-loading`)이 4.5초 넘게 남아 있으면
 * 60초(빌드 값으로 조정 가능)를 세고, 0초에도 아직 로딩 중이면 새로고침한다(같은 탭에서 연속 최대 2회, 그 뒤엔 반복하지 않음).
 * 그 전에 데이터가 오면 아무 일도 하지 않고 새로고침 횟수 기록만 지운다. 브라우저가 보내는 API 요청이 느린 경우에는 화면 입력을 지우지 않도록 아무것도 하지 않는다.
 */
export function SlowPageReload() {
  const [pageStart, setPageStart] = useState<number | null>(null);
  const pageActiveRef = useRef(false);

  useEffect(() => {
    pageActiveRef.current = pageStart !== null;
  }, [pageStart]);

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

  const active = pageStart !== null;

  useEffect(() => {
    if (!active) return undefined;
    const countdown = createCountdown({
      seconds: WAKE_COUNTDOWN_SECONDS,
      onTick: () => {},
      onDone: () => {
        const stillLoadingPage =
          pageActiveRef.current && document.querySelector(`[${PAGE_LOADING_ATTR}]`) !== null;
        if (stillLoadingPage && tryConsumeAutoReload(window.sessionStorage)) {
          window.location.reload();
        }
      },
    });
    return () => countdown.stop();
  }, [active]);

  return null;
}
