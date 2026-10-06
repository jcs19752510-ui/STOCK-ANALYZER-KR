/**
 * 전 종목 준실시간 시세(DEC-084 B) 병합 규칙 — 순수 함수. 목록 화면의 일 단위 종가 요약(`StockQuote`) 위에
 * 로컬 모드 일괄 시세(`/api/v1/local/market/quotes`)를 덮어쓴다.
 * - 값이 없는 종목(missing)·값이 숫자가 아닌 종목은 덮어쓰지 않는다(0으로 채우지 않는다).
 * - 서버가 `stale`로 알리거나 값을 받은 지 `STALE_AFTER_SEC`가 지나면 "지연"으로 표시하되 마지막 값은 보여 준다.
 */
import type { StockQuote } from "../types.ts";

export interface LiveMarketQuote {
  code: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  open: number;
  high: number;
  low: number;
  fetched_at: number; // epoch 초
}

export interface LiveMarketMeta {
  cycle_seconds: number | null;
  last_cycle_at: number | null;
  covered: number;
  total: number;
  stale: boolean;
  running: boolean;
}

export interface LiveMarketView {
  quotes: Record<string, LiveMarketQuote>;
  meta: LiveMarketMeta | null;
  /** 서버가 이 화면에 시세를 줄 수 없다고 한 상태(권한 없음·기능 꺼짐·앱키 없음). 한 번 정해지면 다시 묻지 않는다. */
  unavailable: boolean;
  /** 마지막으로 응답을 받은 시각(epoch 초). 값의 나이는 이 시각 기준으로 센다(렌더 중 현재 시각을 읽지 않기 위함). */
  receivedAt: number;
  /** 최근 조회가 실패 중(한도 초과·네트워크 오류)이면 값은 남기되 "지연"으로 표시한다. */
  failing: boolean;
}

export const EMPTY_LIVE_VIEW: LiveMarketView = { quotes: {}, meta: null, unavailable: false, receivedAt: 0, failing: false };

/** 값을 받은 지 이만큼(초) 지나면 지연 표시. 일괄 순환 한 바퀴(수십 초)보다 충분히 길게 잡는다. */
export const STALE_AFTER_SEC = 180;

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function isValidLive(q: LiveMarketQuote | undefined): q is LiveMarketQuote {
  return !!q && finite(q.price) && q.price > 0 && finite(q.change) && finite(q.change_pct) && finite(q.fetched_at);
}

/** 일 종가 요약 `daily`(없을 수 있음)에 실시간 값을 덮어쓴다. 덮어쓸 값이 없으면 `daily`를 그대로 돌려준다. */
export function overlayQuote(
  daily: StockQuote | undefined,
  live: LiveMarketQuote | undefined,
  metaStale: boolean,
  nowSec: number,
): StockQuote | undefined {
  if (!isValidLive(live)) return daily;
  const age = Math.max(0, nowSec - live.fetched_at);
  return {
    stock_code: live.code,
    trade_date: daily?.trade_date ?? "",
    close: live.price,
    change: live.change,
    change_pct: live.change_pct,
    open: finite(live.open) && live.open > 0 ? live.open : null,
    high: finite(live.high) && live.high > 0 ? live.high : null,
    low: finite(live.low) && live.low > 0 ? live.low : null,
    volume: finite(live.volume) ? live.volume : (daily?.volume ?? null),
    live: { fetchedAt: live.fetched_at, ageSec: Math.round(age), stale: metaStale || age > STALE_AFTER_SEC },
  };
}

export function overlayAll(
  daily: Record<string, StockQuote>,
  view: LiveMarketView,
  codes: readonly string[],
): Record<string, StockQuote> {
  if (view.unavailable) return daily;
  const stale = (view.meta?.stale ?? true) || view.failing;
  const nowSec = view.receivedAt;
  const out: Record<string, StockQuote> = { ...daily };
  for (const code of codes) {
    const merged = overlayQuote(daily[code], view.quotes[code], stale, nowSec);
    if (merged) out[code] = merged;
  }
  return out;
}
