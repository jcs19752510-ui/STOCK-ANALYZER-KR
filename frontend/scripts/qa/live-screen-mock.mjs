// 장중 기준 재계산(DEC-089/090) 화면 시험용 **가짜 JSON 서버**. 계약서 `docs/stock-detail/10-intraday-rescreen-contract.md` §3의 모양만 흉내 낸다 —
// 실제 백엔드·증권사가 아니다(스냅샷 재사용·고정·410·409·503·base_fill·changes·basis를 시험 조작으로 만든다).
// 단독 실행: node scripts/qa/live-screen-mock.mjs [포트]   /   스크립트에서: import { startMock }
import http from "node:http";

export const TOTAL = 140; // 전체 후보 종목 수(결과는 이 중 약 90%)
const code = (i) => `1${String(i).padStart(5, "0")}`; // 6자리 숫자 코드
const nameOf = (i) => `모의종목${String(i).padStart(3, "0")}`;
const marketOf = (i) => (i % 2 === 0 ? "KOSPI" : "KOSDAQ");

export function defaultCtl() {
  return {
    err: "", // "" | stale409 | filling | notready | e403 | e404 | e500 | e503srv | e503cfg | e400 | bad200
    refresh: 5, // meta.live.refresh_seconds
    minInterval: 3, // 서버 최소 계산 간격(초): 이 안의 요청은 직전 스냅샷 재사용
    modulo: 10, // 스냅샷마다 (i+k)%modulo==0인 종목이 빠진다
    covered: 2700, total: 2800, stale: false, policy: "live",
    fill: "none", fillDone: 0, fillTotal: 2800, gap: 0, filled: 0, excluded: 0, mismatched: 0, pending: 0,
    dailyMod: 9, // i%dailyMod==0 인 종목은 basis "daily"
    delayMs: 0,
    noChanges: false,
    basisDate: "2026-10-05",
  };
}

