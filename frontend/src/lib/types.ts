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

/**
 * `GET /api/v1/stocks/{code}/metrics` 응답(REQ-002, 03-system-design.md §4-2).
 * 원본 시세 필드(open/high/low/close/volume)와 PER/PBR/시가총액 원시값은
 * 백엔드 응답 자체에 존재하지 않으므로 이 타입에도 없다(§4-3).
 */
export interface StockMetricsData {
  stock_code: string;
  name: string;
  market: string;
  return_pct: number | null;
  return_rank_pct: number | null;
  ma5_gap_pct: number | null;
  ma20_gap_pct: number | null;
  volume_anomaly_score: number | null;
  per_percentile: number | null;
  pbr_percentile: number | null;
  market_cap_percentile: number | null;
}

/**
 * `GET /api/v1/stocks` 응답 항목(REQ-001, 03-system-design.md §4-2).
 * `stock_master`는 애초에 시세 데이터를 다루지 않으므로 원본 시세 필드가
 * 존재할 수 없다(§4-3과 무관하게 스키마 자체에 없음, `unit-03-note.md` 참조).
 */
export interface StockSearchItem {
  stock_code: string;
  name: string;
  market: string;
}

/**
 * `GET /api/v1/screen` 응답(REQ-003, 03-system-design.md §4-2). `matched_metrics`는
 * 필터 조건에 실제 값이 지정된 지표 ∪ `sort_by` 지표만 담는 화이트리스트
 * 딕셔너리다(DEC-013) — 원본 시세/원시값은 여기에도, 이 타입 어디에도 없다(§4-3).
 */
export interface ScreenResultItem {
  stock_code: string;
  name: string;
  market: string;
  matched_metrics: Record<string, number | null>;
}

export interface ScreenData {
  items: ScreenResultItem[];
  total_count: number;
  page: number;
}

/**
 * `GET /api/v1/market-summary` 응답(REQ-004, 03-system-design.md §4-2).
 * 개별 종목 원본 시세 나열이 아니라 상승/하락/보합 종목 수, 업종별 거래대금
 * 상위 등 가공된 요약 통계로만 구성된다(§4-3).
 */
export interface SectorSummary {
  sector: string;
  trading_value_krw: number;
}

export interface MarketSummaryItem {
  market: string;
  advancers_count: number;
  decliners_count: number;
  unchanged_count: number;
  top_sectors_by_value: SectorSummary[];
  total_trading_value_krw: number;
}

/**
 * `market` 생략(기본값 ALL) 응답. `by_market`은 `market=KOSPI`/`KOSDAQ`를
 * 명시 요청한 응답에서는 `null`이다(백엔드 `services/public_api/schemas/
 * market_summary.py` 참조 — 이 코드베이스의 다른 옵셔널 필드와 동일하게
 * 필드를 생략하지 않고 항상 `null`로 표현하는 일관된 계약을 따른다).
 */
export interface MarketSummaryData extends MarketSummaryItem {
  by_market: MarketSummaryItem[] | null;
}

export interface ApiErrorDetail {
  code: string;
  message: string;
}

export interface Envelope<T> {
  meta: {
    data_freshness: DataFreshness | null;
    disclaimer: string;
    generated_at: string;
  };
  data: T | null;
  error: ApiErrorDetail | null;
}
