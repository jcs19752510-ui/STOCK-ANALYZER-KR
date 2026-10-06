/**
 * 장중 기준 재계산(DEC-089/090) 응답 모양 — 계약서 `docs/stock-detail/10-intraday-rescreen-contract.md` §3.
 * 서버 응답은 믿지 않고 `logic.ts`의 `parseLiveMeta`로 한 번 걸러 쓴다.
 */

/** 항목별 기준: 시세를 받아 장중 값으로 다시 계산했으면 live, 못 받아 일봉 값을 유지했으면 daily. */
export type LiveBasis = "live" | "daily";

export type LiveScreenKind = "screen" | "pattern";

export interface LiveBaseFill {
  gap_days: number;
  /** 계약 최종형은 none|running|ready. failed는 이전 초안 호환으로만 받아들인다. */
  state: "none" | "running" | "ready" | "failed";
  done: number;
  total: number;
  filled: number;
  /** filled 중 DB 캐시로 채운 종목 수(증권사 호출 없음) */
  from_cache: number;
  excluded: number;
  mismatched: number;
  /** 아직 보충 결과가 정해지지 않은 종목 수("보충 중"). excluded(제외)와 구분해서 보인다. */
  pending: number;
  source: "kis_daily_price" | null;
}

export interface LiveChanges {
  entered: string[];
  left: string[];
}

export interface LiveMeta {
  snapshot_id: string;
  /** 스냅샷 계산 시각(epoch 초) */
  as_of: number;
  basis_trade_date: string;
  expected_trade_date: string;
  today: string;
  quotes_covered: number;
  quotes_total: number;
  coverage_ratio: number;
  oldest_quote_age_seconds: number | null;
  stale: boolean;
  volume_partial: true;
  recomputed: string[];
  fixed_daily: string[];
  return_rank_policy: "live" | "daily";
  compute_ms: number;
  refresh_seconds: number;
  priority_codes: number;
  priority_cycle_seconds: number | null;
  base_fill: LiveBaseFill;
  changes: LiveChanges | null;
}

/** 화면이 구분해서 안내하는 오류 종류. */
export type LiveErrorKind =
  | "base_stale" // 409 LIVE_BASE_STALE — 다시 묻지 않음
  | "base_filling" // 503 LIVE_BASE_FILLING — 진행률 표시, 자동 재시도
  | "quotes_not_ready" // 503 LIVE_QUOTES_NOT_READY — 자동 재시도
  | "snapshot_expired" // 410 SNAPSHOT_EXPIRED — 즉시 새로 계산
  | "forbidden" // 401·403 — 다시 묻지 않음
  | "not_found" // 404 — 기능 꺼짐·경로 없음, 다시 묻지 않음
  | "unavailable" // 503 중 설정·기능 문제 — 다시 묻지 않음
  | "invalid" // 400 — 같은 조건으로는 소용없음, 조건을 바꾸면 풀림
  | "rate_limited" // 429 — 간격을 늘려 재시도
  | "server" // 그 밖의 5xx·409 등 — 간격을 늘려 재시도
  | "network" // 연결 실패 — 간격을 늘려 재시도
  | "bad_response"; // 200인데 모양이 어긋남 — 간격을 늘려 재시도

export interface LiveError {
  kind: LiveErrorKind;
  status: number;
  code: string | null;
  message: string | null;
  /** base_filling일 때 증권사 일봉 보충 진행(종목 수) */
  progress: { done: number; total: number; gap_days: number | null } | null;
}

/** 서버가 항목마다 붙이는 `basis`. 화면 컴포넌트가 선택적으로 읽는다. */
export interface WithBasis {
  basis?: LiveBasis;
}
