// 장중 기준 재계산 화면 시험(DEC-089, 프런트만). 백엔드·증권사 없이 `live-screen-mock.mjs`(계약서 §3 모양의 가짜 JSON 서버)와
// 프런트(스크립트가 `next dev`/`next build`+`next start`로 띄우고 PID로 끝냄)로 실제 브라우저(Playwright, 크로미움)를 돌린다. 저장소에 남기는 임시 파일 없음.
//
//   dev  : NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true(로그인 끔 = 내 PC 본인) `next dev` — 전환·배너·자동 갱신·일시정지·410·오류·폭·axe·스크린샷
//   prod : 그 변수 없이 `npm run build` → `next start` — 전환·요청·번들 코드 비노출
//   auth : 로컬 플래그 + 로그인 켠 빌드(AUTH_REQUIRED) — 웹 서버 대행(BFF) 허용 목록·관리자 전용·쿼리 길이·일반 회원 비노출
//
//   node scripts/qa/live-screen.mjs dev | prod | auth
// Playwright 설치 위치는 README.md 참고(QA_PW_DIR). 스크린샷은 docs/qa/2026-10-06/ 에 저장한다.
import { spawn } from "node:child_process";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { launch, measureFn, runAxe, sleep } from "./common.mjs";
import { startMock } from "./live-screen-mock.mjs";

