// DEC-065 점검: 서버 컴포넌트가 API를 부르는 화면(홈·종목 상세)의 "깨우는 중" 안내 + 일시적 실패 재시도.
// 이 스크립트가 가짜 API(포트 4311)를 직접 띄운다. 전제: 운영 빌드를 아래처럼 만들어 4312에서 실행해 둔다.
//   NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:4311 PUBLIC_API_INTERNAL_TOKEN=qa npm run build
//   NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:4311 PUBLIC_API_INTERNAL_TOKEN=qa npx next start -p 4312
// (스트리밍 응답이라 DOMContentLoaded는 스트림이 끝나야 발생하므로 goto는 "commit"으로 기다린다.)
// 실행: QA_BASE=http://localhost:4312 node scripts/qa/server-wake.mjs
import http from "node:http";
import { BASE, launch, runAxe } from "./common.mjs";

const PORT = 4311;
const now = "2026-10-04T10:00:00+09:00";
const meta = {
  data_freshness: { market: "KRX", trade_date: "2026-10-01", session_close_at: null, generated_at: now, is_latest_trading_day: true, expected_last_trading_day: "2026-10-01", staleness_note: null },
  disclaimer: "x", generated_at: now,
};
const ok = (data) => JSON.stringify({ meta, data, error: null });
const err = (code) => JSON.stringify({ meta, data: null, error: { code, message: "x" } });
const item = (market) => ({ market, advancers_count: 10, decliners_count: 5, unchanged_count: 2, top_sectors_by_value: [{ sector: "반도체", trading_value_krw: 1000000000000 }], total_trading_value_krw: 3000000000000 });
const summary = ok({ ...item("ALL"), by_market: [item("KOSPI"), item("KOSDAQ")] });
const metrics = ok({ stock_code: "005930", name: "가짜전자", market: "KOSPI", return_pct: 1.2, return_rank_pct: 10, ma5_gap_pct: 1.1, ma20_gap_pct: 0.5, volume_anomaly_score: 0.7, per_percentile: 50, pbr_percentile: 40, market_cap_percentile: 5 });

// plan: 요청 순번(0부터) → { status, delay }. 경로별로 따로 센다.
let plan = () => ({ status: 200, delay: 0 });
const hits = {};
const server = http.createServer((req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  hits[path] = (hits[path] ?? 0) + 1;
  const n = hits[path] - 1;
  let body, status = 200, delay = 0;
  if (path === "/api/v1/market-summary" || path === "/api/v1/stocks/005930/metrics") {
    ({ status, delay } = plan(path, n));
    body = status === 200 ? (path.endsWith("summary") ? summary : metrics) : err("SERVICE_UNAVAILABLE");
  } else if (path === "/api/v1/stocks/999999/metrics") {
    status = 404; body = err("STOCK_NOT_FOUND");
  } else if (/\/api\/v1\/stocks\/.+\/prices/.test(path)) {
    status = 404; body = err("FEATURE_DISABLED");
  } else { body = ok({}); }
  setTimeout(() => { res.writeHead(status, { "content-type": "application/json" }); res.end(body); }, delay);
});
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

const b = await launch();
const res = [];
const rec = (n, pass, note = "") => { res.push(pass); console.log(`${pass ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const reset = () => { for (const k of Object.keys(hits)) delete hits[k]; };
const sec = (t0) => ((Date.now() - t0) / 1000).toFixed(1);

async function open(w, path) {
  const ctx = await b.newContext({ viewport: { width: w, height: 800 } });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
  return { ctx, p, errs };
}

// S1 빠른 응답: 안내 없음, 재시도 없음
for (const w of [360, 1280]) {
  reset(); plan = () => ({ status: 200, delay: 100 });
  const { ctx, p, errs } = await open(w);
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  await p.waitForSelector("h1.home-page__title", { timeout: 10000 });
  await p.waitForTimeout(1000);
  rec(`홈 빠른 응답 ${w}px: 데이터 화면 표시`, true, `${sec(t0)}s`);
  rec(`홈 빠른 응답 ${w}px: 안내 없음`, (await p.locator(".wake-notice").count()) === 0);
  rec(`홈 빠른 응답 ${w}px: API 호출 1회(재시도 없음)`, hits["/api/v1/market-summary"] === 1, `hits=${hits["/api/v1/market-summary"]}`);
  rec(`홈 빠른 응답 ${w}px: 페이지 오류 없음`, errs.length === 0, errs.join("|"));
  await ctx.close();
}

// S2 첫 2번 503 → 3번째 성공(깨어나는 중): 로딩 화면 → 안내 → 데이터
for (const w of [360, 1280]) {
  reset(); plan = (_p, n) => (n < 2 ? { status: 503, delay: 0 } : { status: 200, delay: 0 });
  const { ctx, p, errs } = await open(w);
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  const loadingAt = await p.locator('section[aria-busy="true"]').count();
  rec(`홈 503×2 후 성공 ${w}px: 응답 전에 로딩 화면이 즉시 보임`, loadingAt === 1);
  await p.waitForTimeout(1500);
  rec(`홈 503×2 후 성공 ${w}px: 1.5초엔 안내 숨김`, (await p.locator(".wake-notice").count()) === 0);
  const shown = await p.waitForSelector(".wake-notice", { timeout: 8000 }).then(() => true).catch(() => false);
  rec(`홈 503×2 후 성공 ${w}px: 4.5초 뒤 "깨우는 중" 안내 표시`, shown, `${sec(t0)}s`);
  if (shown) {
    const txt = await p.locator(".wake-notice").innerText();
    rec(`홈 503×2 후 성공 ${w}px: 안내 문구`, /서버를 깨우는 중/.test(txt) && /최대 1분/.test(txt));
    rec(`홈 503×2 후 성공 ${w}px: role=status 안에 표시`, (await p.locator('div[role="status"] .wake-notice').count()) === 1);
    rec(`홈 503×2 후 성공 ${w}px: 가로 넘침 없음`, !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    const axe = await runAxe(p);
    rec(`홈 503×2 후 성공 ${w}px: 로딩 화면 axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
  }
  await p.waitForSelector("h1.home-page__title", { timeout: 20000 });
  const total = (Date.now() - t0) / 1000;
  rec(`홈 503×2 후 성공 ${w}px: 재시도 끝에 데이터 화면 표시`, true, `${total.toFixed(1)}s`);
  rec(`홈 503×2 후 성공 ${w}px: 대기 시간이 3초+6초 근처(8~14초)`, total >= 8 && total <= 14, `${total.toFixed(1)}s`);
  rec(`홈 503×2 후 성공 ${w}px: API 호출 3회`, hits["/api/v1/market-summary"] === 3, `hits=${hits["/api/v1/market-summary"]}`);
  rec(`홈 503×2 후 성공 ${w}px: 데이터가 오면 안내 사라짐`, (await p.locator(".wake-notice").count()) === 0);
  rec(`홈 503×2 후 성공 ${w}px: 오류 화면 없음`, (await p.locator(".error-state").count()) === 0);
  rec(`홈 503×2 후 성공 ${w}px: 페이지 오류 없음`, errs.length === 0, errs.join("|"));
  await ctx.close();
}

