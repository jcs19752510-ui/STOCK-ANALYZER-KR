// DEC-065/066/076 점검: 서버 컴포넌트가 API를 부르는 화면(홈·종목 상세)에서 **대기 팝업이 없음**(DEC-076) · 일시적 실패 재시도 · 자동 새로고침 규칙(화면 표시 없이 유지).
// 이 스크립트가 가짜 API(포트 4311)를 직접 띄운다. 카운트다운을 12초로 줄인 운영 빌드가 4312에서 실행 중이어야 한다:
//   export NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:4311 PUBLIC_API_INTERNAL_TOKEN=qa NEXT_PUBLIC_WAKE_COUNTDOWN_SECONDS=12
//   npm run build && npx next start -p 4312
// 실행: QA_BASE=http://localhost:4312 QA_COUNTDOWN=12 node scripts/qa/server-wake.mjs
// (스트리밍 응답이라 DOMContentLoaded는 스트림이 끝나야 발생하므로 goto는 "commit"으로 기다린다.)
import fs from "node:fs";
import http from "node:http";
import { BASE, launch, runAxe, SHOTS } from "./common.mjs";

const PORT = 4311;
const CD = Number(process.env.QA_COUNTDOWN ?? 12); // 빌드에 넣은 카운트다운 초
const OUT = process.env.QA_SHOT_DIR ?? "/home/user/STOCK-ANALYZER-KR/docs/qa/2026-10-05";
fs.mkdirSync(OUT, { recursive: true });

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
const kst = (ms) => new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", hourCycle: "h23", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(ms));
const toSec = (hms) => { const [h, m, s] = hms.split(":").map(Number); return h * 3600 + m * 60 + s; };

async function open(w) {
  const ctx = await b.newContext({ viewport: { width: w, height: 800 } });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
  return { ctx, p, errs };
}
const dialog = (p) => p.locator('[role="dialog"].wake-dialog');
const remaining = async (p) => (await p.locator('[data-testid="wake-remaining"]').innerText()).trim();
const mark = (p) => p.evaluate(() => { window.__nr = 1; });
const marked = (p) => p.evaluate(() => window.__nr === 1);
const stored = (p) => p.evaluate(() => sessionStorage.getItem("wake-auto-reloads"));

// S1 빠른 응답: 팝업 없음, 재시도 없음
for (const w of [360, 1280]) {
  reset(); plan = () => ({ status: 200, delay: 100 });
  const { ctx, p, errs } = await open(w);
  await p.goto(BASE + "/", { waitUntil: "commit" });
  await p.waitForSelector("h1.home-page__title", { timeout: 10000 });
  await p.waitForTimeout(1000);
  rec(`빠른 응답 ${w}px: 팝업 없음`, (await dialog(p).count()) === 0);
  rec(`빠른 응답 ${w}px: API 호출 1회`, hits["/api/v1/market-summary"] === 1);
  rec(`빠른 응답 ${w}px: 페이지 오류 없음`, errs.length === 0, errs.join("|"));
  await ctx.close();
}

