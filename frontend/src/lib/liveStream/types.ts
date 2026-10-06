/**
 * 실시간 스트림(SSE) 계약 타입(DEC-084). 서버(`services/public_api/api/local_realtime.py`, `realtime/hub.py`)가 보내는 모양 그대로다.
 * 순수 타입·로직 파일(`reducer.ts`·`aggregate.ts`·`store.ts`·`controller.ts`)은 Node 시험(`scripts/check-live-stream.mjs`)에서 그대로 불러오므로
 * `@/` 별칭과 TS 전용 문법(enum 등)을 쓰지 않는다.
 */

/** 체결 1건. 최신이 앞인 목록에 담긴다. */
export interface LiveTick {
  time: string; // "HH:MM:SS"
  price: number;
  change: number | null;
  change_pct: number | null;
  volume: number;
  strength: number | null;
  acml_volume?: number | null;
}

/** 1분봉. */
export interface LiveBar {
  time: string; // "HH:MM"
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface LiveQuote {
  time: string; // "HH:MM:SS"
  price: number;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  ask1: number | null;
  bid1: number | null;
  acml_volume: number | null;
  acml_value: number | null;
  strength: number | null;
  halted: boolean;
  vi_price: number | null;
}

export interface LiveBookLevel {
  price: number;
  quantity: number;
}

/** REST 호가(`IntradayOrderBookData`)와 같은 모양. */
export interface LiveBook {
  stock_code: string;
  time: string | null;
  asks: LiveBookLevel[]; // 1호가 = 가장 낮은 매도
  bids: LiveBookLevel[]; // 1호가 = 가장 높은 매수
  total_ask_quantity: number;
  total_bid_quantity: number;
  expected: { price: number; change: number | null; change_pct: number | null; volume: number | null } | null;
  source: string;
}

/** 증권사(서버 쪽) 연결 상태. */
export type ServerConnection = "idle" | "connecting" | "connected" | "reconnecting";

export interface LiveSnapshot {
  code: string;
  quote: LiveQuote | null;
  book: LiveBook | null;
  ticks: LiveTick[];
  bars: LiveBar[];
  seeded: boolean;
  business_date: string | null; // "YYYYMMDD"
  connection?: ServerConnection;
}

/** 화면이 보는 라이브 데이터(상태 하나). */
export interface LiveData {
  code: string;
  quote: LiveQuote | null;
  book: LiveBook | null;
  ticks: LiveTick[]; // 최신이 앞, 최대 TICK_LIMIT
  bars: LiveBar[]; // 시간 오름차순 1분봉
  seeded: boolean;
  businessDate: string | null;
}

export type LiveEvent =
  | { type: "snapshot"; data: LiveSnapshot }
  | { type: "tick"; data: LiveTick }
  | { type: "bar"; data: LiveBar }
  | { type: "quote"; data: LiveQuote }
  | { type: "book"; data: LiveBook };

/** 브라우저 쪽 스트림 연결 상태. `off`는 라이브 기능이 꺼진 화면(공개·운영·서버 렌더). */
export type LiveStatus = "off" | "connecting" | "live" | "reconnecting" | "ended" | "error";

export interface LiveMeta {
  status: LiveStatus;
  /** 상태가 `error`일 때의 이유 코드(`intradayErrorMessage`로 문구를 만든다). `ended`면 서버가 알려 준 이유. */
  errorCode: string | null;
  /** 증권사 연결 상태(서버가 `snapshot`·`status` 이벤트로 알려 준다). 모르면 null. */
  serverConnection: ServerConnection | null;
  /** 마지막으로 데이터 이벤트를 받은 시각(ms). 갱신은 초당 1회로 줄여 둔다. 없으면 null. */
  lastReceivedAt: number | null;
  /** 첫 `snapshot`을 받았는가(받기 전에는 화면이 기존 폴링으로 되돌아갈 수 있다). */
  hasSnapshot: boolean;
  /** 지금까지 한 번이라도 증권사 연결이 `connected`였는가. */
  everConnected: boolean;
  /** 재연결이 30초 넘게 이어지는 중(배지가 "끊겼습니다"로 바뀐다). */
  down: boolean;
}
