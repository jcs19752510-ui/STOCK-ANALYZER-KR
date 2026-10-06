"use client";

import copy from "@/content/copy.ko.json";
import { intradayErrorMessage } from "@/lib/localIntraday";
import { useLiveMeta, useLiveMode, useLiveState } from "@/lib/liveStream/react";

/**
 * 실시간 연결 상태 배지(DEC-084). 라이브 기능이 꺼진 화면(공개·운영)에서는 아무것도 그리지 않는다.
 * `role="status"`(정중한 알림)이지만 "마지막 수신" 시각은 초당 한 번 바뀌므로, 연결됨 상태에서는 시각을 스크린리더가 읽지 않게(`aria-hidden`) 하고
 * 상태가 바뀔 때(연결됨 → 재연결 중 → 끊김 …)만 읽히게 한다.
 */
const timeFmt = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  hourCycle: "h23",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function formatStamp(ms: number): string {
  return timeFmt.format(new Date(ms));
}

export function LiveStatusBadge() {
  const state = useLiveState();
  const meta = useLiveMeta();
  const mode = useLiveMode();
  if (state === "off") return null;

  const last = meta.lastReceivedAt === null ? copy.stockDetail.liveNoneYet : copy.stockDetail.liveLastReceived.replace("{time}", formatStamp(meta.lastReceivedAt));
  let tone: "ok" | "warn" | "down" | "info" = "info";
  let text: string;
  let tail: string | null = null;
  let tailHidden = false;
  switch (state) {
    case "live":
      tone = "ok";
      text = copy.stockDetail.liveConnected;
      tail = last;
      tailHidden = true; // 초당 한 번 바뀌는 값: 읽어 주지 않는다
      break;
    case "reconnecting":
      tone = "warn";
      text = copy.stockDetail.liveReconnecting;
      tail = last;
      break;
    case "down":
      tone = "down";
      text = copy.stockDetail.liveDown;
      tail = `(${last})`;
      break;
    case "ended":
      tone = "down";
      text = copy.stockDetail.liveEnded;
      break;
    case "error":
      tone = "warn";
      text = intradayErrorMessage(meta.errorCode ?? "UNKNOWN_ERROR");
      tail = mode === "fallback" ? copy.stockDetail.liveFallbackNote : null;
      break;
    default:
      text = copy.stockDetail.liveConnecting;
  }

  return (
    <p className={`live-badge live-badge--${tone}`} role="status" data-live-state={state}>
      <span className="live-badge__dot" aria-hidden="true" />
      <span className="live-badge__text">
        {text}
        {tail !== null && (
          <>
            {" "}
            {state === "live" || state === "reconnecting" ? "· " : ""}
            <span className="live-badge__time" aria-hidden={tailHidden ? "true" : undefined}>
              {tail}
            </span>
          </>
        )}
      </span>
    </p>
  );
}