// S2 503×2 후 성공(약 15초): 4.5초가 지나도 팝업이 없고, 데이터가 먼저 오면 새로고침하지 않음
for (const w of [360, 1280]) {
  // 503 두 번(각 1.5초) → 3초·6초 대기 → 세 번째가 3초 걸려 성공: 약 15초. 자동 새로고침 시점(4.5초 + 카운트 12초)보다 먼저 데이터가 온다.
  reset(); plan = (_p, n) => (n < 2 ? { status: 503, delay: 1500 } : { status: 200, delay: 3000 });
  const { ctx, p, errs } = await open(w);
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  await mark(p);
  rec(`503×2 후 성공 ${w}px: 로딩 화면 즉시`, (await p.locator('section[aria-busy="true"]').count()) === 1);
  await p.waitForTimeout(6500); // 예전 팝업 표시 시점(4.5초)을 지나 6.5초
  rec(`503×2 후 성공 ${w}px: 4.5초 뒤에도 팝업 없음`, (await dialog(p).count()) === 0 && (await p.getByText("서버를 깨우는 중").count()) === 0, `${sec(t0)}s`);
  rec(`503×2 후 성공 ${w}px: 화면에 겹치는 창(role=dialog) 없음`, (await p.locator('[role="dialog"]').count()) === 0);
  await p.waitForSelector("h1.home-page__title", { timeout: 20000 });
  const total = (Date.now() - t0) / 1000;
  await p.waitForTimeout(500);
  rec(`503×2 후 성공 ${w}px: 데이터가 오면 정상 화면`, true, `${total.toFixed(1)}s`);
  rec(`503×2 후 성공 ${w}px: 새로고침 안 함(표시 유지)`, await marked(p));
  rec(`503×2 후 성공 ${w}px: API 호출 3회`, hits["/api/v1/market-summary"] === 3, `hits=${hits["/api/v1/market-summary"]}`);
  rec(`503×2 후 성공 ${w}px: 새로고침 횟수 저장값 없음`, (await stored(p)) === null);
  await p.waitForTimeout((CD + 1) * 1000);
  rec(`503×2 후 성공 ${w}px: 카운트가 끝나는 시점이 지나도 새로고침 없음`, await marked(p));
  rec(`503×2 후 성공 ${w}px: 페이지 오류 없음`, errs.length === 0, errs.join("|"));
  await ctx.close();
}

// S3 첫 요청만 18초 걸림: 팝업 없이 0초에 아직 로딩 중이면 자동 새로고침 → 새 요청은 빠르게 성공
{
  reset(); plan = (_p, n) => (n === 0 ? { status: 200, delay: 18000 } : { status: 200, delay: 100 });
  const { ctx, p } = await open(360);
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  await mark(p);
  await p.waitForTimeout(6000);
  rec("0초에 아직 로딩 중: 기다리는 동안 팝업 없음", (await dialog(p).count()) === 0);
  const reloaded = await p.waitForFunction(() => window.__nr !== 1, null, { timeout: (CD + 8) * 1000 }).then(() => true).catch(() => false);
  rec("0초에 아직 로딩 중: 자동 새로고침 실행(화면 표시 없이)", reloaded, `${sec(t0)}s`);
  await p.waitForSelector("h1.home-page__title", { timeout: 15000 });
  await p.waitForTimeout(800);
  rec("0초 새로고침 뒤: 데이터 화면 표시, 팝업 없음", (await dialog(p).count()) === 0);
  rec("0초 새로고침 뒤: 데이터 도착 후 새로고침 횟수 저장값 삭제", (await stored(p)) === null);
  rec("0초 새로고침 뒤: API 호출 2회(원래 요청 + 새로고침)", hits["/api/v1/market-summary"] === 2, `hits=${hits["/api/v1/market-summary"]}`);
  await ctx.close();
}

// S5 브라우저 요청이 느린 경우(/stocks 검색): 팝업 없음, 새로고침하지 않으며 입력은 유지
{
  const { ctx, p } = await open(360);
  await p.route("**/api/v1/**", async (r) => {
    await new Promise((s) => setTimeout(s, (CD + 9) * 1000));
    await r.fulfill({ status: 200, contentType: "application/json", body: ok([]) });
  });
  await p.goto(BASE + "/stocks", { waitUntil: "domcontentloaded" });
  await mark(p);
  const box = p.locator("#stock-search-input");
  await box.fill("삼성"); await box.press("Enter").catch(() => {});
  await p.waitForTimeout(6500);
  rec("브라우저 요청 지연: 4.5초 뒤에도 팝업 없음", (await dialog(p).count()) === 0 && (await p.getByText("서버를 깨우는 중").count()) === 0);
  await p.waitForTimeout((CD + 4) * 1000);
  rec("브라우저 요청 지연: 카운트 시점이 지나도 팝업 없음", (await dialog(p).count()) === 0);
  rec("브라우저 요청 지연: 새로고침 안 함", await marked(p));
  rec("브라우저 요청 지연: 입력한 검색어 유지", (await box.inputValue()) === "삼성");
  await ctx.close();
}