const PHASE = process.argv[2] ?? "dev";
const API_PORT = Number(process.env.QA_API_PORT ?? 4611);
const WEB_PORT = Number(process.env.QA_WEB_PORT ?? 4612);
const WEB = `http://localhost:${WEB_PORT}`;
const API = `http://127.0.0.1:${API_PORT}`;
const FRONT = fileURLToPath(new URL("../..", import.meta.url));
const SHOTS = process.env.QA_SHOTS ?? fileURLToPath(new URL("../../../docs/qa/2026-10-06/", import.meta.url));
const OUT = process.env.QA_OUT ?? "/tmp/claude-0/qa-live-screen";
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const rec = (name, ok, note = "") => {
  results.push({ name, ok: !!ok, note });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${note ? "  — " + note : ""}`);
};

// ═══════════════════════ 가짜 서버·프런트 기동 ═══════════════════════
const mock = await startMock(API_PORT);
const setCtl = (q) => fetch(`${API}/__set?${q}`).then((r) => r.json());
const resetCtl = () => fetch(`${API}/__reset`).then((r) => r.json());
const getLog = () => fetch(`${API}/__log`).then((r) => r.json());

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
const AUTH_ENV = {
  AUTH_REQUIRED: "true", AUTH_COOKIE_INSECURE: "true", SESSION_SECRET: "s".repeat(40), PUBLIC_API_INTERNAL_TOKEN: "t".repeat(40),
  NEXT_PUBLIC_AUTH_ENABLED: "true", NEXT_PUBLIC_BROWSER_API_BASE_URL: "same-origin",
};
async function startWeb() {
  const base = { NEXT_PUBLIC_API_BASE_URL: API, NEXT_PUBLIC_BROWSER_API_BASE_URL: "", NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "" };
  const env = PHASE === "dev" ? { ...base, NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "true" } : PHASE === "auth" ? { ...base, ...AUTH_ENV, NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "true" } : base;
  if (PHASE === "dev") {
    web = runCmd("node", ["node_modules/next/dist/bin/next", "dev", "--webpack", "-p", String(WEB_PORT)], env, `${OUT}/web-dev.log`);
  } else {
    await new Promise((resolve, reject) => {
      const b = runCmd("npm", ["run", "build"], env, `${OUT}/web-build-${PHASE}.log`);
      b.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`build 실패 ${code}, 로그 ${OUT}/web-build-${PHASE}.log`))));
    });
    web = runCmd("node", ["node_modules/next/dist/bin/next", "start", "-p", String(WEB_PORT)], env, `${OUT}/web-start-${PHASE}.log`);
  }
  const up = PHASE === "auth" ? await waitHttp(`${WEB}/login`) : await waitHttp(`${WEB}/screener/pattern`);
  rec(`프런트(${PHASE}) 기동`, up);
  if (!up) throw new Error("프런트가 뜨지 않음");
  if (PHASE === "dev") for (const path of ["/screener", "/screener/pattern"]) await waitHttp(`${WEB}${path}`); // dev 첫 컴파일
}

// ═══════════════════════ 공통 도구 ═══════════════════════
const LIVE_RE = /\/api\/v1\/local\/screen(\/pattern)?\?/;
const ROWS = ".results-table tbody tr, .results-list > li";
const codeOf = (text) => (text.match(/\((1\d{5})\)/) || [])[1];
const idxOf = (code) => Number(code.slice(1));

function track(page) {
  const t = { live: [], normal: [], local: [], liveResponses: [], aborted: 0, pageErrors: [], consoleErrors: [], failedResources: [] };
  page.on("request", (r) => {
    const u = r.url();
    const at = Date.now();
    if (LIVE_RE.test(u)) t.live.push({ at, url: u, q: new URL(u).searchParams });
    else if (/\/api\/v1\/(screen|screen\/pattern)\?/.test(u)) t.normal.push({ at, url: u, q: new URL(u).searchParams });
    if (/\/local\//.test(u)) t.local.push(u);
  });
  page.on("response", async (r) => {
    if (!LIVE_RE.test(r.url())) return;
    try {
      t.liveResponses.push({ at: Date.now(), status: r.status(), url: r.url(), body: await r.json() });
    } catch {
      /* 본문 없음 */
    }
  });
  page.on("requestfailed", (r) => {
    if (LIVE_RE.test(r.url()) && /ABORTED/i.test(r.failure()?.errorText ?? "")) t.aborted += 1;
  });
  page.on("pageerror", (e) => t.pageErrors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    (/Failed to load resource/.test(text) ? t.failedResources : t.consoleErrors).push(text);
  });
  return t;
}
async function newPage(browser, { width = 1280, height = 900, ...opts } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, ...opts });
  const page = await ctx.newPage();
  return { ctx, page, t: track(page) };
}
async function until(fn, ms = 15000, step = 150) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      if (await fn()) return true;
    } catch {
      /* 다시 */
    }
    await sleep(step);
  }
  return false;
}
const SWITCH = 'button[role="switch"]';
const switchOn = (page) => page.getAttribute(SWITCH, "aria-checked").then((v) => v === "true");
async function openScreen(page, path) {
  await page.goto(`${WEB}${path}`);
  await page.waitForSelector("main h1");
}
async function applyScreener(page) {
  const btn = page.getByRole("button", { name: "조건 적용" });
  if (!(await btn.first().isVisible())) await page.click(".screener-page__mobile-filter-trigger");
  await page.getByRole("button", { name: "조건 적용" }).first().click();
}
async function waitRows(page, min = 1, ms = 15000) {
  return until(() => page.evaluate(([sel, m]) => document.querySelectorAll(sel).length >= m, [ROWS, min]), ms);
}
const rowCodes = (page) => page.evaluate((sel) => [...document.querySelectorAll(sel)].map((r) => (r.textContent.match(/\((1\d{5})\)/) || [])[1]), ROWS);
const mainText = (page) => page.evaluate(() => document.querySelector("main")?.innerText ?? "");
const bannerText = (page) => page.evaluate(() => document.querySelector(".live-banner")?.innerText ?? "");
const countSel = (page, sel) => page.evaluate((s) => document.querySelectorAll(s).length, sel);
const shot = (page, name) => page.screenshot({ path: `${SHOTS}live-screen-${name}.png`, fullPage: false });
const clickLive = (page, name) => page.locator(".live-button", { hasText: name }).first().click();
const liveCount = (t) => t.live.length;
/** 스크리너에서 장중 기준을 켜고 첫 결과(배너)가 나올 때까지 */
async function turnOnScreener(page) {
  await openScreen(page, "/screener");
  await page.waitForSelector(SWITCH, { timeout: 20000 });
  await applyScreener(page);
  await waitRows(page, 5);
  await page.click(SWITCH);
  return until(() => countSel(page, ".live-banner").then((n) => n > 0), 15000);
}
async function turnOnPattern(page) {
  await openScreen(page, "/screener/pattern");
  await page.waitForSelector(SWITCH, { timeout: 20000 });
  await waitRows(page, 5);
  await page.click(SWITCH);
  return until(() => countSel(page, ".live-banner").then((n) => n > 0), 15000);
}
async function layoutCheck(page, label) {
  const m = await page.evaluate(measureFn);
  const clippedOut = m.clipped.filter((c) => !c.inScroller);
  rec(`${label}: 가로 넘침 없음`, !m.overflow, `scrollWidth ${m.scrollWidth}/${m.vw}`);
  rec(`${label}: 잘림 없음`, clippedOut.length === 0, clippedOut.slice(0, 3).map((c) => `${c.n} ${c.left}~${c.right}`).join("; "));
  rec(`${label}: 조작 요소 겹침 없음`, m.overlaps.length === 0, m.overlaps.slice(0, 3).map((o) => `${o.a}×${o.b}`).join("; "));
  const axe = await runAxe(page);
  rec(`${label}: axe 위반 0`, axe.length === 0, axe.map((v) => `${v.id}(${v.nodes.length}) ${v.nodes[0]?.target}`).join("; "));
}
/** 본문 안 조작 요소 44px 이상(인라인 문장 링크 제외) */
const smallTargets = (page) =>
  page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll('main button, main select, main input, main [role="switch"]')) {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (!r.width || !r.height || cs.visibility === "hidden" || el.closest(".sr-only")) continue;
      if (r.height < 43.5) out.push(`${el.tagName.toLowerCase()}[${(el.textContent || "").trim().slice(0, 14)}] ${r.width.toFixed(0)}x${r.height.toFixed(0)}`);
    }
    return out;
  });
const paramsWithout = (q, drop = []) => [...q.entries()].filter(([k]) => !drop.includes(k)).map(([k, v]) => `${k}=${v}`).sort().join("&");

// ═══════════════════════ dev 단계 ═══════════════════════
async function dev(browser) {
  // ── A. 서버 렌더에는 전환도 화면도 없다 ──
  await resetCtl();
  for (const path of ["/screener", "/screener/pattern"]) {
    const html = await (await fetch(`${WEB}${path}`)).text();
    rec(`SSR ${path}: 전환 스위치·배너 없음`, !/role="switch"|live-switch|live-banner|장중 기준/.test(html));
  }

  // ── B. 기본은 꺼짐: 전환이 보이고, 꺼진 동안은 장중 기준 요청이 0건 ──
  {
    const { ctx, page, t } = await newPage(browser);
    await openScreen(page, "/screener");
    const shown = await page.waitForSelector(SWITCH, { timeout: 20000 }).then(() => true, () => false);
    rec("전환: 로컬 모드(내 PC)에서 '장중 기준' 스위치가 나타남", shown);
    rec("전환: 기본 꺼짐(aria-checked=false)·이름 '장중 기준'", !(await switchOn(page)) && /장중 기준/.test(await page.textContent(SWITCH)));
    await applyScreener(page);
    await waitRows(page, 5);
    await sleep(7000);
    rec("전환 꺼짐: 일봉 기준 요청은 있고 장중 기준 요청 0건", t.normal.length >= 1 && liveCount(t) === 0, `normal ${t.normal.length}, live ${liveCount(t)}`);
    rec("전환 꺼짐: 배너·'신규'·'일봉' 표지 없음", (await countSel(page, ".live-banner, .live-mark")) === 0);
    rec("전환 꺼짐: 기존 안내 '조건 판정은 일봉 기준' 그대로", /조건 판정은 일봉 기준/.test(await mainText(page)));
    rec("전환 꺼짐: 기존 결과 영역 낭독(aria-live=polite) 그대로", (await page.getAttribute(".screener-page__results", "aria-live")) === "polite");
    const dnd = await countSel(page, ".data-freshness-badge");
    rec("전환 꺼짐: 기존 기준시각 배지 그대로", dnd === 1);
    await ctx.close();
  }

  // ── C. 켜기: 같은 조건으로 요청, 기준 배너, 안내 교체 ──
  {
    await resetCtl();
    const { ctx, page, t } = await newPage(browser);
    await openScreen(page, "/screener");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await applyScreener(page);
    await waitRows(page, 5);
    const normalQ = t.normal[0].q;
    await page.click(SWITCH);
    const bannerUp = await until(() => countSel(page, ".live-banner").then((n) => n > 0), 15000);
    rec("켜기: 기준 배너가 나타남", bannerUp);
    rec("켜기: 스위치 aria-checked=true", await switchOn(page));
    const first = t.live[0];
    rec("켜기: 요청 경로 /api/v1/local/screen(패턴 아님)", !!first && new URL(first.url).pathname === "/api/v1/local/screen", first?.url);
    rec("켜기: 첫 요청에는 snapshot_id 없음", !!first && !first.q.has("snapshot_id"));
    rec("켜기: 일봉 화면과 같은 조건 파라미터(market·정렬·시총·거래량·page)", !!first && paramsWithout(first.q) === paramsWithout(normalQ), `${paramsWithout(first?.q ?? new URLSearchParams())} | ${paramsWithout(normalQ)}`);
    const banner = await bannerText(page);
    rec("배너: '장중 기준 · 계산 HH:MM:SS(N초 전) · 시세 수신 2700/2800종목 · 기준 일봉 2026-10-05'", /장중 기준\s*·\s*계산 \d\d:\d\d:\d\d\(\d+초 전\)\s*·\s*시세 수신 2700\/2800종목\s*·\s*기준 일봉 2026-10-05/.test(banner), banner.replace(/\n/g, " / ").slice(0, 200));
    rec("배너: 거래량 계열 부분값·PER·PBR·시가총액 일봉 기준 경고(항상)", banner.includes("거래량 계열(거래량·거래량 이상치·거래량비·급등 이력)은 장중 누적 부분값이며 PER·PBR·시가총액 순위는 일봉 기준입니다."));
    const text = await mainText(page);
    rec("켜짐 동안 기존 안내 '조건 판정은 일봉 기준'·'장중 값으로 다시 계산하지 않습니다' 교체됨", !/조건 판정은 일봉 기준이며/.test(text) && !/다시 계산하지 않습니다/.test(text));
    rec("켜짐 동안 일봉 기준시각 배지 없음(배너가 대신함)", (await countSel(page, ".data-freshness-badge")) === 0);
    rec("켜짐: 보조 경고 없음(시세 지연·커버율·보충 안내 없음 — 정상 상태)", !/시세 갱신이 지연|90% 미만|보충/.test(banner));
    const codes = await rowCodes(page);
    const expectDaily = codes.filter((c) => idxOf(c) % 9 === 0).length;
    const dailyMarks = await countSel(page, ".live-mark--daily");
    rec("항목별 '일봉' 표지: basis=daily 항목에만(개수 일치)", dailyMarks === expectDaily && expectDaily > 0, `표지 ${dailyMarks}, 기대 ${expectDaily}`);
    const marksOk = await page.evaluate(() => [...document.querySelectorAll(".live-mark--daily")].every((m) => /일봉/.test(m.textContent) && m.querySelector(".sr-only")));
    rec("'일봉' 표지: 글자 + 스크린리더 설명(색에만 의존 안 함)", marksOk);
    rec("켜짐: 결과 영역 aria-live=off(10초마다 바뀌는 목록을 읽지 않음)", (await page.getAttribute(".screener-page__results", "aria-live")) === "off");
    rec("켜짐: 낭독 영역(role=status, polite) 정확히 1곳", (await countSel(page, '.screener-page__results [role="status"]')) === 1 && (await page.getAttribute('.screener-page__results [role="status"]', "aria-live")) === "polite");
    rec("켜짐: 건수 문구(Pagination)는 낭독 제외(aria-live=off)", (await page.getAttribute(".pagination__summary", "aria-live")) === "off");
    await shot(page, "screener-1280-light");
    await ctx.close();
  }

  // ── D. 자동 갱신: 간격·제자리 교체·스크롤·쪽 유지·낭독 ──
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    // 결과 영역 낭독 변화 횟수 관측
    await page.evaluate(() => {
      window.__said = [];
      const el = document.querySelector('.screener-page__results [role="status"]');
      new MutationObserver(() => window.__said.push(el.textContent)).observe(el, { childList: true, characterData: true, subtree: true });
    });
    const firstRow = await page.$(".results-table tbody tr:first-child th a, .results-list > li:first-child a");
    const beforeText = await page.textContent(".results-table tbody tr:nth-child(2), .results-list > li:nth-child(2)");
    const start = Date.now();
    await waitRows(page, 5);
    await page.evaluate(() => window.scrollTo(0, 400));
    const y0 = await page.evaluate(() => window.scrollY);
    const n0 = liveCount(t);
    await until(() => liveCount(t) >= n0 + 3, 20000);
    const reqs = t.live.slice(-3);
    const gaps = reqs.slice(1).map((r, i) => (r.at - reqs[i].at) / 1000);
    rec("자동 갱신: refresh_seconds(5초) 간격으로 요청", gaps.length === 2 && gaps.every((g) => g >= 4 && g <= 7.5), `간격 ${gaps.map((g) => g.toFixed(1)).join(", ")}초`);
    rec("자동 갱신: 요청마다 snapshot_id 없음(최신 요청)", t.live.every((r) => !r.q.has("snapshot_id")));
    const y1 = await page.evaluate(() => window.scrollY);
    rec("자동 갱신: 스크롤 위치 유지(제자리 교체)", Math.abs(y1 - y0) <= 2 && y0 > 100, `${y0} → ${y1}`);
    rec("자동 갱신: 첫 행 DOM 요소가 그대로(깜빡임·재마운트 없음)", await firstRow.evaluate((el) => el.isConnected));
    const afterText = await page.textContent(".results-table tbody tr:nth-child(2), .results-list > li:nth-child(2)");
    rec("자동 갱신: 값이 새 스냅샷으로 바뀜(등락률 값 변화)", afterText !== beforeText, `${beforeText.replace(/\s+/g, " ").slice(0, 70)} → ${afterText.replace(/\s+/g, " ").slice(0, 70)}`);
    rec("자동 갱신: 스켈레톤 다시 나타나지 않음", (await countSel(page, ".screener-page__loading")) === 0);
    const said = await page.evaluate(() => window.__said);
    rec("낭독: 15초(3회 갱신) 동안 변경 알림 0~1회(갱신마다 읽지 않음)", said.length <= 1, `알림 ${said.length}회 ${JSON.stringify(said.slice(0, 2))}`);
    // 초 단위 시계
    const age1 = await page.evaluate(() => Number((document.querySelector(".live-banner__time")?.textContent.match(/\((\d+)초 전\)/) || [])[1]));
    const nn = liveCount(t);
    await sleep(2200);
    const age2 = await page.evaluate(() => Number((document.querySelector(".live-banner__time")?.textContent.match(/\((\d+)초 전\)/) || [])[1]));
    rec("'N초 전' 시계: 초 단위로 흐름(새 계산이 오면 줄어듦)", age2 > age1 || liveCount(t) > nn, `${age1} → ${age2}`);
    // 쪽 유지
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByRole("button", { name: "다음" }).click();
    await until(() => page.evaluate(() => /51–/.test(document.querySelector(".pagination__summary")?.textContent ?? "")), 8000);
    const nPage = liveCount(t);
    await until(() => liveCount(t) >= nPage + 2, 15000);
    const lastReqs = t.live.slice(-2);
    rec("쪽 유지: 2쪽에서 자동 갱신 요청이 모두 page=2", lastReqs.every((r) => r.q.get("page") === "2"), lastReqs.map((r) => r.q.get("page")).join(","));
    rec("쪽 유지: 갱신 후에도 2쪽 표시('51–')", /51–/.test(await page.textContent(".pagination__summary")));
    rec("자동 갱신: 페이지 오류·콘솔 오류 0", t.pageErrors.length === 0 && t.consoleErrors.length === 0, [...t.pageErrors, ...t.consoleErrors].join("; ").slice(0, 200));
    await ctx.close();
    void start;
  }

  // ── E. 신규 표지·최근 변화(편입/이탈) ──
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    await until(() => liveCount(t) >= 3, 20000);
    await sleep(1500);
    const entered = new Set();
    const left = new Set();
    for (const r of t.liveResponses) for (const c of r.body?.meta?.live?.changes?.entered ?? []) entered.add(c);
    for (const r of t.liveResponses) for (const c of r.body?.meta?.live?.changes?.left ?? []) left.add(c);
    const marked = await page.evaluate(() => [...document.querySelectorAll(".results-table tbody tr, .results-list > li")].filter((r) => r.querySelector(".live-mark--new")).map((r) => (r.textContent.match(/\((1\d{5})\)/) || [])[1]));
    const visible = await rowCodes(page);
    const expected = visible.filter((c) => entered.has(c));
    rec("신규 표지: changes.entered에 든 종목(보이는 쪽)에만 붙음", marked.length > 0 && marked.sort().join() === expected.sort().join(), `표지 ${marked.length}, 기대 ${expected.length}`);
    const sr = await page.evaluate(() => [...document.querySelectorAll(".live-mark--new")].every((m) => /신규/.test(m.textContent) && /최근 1분/.test(m.querySelector(".sr-only")?.textContent ?? "")));
    rec("신규 표지: 글자 '신규' + 스크린리더 설명", sr);
    const changesText = await page.evaluate(() => document.querySelector(".live-changes")?.innerText ?? "");
    rec("최근 변화: 편입·이탈 목록(시각 HH:MM:SS + 이름(코드))", /\d\d:\d\d:\d\d/.test(changesText) && /편입/.test(changesText) && /이탈/.test(changesText) && /모의종목\d{3}\(1\d{5}\)/.test(changesText), changesText.replace(/\n/g, " / ").slice(0, 160));
    const rowsN = await countSel(page, ".live-changes__row");
    rec("최근 변화: 최대 10건", rowsN >= 1 && rowsN <= 10, `${rowsN}건`);
    rec("신규 표지: 같은 종목이 갱신마다 중복 표지되지 않음(행당 1개)", await page.evaluate(() => [...document.querySelectorAll(".live-marks")].every((m) => m.querySelectorAll(".live-mark--new").length <= 1)));
    await shot(page, "screener-new-changes-1280");
    // 60초 만료: 이후 스냅샷의 changes를 끄고(null) 기다린다 → 이미 붙은 표지는 약 60초 뒤 사라지고 행은 유지
    await setCtl("noChanges=1");
    const stampAt = Date.now();
    const gone = await until(() => countSel(page, ".live-mark--new").then((n) => n === 0), 70000, 500);
    const waited = (Date.now() - stampAt) / 1000;
    rec("신규 표지: 약 60초 뒤 새로고침 없이 사라지고 행은 유지", gone && waited <= 66 && (await countSel(page, ROWS)) >= 5, `${waited.toFixed(0)}초`);
    await ctx.close();
  }

  // ── F. 일시정지·snapshot_id 고정·재개 ──
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    await until(() => liveCount(t) >= 2, 12000);
    await clickLive(page, "일시정지");
    const timeBefore = await page.evaluate(() => document.querySelector(".live-banner__time")?.textContent.match(/계산 (\d\d:\d\d:\d\d)/)?.[1]);
    await sleep(300);
    const pinned = await page.getAttribute(".live-banner", "data-snapshot-id"); // 화면이 고정한 스냅샷(고정 시점에 보이던 결과)
    rec("일시정지: aria-pressed=true + '일시정지 중' 표시 + 안내문", (await page.getAttribute('.live-button[aria-pressed]', "aria-pressed")) === "true" && /일시정지 중/.test(await bannerText(page)) && /같은 결과/.test(await bannerText(page)));
    const nP = liveCount(t);
    await sleep(12000);
    rec("일시정지: 12초 동안 자동 갱신 요청 0건", liveCount(t) === nP, `${liveCount(t) - nP}건`);
    // 서버에는 더 새로운 스냅샷이 생기게 한다(고정이 정말 이전 스냅샷을 쓰는지 확인)
    const newer = await (await fetch(`${API}/api/v1/local/screen?market=ALL&page=1`)).json();
    rec("준비: 서버 최신 스냅샷이 고정 스냅샷과 다름", newer.meta.live.snapshot_id !== pinned, `${pinned} → ${newer.meta.live.snapshot_id}`);
    await page.getByRole("button", { name: "다음" }).click();
    await until(() => page.evaluate(() => /51–/.test(document.querySelector(".pagination__summary")?.textContent ?? "")), 8000);
    const pageReq = t.live.at(-1);
    rec("일시정지 중 쪽 이동: 같은 snapshot_id + page=2", pageReq.q.get("snapshot_id") === pinned && pageReq.q.get("page") === "2", pageReq.url.slice(-80));
    const truth = await (await fetch(`${API}/api/v1/local/screen?market=ALL&page=2&snapshot_id=${pinned}`)).json();
    const shownCodes = await rowCodes(page);
    rec("일시정지 중 쪽 이동: 고정 스냅샷의 2쪽 결과와 표시가 같음(최신이 아님)", JSON.stringify(shownCodes) === JSON.stringify(truth.data.items.map((i) => i.stock_code)), `${shownCodes.length}행`);
    const timeAfter = await page.evaluate(() => document.querySelector(".live-banner__time")?.textContent.match(/계산 (\d\d:\d\d:\d\d)/)?.[1]);
    rec("일시정지 중: 배너의 계산 시각이 그대로(고정)", timeBefore === timeAfter, `${timeBefore} → ${timeAfter}`);
    rec("일시정지 중: 지연 표시가 뜨지 않음(의도된 고정)", !/지연/.test(await bannerText(page).then((s) => s.replace(/시세 갱신이 지연/g, ""))));
    await shot(page, "screener-paused-1280");
    await page.getByRole("button", { name: "이전" }).click();
    await until(() => page.evaluate(() => /1–/.test(document.querySelector(".pagination__summary")?.textContent ?? "")), 8000);
    rec("일시정지 중 이전 쪽도 같은 snapshot_id", t.live.at(-1).q.get("snapshot_id") === pinned && t.live.at(-1).q.get("page") === "1");
    const nR = liveCount(t);
    await clickLive(page, "일시정지"); // 해제
    await until(() => liveCount(t) > nR, 3000);
    const resumed = t.live.at(-1);
    rec("재개: 즉시 snapshot_id 없이 새로 요청", liveCount(t) > nR && !resumed.q.has("snapshot_id"));
    rec("재개: aria-pressed=false, 자동 갱신 다시 시작(7초 안 추가 요청)", (await page.getAttribute('.live-button[aria-pressed]', "aria-pressed")) === "false" && (await until(() => liveCount(t) >= nR + 2, 8000)));
    await ctx.close();
  }

  // ── G. 410: 고정 스냅샷 만료 ──
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    await until(() => liveCount(t) >= 1, 8000);
    await clickLive(page, "일시정지");
    await sleep(300);
    await setCtl("expireAll=1");
    const n = liveCount(t);
    await page.getByRole("button", { name: "다음" }).click();
    await until(() => liveCount(t) >= n + 2, 8000);
    const [expired, again] = t.live.slice(-2);
    rec("410: 만료된 snapshot_id 요청 → 이어서 snapshot_id 없이 새로 계산", expired.q.has("snapshot_id") && !again.q.has("snapshot_id") && again.q.get("page") === "2", `${expired.q.get("snapshot_id")} → ${again.q.get("snapshot_id")}`);
    await sleep(500);
    const b = await bannerText(page);
    rec("410: 만료 안내 표시 + 일시정지 유지(aria-pressed=true)", /만료되어 새로 계산/.test(b) && (await page.getAttribute('.live-button[aria-pressed]', "aria-pressed")) === "true", b.replace(/\n/g, " / ").slice(0, 160));
    rec("410: 오류 패널 없이 결과 유지(2쪽)", (await countSel(page, ".live-error")) === 0 && /51–/.test(await page.textContent(".pagination__summary")));
    const n2 = liveCount(t);
    await sleep(8000);
    rec("410 이후에도 일시정지 유지: 8초간 자동 갱신 0건", liveCount(t) === n2);
    const newPin = await page.getAttribute(".live-banner", "data-snapshot-id");
    await page.getByRole("button", { name: "이전" }).click();
    await until(() => liveCount(t) > n2, 5000);
    rec("410 이후 쪽 이동은 새 스냅샷에 고정", t.live.at(-1).q.get("snapshot_id") === newPin, `${t.live.at(-1).q.get("snapshot_id")} vs ${newPin}`);
    await ctx.close();
  }

  // ── H. 새로 계산·중복 합침·탭 가림 ──
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    await until(() => liveCount(t) >= 1, 8000);
    await sleep(1000);
    // '새로 계산'
    const n = liveCount(t);
    await clickLive(page, "새로 계산");
    rec("새로 계산: 즉시(1초 안) 요청", await until(() => liveCount(t) > n, 1500));
    // 중복 합침: 응답이 느린 동안 세 번 눌러도 요청 1건
    await sleep(1500);
    await setCtl("delayMs=1500");
    const n2 = liveCount(t);
    const btn = page.locator(".live-button", { hasText: "새로 계산" }).first();
    await btn.click(); await btn.click(); await btn.click();
    await sleep(300);
    rec("중복 합침: 응답 대기 중 '새로 계산' 3번 → 요청 1건", liveCount(t) === n2 + 1, `${liveCount(t) - n2}건`);
    await sleep(1800);
    await setCtl("delayMs=0");
    // 진행 중 요청 취소: 응답이 느린 동안(자동 갱신 요청 진행 중) 쪽 이동 → 진행 중이던 요청은 취소되고 새 요청만 남는다
    await setCtl("delayMs=4000");
    const ab0 = t.aborted;
    const n3 = liveCount(t);
    await until(() => liveCount(t) > n3, 8000, 50); // 다음 자동 갱신 요청이 나가 응답을 기다리는 중
    await page.getByRole("button", { name: "다음" }).click();
    await sleep(800);
    rec("취소: 응답 대기 중 쪽 이동하면 이전 요청 취소(ERR_ABORTED ≥1)", t.aborted > ab0, `취소 ${t.aborted - ab0}건`);
    await sleep(4500);
    rec("취소: 취소된 요청의 늦은 응답이 목록을 덮지 않음(2쪽 표시 유지)", /51–/.test(await page.textContent(".pagination__summary")));
    await setCtl("delayMs=0");
    await ctx.close();
  }
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    await until(() => liveCount(t) >= 1, 8000);
    const hide = async (h) => {
      await page.evaluate((hidden) => {
        Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
        Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
        document.dispatchEvent(new Event("visibilitychange"));
      }, h);
    };
    await sleep(1500);
    await hide(true);
    const n = liveCount(t);
    await sleep(13000);
    rec("탭 가림: 13초 동안 요청 0건(자동 갱신 중지)", liveCount(t) === n, `${liveCount(t) - n}건`);
    const t0 = Date.now();
    await hide(false);
    const back = await until(() => liveCount(t) > n, 3000, 50);
    rec("탭 복귀: 즉시(2초 안) 요청", back && Date.now() - t0 < 2500, `${Date.now() - t0}ms`);
    // 응답 대기 중 가림 → 취소
    await setCtl("delayMs=3000");
    const nn = liveCount(t);
    await until(() => liveCount(t) > nn, 9000, 30); // 다음 자동 갱신 요청이 나가 응답을 기다리는 중
    const ab = t.aborted;
    await hide(true);
    await sleep(1200);
    rec("탭 가림: 응답 대기 중 요청 취소", t.aborted > ab, `취소 ${t.aborted - ab}건`);
    await setCtl("delayMs=0");
    await hide(false);
    await ctx.close();
  }

  // ── I. 오류 상태 ──
  for (const [err, kind, titlePart, retry] of [
    ["stale409", "base_stale", "일봉 데이터가 너무 오래되어", false],
    ["e403", "forbidden", "권한이 없습니다", false],
    ["e404", "not_found", "장중 기준을 쓸 수 없습니다", false],
    ["e503cfg", "unavailable", "장중 기준을 쓸 수 없습니다", false],
    ["e400", "invalid", "조건 값이 올바르지 않습니다", false],
  ]) {
    await resetCtl();
    await setCtl(`err=${err}`);
    const { ctx, page, t } = await newPage(browser);
    await openScreen(page, "/screener");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await applyScreener(page);
    await waitRows(page, 5);
    await page.click(SWITCH);
    const shown = await until(() => countSel(page, `[data-live-error="${kind}"]`).then((n) => n > 0), 8000);
    rec(`오류 ${err}: 안내 패널(${kind}) 표시`, shown && (await page.textContent(".live-error")).includes(titlePart), (await page.textContent(".live-error").catch(() => "")).replace(/\s+/g, " ").slice(0, 120));
    rec(`오류 ${err}: 결과 표는 비움(믿을 수 없는 값을 남기지 않음)`, (await countSel(page, ROWS)) === 0);
    rec(`오류 ${err}: '일봉 기준으로 되돌리기'·'다시 시도' 버튼`, (await countSel(page, ".live-error .live-button")) === 2 && /일봉 기준으로 되돌리기/.test(await page.textContent(".live-error")));
    const n = liveCount(t);
    await sleep(11000);
    rec(`오류 ${err}: 자동 재시도 없음(11초간 추가 요청 0건)`, liveCount(t) === n, `${liveCount(t) - n}건`);
    if (err === "stale409") {
      await shot(page, "error-base-stale-390");
      const t2 = Date.now();
      await page.getByRole("button", { name: "일봉 기준으로 되돌리기" }).click();
      await until(() => countSel(page, ROWS).then((c) => c > 0), 8000);
      rec("되돌리기: 스위치 꺼짐 + 일봉 기준 결과·기준시각 배지 복귀", !(await switchOn(page)) && (await countSel(page, ".data-freshness-badge")) === 1 && (await countSel(page, ".live-banner, .live-error")) === 0, `${Date.now() - t2}ms`);
      rec("되돌리기: 일봉 기준 요청이 새로 발생", t.normal.length >= 2);
      const stored = await page.evaluate(() => localStorage.getItem("stock.liveScreen.on"));
      rec("되돌리기: 꺼짐이 이 브라우저에 기억됨(localStorage=0)", stored === "0", String(stored));
      const n3 = liveCount(t);
      await sleep(6500);
      rec("되돌리기 뒤 장중 기준 요청 0건", liveCount(t) === n3);
    }
    await ctx.close();
  }
  {
    // 되돌리기 → 오류 해결 후 다시 켜기
    await resetCtl();
    await setCtl("err=stale409");
    const { ctx, page, t } = await newPage(browser, { width: 390, height: 844 });
    await openScreen(page, "/screener");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await applyScreener(page);
    await waitRows(page, 5);
    await page.click(SWITCH);
    await until(() => countSel(page, ".live-error").then((n) => n > 0), 8000);
    await shot(page, "error-base-stale-390");
    await layoutCheck(page, "오류 패널(LIVE_BASE_STALE) @390");
    await setCtl("err=");
    await page.getByRole("button", { name: "다시 시도" }).click();
    rec("다시 시도: 서버가 회복되면 결과가 나타남(오류 패널 사라짐)", await until(() => countSel(page, ".live-banner").then((n) => n > 0), 8000) && (await countSel(page, ".live-error")) === 0);
    await ctx.close();
  }
  {
    // filling / notready: 진행률 표시 + 5초 자동 재시도
    for (const [err, kind, extra] of [["filling", "base_filling", "fillDone=1400&fillTotal=2800&gap=2"], ["notready", "quotes_not_ready", ""]]) {
      await resetCtl();
      await setCtl(`err=${err}&${extra}`);
      const { ctx, page, t } = await newPage(browser);
      await openScreen(page, "/screener");
      await page.waitForSelector(SWITCH, { timeout: 20000 });
      await applyScreener(page);
      await waitRows(page, 5);
      await page.click(SWITCH);
      await until(() => countSel(page, `[data-live-error="${kind}"]`).then((n) => n > 0), 8000);
      const txt = await page.textContent(".live-error");
      if (err === "filling") {
        const pr = await page.evaluate(() => { const p = document.querySelector(".live-error progress"); return p ? [p.value, p.max] : null; });
        rec("LIVE_BASE_FILLING: 진행률 done/total 표시(1400/2800 + progress)", /1400\/2800/.test(txt) && pr?.[0] === 1400 && pr?.[1] === 2800, txt.replace(/\s+/g, " ").slice(0, 140));
        await shot(page, "filling-1280");
      } else rec("LIVE_QUOTES_NOT_READY: 안내 표시", /시세를 모으는 중/.test(txt));
      await sleep(5500);
      const reqs = t.live;
      rec(`${err}: 5초 간격 자동 재시도(요청 ≥2, 간격 4~6.5초)`, reqs.length >= 2 && (reqs[1].at - reqs[0].at) / 1000 >= 4 && (reqs[1].at - reqs[0].at) / 1000 <= 6.5, reqs.slice(0, 2).map((r) => r.at).join(","));
      if (err === "filling") {
        await setCtl("fillDone=2000");
        await until(() => page.evaluate(() => /2000\/2800/.test(document.querySelector(".live-error")?.textContent ?? "")), 8000);
        rec("LIVE_BASE_FILLING: 재시도마다 진행률 갱신(2000/2800)", true);
      }
      await setCtl("err=&fill=ready&gap=2&filled=2700");
      rec(`${err}: 준비되면 결과 표시·오류 패널 사라짐(새로고침 없이)`, await until(() => countSel(page, ".live-banner").then((n) => n > 0), 10000) && (await countSel(page, ".live-error")) === 0);
      await ctx.close();
    }
  }
  {
    // 성공 뒤 일시 오류: 마지막 값 유지 + 지연 표시 + 백오프 + 복구
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    await until(() => liveCount(t) >= 1, 8000);
    const codes0 = await rowCodes(page);
    const lastOkAt = t.liveResponses.at(-1).at;
    await setCtl("err=e500");
    const n = liveCount(t);
    await until(() => liveCount(t) >= n + 4, 60000, 250);
    const times = t.live.slice(n).map((r) => r.at); // 첫 실패 요청부터
    const gaps = times.slice(1).map((x, i) => (x - times[i]) / 1000);
    rec("실패 백오프: 실패 뒤 재시도 간격 5→10→20초로 늘어남(상한 30초)", gaps.length >= 3 && gaps[0] >= 4 && gaps[0] <= 7 && gaps[1] >= 9 && gaps[1] <= 12 && gaps[2] >= 19 && gaps[2] <= 23, gaps.map((g) => g.toFixed(1)).join(", "));
    rec("실패 중: 마지막 값(행·배너) 그대로 유지", JSON.stringify(await rowCodes(page)) === JSON.stringify(codes0) && (await countSel(page, ".live-banner")) === 1);
    const b = await bannerText(page);
    rec("실패 중: '최근 갱신에 실패해 마지막 값' 안내 + 서버 상태 코드", /최근 갱신에 실패해 마지막 값을 보여 줍니다/.test(b) && /500 INTERNAL_ERROR/.test(b), b.replace(/\n/g, " / ").slice(-200));
    const sinceOk = (Date.now() - lastOkAt) / 1000;
    rec("지연: 마지막 성공이 15초(3×refresh) 넘으면 '지연' 배지", sinceOk > 15 && (await countSel(page, ".live-badge--delayed")) === 1 && /지연/.test(await page.textContent(".live-badge--delayed")), `${sinceOk.toFixed(0)}초`);
    await shot(page, "screener-delayed-1280");
    await setCtl("err=");
    rec("복구: 다음 재시도에서 성공하면 '지연'·실패 안내 사라짐", await until(() => page.evaluate(() => !document.querySelector(".live-badge--delayed") && !/최근 갱신에 실패/.test(document.querySelector(".live-banner")?.textContent ?? "")), 35000, 300));
    await ctx.close();
  }
  {
    // 200인데 모양이 어긋난 응답은 성공으로 받아들이지 않는다
    await resetCtl();
    await setCtl("err=bad200");
    const { ctx, page } = await newPage(browser);
    await openScreen(page, "/screener");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await applyScreener(page);
    await waitRows(page, 5);
    await page.click(SWITCH);
    rec("모양 어긋난 200(meta.live 없음): 성공으로 받아들이지 않고 오류 안내", await until(() => countSel(page, '[data-live-error="bad_response"]').then((n) => n > 0), 8000) && (await countSel(page, ".live-banner")) === 0);
    await ctx.close();
  }

  // ── J. 기준 배너 안내(base_fill·stale·커버율) ──
  {
    await resetCtl();
    await setCtl("refresh=5&fill=running&fillDone=1000&fillTotal=2800&gap=2&pending=1800&excluded=12&mismatched=3&stale=1&covered=2000&policy=daily");
    const { ctx, page } = await newPage(browser);
    await turnOnScreener(page);
    const b = await bannerText(page);
    rec("안내: 보충 중 진행(done/total)·progress", /1000\/2800종목/.test(b) && (await countSel(page, ".live-banner progress")) === 1, b.replace(/\n/g, " / ").slice(0, 200));
    rec("안내: '12종목은 증권사 일봉 보충이 안 되어 결과에서 제외됨'", b.includes("12종목은 증권사 일봉 보충이 안 되어 결과에서 제외됨"));
    rec("안내: 보충 중(pending) '1800종목은 일봉 보충 중'(제외와 구분)", b.includes("1800종목은 일봉 보충 중") && !b.includes("1800종목은 증권사 일봉 보충이 안 되어"));
    rec("안내: 불일치 3개(수정주가 불일치 등)", /종가가 달라 계산에서 뺀 종목 3개/.test(b));
    rec("안내: 시세 갱신 지연(stale)", /시세 갱신이 지연되고 있습니다/.test(b));
    rec("안내: 커버율 90% 미만 → 등락률 순위는 일봉 기준", /90% 미만이라 등락률 순위는 일봉 기준/.test(b) && /2000\/2800종목/.test(b));
    await shot(page, "screener-notices-1280");
    await setCtl("fill=ready&pending=0&excluded=0&mismatched=0&filled=2700&stale=0&covered=2700&policy=live");
    await until(() => page.evaluate(() => /2거래일 뒤처져/.test(document.querySelector(".live-banner")?.textContent ?? "")), 9000);
    const b2 = await bannerText(page);
    rec("안내: 보충 완료 '2거래일 뒤처져 증권사 일봉으로 보충(보충 2700종목)', 경고들은 사라짐", /2거래일 뒤처져 증권사 일봉으로 보충해 계산했습니다\(보충 2700종목\)/.test(b2) && !/보충 중|제외됨|지연되고|90% 미만/.test(b2), b2.replace(/\n/g, " / ").slice(0, 220));
    await ctx.close();
  }

  // ── K. 조건 변경·기억·저장소 차단·키보드 ──
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await turnOnScreener(page);
    await until(() => liveCount(t) >= 1, 8000);
    await page.getByRole("button", { name: "코스피" }).first().click().catch(() => {});
    await applyScreener(page);
    await until(() => t.live.some((r) => r.q.get("market") === "KOSPI"), 8000);
    const kospi = t.live.filter((r) => r.q.get("market") === "KOSPI").at(-1);
    rec("조건 적용(켜짐): 새 조건(market=KOSPI)·page=1·snapshot_id 없음으로 새 요청", !!kospi && kospi.q.get("page") === "1" && !kospi.q.has("snapshot_id"));
    await until(() => rowCodes(page).then((c) => c.length > 0 && c.every((x) => idxOf(x) % 2 === 0)), 8000);
    rec("조건 적용(켜짐): 결과가 새 조건(코스피 = 짝수 코드)으로 교체", (await rowCodes(page)).every((x) => idxOf(x) % 2 === 0));
    // 새로고침 뒤에도 켜짐 기억
    await page.reload();
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    rec("기억: 새로고침 뒤에도 켜짐(localStorage=1) 유지, 조건 적용 전에는 요청 0건", await until(() => switchOn(page), 5000));
    const before = liveCount(t);
    await sleep(2500);
    rec("기억: 켜짐이어도 조건 적용 전에는 장중 기준 요청 없음", liveCount(t) === before);
    await ctx.close();
  }
  {
    // 저장소 차단: 읽기·쓰기가 던져도 전환이 동작
    await resetCtl();
    const { ctx, page, t } = await newPage(browser);
    await ctx.addInitScript(() => {
      const boom = () => { throw new Error("blocked"); };
      Object.defineProperty(window, "localStorage", { configurable: true, get: boom });
    });
    await openScreen(page, "/screener");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await applyScreener(page);
    await waitRows(page, 5);
    await page.click(SWITCH);
    rec("저장소 차단(localStorage 접근이 던짐): 켜짐이 동작하고 배너 표시", await until(() => countSel(page, ".live-banner").then((n) => n > 0), 10000) && (await switchOn(page)));
    await page.click(SWITCH);
    rec("저장소 차단: 끄기도 동작(일봉 기준 복귀)", !(await switchOn(page)) && (await countSel(page, ".live-banner")) === 0);
    rec("저장소 차단: 페이지 오류 0", t.pageErrors.length === 0, t.pageErrors.join("; "));
    await ctx.close();
  }
  {
    // 키보드
    await resetCtl();
    await setCtl("refresh=5");
    const { ctx, page, t } = await newPage(browser);
    await openScreen(page, "/screener");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await applyScreener(page);
    await waitRows(page, 5);
    await page.focus(SWITCH);
    await page.keyboard.press("Space");
    rec("키보드: 스위치에 포커스 후 Space로 켜짐", await until(() => switchOn(page), 3000) && (await until(() => countSel(page, ".live-banner").then((n) => n > 0), 8000)));
    const focusStyle = await page.evaluate(() => { const b = document.querySelector('button[role="switch"]'); b.focus(); return getComputedStyle(b).outlineStyle; });
    rec("키보드: 스위치 포커스 표시(outline)", focusStyle !== "none");
    await page.focus(".live-button");
    await page.keyboard.press("Enter");
    rec("키보드: 일시정지 버튼 Enter로 동작(aria-pressed=true)", await until(() => page.getAttribute('.live-button[aria-pressed]', "aria-pressed").then((v) => v === "true"), 3000));
    const tabbable = await page.evaluate(() => [...document.querySelectorAll(".live-panel button")].every((b) => b.tabIndex >= 0));
    rec("키보드: 배너 조작 버튼이 모두 Tab 순서에 포함", tabbable);
    await ctx.close();
    void t;
  }

  // ── L. 패턴 화면 ──
  {
    await resetCtl();
    await setCtl("refresh=5&minInterval=3");
    const { ctx, page, t } = await newPage(browser);
    await openScreen(page, "/screener/pattern");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await waitRows(page, 5);
    const nq = t.normal[0]?.q;
    const defText = async () => (await page.evaluate(() => document.querySelector(".pattern-definition__note")?.textContent ?? ""));
    await page.click(SWITCH);
    rec("패턴: 켜기 → 배너", await until(() => countSel(page, ".live-banner").then((n) => n > 0), 15000));
    const first = t.live[0];
    rec("패턴: 요청 경로 /api/v1/local/screen/pattern + 같은 조건(required·market·page_size)", !!first && new URL(first.url).pathname === "/api/v1/local/screen/pattern" && paramsWithout(first.q) === paramsWithout(nq), `${paramsWithout(first?.q ?? new URLSearchParams())} | ${paramsWithout(nq ?? new URLSearchParams())}`);
    await page.click(".pattern-definition__summary");
    rec("패턴: '계산 기준' 문구가 일봉 기준에서 장중 기준 문구로 교체", /장중 기준/.test(await defText()) && !/종가·거래량 일봉 기준/.test(await defText()), (await defText()).slice(0, 80));
    const codes = await rowCodes(page);
    const exp = codes.filter((c) => idxOf(c) % 9 === 0).length;
    rec("패턴: 항목별 '일봉' 표지", (await countSel(page, ".live-mark--daily")) === exp && exp > 0, `${await countSel(page, ".live-mark--daily")}/${exp}`);
    rec("패턴: 비예측 고지(PatternNotice)는 그대로", (await countSel(page, ".pattern-notice")) === 1);
    // 일시정지 + 쪽 이동
    await until(() => liveCount(t) >= 2, 10000);
    await clickLive(page, "일시정지");
    await sleep(300);
    const pinned = await page.getAttribute(".live-banner", "data-snapshot-id");
    await page.getByRole("button", { name: "다음" }).click();
    await until(() => page.evaluate(() => /51–/.test(document.querySelector(".pagination__summary")?.textContent ?? "")), 8000);
    rec("패턴: 일시정지 중 쪽 이동은 같은 snapshot_id", t.live.at(-1).q.get("snapshot_id") === pinned && t.live.at(-1).q.get("page") === "2");
    await clickLive(page, "일시정지");
    await shot(page, "pattern-1280-light");
    // 되돌리기
    await page.click(SWITCH);
    await until(() => countSel(page, ".live-banner").then((n) => n === 0), 5000);
    await until(() => countSel(page, ROWS).then((c) => c > 0), 8000);
    rec("패턴: 끄면 일봉 기준 화면 복귀(기준시각 배지·원래 계산 기준 문구)", (await countSel(page, ".data-freshness-badge")) === 1 && (await countSel(page, ".live-mark")) === 0);
    await ctx.close();
  }

  // ── M. 폭·axe·스크린샷(밝은/어두운, 데스크톱/폰) ──
  for (const [w, h] of [[1280, 900], [390, 844], [320, 700]]) {
    for (const scheme of ["light", "dark"]) {
      await resetCtl();
      await setCtl("refresh=5&dailyMod=9");
      const { ctx, page } = await newPage(browser, { width: w, height: h, colorScheme: scheme });
      await turnOnScreener(page);
      await sleep(600);
      await shot(page, `screener-${w}-${scheme}`);
      if (scheme === "light") {
        await layoutCheck(page, `장중 기준 /screener @${w}`);
        const small = await smallTargets(page);
        rec(`장중 기준 /screener @${w}: 본문 조작 요소 높이 44px 이상`, small.length === 0, small.slice(0, 4).join("; "));
      }
      await ctx.close();
      const p2 = await newPage(browser, { width: w, height: h, colorScheme: scheme });
      await turnOnPattern(p2.page);
      await sleep(600);
      await shot(p2.page, `pattern-${w}-${scheme}`);
      if (scheme === "light") await layoutCheck(p2.page, `장중 기준 /screener/pattern @${w}`);
      await p2.ctx.close();
    }
  }
  {
    // 모션 줄이기·고대비: 전환 애니메이션 없음, 강제 색상에서도 스위치 상태 구분
    await resetCtl();
    const { ctx, page } = await newPage(browser, { reducedMotion: "reduce", forcedColors: "active" });
    await openScreen(page, "/screener");
    await page.waitForSelector(SWITCH, { timeout: 20000 });
    await applyScreener(page);
    await waitRows(page, 5);
    await page.click(SWITCH);
    await until(() => countSel(page, ".live-banner").then((n) => n > 0), 10000);
    const tr = await page.evaluate(() => [".live-button", ".live-switch__control", ".live-switch__thumb"].map((s) => getComputedStyle(document.querySelector(s)).transitionDuration));
    rec("모션 줄이기: 전환 애니메이션 없음(transition 0s)", tr.every((d) => /^0s(, 0s)*$/.test(d)), tr.join("|"));
    await shot(page, "screener-forced-colors-1280");
    const axe = await runAxe(page);
    rec("고대비(forced-colors)+모션 줄이기: axe 위반 0", axe.length === 0, axe.map((v) => v.id).join(","));
    await ctx.close();
  }
}

// ═══════════════════════ prod 단계 ═══════════════════════
async function prod(browser) {
  await resetCtl();
  for (const path of ["/screener", "/screener/pattern"]) {
    const html = await (await fetch(`${WEB}${path}`)).text();
    rec(`prod SSR ${path}: 전환 스위치·배너 없음`, !/role="switch"|live-switch|live-banner|장중 기준/.test(html));
  }
  for (const path of ["/screener", "/screener/pattern"]) {
    const { ctx, page, t } = await newPage(browser);
    await openScreen(page, path);
    if (path === "/screener") await applyScreener(page);
    await waitRows(page, 5);
    await sleep(13000);
    rec(`prod ${path}: 스위치·배너 없음(하이드레이션 뒤에도)`, (await countSel(page, 'button[role="switch"], .live-switch, .live-banner, .live-mark')) === 0);
    rec(`prod ${path}: 장중 기준 요청 0건·/local/ 요청 0건`, t.live.length === 0 && t.local.length === 0, `live ${t.live.length}, local ${t.local.length}`);
    rec(`prod ${path}: 일봉 기준 요청은 정상(≥1건)`, t.normal.length >= 1);
    rec(`prod ${path}: 낭독(aria-live=polite)·기준시각 배지 그대로`, (await page.getAttribute(".screener-page__results", "aria-live")) === "polite" && (await countSel(page, ".data-freshness-badge")) === 1);
    // 화면 전환 저장값이 있어도(이전 로컬 세션 값) 켜지지 않는다
    await page.evaluate(() => localStorage.setItem("stock.liveScreen.on", "1"));
    await page.reload();
    await waitRows(page, 5).catch(() => {});
    await sleep(2500);
    const t2 = t.live.length;
    rec(`prod ${path}: localStorage에 켜짐(1)이 있어도 스위치·요청 없음`, (await countSel(page, 'button[role="switch"], .live-banner')) === 0 && t2 === 0);
    rec(`prod ${path}: 페이지 오류 0`, t.pageErrors.length === 0, t.pageErrors.join("; "));
    await ctx.close();
  }
  const log = await getLog();
  rec("prod: 가짜 서버가 받은 /local/ 요청 0건(브라우저 전체)", log.filter((r) => r.path.includes("/local/")).length === 0, `${log.length}건 중 local ${log.filter((r) => r.path.includes("/local/")).length}`);
  // 번들 검사: 운영 번들에 장중 기준 요청 코드가 남아 있는지(DEC-085와 같은 방식 + 문자열 검사)
  const staticDir = `${FRONT}.next/static`;
  const files = [];
  (function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = `${d}/${e.name}`;
      if (e.isDirectory()) walk(p);
      else if (/\.(js|css)$/.test(e.name)) files.push(p);
    }
  })(staticDir);
  const needles = ["api/v1/local/screen", "snapshot_id", "SNAPSHOT_EXPIRED", "LIVE_BASE_STALE", "LIVE_BASE_FILLING", "LIVE_QUOTES_NOT_READY", "stock.liveScreen.on", "kis_daily_price"];
  const hits = {};
  for (const n of needles) hits[n] = files.filter((f) => fs.readFileSync(f, "utf8").includes(n)).length;
  const html = await (await fetch(`${WEB}/screener`)).text();
  console.log("번들 문자열 검사(운영 빌드, 파일 수):", JSON.stringify(hits), `정적 파일 ${files.length}개`);
  rec("prod 번들: 장중 기준 요청 경로·오류 코드·저장 키·증권사 일봉 문자열이 JS에 없음(snapshot_id는 조건 정리 함수의 파라미터 이름으로만 남음)", ["api/v1/local/screen", "SNAPSHOT_EXPIRED", "LIVE_BASE_STALE", "LIVE_BASE_FILLING", "LIVE_QUOTES_NOT_READY", "stock.liveScreen.on", "kis_daily_price"].every((n) => hits[n] === 0), JSON.stringify(hits));
  void html;
}

// ═══════════════════════ auth 단계(웹 서버 대행 경로) ═══════════════════════
async function auth(browser) {
  const { signSession } = await import("../../src/lib/auth/session.ts");
  const mint = (role) => {
    const now = Math.floor(Date.now() / 1000);
    const uid = role === "admin" ? "11111111-1111-4111-8111-111111111111" : "22222222-2222-4222-8222-222222222222";
    return signSession({ v: 3, uid, sid: "33333333-3333-4333-8333-333333333333", rm: 0, rl: role === "admin" ? "a" : "u", un: role, dn: role === "admin" ? "관리자" : "회원", iat: now, exp: now + 3600, chk: now }, AUTH_ENV.SESSION_SECRET);
  };
  const withCookie = async (role, opts = {}) => {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, ...opts });
    if (role) await ctx.addCookies([{ name: "session", value: mint(role), url: WEB }]);
    const page = await ctx.newPage();
    return { ctx, page, t: track(page) };
  };
  await resetCtl();
  await setCtl("refresh=5&minInterval=3");

  // 웹 서버 대행 경로(직접 호출)
  {
    const { ctx } = await withCookie(null);
    const anon = await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=1`);
    rec("BFF: 비로그인 /api/v1/local/screen → 401", anon.status() === 401, String(anon.status()));
    await ctx.close();
  }
  {
    const { ctx } = await withCookie("user");
    for (const p of ["/api/v1/local/screen?market=ALL&page=1", "/api/v1/local/screen/pattern?market=ALL&page=1"]) {
      const r = await ctx.request.get(`${WEB}${p}`);
      const j = await r.json().catch(() => null);
      rec(`BFF: 일반 회원 ${p.split("?")[0]} → 403 FORBIDDEN(API까지 가지 않음)`, r.status() === 403 && j?.error?.code === "FORBIDDEN", `${r.status()} ${j?.error?.code}`);
    }
    const ok = await ctx.request.get(`${WEB}/api/v1/screen?market=ALL&page=1`);
    rec("BFF: 일반 회원의 기존 /api/v1/screen은 그대로 200", ok.status() === 200, String(ok.status()));
    await ctx.close();
  }
  {
    const before = (await getLog()).length;
    const { ctx } = await withCookie("admin");
    for (const [p, expectPath] of [["/api/v1/local/screen?market=ALL&page=1", "/api/v1/local/screen"], ["/api/v1/local/screen/pattern?market=ALL&required=c1%2Cc2&page=1&page_size=50", "/api/v1/local/screen/pattern"]]) {
      const r = await ctx.request.get(`${WEB}${p}`);
      const j = await r.json().catch(() => null);
      rec(`BFF: 관리자 ${expectPath} → 200 + meta.live.snapshot_id`, r.status() === 200 && !!j?.meta?.live?.snapshot_id, String(r.status()));
    }
    const log = (await getLog()).slice(before).filter((r) => r.path.includes("/local/screen"));
    rec("BFF: API로 내부 토큰·회원 id·세션 id 헤더를 붙여 전달", log.length >= 2 && log.every((r) => r.token === AUTH_ENV.PUBLIC_API_INTERNAL_TOKEN && r.user === "11111111-1111-4111-8111-111111111111" && r.sid === "33333333-3333-4333-8333-333333333333"), JSON.stringify(log[0]));
    // 스냅샷 고정 쿼리도 그대로 전달
    const first = await (await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=1`)).json();
    const sid = first.meta.live.snapshot_id;
    const pinned = await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=2&snapshot_id=${sid}`);
    rec("BFF: snapshot_id 쿼리가 그대로 전달됨(같은 스냅샷 2쪽)", pinned.status() === 200 && (await pinned.json()).meta.live.snapshot_id === sid);
    const gone = await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=1&snapshot_id=snap-nope`);
    rec("BFF: API의 410 SNAPSHOT_EXPIRED 상태·코드가 그대로 전달됨", gone.status() === 410 && (await gone.json()).error?.code === "SNAPSHOT_EXPIRED", String(gone.status()));
    await setCtl("err=filling&fillDone=10&fillTotal=100&gap=2");
    const fill = await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=1`);
    const fj = await fill.json();
    rec("BFF: 503 LIVE_BASE_FILLING의 error.details(done/total/gap_days)가 그대로 전달됨", fill.status() === 503 && fj.error?.details?.done === 10 && fj.error?.details?.total === 100, JSON.stringify(fj.error));
    await setCtl("err=stale409");
    const st = await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=1`);
    rec("BFF: 409 LIVE_BASE_STALE 그대로 전달", st.status() === 409 && (await st.json()).error?.code === "LIVE_BASE_STALE");
    await setCtl("err=");
    // 허용되지 않는 변형 경로
    // 끝 슬래시는 Next가 경로를 정리해 핸들러에 넘기므로(기존 /api/v1/screen/도 같음) 허용 목록의 정규식 단위 시험(check-auth.mjs)으로 확인한다.
    for (const p of ["/api/v1/local/screen/other", "/api/v1/local/screens", "/api/v1/local/screen/pattern/x"]) {
      const r = await ctx.request.get(`${WEB}${p}?market=ALL`);
      rec(`BFF: 허용되지 않은 경로 ${p} → 404`, r.status() === 404, String(r.status()));
    }
    // 쿼리 길이
    const longOk = "&" + Array.from({ length: 14 }, (_, i) => `f${i}=${"9".repeat(60)}`).join("&"); // 약 880자
    const r1 = await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=1${longOk}`);
    rec("BFF: 긴 조건(약 900자, 모든 조건을 최대로 채운 길이) 통과", r1.status() === 200, String(r1.status()));
    const r2 = await ctx.request.get(`${WEB}/api/v1/local/screen?market=ALL&page=1&x=${"9".repeat(2100)}`);
    rec("BFF: 쿼리 2048자 초과 → 400 INVALID_PARAMETER", r2.status() === 400, String(r2.status()));
    await ctx.close();
  }

  // 화면: 관리자
  {
    const { ctx, page, t } = await withCookie("admin");
    await openScreen(page, "/screener");
    const shown = await page.waitForSelector(SWITCH, { timeout: 20000 }).then(() => true, () => false);
    rec("로그인 로컬(관리자): 스위치가 나타남(/auth/me 확인 뒤)", shown);
    await applyScreener(page);
    await waitRows(page, 5);
    await page.click(SWITCH);
    const up = await until(() => countSel(page, ".live-banner").then((n) => n > 0), 15000);
    rec("로그인 로컬(관리자): 켜면 대행 경로(웹 서버 same-origin)로 결과·배너", up && t.live.every((r) => r.url.startsWith(WEB)), t.live[0]?.url.slice(0, 60));
    await until(() => liveCount(t) >= 2, 10000);
    rec("로그인 로컬(관리자): 자동 갱신 동작", liveCount(t) >= 2);
    rec("로그인 로컬(관리자): 페이지 오류 0", t.pageErrors.length === 0, t.pageErrors.join("; "));
    await ctx.close();
  }
  // 화면: 일반 회원 — 스위치도 요청도 없음
  {
    const { ctx, page, t } = await withCookie("user");
    await page.addInitScript(() => localStorage.setItem("stock.liveScreen.on", "1"));
    for (const path of ["/screener", "/screener/pattern"]) {
      await openScreen(page, path);
      if (path === "/screener") await applyScreener(page);
      await waitRows(page, 5);
      await sleep(9000);
      rec(`로그인 로컬(일반 회원) ${path}: 스위치·배너 없음(저장값 1이 있어도)`, (await countSel(page, 'button[role="switch"], .live-switch, .live-banner')) === 0);
      rec(`로그인 로컬(일반 회원) ${path}: /local/screen 요청 0건`, t.live.length === 0, `${t.live.length}건`);
    }
    const log = (await getLog()).filter((r) => r.path.includes("/local/screen") && r.user === "22222222-2222-4222-8222-222222222222");
    rec("로그인 로컬(일반 회원): API가 받은 /local/screen 요청 0건", log.length === 0);
    await ctx.close();
  }
}

// ═══════════════════════ 실행 ═══════════════════════
const browser = await launch();
let crashed = null;
try {
  await startWeb();
  if (PHASE === "dev") await dev(browser);
  else if (PHASE === "prod") await prod(browser);
  else if (PHASE === "auth") await auth(browser);
} catch (e) {
  crashed = e;
  rec("시험 진행 중 예외 없음", false, String(e?.stack ?? e).slice(0, 400));
} finally {
  await browser.close().catch(() => {});
  killGroup(web);
  mock.close();
}
const pass = results.filter((r) => r.ok).length;
console.log(`\n== ${PHASE}: ${pass}/${results.length} 통과 ==`);
fs.writeFileSync(`${OUT}/result-${PHASE}.json`, JSON.stringify(results, null, 2));
for (const r of results.filter((x) => !x.ok)) console.log(`FAIL: ${r.name} — ${r.note}`);
process.exit(pass === results.length && !crashed ? 0 : 1);
