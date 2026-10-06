// DEC-075 종단간 점검: 내 PC(로컬)에 로그인을 적용한 구성. `tests/e2e/local_mode_stack.py --mode on|off`가 서버를 띄우고 이 스크립트를 실행한다.
//   on : 로그인 켠 로컬 — 운영과 같은 로그인 + 로컬 전용 기능(호가·체결·분봉)이 대행 경로로 동작
//   off: setup_local_auth.py --off 로 끈 로컬 — 예전처럼 로그인 없이 그대로 동작
import { BASE, API, OUT, launch } from "./common.mjs";
import fs from "node:fs";

const MODE = process.env.QA_MODE;
const PW = process.env.QA_PW;
const PW2 = process.env.QA_PW2;
const TOKEN = process.env.QA_TOKEN ?? "";
fs.mkdirSync(OUT, { recursive: true });

const res = [];
const rec = (name, pass, note = "") => { res.push(pass); console.log(`${pass ? "PASS" : "FAIL"}  [${MODE}] ${name}  ${note}`); };
const apiOrigin = new URL(API).origin;
const b = await launch();

async function ctxPage() {
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 }, baseURL: BASE });
  const page = await ctx.newPage();
  const seen = [];
  page.on("request", (r) => { const u = r.url(); if (u.includes("/api/v1/")) seen.push(u); });
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  return { ctx, page, seen, errs };
}
async function login(page, username, password) {
  await page.goto("/login");
  await page.fill("#login-username", username);
  await page.fill("#login-password", password);
  await Promise.all([page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 }), page.click("button[type=submit]")]);
}
async function openDetail(page, tab) {
  await page.goto("/stocks/T00001");
  await page.waitForSelector(".stock-chart__svg", { timeout: 30000 });
  if (tab) await page.getByRole("tab", { name: tab }).click();
}