// S6 계속 503: 3번 시도 뒤 기존 오류 화면, 팝업 남지 않음
{
  reset(); plan = () => ({ status: 503, delay: 0 });
  const { ctx, p } = await open(360);
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  await p.waitForSelector(".error-state", { timeout: 20000 });
  const total = (Date.now() - t0) / 1000;
  rec("계속 503: 3번 시도 뒤 오류 화면 + 다시 시도", /일시적인 오류가 발생했습니다/.test(await p.locator(".error-state").innerText()), `${total.toFixed(1)}s`);
  rec("계속 503: API 호출 3회", hits["/api/v1/market-summary"] === 3);
  await p.waitForTimeout(500);
  rec("계속 503: 오류 화면과 팝업이 함께 남지 않음", (await dialog(p).count()) === 0);
  await ctx.close();
}

// S7 종목 상세: 404는 재시도·팝업 없이 즉시, 503 한 번 뒤 성공은 재시도
{
  reset(); plan = () => ({ status: 200, delay: 0 });
  const { ctx, p } = await open(360);
  const t0 = Date.now();
  await p.goto(BASE + "/stocks/999999", { waitUntil: "commit" });
  await p.waitForSelector("text=요청하신 종목 정보를 찾을 수 없습니다", { timeout: 10000 });
  rec("종목 상세 404: 즉시 종목 없음 화면, 팝업 없음", (Date.now() - t0) < 3000 && (await dialog(p).count()) === 0, `${sec(t0)}s`);
  rec("종목 상세 404: 호출 1회(재시도 안 함)", hits["/api/v1/stocks/999999/metrics"] === 1);
  await ctx.close();

  reset(); plan = (_p, n) => (n < 1 ? { status: 503, delay: 0 } : { status: 200, delay: 0 });
  const c2 = await open(360);
  const t1 = Date.now();
  await c2.p.goto(BASE + "/stocks/005930", { waitUntil: "commit" });
  await c2.p.waitForSelector("text=가짜전자", { timeout: 15000 });
  const total = (Date.now() - t1) / 1000;
  rec("종목 상세 503 한 번 후 성공: 재시도로 정상 화면, 호출 2회", hits["/api/v1/stocks/005930/metrics"] === 2 && total <= 8, `${total.toFixed(1)}s`);
  await c2.ctx.close();
}

// (마지막에 실행: 이 시험이 남기는 서버 쪽 재시도가 다른 시험의 호출 수를 흐리지 않게 한다)
// S4 계속 느림: 새로고침은 최대 2회, 그 뒤엔 반복하지 않음
{
  reset(); plan = () => ({ status: 200, delay: 30000 });
  const { ctx, p } = await open(360);
  // 같은 문서 안의 주소 변경(history.replaceState)은 세지 않고, 실제 문서 요청만 센다.
  let navs = 0;
  p.on("request", (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame() && new URL(r.url()).pathname === "/") navs += 1; });
  const t0 = Date.now();
  await p.goto(BASE + "/", { waitUntil: "commit" });
  // 팝업이 없으므로 문서 요청 횟수로 새로고침을 센다: 주기마다(약 4.5초 + 카운트 + 여유) 한 번씩, 총 3번에서 멈춰야 한다.
  const waitNavs = async (n) => { for (let i = 0; i < (CD + 12) * 2 && navs < n; i += 1) await p.waitForTimeout(500); };
  await waitNavs(2); await p.waitForTimeout(1500); // 1회차 새로고침
  await waitNavs(3);                               // 2회차 새로고침
  const navsAfterThird = navs;
  await p.waitForTimeout((CD + 8) * 1000);          // 3회차는 새로고침 없이 끝남
  rec("계속 느림: 화면 로딩은 총 3번(최초 + 자동 새로고침 2회)", navsAfterThird === 3, `문서 요청=${navsAfterThird}, ${sec(t0)}s`);
  rec("계속 느림: 내내 팝업 없음", (await dialog(p).count()) === 0);
  rec("계속 느림: 그 뒤 추가 새로고침 없음(반복 방지)", navs === 3, `문서 요청=${navs}`);
  rec("계속 느림: 저장된 새로고침 횟수 2", (await stored(p)) === "2");
  await ctx.close();
}

await b.close();
server.closeAllConnections?.();
server.close();
console.log(res.every(Boolean) ? "ALL PASS" : "SOME FAIL", `(${res.filter(Boolean).length}/${res.length})`);
process.exit(res.every(Boolean) ? 0 : 1);
