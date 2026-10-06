// 실시간 화면 시험(DEC-084). 실제 스택: 모의 KIS REST(4413) + 모의 KIS 웹소켓(4414, 이 스크립트가 직접 띄우고 끊었다 켠다) + API(4411) + 프런트(4412).
//
//   dev  단계: NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:4411 npx next dev --webpack -p 4412
//              node scripts/qa/live-stream.mjs dev        (모의 웹소켓 4414는 비워 둘 것: 스크립트가 직접 띄운다)
//   prod 단계: 같은 변수에서 NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED 없이 `next build` → `next start -p 4412`
//              node scripts/qa/live-stream.mjs prod
//
// 실제 종목 상세(`app/stocks/[code]`)는 서버가 DB를 읽어야 열리므로, 같은 부품을 같은 순서로 붙인 임시 페이지(`live-stream-harness.page.tsx`)를
// `src/app/qa-live/page.tsx`로 복사해 쓰고 끝나면 지운다. Playwright 설치 위치는 README.md 참고(QA_PW_DIR).
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { launch, measureFn, runAxe, sleep } from "./common.mjs";

const PHASE = process.argv[2] ?? "dev";
const BASE = process.env.QA_BASE ?? "http://localhost:4412";
const API = process.env.QA_API ?? "http://127.0.0.1:4411";
const PY = process.env.QA_PY ?? "/var/tmp/venv312/bin/python";
const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const HARNESS_SRC = fileURLToPath(new URL("./live-stream-harness.page.tsx", import.meta.url));
const HARNESS_DST = fileURLToPath(new URL("../../src/app/qa-live/page.tsx", import.meta.url));
const OUT = process.env.QA_OUT ?? "/tmp/claude-0/qa-live";
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const rec = (name, ok, note = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${note ? "  — " + note : ""}`);
};

// ── 모의 웹소켓 서버(스크립트가 소유) ───────────────────────────────────────
let ws = null;
function startWs() {
  ws = spawn(PY, ["scripts/mock_kis_ws_server.py", "--port", "4414"], { cwd: ROOT, stdio: "ignore" });
}
async function stopWs() {
  if (!ws) return;
  const p = ws;
  ws = null;
  await new Promise((r) => { p.once("exit", r); p.kill("SIGKILL"); });
}

const getJson = (path) =>
  new Promise((resolve, reject) => {
    http.get(API + path, (res) => {
      let b = "";
      res.on("data", (c) => (b += c));
      res.on("end", () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
    }).on("error", reject);
  });
const realtimeCodes = async () => (await getJson("/api/v1/local/realtime/status")).data.codes;
async function waitFor(fn, ms = 15000, step = 250) {
  const end = Date.now() + ms;
  for (;;) {
    try { const v = await fn(); if (v) return v; } catch { /* 다시 시도 */ }
    if (Date.now() > end) return false;
    await sleep(step);
  }
}

// ── 페이지 도우미 ──────────────────────────────────────────────────────
const INIT = () => {
  // EventSource 생성 횟수와 현재 열린 수를 센다
  const Native = window.EventSource;
  window.__es = { created: 0, open: 0, urls: [] };
  window.EventSource = class extends Native {
    constructor(url, init) {
      super(url, init);
      window.__es.created += 1;
      window.__es.open += 1;
      window.__es.urls.push(String(url));
      const origClose = this.close.bind(this);
      let closed = false;
      this.close = () => { if (!closed) { closed = true; window.__es.open -= 1; } origClose(); };
    }
  };
  // 현재가 강조(.quote-flash) 요소가 생긴 횟수와 현재가가 바뀐 횟수
  window.__flash = { flashes: 0, priceChanges: 0, last: null };
  new MutationObserver((muts) => {
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1 && (n.matches?.(".quote-flash") || n.querySelector?.(".quote-flash"))) window.__flash.flashes += 1;
      }
      const el = document.querySelector(".quote-band__close");
      if (el && el.textContent !== window.__flash.last) {
        if (window.__flash.last !== null) window.__flash.priceChanges += 1;
        window.__flash.last = el.textContent;
      }
    }
    const el = document.querySelector(".quote-band__close");
    if (el && el.classList.contains("quote-flash")) window.__flash.flashed = true;
  }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
};

const badge = (page) => page.locator("p.live-badge");
const badgeText = async (page) => ((await badge(page).first().textContent().catch(() => "")) ?? "").replace(/\s+/g, " ").trim();
async function waitBadge(page, re, ms = 20000) {
  return waitFor(async () => re.test(await badgeText(page)), ms, 200);
}
async function newLivePage(browser, { width = 1280, height = 900, reducedMotion = "no-preference", init = true } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion });
  const page = await ctx.newPage();
  const log = { requests: [], errors: [] };
  page.on("request", (r) => log.requests.push(r.url()));
  page.on("pageerror", (e) => log.errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") log.errors.push("console: " + m.text()); });
  if (init) await page.addInitScript(INIT);
  return { ctx, page, log };
}
const isPoll = (u) => /\/api\/v1\/local\/stocks\/[^/]+\/(orderbook|ticks|minutes)/.test(u);
const isStream = (u) => /\/api\/v1\/local\/stocks\/[^/]+\/stream/.test(u);
const goLive = (page, code = "005930") => page.goto(`${BASE}/qa-live?code=${code}`, { waitUntil: "domcontentloaded" });

async function sample(page, selector, times = 8, gap = 500) {
  const seen = new Set();
  for (let i = 0; i < times; i++) {
    seen.add(((await page.locator(selector).first().textContent().catch(() => "")) ?? "").replace(/\s+/g, " "));
    await sleep(gap);
  }
  return seen;
}

// ═══════════════════════════════ dev 단계 ═════════════════════════════════
async function dev(browser) {
  // ① ② ③ 갱신·폴링 0건·연결 1개 ────────────────────────────────────────
  {
    const { ctx, page, log } = await newLivePage(browser);
    await goLive(page);
    const connected = await waitBadge(page, /실시간 연결됨/);
    rec("① 배지: 실시간 연결됨 표시", connected, await badgeText(page));
    rec("① 배지 문구 형식(마지막 수신 HH:MM:SS)", /실시간 연결됨 · 마지막 수신 \d{2}:\d{2}:\d{2}/.test(await badgeText(page)), await badgeText(page));
    const role = await badge(page).first().getAttribute("role");
    rec("⑧ 배지 role=status", role === "status");
    await waitFor(() => page.evaluate(() => document.querySelector(".quote-band__price")?.dataset.live === "true"), 10000);
    const prices = await sample(page, ".quote-band__close", 14, 500);
    rec("① 현재가가 새로고침 없이 갱신(서로 다른 값 ≥2)", prices.size >= 2, [...prices].join(" / "));
    const basis = (await page.locator(".stock-quote__basis").textContent()) ?? "";
    rec("① 기준 안내가 '내 증권사 실시간 시세(본인 전용)'로 전환", basis.includes("내 증권사 실시간 시세(본인 전용)") && !basis.includes("종가 기준 ·"), basis.replace(/\s+/g, " ").slice(0, 80));
    const flashInfo = await page.evaluate(() => ({ ...window.__flash }));
    rec("① 현재가 변경 시 강조(.quote-flash) 발생", flashInfo.flashes >= 1, `강조 ${flashInfo.flashes}회/가격 변경 ${flashInfo.priceChanges}회`);

    await page.getByRole("tab", { name: "호가", exact: true }).click();
    await page.waitForSelector(".orderbook__table", { timeout: 15000 });
    const books = await sample(page, ".orderbook__table tbody", 10, 500);
    rec("① 호가가 새로고침 없이 갱신(서로 다른 값 ≥2)", books.size >= 2, `${books.size}종`);
    await page.getByRole("tab", { name: "체결", exact: true }).click();
    await page.waitForSelector(".daily-table tbody tr", { timeout: 15000 });
    const ticks = await sample(page, ".daily-table tbody tr", 10, 500);
    rec("① 체결 첫 행이 새로고침 없이 갱신(서로 다른 값 ≥2)", ticks.size >= 2, `${ticks.size}종`);
    const rows = await page.locator(".daily-table tbody tr").count();
    rec("① 체결 표는 최대 120행", rows > 0 && rows <= 120, `${rows}행`);

    await page.getByRole("tab", { name: "차트", exact: true }).click();
    await page.getByRole("button", { name: "분봉 간격 선택" }).click();
    await page.getByRole("menuitem", { name: "5분", exact: true }).click();
    const chartOk = await waitFor(() => page.locator(".stock-chart__svg").count().then((n) => n > 0), 15000);
    rec("① 차트 분봉(5분)이 라이브 데이터로 그려짐", chartOk);
    const sig1 = await page.evaluate(() => document.querySelector(".stock-chart__svg")?.innerHTML.length ?? 0);
    await page.getByRole("button", { name: "틱 묶음 선택" }).click();
    await page.getByRole("menuitem", { name: "3틱", exact: true }).click();
    await sleep(500);
    const sigA = await page.evaluate(() => document.querySelector(".stock-chart__svg")?.innerHTML ?? "");
    await sleep(4000);
    const sigB = await page.evaluate(() => document.querySelector(".stock-chart__svg")?.innerHTML ?? "");
    rec("① 차트 틱(3틱)이 새로고침 없이 갱신", sigA.length > 0 && sigA !== sigB, `${sigA.length}→${sigB.length}`);
    void sig1;

    const polls = log.requests.filter(isPoll);
    rec("② 호가·체결·분봉 폴링 요청 0건(탭·차트 모두 돌아다닌 뒤)", polls.length === 0, polls.slice(0, 3).join(" | "));
    const es = await page.evaluate(() => ({ ...window.__es }));
    rec("③ EventSource 생성 1개·열린 연결 1개(탭 전환 후)", es.created === 1 && es.open === 1, JSON.stringify({ created: es.created, open: es.open }));
    rec("③ /stream 네트워크 요청 1건", log.requests.filter(isStream).length === 1, String(log.requests.filter(isStream).length));
    const live = await page.evaluate(() => [...document.querySelectorAll("[aria-live]")].filter((e) => e.getAttribute("aria-live") !== "off").filter((e) => e.tagName.toLowerCase() !== "next-route-announcer" && !e.closest("next-route-announcer")).map((e) => e.tagName.toLowerCase()));
    rec("⑧ 초당 갱신되는 영역에 켜진 aria-live 없음(Next 경로 안내기 제외, 차트 읽기 줄은 off)", live.length === 0, `aria-live 요소 ${live.join(",") || "없음"}`);
    rec("① 페이지 오류 0건", log.errors.length === 0, log.errors.slice(0, 2).join(" | "));
    const codes = await realtimeCodes();
    rec("⑤ 화면을 열어 둔 동안 서버 구독에 종목이 있음", codes.includes("005930"), JSON.stringify(codes));

    // ④ 모의 웹소켓을 끊었다 켜면 배지가 재연결 중 → 연결됨
    await page.getByRole("tab", { name: "체결", exact: true }).click();
    await stopWs();
    const reconnecting = await waitBadge(page, /재연결 중|끊겼습니다/, 45000);
    const t1 = await badgeText(page);
    rec("④ 모의 웹소켓 종료 → 배지 '재연결 중'", reconnecting && /재연결 중/.test(t1), t1);
    rec("④ 재연결 중에도 마지막 값은 화면에 남아 있음", (await page.locator(".daily-table tbody tr").count()) > 0);
    startWs();
    const back = await waitBadge(page, /실시간 연결됨/, 90000);
    rec("④ 모의 웹소켓 복구 → 배지 '실시간 연결됨'", back, await badgeText(page));
    // 모의 서버를 다시 띄우면 누적 거래량 카운터가 처음부터 다시 시작해(실제 증권사는 줄어들지 않는다) 서버가 한동안 체결을 걸러 낸다 → 호가로 확인
    await page.getByRole("tab", { name: "호가", exact: true }).click();
    const afterBooks = await sample(page, ".orderbook__table tbody", 8, 500);
    rec("④ 복구 뒤 호가가 다시 갱신", afterBooks.size >= 2, `${afterBooks.size}종`);
    rec("④ 복구 과정에서도 EventSource는 1개 유지(새로 만들지 않음)", (await page.evaluate(() => window.__es.created)) === 1);

    // ⑤ 화면을 떠나면(클라이언트 이동으로 언마운트) 구독 해지
    await page.locator('a.quote-band__icon[href="/stocks"]').click();
    const released = await waitFor(async () => !(await realtimeCodes()).includes("005930"), 15000, 400);
    rec("⑤ 화면을 떠나면(언마운트) 서버 구독 해지", released, JSON.stringify(await realtimeCodes()));
    await ctx.close();
  }

  // ⑤ 탭을 닫아도 해지
  {
    const { ctx, page } = await newLivePage(browser);
    await goLive(page, "000660");
    await waitBadge(page, /실시간 연결됨/);
    const had = (await realtimeCodes()).includes("000660");
    await ctx.close();
    const released = await waitFor(async () => !(await realtimeCodes()).includes("000660"), 15000, 400);
    rec("⑤ 탭을 닫으면 서버 구독 해지", had && released);
  }

  // ⑥ 종목 21개 초과 안내
  {
    const held = [];
    const codes = Array.from({ length: 20 }, (_, i) => String(100001 + i));
    for (const c of codes) {
      // 증권사 시작 값 조회가 자체 간격 제한이 있어 하나씩, 200 응답(스트림)을 확인하며 연다
      for (let attempt = 0; attempt < 6; attempt++) {
        const res = await new Promise((resolve) => { http.get(`${API}/api/v1/local/stocks/${c}/stream`, resolve).on("error", () => resolve(null)); });
        if (res && res.statusCode === 200) { held.push(res); res.on("data", () => {}); break; }
        res?.destroy();
        await sleep(1500);
      }
    }
    const status = await getJson("/api/v1/local/realtime/status");
    rec("⑥ 사전 조건: 서버에 동시 종목 20개 구독 중", status.data.codes.length === 20, `${status.data.codes.length}개`);
    const { ctx, page, log } = await newLivePage(browser);
    await goLive(page, "005930");
    const shown = await waitBadge(page, /20개/, 20000);
    const txt = await badgeText(page);
    rec("⑥ 21번째 종목: 동시 종목 한도 안내가 배지에 표시", shown, txt);
    await page.getByRole("tab", { name: "호가", exact: true }).click();
    const polled = await waitFor(() => log.requests.some((u) => /\/orderbook/.test(u)), 10000);
    rec("⑥ 한도 초과 시 기존 폴링 화면으로 되돌아감(호가 요청 발생)", polled);
    const bookRows = await waitFor(() => page.locator(".orderbook__row").count().then((n) => n > 0), 10000);
    const realErrors = log.errors.filter((e) => !/Failed to load resource/.test(e)); // 거절된 스트림 연결의 브라우저 기본 콘솔 문구는 예상된 것
    rec("⑥ 폴링 화면에 호가가 표시됨(깨지지 않음, 예상 밖 오류 0)", bookRows && realErrors.length === 0, realErrors.slice(0, 2).join(" | "));
    rec("⑥ 거절된 뒤 스트림을 다시 열지 않음(/stream 요청 ≤2: EventSource+진단 fetch)", log.requests.filter(isStream).length <= 2, String(log.requests.filter(isStream).length));
    held.forEach((r) => r.destroy());
    await ctx.close();
    await waitFor(async () => (await realtimeCodes()).length === 0, 15000, 400);
  }

  // 기능 꺼짐·권한 없음·미설정 → 폴링으로 되돌아가고 배지가 안내
  for (const [status, code, expect] of [[404, "FEATURE_DISABLED", /개인 로컬 모드가 꺼져/], [403, "FORBIDDEN", /권한/], [503, "LOCAL_INTRADAY_NOT_CONFIGURED", /앱키/]]) {
    const { ctx, page, log } = await newLivePage(browser);
    await page.route(/\/local\/stocks\/[^/]+\/stream/, (r) =>
      r.fulfill({ status, contentType: "application/json", body: JSON.stringify({ data: null, error: { code, message: "x" } }) }));
    await goLive(page);
    const ok = await waitBadge(page, expect, 20000);
    rec(`⑥ HTTP ${status}(${code}) → 배지 안내`, ok, await badgeText(page));
    await page.getByRole("tab", { name: "체결", exact: true }).click();
    const polled = await waitFor(() => log.requests.some((u) => /\/ticks/.test(u)), 10000);
    const shownRows = await waitFor(() => page.locator(".daily-table tbody tr").count().then((n) => n > 0), 10000);
    rec(`⑥ HTTP ${status} → 체결 탭은 기존 폴링으로 동작(요청 발생·행 표시)`, polled && shownRows);
    rec(`⑥ HTTP ${status} → 페이지 오류 없음`, log.errors.filter((e) => !/Failed to load resource|EventSource/.test(e)).length === 0, log.errors.slice(0, 2).join(" | "));
    await ctx.close();
  }

  // end 이벤트 → 다시 연결하지 않음
  {
    const { ctx, page, log } = await newLivePage(browser);
    await page.route(/\/local\/stocks\/[^/]+\/stream/, (r) =>
      r.fulfill({ status: 200, contentType: "text/event-stream", body: 'retry: 500\n\nevent: end\ndata: {"reason":"forbidden"}\n\n' }));
    await goLive(page);
    const ended = await waitBadge(page, /종료/, 15000);
    await sleep(4000);
    rec("end 이벤트: 배지에 종료 안내", ended, await badgeText(page));
    rec("end 이벤트: 4초 넘게 지나도 다시 연결하지 않음(/stream 1건)", log.requests.filter(isStream).length === 1, String(log.requests.filter(isStream).length));
    await ctx.close();
  }

  // 모션 줄이기: 강조 생략
  {
    const { ctx, page } = await newLivePage(browser, { reducedMotion: "reduce" });
    await goLive(page);
    await waitBadge(page, /실시간 연결됨/);
    await sleep(9000);
    const f = await page.evaluate(() => ({ ...window.__flash }));
    rec("prefers-reduced-motion: 현재가가 바뀌어도 강조 없음", f.priceChanges >= 1 && f.flashes === 0 && !f.flashed, `가격 변경 ${f.priceChanges}회, 강조 ${f.flashes}회`);
    await ctx.close();
  }

  // ⑦ ⑧ 폭·접근성
  for (const w of [320, 360, 412, 1280]) {
    const { ctx, page, log } = await newLivePage(browser, { width: w, height: w >= 1000 ? 900 : 800 });
    await goLive(page);
    await waitBadge(page, /실시간 연결됨/);
    const states = [
      ["차트(일봉)", async () => {}],
      ["호가", async () => { await page.getByRole("tab", { name: "호가", exact: true }).click(); await page.waitForSelector(".orderbook__table"); }],
      ["체결", async () => { await page.getByRole("tab", { name: "체결", exact: true }).click(); await page.waitForSelector(".daily-table tbody tr"); }],
      ["차트(분봉)", async () => {
        await page.getByRole("tab", { name: "차트", exact: true }).click();
        await page.getByRole("button", { name: "분봉 간격 선택" }).click();
        await page.getByRole("menuitem", { name: "5분", exact: true }).click();
        await page.waitForSelector(".stock-chart__svg");
      }],
    ];
    let overflowBad = [], clippedBad = [], overlapBad = [], smallBad = [], axeBad = [];
    for (const [label, go] of states) {
      await go();
      await sleep(700);
      const m = await page.evaluate(measureFn);
      if (m.overflow) overflowBad.push(`${label}: ${m.scrollWidth}>${m.vw}`);
      const clipped = m.clipped.filter((c) => !c.inScroller);
      if (clipped.length) clippedBad.push(`${label}: ${clipped.slice(0, 2).map((c) => c.n).join(",")}`);
      const overlaps = m.overlaps.filter((o) => !(/stock-tabs__tab/.test(o.a + o.b) && /stock-tabs__more/.test(o.a + o.b)));
      if (overlaps.length) overlapBad.push(`${label}: ${overlaps.slice(0, 2).map((o) => o.a + "×" + o.b).join(",")}`);
      const small = m.small.filter((s) => !s.inline && /live-badge|orderbook|quote-flash|quote-band__close/.test(s.n));
      if (small.length) smallBad.push(`${label}: ${small.map((s) => s.n).join(",")}`);
      if (w === 360 || w === 1280) await page.screenshot({ path: `${OUT}/live-${w}-${label.replace(/[()]/g, "")}.png` });
      if (w === 390 || w === 360 || w === 1280) {
        const v = await runAxe(page);
        if (v.length) axeBad.push(`${label}: ${v.map((x) => `${x.id}(${x.nodes.length}) ${x.nodes[0]?.target}`).join("; ")}`);
      }
    }
    rec(`⑦ [${w}px] 가로 넘침 없음(차트·호가·체결·분봉)`, overflowBad.length === 0, overflowBad.join(" | "));
    rec(`⑦ [${w}px] 잘림 없음(스크롤 영역 밖)`, clippedBad.length === 0, clippedBad.join(" | "));
    rec(`⑦ [${w}px] 겹침 없음(기존 탭 줄: 스크롤되는 탭이 "탭 전체 보기" 버튼 밑으로 지나가는 것은 제외)`, overlapBad.length === 0, overlapBad.join(" | "));
    rec(`⑦ [${w}px] 새·변경 요소의 터치 대상 44px 미만 없음`, smallBad.length === 0, smallBad.join(" | "));
    if (w === 360 || w === 1280) rec(`⑧ [${w}px] axe(wcag2a/aa·21a/aa·best-practice) 위반 0`, axeBad.length === 0, axeBad.join(" | "));
    rec(`⑦ [${w}px] 페이지 오류 0건`, log.errors.length === 0, log.errors.slice(0, 2).join(" | "));
    await ctx.close();
  }
  // axe는 390에서도 한 번(모바일 대표 폭)
  {
    const { ctx, page } = await newLivePage(browser, { width: 390, height: 844 });
    await goLive(page);
    await waitBadge(page, /실시간 연결됨/);
    let bad = [];
    for (const name of ["호가", "체결"]) {
      await page.getByRole("tab", { name, exact: true }).click();
      await sleep(900);
      const v = await runAxe(page);
      if (v.length) bad.push(`${name}: ${v.map((x) => x.id).join(",")}`);
    }
    rec("⑧ [390px] axe 위반 0(호가·체결)", bad.length === 0, bad.join(" | "));
    await ctx.close();
  }
}

// ═══════════════════════════════ prod 단계 ═════════════════════════════════
async function prod(browser) {
  const { ctx, page, log } = await newLivePage(browser);
  await goLive(page);
  await sleep(6000);
  const es = await page.evaluate(() => ({ ...window.__es }));
  rec("⑨ 운영 빌드: 스트림·로컬 API 요청 0건", log.requests.filter((u) => isStream(u) || /\/api\/v1\/local\//.test(u)).length === 0, log.requests.filter((u) => /\/local\//.test(u)).join(" | "));
  rec("⑨ 운영 빌드: EventSource 생성 0개", es.created === 0, String(es.created));
  rec("⑨ 운영 빌드: 연결 배지 요소 없음", (await page.locator(".live-badge").count()) === 0);
  rec("⑨ 운영 빌드: 호가·체결 탭 없음", (await page.getByRole("tab", { name: "호가", exact: true }).count()) === 0 && (await page.getByRole("tab", { name: "체결", exact: true }).count()) === 0);
  const basis = (await page.locator(".stock-quote__basis").textContent()) ?? "";
  rec("⑨ 운영 빌드: 기준 안내는 기존 '종가 기준' 문구", /종가 기준 · 일 단위 종가 기준 시세이며 실시간 시세가 아닙니다/.test(basis.replace(/\s+/g, " ")), basis.replace(/\s+/g, " ").slice(0, 100));
  rec("⑨ 운영 빌드: 현재가 요소에 라이브 표시(data-live) 없음", (await page.locator('.quote-band__price[data-live="true"]').count()) === 0);
  rec("⑨ 운영 빌드: 페이지 오류 0건", log.errors.length === 0, log.errors.slice(0, 2).join(" | "));
  await ctx.close();
}

// ═══════════════════════════════ 실행 ═════════════════════════════════════
fs.mkdirSync(fileURLToPath(new URL("../../src/app/qa-live", import.meta.url)), { recursive: true });
fs.copyFileSync(HARNESS_SRC, HARNESS_DST);
let browser;
try {
  if (PHASE === "dev") startWs();
  await sleep(1500);
  browser = await launch();
  await (PHASE === "prod" ? prod : dev)(browser);
} finally {
  if (browser) await browser.close();
  await stopWs();
  if (process.env.QA_KEEP_HARNESS !== "1") fs.rmSync(fileURLToPath(new URL("../../src/app/qa-live", import.meta.url)), { recursive: true, force: true });
}
const pass = results.filter((r) => r.ok).length;
const fail = results.length - pass;
console.log(`\n합계: PASS ${pass} / FAIL ${fail} (총 ${results.length})`);
process.exit(fail === 0 ? 0 : 1);