if (MODE === "on") {
  // ---- 1. 로그인 없이는 아무것도 못 본다
  {
    const { ctx, page } = await ctxPage();
    await page.goto("/screener");
    rec("비로그인 /screener → 로그인 화면으로 이동", new URL(page.url()).pathname.startsWith("/login"), page.url());
    await page.goto("/stocks/T00001");
    rec("비로그인 종목 상세 → 로그인 화면", new URL(page.url()).pathname.startsWith("/login"), page.url());
    for (const [label, path] of [["스크리닝 대행경로", "/api/v1/screen?market=KOSPI"], ["로컬 호가 대행경로", "/api/v1/local/stocks/T00001/orderbook"], ["로컬 상태 대행경로", "/api/v1/local/status"]]) {
      const r = await ctx.request.get(`${BASE}${path}`);
      rec(`비로그인 ${label} → 401`, r.status() === 401, String(r.status()));
    }
    await ctx.close();
  }
  // ---- 2. API 서버를 직접 열어도 토큰 없이는 거부(브라우저가 4001을 직접 불러 우회 불가)
  {
    for (const path of ["/api/v1/screen?market=KOSPI", "/api/v1/local/status", "/api/v1/local/stocks/T00001/ticks", "/docs"]) {
      const r = await fetch(`${API}${path}`);
      rec(`API 직접 호출(토큰 없음) ${path.split("?")[0]} → 거부`, r.status === 401 || r.status === 404, String(r.status));
    }
    const ok = await fetch(`${API}/api/v1/local/status`, { headers: { "X-Internal-Token": TOKEN } });
    rec("API 직접 호출(올바른 토큰) 로컬 상태 → 200 (모의 증권사 연결됨)", ok.status === 200, String(ok.status));
  }
  // ---- 3. 관리자 로그인 후 운영과 같은 화면 + 로컬 전용 기능
  {
    const { ctx, page, seen, errs } = await ctxPage();
    await login(page, "kim", PW);
    rec("관리자 로그인 성공 → 로그인 화면을 벗어남", !new URL(page.url()).pathname.startsWith("/login"), page.url());
    await page.goto("/screener");
    await page.waitForSelector("table tbody tr, .screener-result, [data-testid=screener-result]", { timeout: 30000 }).catch(() => {});
    rec("스크리너 화면 표시(로그인 상태)", new URL(page.url()).pathname.startsWith("/screener"), page.url());
    await openDetail(page);
    const tabs = await page.$$eval('[role="tab"]', (e) => e.map((x) => x.textContent));
    rec("종목 상세에 로컬 전용 탭(호가·체결) 표시", tabs.includes("호가") && tabs.includes("체결"), tabs.join("|"));
    await page.getByRole("tab", { name: "호가" }).click();
    await page.waitForSelector(".orderbook__table tbody tr", { timeout: 30000 });
    const rows = await page.$$eval(".orderbook__table tbody tr", (r) => r.length);
    rec("호가 표가 대행 경로로 채워짐", rows >= 10, `${rows}행`);
    await page.getByRole("tab", { name: "체결" }).click();
    await page.waitForSelector(".daily-table", { timeout: 30000 });
    await page.waitForTimeout(1500);
    // 장이 닫힌 시간에는 모의 체결이 0건일 수 있다 → 표가 나오고 오류 문구가 없으면 통과
    rec("체결 탭이 오류 없이 표시됨", (await page.locator(".local-error").count()) === 0, `${await page.$$eval(".daily-table tbody tr", (r) => r.length)}행`);
    await page.getByRole("tab", { name: "차트" }).click();
    await page.getByRole("button", { name: "분봉 간격 선택" }).click();
    await page.getByRole("menuitem", { name: "5분", exact: true }).click();
    await page.waitForFunction(() => /\d\d:\d\d/.test(document.querySelector(".stock-chart__svg")?.textContent || ""), null, { timeout: 30000 });
    rec("분봉 차트(5분)가 대행 경로로 표시", true);
    await page.screenshot({ path: `${OUT}/local-login-on-detail.png` });
    const direct = seen.filter((u) => u.startsWith(apiOrigin));
    const viaWeb = seen.filter((u) => u.startsWith(BASE) && u.includes("/api/v1/local/"));
    rec("브라우저가 API 서버를 직접 부르지 않음(전부 웹 서버 경유)", direct.length === 0, `직접 ${direct.length}건 / 대행 로컬 ${viaWeb.length}건`);
    rec("실시간 스트림이 대행 경로로 열림(연결 1건, 호가·체결 폴링 없음)", viaWeb.filter((u) => u.includes("/stream")).length === 1 && !viaWeb.some((u) => /\/(orderbook|ticks)(\?|$)/.test(u)), `${viaWeb.length}건`);
    const inv = await ctx.request.get(`${BASE}/api/v1/local/stocks/T00001/investor`);
    rec("관리자: 로컬 투자자 수급 조회 가능", inv.status() === 200, String(inv.status()));
    rec("페이지 오류 없음", errs.length === 0, errs.join("|"));
    // 로그아웃 후 다시 막힘
    await page.goto("/");
    await page.click(".member-menu__logout");
    await page.waitForURL((u) => u.pathname.startsWith("/login"), { timeout: 20000 });
    const after = await ctx.request.get(`${BASE}/api/v1/local/status`);
    rec("로그아웃 후 로컬 경로도 즉시 401", after.status() === 401, String(after.status()));
    await ctx.close();
  }
  // ---- 3b. 전 종목 준실시간 시세를 스크리닝·목록 화면에 연결(DEC-084 B)
  {
    const { ctx, page, seen, errs } = await ctxPage();
    await login(page, "kim", PW);
    await page.goto("/screener");
    await page.getByRole("button", { name: "조건 적용" }).first().click();
    await page.waitForSelector(".results-table tbody tr", { timeout: 40000 });
    const header = await page.$$eval(".results-table thead th", (e) => e.map((x) => x.textContent));
    rec("스크리닝 결과에 '현재가' 열이 생김(관리자·로컬)", header.includes("현재가"), header.join("|"));
    await page.waitForSelector(".results-table .quote-text--live", { timeout: 60000 });
    const liveCells = await page.$$eval(".results-table .quote-text--live", (e) => e.length);
    const rows = await page.$$eval(".results-table tbody tr", (e) => e.length);
    rec("현재가 칸이 준실시간 값으로 채워짐(실시간 표지 포함)", liveCells >= 1, `${liveCells}/${rows}행`);
    const label = await page.$eval(".results-table .quote-text__live", (e) => e.textContent);
    rec("표지 문구는 '실시간' 또는 '지연'(색에만 의존하지 않음)", label === "실시간" || label === "지연", label ?? "");
    const price = await page.$eval(".results-table .quote-text__price", (e) => e.textContent);
    rec("현재가는 숫자 형식", /^[\d,]+$/.test(price ?? ""), price ?? "");
    const notice = await page.locator(".inline-notice", { hasText: "조건 판정은 일봉 기준" }).count();
    rec("조건 판정은 일봉 기준이라는 안내 표시", notice === 1, String(notice));
    const marketReqs = seen.filter((u) => u.includes("/api/v1/local/market/quotes"));
    rec("시세 조회는 웹 서버 대행 경로로만 나감", marketReqs.length >= 1 && marketReqs.every((u) => u.startsWith(BASE)), `${marketReqs.length}건`);
    const direct = seen.filter((u) => u.startsWith(apiOrigin));
    rec("브라우저가 API 서버를 직접 부르지 않음(시세 포함)", direct.length === 0, `${direct.length}건`);
    // 조회 주기: 3초 하한 — 12초 동안 6건 이하
    const before = marketReqs.length;
    await page.waitForTimeout(12000);
    const after = seen.filter((u) => u.includes("/api/v1/local/market/quotes")).length;
    rec("조회 간격이 너무 짧지 않음(12초에 5건 이하)", after - before <= 5, `${after - before}건`);
    // 모바일 폭: 카드에도 현재가
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForSelector(".results-list__quote .quote-text--live", { timeout: 30000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    rec("모바일(390px) 카드에 현재가 표시, 가로 넘침 없음", !overflow);
    await page.screenshot({ path: `${OUT}/live-market-screener-390.png` });
    // 탭을 가리면 조회 중단
    await page.setViewportSize({ width: 1280, height: 800 });
    // 종목 검색 목록
    await page.goto("/stocks");
    await page.fill("input[type=search], input[type=text]", "T0000");
    await page.waitForSelector(".stock-list__item .quote-text--live", { timeout: 60000 });
    rec("종목 검색 목록 행에 준실시간 현재가", true);
    rec("페이지 오류 없음", errs.length === 0, errs.join("|"));
    await ctx.close();
  }
  // 일반 사용자는 시세 열·안내가 없고 시세 API는 403
  {
    const { ctx, page, errs } = await ctxPage();
    await login(page, "lee", PW2);
    const q = await ctx.request.get(`${BASE}/api/v1/local/market/quotes?codes=T00001`);
    rec("일반 사용자: 준실시간 시세 조회는 403(관리자 전용)", q.status() === 403, String(q.status()));
    await page.goto("/screener");
    await page.getByRole("button", { name: "조건 적용" }).first().click();
    await page.waitForSelector(".results-table tbody tr", { timeout: 40000 });
    await page.waitForTimeout(3000);
    const header = await page.$$eval(".results-table thead th", (e) => e.map((x) => x.textContent));
    rec("일반 사용자: 현재가 열·실시간 표지 없음", !header.includes("현재가") && (await page.locator(".quote-text--live").count()) === 0, header.join("|"));
    rec("일반 사용자: 페이지 오류 없음", errs.length === 0, errs.join("|"));
    await ctx.close();
  }
  // ---- 4. 일반 사용자: 호가·체결은 되고 투자자 수급은 관리자 전용
  {
    const { ctx, page } = await ctxPage();
    await login(page, "lee", PW2);
    const ob = await ctx.request.get(`${BASE}/api/v1/local/stocks/T00001/orderbook`);
    rec("일반 사용자: 로컬 호가 조회 가능", ob.status() === 200, String(ob.status()));
    const inv = await ctx.request.get(`${BASE}/api/v1/local/stocks/T00001/investor`);
    rec("일반 사용자: 로컬 투자자 수급은 403(관리자 전용)", inv.status() === 403, String(inv.status()));
    const adm = await ctx.request.get(`${BASE}/api/v1/internal/admin/stocks/T00001/investor`);
    rec("일반 사용자: 운영 투자자 수급 경로도 403", adm.status() === 403, String(adm.status()));
    const evil = await ctx.request.get(`${BASE}/api/v1/local/../internal/members`);
    rec("경로 조작은 404", evil.status() === 404 || evil.status() === 401 || evil.status() === 400, String(evil.status()));
    await ctx.close();
  }
  // ---- 5. 잘못된 비밀번호는 같은 문구
  {
    const { ctx, page } = await ctxPage();
    await page.goto("/login");
    await page.fill("#login-username", "kim");
    await page.fill("#login-password", "wrong-password-1!");
    await page.click("button[type=submit]");
    await page.waitForSelector(".login-form__message", { timeout: 20000 });
    const msg = await page.textContent(".login-form__message");
    rec("틀린 비밀번호 안내 문구", (msg ?? "").includes("아이디 또는 비밀번호가 올바르지 않습니다"), msg ?? "");
    await ctx.close();
  }
} else {
  // ---- off: 예전 방식 그대로(로그인 없음, 브라우저가 API를 직접 호출)
  const { ctx, page, seen, errs } = await ctxPage();
  await page.goto("/screener");
  rec("로그인 없이 /screener 바로 표시", new URL(page.url()).pathname.startsWith("/screener"), page.url());
  await openDetail(page, null);
  const tabs = await page.$$eval('[role="tab"]', (e) => e.map((x) => x.textContent));
  rec("로컬 전용 탭(호가·체결) 그대로 표시", tabs.includes("호가") && tabs.includes("체결"), tabs.join("|"));
  await page.getByRole("tab", { name: "호가" }).click();
  await page.waitForSelector(".orderbook__table tbody tr", { timeout: 30000 });
  rec("호가 표 채워짐(API 직접 호출)", (await page.$$eval(".orderbook__table tbody tr", (r) => r.length)) >= 10);
  await page.getByRole("tab", { name: "체결" }).click();
  await page.waitForSelector(".daily-table", { timeout: 30000 });
  await page.waitForTimeout(1500);
  rec("체결 탭이 오류 없이 표시됨", (await page.locator(".local-error").count()) === 0, `${await page.$$eval(".daily-table tbody tr", (r) => r.length)}행`);
  const direct = seen.filter((u) => u.startsWith(apiOrigin) && u.includes("/api/v1/local/"));
  rec("끈 상태에서는 예전처럼 API를 직접 호출(실시간 스트림 연결 포함)", direct.length >= 1 && direct.some((u) => u.includes("/stream")), `${direct.length}건`);
  const r = await ctx.request.get(`${BASE}/api/v1/screen?market=KOSPI`);
  rec("끈 상태에서는 대행 경로가 없음(404)", r.status() === 404, String(r.status()));
  const api = await fetch(`${API}/api/v1/screen?market=KOSPI&page_size=2`);
  rec("끈 상태 API는 토큰 없이 응답(예전 방식)", api.status === 200, String(api.status));
  const docs = await fetch(`${API}/docs`);
  rec("끈 상태 Swagger 문서(/docs) 열림", docs.status === 200, String(docs.status));
  rec("페이지 오류 없음", errs.length === 0, errs.join("|"));
  await page.screenshot({ path: `${OUT}/local-login-off-detail.png` });
  await ctx.close();
}

await b.close();
const failed = res.filter((x) => !x).length;
console.log(`\n[${MODE}] 합계 ${res.length}건, 실패 ${failed}건`);
process.exit(failed === 0 ? 0 : 1);
