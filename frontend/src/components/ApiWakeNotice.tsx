"use client";

import { useEffect, useState } from "react";
import copy from "@/content/copy.ko.json";
import { createWakeTracker, installWakeTracking } from "@/lib/apiWake";

/**
 * 무료 호스팅 베타용 "서버가 깨어나는 중" 안내(DEC-063). API 요청이 오래 걸릴 때만 화면 상단에 표시되고,
 * 응답이 오면 사라진다. 기능에는 영향이 없고 화면 읽기 프로그램에도 상태로 전달된다(role="status").
 */
export function ApiWakeNotice() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const tracker = createWakeTracker(setVisible);
    const restore = installWakeTracking(window, process.env.NEXT_PUBLIC_API_BASE_URL, tracker);
    return () => {
      restore();
      setVisible(false);
    };
  }, []);

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
