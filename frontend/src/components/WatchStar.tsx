"use client";

import { useState } from "react";
import copy from "@/content/copy.ko.json";
import { useWatchlist } from "@/lib/useWatchlist";
import { MAX_PER_GROUP, addToDefault, isWatched, removeEverywhere, type WatchItem } from "@/lib/watchlist";

/**
 * 관심종목 별 버튼(DEC-055). 켜면 첫 번째 그룹에 추가, 끄면 모든 그룹에서 제거한다. 색에만 의존하지 않도록 ★/☆ 글리프와
 * aria-pressed·라벨을 함께 쓰고, 결과(추가/제거/가득 참)는 aria-live 문구로 알린다.
 */
export function WatchStar({ item, variant }: { item: WatchItem; variant: "band" | "row" }) {
  const { state, update } = useWatchlist();
  const [message, setMessage] = useState("");
  const on = isWatched(state, item.code);

  const toggle = () => {
    if (on) {
      update((s) => removeEverywhere(s, item.code));
      setMessage(copy.watchlist.removedMessage);
      return;
    }
    let result = "";
    update((s) => {
      const r = addToDefault(s, item);
      result = r.result;
      return r.state;
    });
    setMessage(
      result === "full"
        ? copy.watchlist.fullMessage.replace("{max}", String(MAX_PER_GROUP))
        : copy.watchlist.addedMessage,
    );
  };

  return (
    <>
      <button
        type="button"
        className={`watch-star watch-star--${variant}`}
        aria-pressed={on}
        aria-label={`${on ? copy.watchlist.removeLabel : copy.watchlist.addLabel}: ${item.name}`}
        onClick={toggle}
      >
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <path
            d="m12 3.500 2.600 5.400 5.900.8-4.300 4.100 1 5.800-5.200-2.800-5.200 2.800 1-5.800L3.500 9.700l5.900-.8Z"
            fill={on ? "currentColor" : "none"}
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <span className="sr-only" role="status">
        {message}
      </span>
    </>
  );
}
