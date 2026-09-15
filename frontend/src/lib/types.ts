/**
 * 03-system-design.md §3-4 `meta.data_freshness` 객체와 1:1 대응.
 * 필드명/타입은 `services/public_api/schemas/envelope.py`의 `DataFreshness`를
 * 그대로 따른다 — 프론트엔드가 이 값을 재계산하지 않고 그대로 표시하기 위함(§3-4).
 */
export interface DataFreshness {
  /** 거래소 세션 구분(KRX|NXT), 상장시장(코스피/코스닥) 구분과 다른 축(§3-1-1) */
  market: string;
  trade_date: string;
  session_close_at: string | null;
  generated_at: string;
  is_latest_trading_day: boolean;
  expected_last_trading_day: string;
  staleness_note: string | null;
}
