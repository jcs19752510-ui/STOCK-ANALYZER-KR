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
  /** PER/PBR이 null인 이유: LOSS=적자·자본잠식, NO_DATA=재무 데이터 없음, null/없음=알 수 없음(DEC-057) */
  per_unavailable_reason?: "LOSS" | "NO_DATA" | null;
  pbr_unavailable_reason?: "LOSS" | "NO_DATA" | null;
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

/**
 * `GET /api/v1/screen/pattern` 응답(REQ-032, docs/pattern-screening/02-system-design.md §5-2).
 * 서버 응답 화이트리스트와 **같은 필드만** 선언한다 — 가격·거래량 원값·`*_raw`·시가총액 원값은
 * 서버 응답에 없으므로 이 타입에도 없다(§4-3). 점수·순위 필드도 없다(REQ-034).
 */
export type PatternConditionId = "c1" | "c2" | "c3" | "c4" | "c5" | "c9";

export interface PatternConditionResult {
  /** true=충족, false=미충족, null=산정 불가 */
  met: boolean | null;
  /** met=null일 때만: INSUFFICIENT_HISTORY | SUSPECT_PRICE_JUMP | METRIC_UNAVAILABLE */
  reason: string | null;
}

export interface PatternMetrics {
  sideways_range_pct: number | null;
  sideways_net_change_pct: number | null;
  ma_convergence_pct: number | null;
  volatility_contraction_ratio: number | null;
  ma60_gap_pct: number | null;
  ma20_vs_ma60_gap_pct: number | null;
  ma60_slope_pct: number | null;
  ma60_cross_up_days: number | null;
  volume_ratio_5_60: number | null;
  volume_anomaly_score: number | null;
  recent_surge_flag: boolean | null;
}

export interface PatternItem {
  stock_code: string;
  name: string;
  market: string;
  conditions: Record<PatternConditionId, PatternConditionResult>;
  metrics: PatternMetrics;
  /** c4 화면 문구용 단계(서버가 c4와 같은 경계로 산출 — 프런트는 재계산하지 않는다) */
  ma60_stage: string | null;
}

export interface PatternDefinition {
  version: string;
  thresholds: {
    range_max_pct: number;
    net_change_max_pct: number;
    convergence_max_pct: number;
    volatility_contraction_max: number;
    ma60_approach_band_pct: number;
    ma60_early_max_gap_pct: number;
    cross_early_max_days: number;
    volume_ratio_min: number;
    volume_ratio_max: number;
    volume_anomaly_max: number;
  };
  calc: {
    lookback_days: number;
    ma60_window: number;
    cross_lookback_days: number;
    surge_lookback_days: number;
    surge_return_pct: number;
    surge_volume_mult: number;
  };
  universe: { excluded_types: string[] };
}

export interface PatternReadiness {
  evaluated_count: number;
  total_count: number;
  ready_ratio: number;
}

export interface PatternScreenData {
  items: PatternItem[];
  total_count: number;
  page: number;
  definition: PatternDefinition;
  readiness: PatternReadiness;
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

/** 일봉 1개(`GET /stocks/{code}/prices`, DEC-041). 일 단위 종가 기준이며 실시간 시세가 아니다. */
export interface StockPricePoint {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trading_value: number;
  change: number | null;
  change_pct: number | null;
}

export interface StockPricesData {
  stock_code: string;
  name: string;
  market: string;
  prices: StockPricePoint[]; // 거래일 오름차순
}

/** `GET /stocks/{code}/pattern-check` — `item`이 null이면 평가 대상이 아니거나 데이터가 없다. */
export interface PatternCheckData {
  trade_date: string;
  item: PatternItem | null;
  definition: PatternDefinition;
}

/** `GET /stocks/{code}/earnings` — DART 사업보고서 연간 공시 수치(원). 찾지 못한 항목은 null(0 아님). */
export interface EarningsYear {
  fiscal_year: number;
  fs_div: "CFS" | "OFS";
  revenue: number | null;
  operating_income: number | null;
  net_income: number | null;
}

export interface StockEarningsData {
  stock_code: string;
  name: string;
  market: string;
  earnings: EarningsYear[]; // 연도 오름차순
}

/** `GET /stocks/quotes` 항목 — 목록용 최신 종가·전일대비(일 단위 종가 기준). */
export interface StockQuote {
  stock_code: string;
  trade_date: string;
  close: number;
  change: number | null;
  change_pct: number | null;
  // 목록 행 미니 캔들·거래량 표시용(DEC-051). 값이 없으면 null.
  open?: number | null;
  high?: number | null;
  low?: number | null;
  volume?: number | null;
}

// ── 개인 로컬 모드 장중 시세(DEC-052): 분봉·체결·호가 ─────────────────────────────────────────
export interface IntradayMinuteBar {
  time: string; // "HH:MM"
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IntradayMinutesData {
  stock_code: string;
  date: string;
  interval: number;
  bars: IntradayMinuteBar[];
  source: string;
}

export interface IntradayTick {
  time: string; // "HH:MM:SS"
  price: number;
  change: number | null;
  change_pct: number | null;
  volume: number;
  strength: number | null;
  /** 실시간 스트림이 붙여 주는 당일 누적 거래량(REST 체결에는 없다). */
  acml_volume?: number | null;
}

export interface IntradayTicksData {
  stock_code: string;
  ticks: IntradayTick[]; // 최근 체결이 앞
  truncated: boolean;
  source: string;
}

export interface IntradayBookLevel {
  price: number;
  quantity: number;
}

export interface IntradayOrderBookData {
  stock_code: string;
  time: string | null;
  asks: IntradayBookLevel[]; // 매도 1단계(가장 낮은 가격)부터
  bids: IntradayBookLevel[]; // 매수 1단계(가장 높은 가격)부터
  total_ask_quantity: number;
  total_bid_quantity: number;
  expected: { price: number; change: number | null; change_pct: number | null; volume: number | null } | null;
  source: string;
}

export interface IntradayInvestorDay {
  date: string; // "YYYY-MM-DD"
  personal_quantity: number | null; // 순매수 수량(주), 순매도는 음수
  foreign_quantity: number | null;
  institution_quantity: number | null;
  personal_amount_million: number | null; // 순매수 거래대금(백만원, 증권사 단위)
  foreign_amount_million: number | null;
  institution_amount_million: number | null;
}

export interface IntradayInvestorData {
  stock_code: string;
  rows: IntradayInvestorDay[]; // 최근 거래일이 앞
  source: string;
}