export function startMock(port, { host = "127.0.0.1" } = {}) {
  const ctl = defaultCtl();
  let k = 0;
  let snaps = new Map(); // id -> {k, createdAt, passing:Set<number>, changes}
  let order = [];
  let last = null;
  const log = [];
  let normalCount = 0;

  const reset = () => {
    Object.assign(ctl, defaultCtl());
    k = 0; snaps = new Map(); order = []; last = null; log.length = 0;
  };
  const passingOf = (kk) => new Set(Array.from({ length: TOTAL }, (_, i) => i).filter((i) => (i + kk) % ctl.modulo !== 0));
  function computeSnapshot(now) {
    k += 1;
    const passing = passingOf(k);
    let changes = null;
    if (last && !ctl.noChanges) {
      const entered = [...passing].filter((i) => !last.passing.has(i)).map(code).slice(0, 100);
      const left = [...last.passing].filter((i) => !passing.has(i)).map(code).slice(0, 100);
      changes = { entered, left };
    }
    const snap = { id: `snap-${k}`, k, createdAt: now, passing, changes };
    snaps.set(snap.id, snap);
    order.push(snap.id);
    while (order.length > 5) snaps.delete(order.shift()); // 최근 5개만 보관(계약 §0-4)
    last = snap;
    return snap;
  }
  const latest = (now) => (last && now - last.createdAt < ctl.minInterval ? last : computeSnapshot(now));

  const envelopeMeta = () => ({ data_freshness: { market: "KRX", trade_date: "2026-10-05", session_close_at: null, generated_at: new Date().toISOString(), is_latest_trading_day: true, expected_last_trading_day: "2026-10-05", staleness_note: null }, disclaimer: "", generated_at: new Date().toISOString() });
  const liveMeta = (snap) => ({
    snapshot_id: snap.id, as_of: Math.floor(snap.createdAt), basis_trade_date: ctl.basisDate, expected_trade_date: "2026-10-05", today: "2026-10-06",
    quotes_covered: ctl.covered, quotes_total: ctl.total, coverage_ratio: ctl.covered / ctl.total, oldest_quote_age_seconds: 4, stale: ctl.stale, volume_partial: true,
    recomputed: ["return_pct", "ma5_gap_pct", "volume_anomaly_score"], fixed_daily: ["per", "pbr", "market_cap"], return_rank_policy: ctl.policy, compute_ms: 180,
    refresh_seconds: ctl.refresh, priority_codes: 50, priority_cycle_seconds: 3,
    base_fill: { gap_days: ctl.gap, state: ctl.fill, done: ctl.fillDone, total: ctl.fillTotal, filled: ctl.filled, excluded: ctl.excluded, mismatched: ctl.mismatched, pending: ctl.pending, source: ctl.fill === "none" ? null : "kis_daily_price" },
    changes: snap.changes,
  });
  const itemOf = (i, snap, pattern) => {
    const basis = i % ctl.dailyMod === 0 ? "daily" : "live";
    const base = { stock_code: code(i), name: nameOf(i), market: marketOf(i), basis };
    if (!pattern) return { ...base, matched_metrics: { market_cap: 50 + (i % 50), return_pct: +(((i * 7 + snap.k * 13) % 300) / 10 - 5).toFixed(2) } };
    const m = (v) => ((i + snap.k) % 7 === 0 ? null : v);
    return {
      ...base,
      conditions: Object.fromEntries(["c1", "c2", "c3", "c4", "c5", "c9"].map((c, n) => [c, (i + n) % 5 === 0 ? { met: null, reason: "INSUFFICIENT_HISTORY" } : { met: (i + n + snap.k) % 3 !== 0, reason: null }])),
      metrics: { sideways_range_pct: m(8.5 + (i % 4)), sideways_net_change_pct: m(1.2), ma_convergence_pct: m(2.1), volatility_contraction_ratio: m(0.7), ma60_gap_pct: m(-1.5), ma20_vs_ma60_gap_pct: m(0.8), ma60_slope_pct: m(0.1), ma60_cross_up_days: 2, volume_ratio_5_60: m(1.3), volume_anomaly_score: m(0.4), recent_surge_flag: false },
      ma60_stage: "BELOW_NEAR",
    };
  };
  const definition = {
    version: "v1", thresholds: { range_max_pct: 15, net_change_max_pct: 5, convergence_max_pct: 3, volatility_contraction_max: 0.8, ma60_approach_band_pct: 3, ma60_early_max_gap_pct: 5, cross_early_max_days: 5, volume_ratio_min: 0.8, volume_ratio_max: 2, volume_anomaly_max: 2 },
    calc: { lookback_days: 40, ma60_window: 60, cross_lookback_days: 10, surge_lookback_days: 60, surge_return_pct: 30, surge_volume_mult: 3 }, universe: { excluded_types: [] },
  };

  const send = (res, status, body) => {
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*" });
    res.end(JSON.stringify(body));
  };
  const errBody = (code_, message, extra = {}) => ({ data: null, meta: envelopeMeta(), error: { code: code_, message, ...extra } });

  function handleLive(url, res, pattern) {
    const search = Object.fromEntries(url.searchParams);
    const e = ctl.err;
    if (e === "stale409") return send(res, 409, errBody("LIVE_BASE_STALE", "일봉 데이터가 직전 거래일(2026-10-05)보다 5거래일 넘게 뒤처져 장중 재계산을 쓸 수 없습니다. (현재 2026-09-25)"));
    if (e === "filling") return send(res, 503, errBody("LIVE_BASE_FILLING", "직전 거래일 일봉을 증권사에서 보충하는 중입니다(done/total). 잠시 후 다시 시도", { details: { done: ctl.fillDone, total: ctl.fillTotal, gap_days: ctl.gap || 2 } }));
    if (e === "notready") return send(res, 503, errBody("LIVE_QUOTES_NOT_READY", "시세를 모으는 중입니다. 잠시 후 다시 시도"));
    if (e === "e403") return send(res, 403, errBody("FORBIDDEN", "관리자만 사용할 수 있습니다."));
    if (e === "e404") return send(res, 404, errBody("NOT_FOUND", "찾을 수 없습니다."));
    if (e === "e500") return send(res, 500, errBody("INTERNAL_ERROR", "서버 오류"));
    if (e === "e503srv") return send(res, 503, errBody("SERVICE_UNAVAILABLE", "일시적인 서비스 장애입니다."));
    if (e === "e503cfg") return send(res, 503, errBody("LOCAL_INTRADAY_NOT_CONFIGURED", "앱키가 설정되지 않았습니다."));
    if (e === "e400") return send(res, 400, errBody("INVALID_PARAMETER", "요청 파라미터가 올바르지 않습니다."));
    if (e === "bad200") return send(res, 200, { data: { items: [], total_count: 0, page: 1 }, meta: envelopeMeta(), error: null });
    const now = Date.now() / 1000;
    let snap;
    if (search.snapshot_id) {
      snap = snaps.get(search.snapshot_id);
      if (!snap) return send(res, 410, errBody("SNAPSHOT_EXPIRED", "계산 결과가 만료되었습니다. 새로 계산하세요."));
    } else snap = latest(now);
    const market = search.market ?? "ALL";
    const all = [...snap.passing].sort((a, b) => a - b).filter((i) => market === "ALL" || marketOf(i) === market);
    const pageSize = Number(search.page_size ?? 50);
    const page = Math.max(1, Number(search.page ?? 1));
    const rows = all.slice((page - 1) * pageSize, page * pageSize).map((i) => itemOf(i, snap, pattern));
    const data = { items: rows, total_count: all.length, page };
    if (pattern) Object.assign(data, { definition, readiness: { evaluated_count: 2500, total_count: 2800, ready_ratio: 2500 / 2800 } });
    const body = { data, meta: { ...envelopeMeta(), live: liveMeta(snap) }, error: null };
    return ctl.delayMs ? void setTimeout(() => send(res, 200, body), ctl.delayMs) : send(res, 200, body);
  }

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, `http://${host}:${port}`);
    const p = url.pathname;
    if (req.method === "OPTIONS") return send(res, 204, {});
    if (p === "/__set") {
      for (const [key, v] of url.searchParams) {
        if (key === "expireAll") { snaps = new Map(); order = []; last = null; continue; }
        if (key === "resetSnaps") { snaps = new Map(); order = []; last = null; k = 0; continue; }
        ctl[key] = typeof ctl[key] === "number" ? Number(v) : typeof ctl[key] === "boolean" ? v === "1" : v;
      }
      return send(res, 200, ctl);
    }
    if (p === "/__reset") { reset(); return send(res, 200, { ok: true }); }
    if (p === "/__log") return send(res, 200, log);
    if (p === "/__state") return send(res, 200, { k, order, ctl, normalCount });
    log.push({ t: Date.now(), path: p, search: url.search, token: req.headers["x-internal-token"] ?? null, user: req.headers["x-auth-user"] ?? null, sid: req.headers["x-auth-session"] ?? null });
    if (p === "/api/v1/local/screen") return handleLive(url, res, false);
    if (p === "/api/v1/local/screen/pattern") return handleLive(url, res, true);
    // 일봉 기준(기존) 화면: 같은 모양, live 없음
    if (p === "/api/v1/screen" || p === "/api/v1/screen/pattern") {
      normalCount += 1;
      const pattern = p.endsWith("pattern");
      const pageSize = Number(url.searchParams.get("page_size") ?? 50);
      const page = Math.max(1, Number(url.searchParams.get("page") ?? 1));
      const snap0 = { k: 0 };
      const all = Array.from({ length: TOTAL }, (_, i) => i).filter((i) => i % 10 !== 0);
      const rows = all.slice((page - 1) * pageSize, page * pageSize).map((i) => {
        const it = itemOf(i, snap0, pattern);
        delete it.basis;
        return it;
      });
      const data = { items: rows, total_count: all.length, page };
      if (pattern) Object.assign(data, { definition, readiness: { evaluated_count: 2500, total_count: 2800, ready_ratio: 2500 / 2800 } });
      return send(res, 200, { data, meta: envelopeMeta(), error: null });
    }
    if (p === "/api/v1/local/market/quotes") {
      const codes = (url.searchParams.get("codes") ?? "").split(",").filter(Boolean);
      const now = Date.now() / 1000;
      const quotes = codes.map((c) => ({ code: c, price: 70000 + Number(c.slice(-3)), change: 500, change_pct: 0.72, volume: 1234, open: 69800, high: 70500, low: 69500, fetched_at: Math.floor(now) }));
      return send(res, 200, { data: { quotes, missing: [], meta: { cycle_seconds: 12, last_cycle_at: Math.floor(now), covered: quotes.length, total: codes.length, stale: false, running: true } }, error: null });
    }
    if (p === "/api/v1/stocks/quotes") {
      const codes = (url.searchParams.get("codes") ?? "").split(",").filter(Boolean);
      return send(res, 200, { data: { quotes: codes.map((c) => ({ stock_code: c, trade_date: "2026-10-05", close: 69000 + Number(c.slice(-3)), change: 300, change_pct: 0.4, open: 68800, high: 69500, low: 68500, volume: 99 })) }, error: null });
    }
    return send(res, 404, errBody("NOT_FOUND", "모의 서버에 없는 경로"));
  });
  return new Promise((resolve) => server.listen(port, host, () => resolve({ server, ctl, log, close: () => server.close() })));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.argv[2] ?? 4611);
  await startMock(port);
  console.log(`모의 서버 http://127.0.0.1:${port}`);
}
