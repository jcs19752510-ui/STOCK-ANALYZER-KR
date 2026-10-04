"use client";

import { useEffect, useState } from "react";
import copy from "@/content/copy.ko.json";
import {
  createWakeTracker,
  installWakeTracking,
  PAGE_LOADING_ATTR,
  WAKE_NOTICE_THRESHOLD_MS,
} from "@/lib/apiWake";

/**
 * 무료 호스팅 베타용 "서버가 깨어나는 중" 안내(DEC-063, DEC-065). 아래 두 경우에 화면 상단에 표시되고, 끝나면 사라진다.
 * 기능에는 영향이 없고 화면 읽기 프로그램에도 상태로 전달된다(role="status").
 *  1) 브라우저가 보내는 API 요청이 오래 걸릴 때(`installWakeTracking`)
 *  2) 서버가 화면 데이터를 받아 오는 동안 보이는 로딩 폴백(`data-page-loading`)이 오래 남아 있을 때
 */
export function ApiWakeNotice() {
  const [requestSlow, setRequestSlow] = useState(false);
  const [pageSlow, setPageSlow] = useState(false);

  useEffect(() => {
    const tracker = createWakeTracker(setRequestSlow);
    const restore = installWakeTracking(window, process.env.NEXT_PUBLIC_API_BASE_URL, tracker);
    return () => {
      restore();
      setRequestSlow(false);
    };
  }, []);

  useEffect(() => {
    const selector = `[${PAGE_LOADING_ATTR}]`;
    let timer: number | undefined;
    const sync = () => {
      const loading = document.querySelector(selector) !== null;
      if (loading && timer === undefined) {
        timer = window.setTimeout(() => setPageSlow(true), WAKE_NOTICE_THRESHOLD_MS);
      } else if (!loading && timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
        setPageSlow(false);
      }
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (timer !== undefined) window.clearTimeout(timer);
      setPageSlow(false);
    };
  }, []);

  const visible = requestSlow || pageSlow;
  return (
    <div role="status" aria-live="polite">
      {visible ? (
        <p className="wake-notice">
          <strong>{copy.wakeNotice.title}</strong> {copy.wakeNotice.body}
        </p>
      ) : null}
    </div>
  );
}
