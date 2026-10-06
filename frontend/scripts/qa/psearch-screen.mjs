// 증권사 조건검색 화면 시험(DEC-088). 백엔드·증권사 없이 이 스크립트가 직접 띄우는 **가짜 JSON 서버**(계약서 `docs/stock-detail/09-psearch-api-contract.md` 모양)와
// 프런트(스크립트가 직접 `next dev`/`next build`+`next start`로 띄우고 PID로 끝냄)만으로 실제 브라우저(Playwright)를 돌린다. 저장소에 남기는 임시 파일 없음.
//
//   dev  단계: NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true 로 `next dev`(포트 4512) — 표·갱신·간격·탭 가림·상태 안내·폭·axe·접근 불가 숨김
//   prod 단계: 그 변수 없이 `npm run build` → `next start` — 운영 빌드에서는 전환 항목·화면 내용·`/psearch` 요청 0건
//
//   node scripts/qa/psearch-screen.mjs dev     |     node scripts/qa/psearch-screen.mjs prod
// Playwright 설치 위치는 README.md 참고(QA_PW_DIR). 스크린샷은 docs/qa/2026-10-06/ 에 저장한다.
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { launch, measureFn, runAxe, sleep } from "./common.mjs";

const PHASE = process.argv[2] ?? "dev";
const API_PORT = Number(process.env.QA_API_PORT ?? 4511);
const WEB_PORT = Number(process.env.QA_WEB_PORT ?? 4512);
const WEB = `http://localhost:${WEB_PORT}`;
const API = `http://127.0.0.1:${API_PORT}`;
const FRONT = fileURLToPath(new URL("../..", import.meta.url));
const SHOTS = process.env.QA_SHOTS ?? fileURLToPath(new URL("../../../docs/qa/2026-10-06/", import.meta.url));
const OUT = process.env.QA_OUT ?? "/tmp/claude-0/qa-psearch";
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const rec = (name, ok, note = "") => {
  results.push({ name, ok: !!ok, note });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${note ? "  — " + note : ""}`);
};

// ═══════════════════════ 가짜 JSON 서버 ═══════════════════════
// 시간에 따라 종목이 바뀐다: 6초마다 보이는 5종목 창이 한 칸씩 이동(한 종목 편입·한 종목 이탈). 서버가 처음 본 시각(entered_at)·변화 목록(changes)도 계약대로 만든다.
const UNIVERSE = [
  ["005930", "삼성전자", "KOSPI"],
  ["999999", null, null], // 이름·시장·시세 모두 없음 → 화면은 코드만, 가격 "-"
  ["373220", "아주아주긴이름의종목명테스트주식회사우선주", "KOSDAQ"],
  ["000660", "SK하이닉스", "KOSPI"],
  ["035420", "NAVER", "KOSPI"],
  ["035720", "카카오", "KOSPI"],
  ["247540", "에코프로비엠", "KOSDAQ"],
  ["086520", "에코프로", "KOSDAQ"],
  ["068270", "셀트리온", "KOSPI"],
];
const ctl = { cond: "ok", res: "normal", ttl: 5, slot: 6, delay: {}, t0: Date.now() / 1000 };
let seen = null; // code → entered_at
let changes = [];
let lastSet = null;
const serverLog = [];
const sec = () => Date.now() / 1000;

function resetTracker() {
  ctl.t0 = sec();
  seen = null;
  changes = [];
  lastSet = null;
  serverLog.length = 0;
}
function currentCodes(now) {
  const slot = Math.floor((now - ctl.t0) / ctl.slot);
  return Array.from({ length: 5 }, (_, i) => UNIVERSE[(slot + i) % UNIVERSE.length][0]);
}
function track(now) {
  const set = currentCodes(now);
  if (seen === null) {
    seen = new Map(set.map((c) => [c, Math.floor(ctl.t0 - 600)])); // 서버가 한참 전부터 보던 종목
  } else {
    const added = set.filter((c) => !lastSet.includes(c));
    const removed = lastSet.filter((c) => !set.includes(c));
    for (const c of added) seen.set(c, Math.floor(now));
    for (const c of removed) seen.delete(c);
    if (added.length || removed.length) changes = [{ at: Math.floor(now), added, removed }, ...changes].slice(0, 20);
  }
  lastSet = set;
  return set;
}
const hundred = () => Array.from({ length: 100 }, (_, i) => `X${String(i).padStart(5, "0")}`);
const hash = (code) => [...code].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7);

function resultsBody(seq, now) {
  const base = { seq, count: 0, capped: false, empty: false, empty_message: null, changes: [], fields: ["code", "name"], fetched_at: Math.floor(now), age_seconds: 0, cache_ttl_seconds: ctl.ttl, stale: ctl.res === "stale" };
  if (seq === "1") return { ...base, items: [], empty: true, empty_message: "조회된 종목이 없습니다. (모의 증권사 문구 — 그대로 보여야 함)" };
  if (seq === "2") {
    const items = hundred().map((code, i) => ({ code, name: `한도종목${i}`, market: i % 2 ? "KOSDAQ" : "KOSPI", entered_at: Math.floor(ctl.t0 - 100) }));
    return { ...base, items, count: 100, capped: true };
  }
  const set = track(now);
  const items = set.map((code) => {
    const u = UNIVERSE.find((x) => x[0] === code);
    return { code, name: u[1], market: u[2], entered_at: seen.get(code) };
  });
  return { ...base, items, count: items.length, changes };
}
function liveQuote(code, now) {
  const p = 70000 + (hash(code) % 1000) + Math.floor(now / 5) % 7;
  return { code, price: p, change: 500, change_pct: 0.72, volume: 1234, open: p - 300, high: p + 400, low: p - 500, fetched_at: Math.floor(now) };
}
const hasQuote = (code) => code !== "999999" && !(code.startsWith("X") && hash(code) % 3 === 0);

function send(res, status, body, extra = {}) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", ...extra });
  res.end(JSON.stringify(body));
}
const ok = (data) => ({ data, error: null });
const err = (code, message) => ({ data: null, error: { code, message } });

const server = http.createServer((req, res) => {
  const url = new URL(req.url, API);
  const p = url.pathname;
  if (req.method === "OPTIONS") return send(res, 204, {});
  if (p === "/__set") {
    for (const k of ["cond", "res"]) if (url.searchParams.has(k)) ctl[k] = url.searchParams.get(k);
    if (url.searchParams.has("ttl")) ctl.ttl = Number(url.searchParams.get("ttl"));
    if (url.searchParams.has("slot")) ctl.slot = Number(url.searchParams.get("slot"));
    if (url.searchParams.has("delay2")) ctl.delay = { 2: Number(url.searchParams.get("delay2")) };
    return send(res, 200, ctl);
  }
  if (p === "/__reset") {
    Object.assign(ctl, { cond: "ok", res: "normal", ttl: 5, slot: 6, delay: {} });
    resetTracker();
    return send(res, 200, { ok: true });
  }
  if (p === "/__log") return send(res, 200, serverLog);
  const now = sec();
  serverLog.push({ t: Date.now(), path: p, search: url.search });

  if (p === "/api/v1/local/psearch/conditions") {
    const c = ctl.cond;
    if (c === "403") return send(res, 403, err("FORBIDDEN", "관리자만 사용할 수 있습니다."));
    if (c === "404") return send(res, 404, err("NOT_FOUND", "찾을 수 없습니다."));
    if (c === "503p") return send(res, 503, err("PSEARCH_NOT_CONFIGURED", "HTS ID가 설정되지 않았습니다. .env의 KIS_HTS_ID를 확인하세요."));
    if (c === "503a") return send(res, 503, err("LOCAL_INTRADAY_NOT_CONFIGURED", "앱키가 설정되지 않았습니다."));
    if (c === "502") return send(res, 502, err("PSEARCH_REJECTED", "HTS ID 불일치(모의 증권사 문구)"));
    if (c === "none") return send(res, 200, ok({ conditions: [], fetched_at: Math.floor(now) }));
    return send(res, 200, ok({ conditions: [{ seq: "0", group: "내 조건", name: "급등 포착" }, { seq: "1", group: "내 조건", name: "0건 조건" }, { seq: "2", group: "테스트", name: "100건 한도" }], fetched_at: Math.floor(now) }));
  }
  if (p === "/api/v1/local/psearch/results") {
    const seq = url.searchParams.get("seq") ?? "";
    const respond = () => {
      const r = ctl.res;
      if (r === "r403") return send(res, 403, err("FORBIDDEN", "관리자만 사용할 수 있습니다."));
      if (r === "r404") return send(res, 404, err("NOT_FOUND", "찾을 수 없습니다."));
      if (r === "r503p") return send(res, 503, err("PSEARCH_NOT_CONFIGURED", "HTS ID가 설정되지 않았습니다. .env의 KIS_HTS_ID를 확인하세요."));
      if (r === "r503") return send(res, 503, err("LOCAL_INTRADAY_NOT_CONFIGURED", "앱키가 설정되지 않았습니다."));
      if (r === "r429") return send(res, 429, err("RATE_LIMITED", "한도"));
      if (r === "r502") return send(res, 502, err("PSEARCH_REJECTED", "조건 목록 조회 거절(모의 증권사 문구)"));
      if (!/^[A-Za-z0-9]{1,10}$/.test(seq)) return send(res, 400, err("INVALID_SEQ", "seq가 올바르지 않습니다."));
      return send(res, 200, ok(resultsBody(seq, sec())));
    };
    const d = ctl.delay[seq] ?? 0;
    return d ? void setTimeout(respond, d) : respond();
  }
  if (p === "/api/v1/local/market/quotes") {
    const codes = (url.searchParams.get("codes") ?? "").split(",").filter(Boolean);
    const quotes = codes.filter(hasQuote).map((c) => liveQuote(c, now));
    return send(res, 200, ok({ quotes, missing: codes.filter((c) => !hasQuote(c)), meta: { cycle_seconds: 12, last_cycle_at: Math.floor(now), covered: quotes.length, total: codes.length, stale: false, running: true } }));
  }
  if (p === "/api/v1/stocks/quotes") {
    const codes = (url.searchParams.get("codes") ?? "").split(",").filter(Boolean);
    return send(res, 200, ok({ quotes: codes.filter(hasQuote).map((c) => ({ stock_code: c, trade_date: "2026-10-05", close: 69000 + (hash(c) % 1000), change: 300, change_pct: 0.4, open: 68800, high: 69500, low: 68500, volume: 99 })) }));
  }
  return send(res, 404, err("NOT_FOUND", "모의 서버에 없는 경로"));
});

const setCtl = (q) => fetch(`${API}/__set?${q}`).then((r) => r.json());
const resetCtl = () => fetch(`${API}/__reset`).then((r) => r.json());
const getLog = () => fetch(`${API}/__log`).then((r) => r.json());

// ═══════════════════════ 프런트 서버 ═══════════════════════
let web = null;
function runCmd(cmd, args, env, logFile) {
  const out = fs.openSync(logFile, "w");
  return spawn(cmd, args, { cwd: FRONT, env: { ...process.env, ...env }, stdio: ["ignore", out, out], detached: true });
}
function killGroup(child) {
  if (!child?.pid) return;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    /* 이미 끝남 */
  }
}
async function waitHttp(url, ms = 240000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      const r = await fetch(url);
      if (r.status === 200) return true;
    } catch {
      /* 아직 */
    }
    await sleep(1000);
  }
  return false;
}
async function startWeb() {
  const env = { NEXT_PUBLIC_API_BASE_URL: API, NEXT_PUBLIC_BROWSER_API_BASE_URL: "", ...(PHASE === "dev" ? { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "true" } : { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "" }) };
  if (PHASE === "dev") {
    web = runCmd("node", ["node_modules/next/dist/bin/next", "dev", "--webpack", "-p", String(WEB_PORT)], env, `${OUT}/web-dev.log`);
  } else {
    await new Promise((resolve, reject) => {
      const b = runCmd("npm", ["run", "build"], env, `${OUT}/web-build.log`);
      b.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`build 실패 ${code}, 로그 ${OUT}/web-build.log`))));
    });
    web = runCmd("node", ["node_modules/next/dist/bin/next", "start", "-p", String(WEB_PORT)], env, `${OUT}/web-start.log`);
  }
  const up = await waitHttp(`${WEB}/screener/pattern`);
  rec(`프런트(${PHASE}) 기동`, up);
  if (!up) throw new Error("프런트가 뜨지 않음");
  for (const path of ["/screener", "/screener/pattern", "/screener/broker"]) await waitHttp(`${WEB}${path}`); // dev 첫 컴파일
}

// ═══════════════════════ 공통 ═══════════════════════
const BROKER_LINK = 'nav.screening-mode-nav a[href="/screener/broker"]';
const tracked = (page) => {
  const t = { psearch: [], results: [], conditions: [], quotesLive: [], pageErrors: [], consoleErrors: [], failedResources: [] };
  page.on("request", (r) => {
    const u = r.url();
    const at = Date.now();
    if (u.includes("/psearch/results")) t.results.push({ at, url: u });
    if (u.includes("/psearch/conditions")) t.conditions.push({ at, url: u });
    if (u.includes("/psearch")) t.psearch.push({ at, url: u });
    if (u.includes("/local/market/quotes")) t.quotesLive.push({ at, url: u });
  });
  page.on("pageerror", (e) => t.pageErrors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    (/Failed to load resource/.test(text) ? t.failedResources : t.consoleErrors).push(text);
  });
  return t;
};
async function newPage(browser, width = 1280, height = 900, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, ...opts });
  const page = await ctx.newPage();
  const t = tracked(page);
  return { ctx, page, t };
}
const rowCount = (page) => page.evaluate(() => document.querySelectorAll(".broker-table tbody tr, .broker-list > li").length);
const rowCodes = (page) =>
  page.evaluate(() => [...document.querySelectorAll(".broker-table tbody tr, .broker-list > li")].map((r) => (r.textContent.match(/\((\w{6})\)/) || [])[1]));
async function waitRows(page, min = 1, ms = 15000) {
  try {
    await page.waitForFunction((m) => document.querySelectorAll(".broker-table tbody tr, .broker-list > li").length >= m, min, { timeout: ms });
    return true;
  } catch {
    return false;
  }
}
const mainText = (page) => page.evaluate(() => document.querySelector("main")?.innerText ?? "");
// 본문(main) 안 조작 요소의 44px 확인(인라인 문장 링크 제외) — 공통 측정은 머리글·바닥글도 포함하므로 별도로 확인
const mainTargets = (page) =>
  page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll('main a[href], main button, main select, main input, main [tabindex="0"]')) {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (!r.width || !r.height || cs.visibility === "hidden" || el.closest(".sr-only")) continue;
      if (r.width < 43.5 || r.height < 43.5) out.push({ el: `${el.tagName.toLowerCase()}.${el.className}`.slice(0, 50), text: (el.textContent || "").trim().slice(0, 20), w: +r.width.toFixed(1), h: +r.height.toFixed(1) });
    }
    return out;
  });
async function layoutCheck(page, label, { skipTargets = false } = {}) {
  const m = await page.evaluate(measureFn);
  const clippedOut = m.clipped.filter((c) => !c.inScroller);
  rec(`${label}: 가로 넘침 없음`, !m.overflow, `scrollWidth ${m.scrollWidth}/${m.vw}`);
  rec(`${label}: 잘림 없음`, clippedOut.length === 0, clippedOut.slice(0, 3).map((c) => `${c.n} ${c.left}~${c.right}`).join("; "));
  const targets = skipTargets ? [] : await mainTargets(page);
  rec(`${label}: 본문 조작 요소 44px 이상`, targets.length === 0, targets.slice(0, 4).map((s) => `${s.el}[${s.text}] ${s.w}x${s.h}`).join("; "));
  const ov = m.overlaps.filter((o) => !/^a\./.test(o.a) || true);
  rec(`${label}: 조작 요소 겹침 없음`, ov.length === 0, ov.slice(0, 3).map((o) => `${o.a}×${o.b}`).join("; "));
  const axe = await runAxe(page);
  rec(`${label}: axe 위반 0`, axe.length === 0, axe.map((v) => `${v.id}(${v.nodes.length}) ${v.nodes[0]?.target}`).join("; "));
}
const shot = (page, name) => page.screenshot({ path: `${SHOTS}${name}.png`, fullPage: true });

// ═══════════════════════ dev 단계 ═══════════════════════
async function dev(browser) {
  // ── A. 서버 렌더(HTML)에는 전환 항목도 화면 내용도 없다 ──
  await resetCtl();
  for (const path of ["/screener", "/screener/pattern", "/screener/broker"]) {
    const html = await (await fetch(`${WEB}${path}`)).text();
    rec(`SSR ${path}: 전환 항목 링크 없음`, !html.includes('href="/screener/broker"'));
    rec(`SSR ${path}: 조건 선택·결과 표 없음`, !/id="broker-condition"|broker-table|broker-list/.test(html));
  }

  // ── B. 전환 항목 ──
  {
    await resetCtl();
    const { ctx, page, t } = await newPage(browser, 1280);
    await page.goto(`${WEB}/screener/pattern`);
    const shown = await page.waitForSelector(BROKER_LINK, { timeout: 15000 }).then(() => true, () => false);
    rec("전환 항목: 조건 목록 200이면 세 번째 항목이 나타남", shown);
    const labels = await page.$$eval("nav.screening-mode-nav a", (as) => as.map((a) => `${a.textContent.trim()}|${a.getAttribute("href")}|${a.getAttribute("aria-current") ?? ""}`));
    rec("전환 항목: 기존 두 항목 문구·주소·현재 표시 그대로 + 세 번째", JSON.stringify(labels) === JSON.stringify(["직접 조건 설정|/screener|", "급등 전 압축주|/screener/pattern|page", "증권사 조건검색|/screener/broker|"]), labels.join(" / "));
    rec("전환 항목: 조건 목록 요청 1건(중복 없음)", t.conditions.length === 1, `${t.conditions.length}건`);
    await layoutCheck(page, "전환 항목 보이는 /screener/pattern @1280", { skipTargets: true });
    await page.click(BROKER_LINK);
    await page.waitForURL("**/screener/broker");
    await waitRows(page, 5);
    const navNow = await page.$$eval("nav.screening-mode-nav a", (as) => as.map((a) => `${a.textContent.trim()}|${a.getAttribute("aria-current") ?? ""}`));
    rec("전환 항목: 클릭해 이동하면 현재 항목 표시(aria-current=page)", navNow[2] === "증권사 조건검색|page", navNow.join(" / "));
    rec("전환 항목: 이동 후에도 조건 목록 요청은 총 2건 이하(전환 항목 1 + 화면 1)", t.conditions.length <= 2, `${t.conditions.length}건`);
    await ctx.close();

    const manual = await newPage(browser, 1280);
    await manual.page.goto(`${WEB}/screener`);
    const shown2 = await manual.page.waitForSelector(BROKER_LINK, { timeout: 15000 }).then(() => true, () => false);
    rec("전환 항목: /screener(직접 조건 설정)에서도 나타남", shown2);
    const count = await manual.page.$$eval("nav.screening-mode-nav a", (as) => as.length);
    rec("전환 항목: /screener 항목 3개", count === 3);
    rec("전환 항목: 페이지 오류 0(/screener·/screener/pattern)", manual.t.pageErrors.length === 0, manual.t.pageErrors.join("; "));
    await manual.ctx.close();
  }

  // ── C. 접근 불가(403·404·503): 항목도 내용도 요청도 없다 ──
  for (const [cond, label, expectText] of [["403", "403", "관리자만"], ["404", "404", "관리자만"], ["503a", "503(앱키 없음)", "앱키가 설정되지 않았습니다"], ["503p", "503(HTS ID 없음)", "KIS_HTS_ID"]]) {
    await resetCtl();
    await setCtl(`cond=${cond}`);
    const a = await newPage(browser, 1280);
    await a.page.goto(`${WEB}/screener/pattern`);
    await sleep(2500);
    const present = await a.page.$(BROKER_LINK);
    const n = await a.page.$$eval("nav.screening-mode-nav a", (as) => as.length);
    if (cond === "503p") rec(`접근 불가 ${label}: 설정 안내를 위해 전환 항목은 보임(3개)`, !!present && n === 3, `항목 ${n}개`); // HTS ID 미설정 관리자: 안내 화면으로 이어지는 예외
    else rec(`접근 불가 ${label}: 전환 항목 없음(기존 2개만)`, !present && n === 2, `항목 ${n}개`);
    rec(`접근 불가 ${label}: 결과·시세 조회 요청 0건`, a.t.results.length === 0 && a.t.quotesLive.length === 0, `results ${a.t.results.length}, quotes ${a.t.quotesLive.length}`);
    await a.ctx.close();

    const b = await newPage(browser, 1280);
    await b.page.goto(`${WEB}/screener/broker`);
    await sleep(2500);
    const txt = await mainText(b.page);
    const uiBits = await b.page.evaluate(() => ({ select: !!document.querySelector("main select"), table: !!document.querySelector("main table, .broker-list"), panel: !!document.querySelector(".broker-panel") }));
    rec(`접근 불가 ${label}: 화면은 안내만(조건 선택·표 없음)`, !uiBits.select && !uiBits.table && uiBits.panel && txt.includes(expectText), `${JSON.stringify(uiBits)} 문구 "${expectText}" ${txt.includes(expectText)}`);
    rec(`접근 불가 ${label}: 결과·시세 조회 0건, 조건 목록은 1건`, b.t.results.length === 0 && b.t.quotesLive.length === 0 && b.t.conditions.length === 1, `results ${b.t.results.length}, quotes ${b.t.quotesLive.length}, conditions ${b.t.conditions.length}`);
    rec(`접근 불가 ${label}: 안내문(투자 권유 아님) 상단 표시`, txt.includes("투자 권유가 아닙니다"));
    if (cond === "403" || cond === "503p") await layoutCheck(b.page, `접근 불가 ${label} @1280`);
    if (cond === "503p") {
      await b.page.setViewportSize({ width: 320, height: 640 });
      await layoutCheck(b.page, `접근 불가 ${label} @320`);
      await shot(b.page, "psearch-broker-notconfigured-320");
    }
    rec(`접근 불가 ${label}: 페이지 오류 0`, b.t.pageErrors.length === 0 && b.t.consoleErrors.length === 0, [...b.t.pageErrors, ...b.t.consoleErrors].join("; "));
    await b.ctx.close();
  }

  // ── D. 조건 없음(200 빈 배열) ──
  {
    await resetCtl();
    await setCtl("cond=none");
    const { ctx, page, t } = await newPage(browser, 360, 800);
    await page.goto(`${WEB}/screener/broker`);
    await page.waitForSelector(".broker-panel", { timeout: 15000 });
    const txt = await mainText(page);
    rec("조건 없음: [0110]·서버저장 안내 + 다시 불러오기 버튼, 결과 조회 0건", txt.includes("[0110]") && txt.includes("서버저장") && txt.includes("조건 목록 다시 불러오기") && t.results.length === 0);
    await layoutCheck(page, "조건 없음 @360");
    await setCtl("cond=ok");
    await page.click("text=조건 목록 다시 불러오기");
    const rowsOk = await waitRows(page, 5);
    rec("조건 없음: 저장 후 '다시 불러오기'로 표가 채워짐(새로고침 없이)", rowsOk && t.conditions.length === 2, `conditions ${t.conditions.length}`);
    await ctx.close();
    await setCtl("cond=502");
    const e = await newPage(browser, 360, 800);
    await e.page.goto(`${WEB}/screener/broker`);
    await e.page.waitForSelector(".broker-panel", { timeout: 15000 });
    const et = await mainText(e.page);
    rec("조건 목록 502 PSEARCH_REJECTED: 증권사 문구 표시 + 다시 불러오기, 화면 오류 아님", et.includes("HTS ID 불일치(모의 증권사 문구)") && et.includes("다시 불러오기") && e.t.pageErrors.length === 0);
    await layoutCheck(e.page, "조건 목록 502 @360");
    await e.ctx.close();
  }

  // ── E. 본 시험: 표·자동 갱신·신규·변화·간격·탭 가림·조건 변경 ──
  await resetCtl();
  let main;
  {
    main = await newPage(browser, 1280, 900);
    const { page, t } = main;
    await page.goto(`${WEB}/screener/broker`);
    const filled = await waitRows(page, 5);
    const startAt = Date.now();
    rec("첫 조회 후 표가 채워짐(5종목)", filled, `${await rowCount(page)}행`);
    await page.evaluate(() => {
      window.__noReload = 1;
      window.__statusMutations = 0;
      const st = document.querySelector('main [role="status"], [role="status"]');
      if (st) new MutationObserver(() => (window.__statusMutations += 1)).observe(st, { childList: true, characterData: true, subtree: true });
    });
    const head = await page.$$eval("table.broker-table thead th", (ths) => ths.map((th) => `${th.textContent.trim()}|${th.getAttribute("scope")}`));
    rec("표: <caption>+열 머리글 scope=col(종목명(코드)·시장·현재가·편입 시각)", JSON.stringify(head) === JSON.stringify(["종목명(코드)|col", "시장|col", "현재가|col", "편입 시각|col"]) && (await page.$("table.broker-table caption")) !== null, head.join(","));
    const rowScope = await page.$$eval("table.broker-table tbody th", (ths) => ths.every((th) => th.getAttribute("scope") === "row"));
    rec("표: 종목명 셀 scope=row", rowScope);
    const options = await page.$$eval("#broker-condition option", (os) => os.map((o) => o.textContent));
    rec("조건 선택 목록이 `group · name`", JSON.stringify(options) === JSON.stringify(["내 조건 · 급등 포착", "내 조건 · 0건 조건", "테스트 · 100건 한도"]), options.join(" | "));
    const labelOk = await page.$eval("label[for=broker-condition]", (l) => l.textContent.trim());
    rec("조건 선택에 연결된 label", labelOk === "조건 선택");

    const first = await page.$$eval(".broker-table tbody tr", (trs) =>
      trs.map((tr) => ({ name: tr.querySelector("th")?.innerText.replace(/\s+/g, " ").trim(), market: tr.children[1].innerText.trim(), price: tr.children[2].innerText.replace(/\s+/g, " ").trim(), time: tr.children[3].innerText.trim() })),
    );
    rec("행: 시간 형식 HH:MM:SS", first.every((r) => /^\d\d:\d\d:\d\d$/.test(r.time)), first.map((r) => r.time).join(","));
    const noName = first.find((r) => r.name.includes("999999"));
    rec("행: 이름 없는 종목은 코드만, 시장 '-'", !!noName && /^\(?999999\)?$/.test(noName.name.replace("신규", "").trim().replace(/[()]/g, "")) && noName.market === "-", JSON.stringify(noName));
    rec("행: 값 없는 종목의 현재가는 '-'(0이 아님)", !!noName && noName.price.startsWith("-") && !/\b0\b/.test(noName.price.replace("시세 없음", "")), JSON.stringify(noName?.price));
    const priced = first.filter((r) => !r.name.includes("999999"));
    rec("행: 나머지는 준실시간 값(QuoteText: 숫자 + '실시간' 표지)", priced.length === 4 && priced.every((r) => /\d{2},\d{3}/.test(r.price) && r.price.includes("실시간")), JSON.stringify(priced.map((r) => r.price)));
    rec("신규: 처음부터 있던 종목에는 '신규' 표지 없음", first.every((r) => !r.name.includes("신규")));
    rec("긴 종목명(전각 24자)이 표에서 잘리지 않고 보임", first.some((r) => r.name.includes("아주아주긴이름의종목명테스트주식회사우선주")));
    await shot(page, "psearch-broker-1280");

    const text0 = await mainText(page);
    rec("상단: 안내문(계약서 §5 한 줄) 그대로", text0.includes("증권사 HTS 조건검색 결과입니다(본인 전용). 조건 판정은 증권사가 하며 이 사이트는 결과를 표시만 합니다. 투자 권유가 아닙니다."));
    rec("상단: '마지막 조회 HH:MM:SS'와 증권사 수신 시각 표시", /마지막 조회 \d\d:\d\d:\d\d/.test(text0) && /증권사 수신 \d\d:\d\d:\d\d/.test(text0));
    rec("'실시간 보장' 류 문구 없음(보장·실시간 반영·제공 단어 없음)", !/보장|실시간\s*(반영|제공)/.test(text0.replace(/실시간(?=\s|$)/g, "")));
    const firstQuery = (text0.match(/마지막 조회 (\d\d:\d\d:\d\d)/) ?? [])[1];

    // 자동 갱신(편입·이탈) — 6초마다 창이 한 칸 이동. 새로고침 없이 반영돼야 한다.
    const seenSets = new Set([(await rowCodes(page)).join(",")]);
    let prevCodes = new Set(await rowCodes(page));
    const flicker = [];
    let sawNewBadge = false;
    let changeSeen = null;
    const tEnd = startAt + 26000;
    while (Date.now() < tEnd) {
      await sleep(1000);
      const snap = await page.evaluate(() => [...document.querySelectorAll(".broker-table tbody tr")].map((r) => [(r.textContent.match(/\((\w{6})\)/) || [])[1], r.children[2].innerText.trim().startsWith("-")]));
      for (const [code, dash] of snap) if (dash && code !== "999999" && prevCodes.has(code)) flicker.push(`${code}@${Math.round((Date.now() - startAt) / 1000)}s`);
      prevCodes = new Set(snap.map((x) => x[0]));
      seenSets.add((await rowCodes(page)).join(","));
      if (!sawNewBadge) sawNewBadge = await page.evaluate(() => !!document.querySelector(".broker-table .broker-new"));
      if (!changeSeen) changeSeen = await page.evaluate(() => document.querySelector(".broker-change")?.innerText.replace(/\s+/g, " ") ?? null);
    }
    rec("자동 갱신: 새로고침 없이 종목 구성이 바뀜", seenSets.size >= 3 && (await page.evaluate(() => window.__noReload === 1)), `서로 다른 구성 ${seenSets.size}가지`);
    rec("가격 유지: 이어서 보이는 종목의 현재가가 구성 변경 중에도 '-'로 깜박이지 않음", flicker.length === 0, flicker.slice(0, 5).join(","));
    rec("신규 표지: 새로 편입된 종목에 '신규' 글자(색이 아닌 텍스트)", sawNewBadge);
    const newInfo = await page.evaluate(() => {
      const b = document.querySelector(".broker-table .broker-new");
      return b ? { text: b.textContent.trim(), sr: b.querySelector(".sr-only")?.textContent ?? "" } : null;
    });
    rec("신규 표지: 보이는 글자 '신규' + 스크린리더용 설명", !newInfo || (newInfo.text.startsWith("신규") && newInfo.sr.includes("최근 1분")), JSON.stringify(newInfo));
    rec("변화 목록: 'HH:MM:SS 편입 …' 항목이 생김", !!changeSeen && /^\d\d:\d\d:\d\d /.test(changeSeen) && changeSeen.includes("편입"), String(changeSeen));
    const changeAll = await page.$$eval(".broker-change", (els) => els.map((e) => e.innerText.replace(/\s+/g, " ")));
    rec("변화 목록: 이탈 항목도 이름(코드)로 표시, 최대 10건", changeAll.some((c) => c.includes("이탈")) && changeAll.length <= 10 && changeAll.some((c) => /이탈 [^ ]+\(\d{6}\)|이탈 \d{6}/.test(c)), `${changeAll.length}건 예: ${changeAll[0]}`);
    const lastQuery2 = (await mainText(page)).match(/마지막 조회 (\d\d:\d\d:\d\d)/)?.[1];
    rec("마지막 조회 시각이 갱신됨", !!lastQuery2 && lastQuery2 !== firstQuery, `${firstQuery} → ${lastQuery2}`);
    // 간격
    const times = t.results.map((r) => r.at).sort((a, b) => a - b);
    let worst = 0;
    for (const s of times) worst = Math.max(worst, times.filter((x) => x >= s && x < s + 12000).length);
    rec("조회 간격: 어떤 12초 구간에도 결과 요청 5건 이하", worst <= 5, `최대 ${worst}건/12초, 총 ${times.length}건/${Math.round((Date.now() - startAt) / 1000)}초, 간격 ${times.slice(1).map((x, i) => ((x - times[i]) / 1000).toFixed(1)).join(",")}`);
    const muts = await page.evaluate(() => window.__statusMutations);
    rec("낭독: 상태 영역(role=status) 변경은 조회 횟수보다 훨씬 적음(초당 낭독 없음)", muts <= 8, `${muts}회 / 조회 ${times.length}회`);
    const live = await page.$$eval("main [aria-live], main [role=status], main [role=alert]", (els) => els.map((e) => `${e.tagName.toLowerCase()}[${e.getAttribute("aria-live") ?? e.getAttribute("role")}]${e.closest("table, .broker-table-wrap, .broker-list") ? " IN-TABLE" : ""}`));
    const liveAll = await page.$$eval("[aria-live], [role=status], [role=alert]", (els) => els.map((e) => `${e.tagName.toLowerCase()}[${e.getAttribute("aria-live") ?? e.getAttribute("role")}]${e.closest("main") ? "" : " (main 밖)"}`));
    rec("낭독: 화면 본문의 live 영역은 표 밖 1곳뿐(표 전체를 live로 두지 않음)", live.length === 1 && !live[0].includes("IN-TABLE"), `본문 ${live.join(",")} / 전체 ${liveAll.join(",")}`);
    await layoutCheck(page, "본 화면 @1280");

    // 키보드: 조건 선택 → 방향키로 바꾸면 그 조건 조회
    await page.focus("#broker-condition");
    await page.keyboard.press("Tab");
    const afterTab = await page.evaluate(() => document.activeElement?.className ?? "");
    rec("키보드: 조건 선택 다음 Tab은 결과 영역(스크롤 영역 또는 종목 링크)으로 이동", /broker-table-wrap|results-table__link|broker-list__link|broker-button/.test(String(afterTab)), String(afterTab));
    await page.focus("#broker-condition");
    const before = t.results.length;
    await page.keyboard.press("ArrowDown");
    await sleep(1500);
    const lastUrl = t.results.at(-1)?.url ?? "";
    rec("키보드: 조건 선택에 포커스 후 ↓ 키로 조건 변경 → seq=1 조회", t.results.length > before && /seq=1$/.test(lastUrl), lastUrl);
    const focusRing = await page.evaluate(() => {
      const el = document.getElementById("broker-condition");
      el.focus();
      return getComputedStyle(el).outlineStyle !== "none";
    });
    rec("키보드: 조건 선택 포커스 표시(outline)", focusRing);
    const empty1 = await mainText(page);
    rec("0건 조건: 증권사 문구 그대로 표시 + 표 없음", empty1.includes("조회된 종목이 없습니다. (모의 증권사 문구 — 그대로 보여야 함)") && (await rowCount(page)) === 0, "");
    rec("0건 조건: '증권사가 결과 0건' 안내", empty1.includes("증권사가 결과 0건을 돌려주었습니다"));
    await layoutCheck(page, "0건 @1280");
  }

  // 탭 가림
  {
    const { page, t } = main;
    await page.selectOption("#broker-condition", "0");
    await waitRows(page, 5);
    await sleep(500);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await sleep(300);
    const n0 = t.results.length;
    await sleep(12000);
    rec("탭 가림: 12초 동안 결과 요청 0건", t.results.length === n0, `${t.results.length - n0}건`);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await sleep(1800);
    rec("탭 복귀: 곧바로(2초 안) 한 번 조회", t.results.length === n0 + 1, `${t.results.length - n0}건`);
  }

  // 100건·한도·조건 변경 취소
  {
    const { page, t } = main;
    await page.selectOption("#broker-condition", "2");
    const ok100 = await waitRows(page, 100);
    const txt = await mainText(page);
    rec("100건 조건: 100행 + 한도 안내(조건을 좁히라는 문구)", ok100 && (await rowCount(page)) === 100 && txt.includes("100건 한도에 닿았습니다") && txt.includes("더 좁히면") && txt.includes("결과 종목 (100건)"), `${await rowCount(page)}행`);
    const dash = await page.$$eval(".broker-table tbody tr", (trs) => trs.filter((tr) => tr.children[2].innerText.trim().startsWith("-")).length);
    rec("100건 조건: 시세 없는 종목은 '-'로(일부), 나머지는 값", dash > 0 && dash < 100, `'-' ${dash}행`);
    await layoutCheck(page, "100건 @1280");
    // 늦은 응답 폐기: 100건 조건 응답을 3초 늦추고, 그 사이 다른 조건으로 바꿈
    await page.selectOption("#broker-condition", "0");
    await waitRows(page, 5);
    await setCtl("delay2=3000");
    const rBefore = t.results.length;
    await page.selectOption("#broker-condition", "2");
    await sleep(400);
    await page.selectOption("#broker-condition", "0");
    await sleep(4500);
    const rows = await rowCount(page);
    const urls = t.results.slice(rBefore).map((r) => r.url.split("seq=")[1]);
    rec("조건 변경: 늦게 도착한 이전 조건(100건) 응답이 표를 덮어쓰지 않음", rows === 5 && (await page.inputValue("#broker-condition")) === "0", `${rows}행, 요청 순서 seq=${urls.join(",")}`);
    await setCtl("delay2=0");
  }

  // 실패(429)·복구·stale
  {
    const { page, t } = main;
    await page.selectOption("#broker-condition", "0");
    await waitRows(page, 5);
    await setCtl("res=r429");
    const delayed = await page.waitForFunction(() => document.body.innerText.includes("조회 지연"), null, { timeout: 15000 }).then(() => true, () => false);
    const keep = await rowCount(page);
    rec("429: '조회 지연' 안내 + 마지막 값(표) 유지", delayed && keep === 5, `${keep}행`);
    const retryText = (await mainText(page)).match(/(\d+)초 뒤 다시 시도/)?.[1];
    rec("429: 다시 시도 간격이 늘어남(10초 이상)", Number(retryText) >= 10, `${retryText}초`);
    const lastQ = (await mainText(page)).match(/마지막 조회 (\d\d:\d\d:\d\d)/)?.[1];
    rec("429: 마지막 조회 시각은 마지막 성공 시각으로 유지", !!lastQ);
    await setCtl("res=normal");
    const recovered = await page.waitForFunction(() => !document.body.innerText.includes("조회 지연"), null, { timeout: 35000 }).then(() => true, () => false);
    rec("429 복구: 다음 시도에 성공하면 지연 안내가 사라짐", recovered);
    await layoutCheck(page, "429 지연 안내(복구 후) @1280", { skipTargets: false });
    await setCtl("res=stale");
    const staleSeen = await page.waitForFunction(() => document.body.innerText.includes("이전 결과를 보여 주는 중"), null, { timeout: 15000 }).then(() => true, () => false);
    rec("stale: 이전 결과를 보여 주는 중 안내(표 유지)", staleSeen && (await rowCount(page)) === 5);
    await layoutCheck(page, "stale @1280");
    await setCtl("res=normal");
    rec("본 화면 페이지 오류 0·콘솔 오류 0(요청 실패 로그 제외)", t.pageErrors.length === 0 && t.consoleErrors.length === 0, [...t.pageErrors, ...t.consoleErrors].join("; "));
    await main.ctx.close();
  }

  // ── E2. 신규 표지는 60초 뒤 새로고침 없이 사라진다(구성이 바뀌지 않아도) ──
  {
    await resetCtl();
    await setCtl("slot=25");
    const { ctx, page } = await newPage(browser, 1280, 900);
    await page.goto(`${WEB}/screener/broker`);
    await waitRows(page, 5);
    await page.evaluate(() => (window.__noReload = 1));
    const appeared = await page.waitForFunction(() => !!document.querySelector(".broker-table .broker-new"), null, { timeout: 40000 }).then(() => Date.now(), () => null);
    rec("신규 만료: 편입된 종목에 '신규'가 나타남(구성 25초 간격)", !!appeared);
    const code = appeared ? await page.evaluate(() => (document.querySelector(".broker-table .broker-new").closest("tr").textContent.match(/\((\w{6})\)/) || [])[1]) : null;
    const entered = code ? await page.evaluate((c) => [...document.querySelectorAll(".broker-table tbody tr")].find((r) => r.textContent.includes(`(${c})`)).children[3].innerText.trim(), code) : null;
    let gone = null;
    const limit = Date.now() + 75000;
    while (appeared && Date.now() < limit) {
      const still = await page.evaluate((c) => { const tr = [...document.querySelectorAll(".broker-table tbody tr")].find((r) => r.textContent.includes(`(${c})`)); return tr ? !!tr.querySelector(".broker-new") : "left"; }, code);
      if (still === false) { gone = Date.now(); break; }
      if (still === "left") break;
      await sleep(1000);
    }
    const lived = gone && appeared ? Math.round((gone - appeared) / 1000) : null;
    rec("신규 만료: 약 60초 뒤 새로고침 없이 '신규'가 사라지고 행은 남음", !!gone && (await page.evaluate(() => window.__noReload === 1)), `종목 ${code} 편입 ${entered}, 표지 확인 후 ${lived}초에 사라짐(편입 후 60~66초 기대)`);
    await ctx.close();
    await setCtl("slot=6");
  }

  // ── F. 결과 쪽 접근 불가·오류(조건 목록은 200) ──
  for (const [res, label, expect] of [["r403", "결과 403", "관리자만"], ["r404", "결과 404", "관리자만"], ["r503p", "결과 503(HTS ID 없음)", "KIS_HTS_ID"], ["r503", "결과 503(앱키 없음)", "앱키가 설정되지 않았습니다"]]) {
    await resetCtl();
    await setCtl(`res=${res}`);
    const { ctx, page, t } = await newPage(browser, 360, 800);
    await page.goto(`${WEB}/screener/broker`);
    await page.waitForSelector(".broker-panel", { timeout: 15000 });
    await sleep(500);
    const txt = await mainText(page);
    const ui = await page.evaluate(() => ({ select: !!document.querySelector("main select"), table: !!document.querySelector("main table, .broker-list") }));
    rec(`${label}: 안내만 보이고 선택·표 숨김`, txt.includes(expect) && !ui.select && !ui.table, JSON.stringify(ui));
    await sleep(11000);
    rec(`${label}: 다시 묻지 않음(결과 요청 1건 유지)`, t.results.length === 1, `${t.results.length}건`);
    await layoutCheck(page, `${label} @360`);
    await ctx.close();
  }
  {
    await resetCtl();
    await setCtl("res=r502");
    const { ctx, page, t } = await newPage(browser, 360, 800);
    await page.goto(`${WEB}/screener/broker`);
    const seen = await page.waitForFunction(() => document.body.innerText.includes("조건 목록 조회 거절(모의 증권사 문구)"), null, { timeout: 15000 }).then(() => true, () => false);
    rec("결과 502 PSEARCH_REJECTED(첫 조회): 증권사 문구 표시 + 재시도 안내, 표 없음", seen && (await mainText(page)).includes("초 뒤 다시 시도합니다") && (await rowCount(page)) === 0);
    await layoutCheck(page, "결과 502 @360");
    await sleep(11000);
    rec("결과 502: 간격을 늘려 재시도(12초 동안 2건 이하)", t.results.length <= 3 && t.results.length >= 2, `${t.results.length}건`);
    await ctx.close();
  }

  // ── G. 폭별(320·360·412·768·1280) 본 화면: 표/카드, 넘침·잘림·44px·겹침·axe ──
  for (const w of [320, 360, 412, 768, 1280]) {
    await resetCtl();
    const { ctx, page, t } = await newPage(browser, w, 800);
    await page.goto(`${WEB}/screener/broker`);
    const okRows = await waitRows(page, 5);
    const isCards = await page.evaluate(() => !!document.querySelector(".broker-list") && !document.querySelector(".broker-table"));
    rec(`폭 ${w}: ${w >= 768 ? "표" : "카드 목록"}로 표시`, okRows && isCards === w < 768, isCards ? "카드" : "표");
    await layoutCheck(page, `폭 ${w} 본 화면`);
    if (w === 320) {
      await shot(page, "psearch-broker-320");
      const card = await page.$eval(".broker-list > li", (li) => li.innerText.replace(/\s+/g, " "));
      rec("폭 320 카드: 종목명(코드)·시장·현재가·편입 시각이 한 카드에", /\(\d{6}\)/.test(card) && /\d\d:\d\d:\d\d/.test(card), card.slice(0, 80));
    }
    rec(`폭 ${w}: 페이지 오류 0`, t.pageErrors.length === 0 && t.consoleErrors.length === 0, [...t.pageErrors, ...t.consoleErrors].join("; "));
    await ctx.close();
  }
  // 상태 화면 폭(320·1280): 0건·100건·stale
  for (const w of [320, 1280]) {
    await resetCtl();
    const { ctx, page } = await newPage(browser, w, 800);
    await page.goto(`${WEB}/screener/broker`);
    await waitRows(page, 5);
    await page.selectOption("#broker-condition", "1");
    await page.waitForFunction(() => document.body.innerText.includes("증권사가 결과 0건"), null, { timeout: 15000 });
    await layoutCheck(page, `0건 @${w}`);
    await page.selectOption("#broker-condition", "2");
    await waitRows(page, 100);
    await layoutCheck(page, `100건 @${w}`);
    if (w === 320) await shot(page, "psearch-broker-capped-320");
    await ctx.close();
  }
  // 고대비·모션 줄이기
  {
    await resetCtl();
    const { ctx, page } = await newPage(browser, 360, 800, { forcedColors: "active", reducedMotion: "reduce" });
    await page.goto(`${WEB}/screener/broker`);
    await waitRows(page, 5);
    await page.waitForFunction(() => true);
    await sleep(500);
    await setCtl("res=stale");
    await sleep(6000);
    await layoutCheck(page, "고대비+모션 줄이기 @360");
    await setCtl("res=normal");
    await ctx.close();
  }
}

// ═══════════════════════ prod 단계 ═══════════════════════
async function prod(browser) {
  await resetCtl();
  for (const path of ["/screener", "/screener/pattern", "/screener/broker"]) {
    const html = await (await fetch(`${WEB}${path}`)).text();
    rec(`prod SSR ${path}: 전환 항목·조건 선택·결과 표 없음`, !html.includes('href="/screener/broker"') && !/id="broker-condition"|broker-table|broker-list/.test(html));
  }
  const scripts = [];
  const { ctx, page, t } = await newPage(browser, 1280, 900);
  page.on("request", (r) => scripts.push(r.url()));
  await page.goto(`${WEB}/screener/pattern`);
  await sleep(4000);
  const n = await page.$$eval("nav.screening-mode-nav a", (as) => as.map((a) => a.textContent.trim()));
  rec("prod: /screener/pattern 전환 항목은 기존 2개뿐", JSON.stringify(n) === JSON.stringify(["직접 조건 설정", "급등 전 압축주"]), n.join(","));
  await page.goto(`${WEB}/screener`);
  await sleep(3000);
  const n2 = await page.$$eval("nav.screening-mode-nav a", (as) => as.length);
  rec("prod: /screener 전환 항목 2개", n2 === 2);
  await page.goto(`${WEB}/screener/broker`);
  await sleep(4000);
  const txt = await mainText(page);
  const ui = await page.evaluate(() => ({ select: !!document.querySelector("main select"), table: !!document.querySelector("main table, .broker-list") }));
  rec("prod: /screener/broker는 안내만(조건 선택·결과 없음)", txt.includes("로컬 모드에서만 열립니다") && !ui.select && !ui.table, JSON.stringify(ui));
  rec("prod: 브라우저가 보낸 /psearch 요청 0건·/local/ 시세 요청 0건", t.psearch.length === 0 && t.quotesLive.length === 0, `psearch ${t.psearch.length}, quotes ${t.quotesLive.length}`);
  const log = await getLog();
  const bad = log.filter((l) => l.path.includes("/psearch") || l.path.includes("/local/"));
  rec("prod: 모의 서버가 받은 /psearch·/local/ 요청 0건(세 화면 전체)", bad.length === 0, `서버 수신 ${log.length}건 중 ${bad.length}건`);
  const brokerRefs = await page.evaluate(() => [...document.scripts].map((s) => s.src));
  rec("prod: 페이지 오류 0", t.pageErrors.length === 0 && t.consoleErrors.length === 0, [...t.pageErrors, ...t.consoleErrors].join("; "));
  await layoutCheck(page, "prod /screener/broker @1280");
  await page.setViewportSize({ width: 320, height: 640 });
  await layoutCheck(page, "prod /screener/broker @320");
  await shot(page, "psearch-broker-prod-320");
  await page.goto(`${WEB}/screener/pattern`);
  await sleep(2500);
  await layoutCheck(page, "prod /screener/pattern @320", { skipTargets: true });
  void brokerRefs;
  await ctx.close();
}

// ═══════════════════════ 실행 ═══════════════════════
let browser;
try {
  await new Promise((resolve) => server.listen(API_PORT, "127.0.0.1", resolve));
  await startWeb();
  browser = await launch();
  await (PHASE === "prod" ? prod : dev)(browser);
} catch (e) {
  rec(`시험 중단: ${e.message}`, false);
} finally {
  await browser?.close();
  killGroup(web);
  server.close();
  const fail = results.filter((r) => !r.ok);
  fs.writeFileSync(`${OUT}/psearch-${PHASE}.json`, JSON.stringify(results, null, 2));
  console.log(`\n${PHASE}: ${results.length - fail.length}/${results.length} 통과, 실패 ${fail.length}`);
  for (const f of fail) console.log("  FAIL:", f.name, f.note);
  setTimeout(() => process.exit(fail.length ? 1 : 0), 500);
}