// S3 느린 단일 응답(8초): 재시도 없이 기다린 뒤 성공, 안내는 중간에만
{
  reset(); plan = () => ({ status: 200, delay: 8000 });
  const { ctx, p } = await open(360);
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  const shown = await p.waitForSelector(".wake-notice", { timeout: 8000 }).then(() => true).catch(() => false);
  rec("홈 느린 응답(8초): 안내 표시", shown, `${sec(t0)}s`);
  await p.waitForSelector("h1.home-page__title", { timeout: 15000 });
  rec("홈 느린 응답(8초): 데이터 화면 + 안내 사라짐", (await p.locator(".wake-notice").count()) === 0);
  rec("홈 느린 응답(8초): API 호출 1회", hits["/api/v1/market-summary"] === 1, `hits=${hits["/api/v1/market-summary"]}`);
  await ctx.close();
}

// S4 계속 503: 3번 시도 후 기존 오류 화면 + 다시 시도 링크
{
  reset(); plan = () => ({ status: 503, delay: 0 });
  const { ctx, p } = await open(360);
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  await p.waitForSelector(".error-state", { timeout: 20000 });
  const total = (Date.now() - t0) / 1000;
  const txt = await p.locator(".error-state").innerText();
  rec("홈 계속 503: 3번 시도 뒤 오류 화면", /일시적인 오류가 발생했습니다/.test(txt) && /다시 시도/.test(txt), `${total.toFixed(1)}s`);
  rec("홈 계속 503: 대기 시간 8~14초", total >= 8 && total <= 14, `${total.toFixed(1)}s`);
  rec("홈 계속 503: API 호출 3회(무한 반복 없음)", hits["/api/v1/market-summary"] === 3, `hits=${hits["/api/v1/market-summary"]}`);
  rec("홈 계속 503: 로딩 안내는 오류 화면과 함께 남지 않음", (await p.locator(".wake-notice").count()) === 0);
  await ctx.close();
}

// S5 종목 상세: 404는 재시도 없이 즉시, 503 한 번 뒤 성공은 재시도
{
  reset(); plan = () => ({ status: 200, delay: 0 });
  const { ctx, p } = await open(360);
  const t0 = Date.now();
  await p.goto(BASE + "/stocks/999999", { waitUntil: "commit" });
  await p.waitForSelector("text=요청하신 종목 정보를 찾을 수 없습니다", { timeout: 10000 });
  rec("종목 상세 404: 종목 없음 화면", true, `${sec(t0)}s`);
  rec("종목 상세 404: metrics 호출 1회(재시도 안 함)", hits["/api/v1/stocks/999999/metrics"] === 1, `hits=${hits["/api/v1/stocks/999999/metrics"]}`);
  rec("종목 상세 404: 3초 안에 표시(대기 없음)", (Date.now() - t0) < 3000, `${sec(t0)}s`);
  await ctx.close();

  reset(); plan = (_p, n) => (n < 1 ? { status: 503, delay: 0 } : { status: 200, delay: 0 });
  const c2 = await open(360);
  const t1 = Date.now();
  await c2.p.goto(BASE + "/stocks/005930", { waitUntil: "commit" });
  rec("종목 상세 503 한 번 후 성공: 로딩 화면 즉시", (await c2.p.locator('section[aria-busy="true"]').count()) === 1);
  await c2.p.waitForSelector("text=가짜전자", { timeout: 15000 });
  const total = (Date.now() - t1) / 1000;
  rec("종목 상세 503 한 번 후 성공: 재시도 뒤 정상 화면", true, `${total.toFixed(1)}s`);
  rec("종목 상세 503 한 번 후 성공: 대기 약 3초(2.5~8초)", total >= 2.5 && total <= 8, `${total.toFixed(1)}s`);
  rec("종목 상세 503 한 번 후 성공: metrics 호출 2회", hits["/api/v1/stocks/005930/metrics"] === 2, `hits=${hits["/api/v1/stocks/005930/metrics"]}`);
  await c2.ctx.close();
}

await b.close();
server.close();
console.log(res.every(Boolean) ? "ALL PASS" : "SOME FAIL", `(${res.filter(Boolean).length}/${res.length})`);
process.exit(res.every(Boolean) ? 0 : 1);
