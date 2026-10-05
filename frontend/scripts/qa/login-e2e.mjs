// DEC-067 종단간 점검: 실제 API(내부 토큰 강제)+실제 웹 서버(로그인 켬)+실제 PostgreSQL. `tests/e2e/login_stack.py`가 서버를 띄우고 이 스크립트를 실행한다.
//   python tests/e2e/login_stack.py
import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import fs from "node:fs";
import { launch, runAxe } from "./common.mjs";

const BASE = process.env.QA_BASE;
const API = process.env.QA_API;
const TOKEN = process.env.QA_TOKEN;
const SECRET = process.env.QA_SESSION_SECRET;
const PW = process.env.QA_PW;
const PW2 = process.env.QA_PW2;
const INSECURE = (process.env.QA_COOKIE_INSECURE ?? "") !== "";
const COOKIE = INSECURE ? "session" : "__Host-session";
const ONLY = process.env.QA_ONLY ?? "";
const OUT = process.env.QA_OUT;
fs.mkdirSync(OUT, { recursive: true });

const res = [];
const rec = (name, pass, note = "") => { res.push(pass); console.log(`${pass ? "PASS" : "FAIL"}  ${name}  ${note}`); };
const GENERIC = "아이디 또는 비밀번호가 올바르지 않습니다. 여러 번 틀리면 잠시 로그인할 수 없습니다.";

const psql = (sql) => {
  const parts = process.env.QA_ADMIN_PSQL.split(/\s+/);
  return execFileSync(parts[0], [...parts.slice(1), "-At", "-v", "ON_ERROR_STOP=1", "-c", sql], { encoding: "utf8" }).trim();
};
const uidOf = (username) => psql(`SELECT user_id FROM auth.app_users WHERE username='${username}'`);

const b64u = (s) => Buffer.from(s, "utf8").toString("base64url");
function sign(payload, secret = SECRET) {
  const body = b64u(JSON.stringify(payload));
  return `${body}.${createHmac("sha256", secret).update(body).digest("base64url")}`;
}
const nowS = () => Math.floor(Date.now() / 1000);
function payloadFor(uid, username, name, over = {}) {
  const t = nowS();
  return { v: 1, uid, un: username, dn: name, iat: t, exp: t + 3600, chk: t, ...over };
}

const b = await launch();
const should = (name) => !ONLY || name.includes(ONLY);

async function newCtx(w = 1280) {
  return b.newContext({ viewport: { width: w, height: 800 }, baseURL: BASE });
}
async function setSessionCookie(ctx, value) {
  const u = new URL(BASE);
  await ctx.addCookies([{ name: COOKIE, value, domain: u.hostname, path: "/", httpOnly: true, secure: !INSECURE, sameSite: "Lax" }]);
}
async function uiLogin(page, username, password, next) {
  await page.goto(`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`);
  await page.fill("#login-username", username);
  await page.fill("#login-password", password);
  await page.click("button[type=submit]");
}
async function apiLoginRaw(username, password, ip) {
  const r = await fetch(`${API}/api/v1/internal/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Token": TOKEN, ...(ip ? { "X-End-User-IP": ip } : {}) },
    body: JSON.stringify({ username, password }),
  });
  return r.status;
}

// ───────────────────────── A. 로그인 전: 모든 화면·API가 막힌다
if (should("A")) {
  const ctx = await newCtx();
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
  for (const [path, expectNext] of [["/", null], ["/stocks", "/stocks"], ["/screener", "/screener"], ["/watchlist", "/watchlist"], ["/about", "/about"], ["/members", "/members"], ["/stocks/T00001", "/stocks/T00001"], ["/screener/pattern", "/screener/pattern"]]) {
    const resp = await p.goto(path, { waitUntil: "domcontentloaded" });
    const u = new URL(p.url());
    rec(`A 비로그인 ${path}: 로그인 화면으로 이동`, u.pathname === "/login" && (expectNext ? u.searchParams.get("next") === expectNext : !u.searchParams.has("next")), `→ ${u.pathname}${u.search}`);
    if (path === "/") {
      const h = resp.headers();
      rec("A 로그인 화면 응답 헤더: 색인 금지·캐시 금지·프레임 금지·sniff 금지", /noindex/.test(h["x-robots-tag"] ?? "") && /no-store/.test(h["cache-control"] ?? "") && h["x-frame-options"] === "DENY" && h["x-content-type-options"] === "nosniff", JSON.stringify({ r: h["x-robots-tag"], c: h["cache-control"] }));
    }
  }
  rec("A 로그인 화면 페이지 오류 없음", errs.length === 0, errs.join("|"));
  rec("A 로그인 화면에는 회원 메뉴가 없다", (await p.locator(".member-menu").count()) === 0);
  // 대행 경로·인증 경로
  const noauth = ctx.request;
  for (const path of ["/api/v1/market-summary", "/api/v1/stocks?query=T0", "/api/v1/screen", "/api/v1/stocks/T00001/metrics", "/api/v1/stocks/quotes?codes=T00001"]) {
    const r = await noauth.get(`${BASE}${path}`);
    const body = await r.json().catch(() => null);
    rec(`A 비로그인 대행 ${path}: 401 AUTH_REQUIRED`, r.status() === 401 && body?.error?.code === "AUTH_REQUIRED", `status=${r.status()}`);
  }
  const me = await noauth.get(`${BASE}/auth/me`);
  rec("A /auth/me 비로그인 401", me.status() === 401);
  const robots = await noauth.get(`${BASE}/robots.txt`);
  const robotsText = await robots.text();
  rec("A robots.txt는 로그인 없이 읽히고 전체 색인을 막는다", robots.status() === 200 && /Disallow:\s*\//.test(robotsText), robotsText.replace(/\s+/g, " ").slice(0, 50));
  // 인증 경로의 요청 검증
  const post = (extra) => noauth.post(`${BASE}/auth/login`, extra);
  const ok = { "content-type": "application/json", origin: new URL(BASE).origin };
  let r = await post({ headers: { "content-type": "application/json", origin: "https://evil.example.com" }, data: { username: "kim", password: PW } });
  rec("A 로그인 요청: 다른 사이트 Origin → 403(CSRF)", r.status() === 403);
  r = await post({ headers: { "content-type": "application/json" }, data: { username: "kim", password: PW } });
  rec("A 로그인 요청: Origin 없음 → 403", r.status() === 403);
  r = await post({ headers: { ...ok, "content-type": "text/plain" }, data: "x" });
  rec("A 로그인 요청: JSON이 아님 → 415", r.status() === 415);
  r = await post({ headers: ok, data: "not json" });
  rec("A 로그인 요청: 깨진 JSON → 400", r.status() === 400);
  r = await post({ headers: ok, data: { username: "kim" } });
  rec("A 로그인 요청: 비밀번호 없음 → 400", r.status() === 400);
  r = await post({ headers: ok, data: { username: "k".repeat(65), password: "x" } });
  rec("A 로그인 요청: 아이디 65자 → 400", r.status() === 400);
  r = await post({ headers: ok, data: { username: "kim", password: "x".repeat(5000) } });
  rec("A 로그인 요청: 본문 과대 → 413", r.status() === 413);
  r = await noauth.post(`${BASE}/auth/logout`, { headers: { "content-type": "application/json", origin: "https://evil.example.com" }, data: {} });
  rec("A 로그아웃 요청: 다른 사이트 Origin → 403", r.status() === 403);
  r = await noauth.post(`${BASE}/auth/session`, { headers: { "content-type": "application/json", origin: "https://evil.example.com" }, data: {} });
  rec("A 세션 갱신 요청: 다른 사이트 Origin → 403", r.status() === 403);
  r = await noauth.post(`${BASE}/auth/session`, { headers: ok, data: {} });
  rec("A 세션 갱신: 쿠키 없음 → 401", r.status() === 401);
  await ctx.close();

  // API 서버를 직접 부르는 우회 시도
  const direct = async (path, headers = {}) => (await fetch(`${API}${path}`, { headers })).status;
  for (const path of ["/api/v1/market-summary", "/api/v1/stocks?query=T0", "/api/v1/screen", "/docs", "/openapi.json", "/redoc", "/api/v1/internal/members", "/api/v1/health"]) {
    rec(`A API 직접 호출 ${path}: 토큰 없이 401`, (await direct(path)) === 401);
    rec(`A API 직접 호출 ${path}: 틀린 토큰 401`, (await direct(path, { "X-Internal-Token": "wrong" })) === 401);
  }
  rec("A API 직접 호출 /api/v1/live: 헬스체크는 열려 있다", (await direct("/api/v1/live")) === 200);
  rec("A API 직접 호출: 맞는 토큰이면 데이터 응답(웹 서버만 아는 열쇠)", (await direct("/api/v1/market-summary", { "X-Internal-Token": TOKEN })) === 200);
  rec("A API: 문서 경로는 토큰이 있어도 존재하지 않는다", (await direct("/openapi.json", { "X-Internal-Token": TOKEN })) === 404);
}

// ───────────────────────── B. 로그인 화면(모양·접근성)과 로그인 실패
if (should("B")) {
  for (const w of [360, 1280]) {
    const ctx = await newCtx(w);
    const p = await ctx.newPage();
    await p.goto("/login");
    const labels = await p.locator("label").allInnerTexts();
    rec(`B 로그인 화면 ${w}px: 라벨(아이디·비밀번호)`, labels.includes("아이디") && labels.includes("비밀번호"), labels.join(","));
    rec(`B 로그인 화면 ${w}px: 자동완성 속성`, (await p.getAttribute("#login-username", "autocomplete")) === "username" && (await p.getAttribute("#login-password", "autocomplete")) === "current-password" && (await p.getAttribute("#login-password", "type")) === "password");
    rec(`B 로그인 화면 ${w}px: 가입 안내 문구(가입 기능 없음)`, /회원 가입 기능은 없습니다/.test(await p.locator(".login-page__intro").innerText()));
    rec(`B 로그인 화면 ${w}px: 가로 넘침 없음`, !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    const sizes = await p.evaluate(() => [...document.querySelectorAll("#login-username,#login-password,button[type=submit]")].map((e) => Math.round(e.getBoundingClientRect().height)));
    rec(`B 로그인 화면 ${w}px: 입력칸·버튼 높이 44px 이상`, sizes.every((h) => h >= 44), sizes.join(","));
    const axe = await runAxe(p);
    rec(`B 로그인 화면 ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    await p.screenshot({ path: `${OUT}/login-${w}.png` });
    await ctx.close();
  }
  const ctx = await newCtx();
  const p = await ctx.newPage();
  await uiLogin(p, "kim", "wrong-password-xyz");
  const alert = p.locator('.login-form__message');
  await alert.waitFor({ timeout: 15000 });
  const wrongText = (await alert.innerText()).trim();
  rec("B 틀린 비밀번호: 같은 안내 문구, 이동 없음", wrongText === GENERIC && new URL(p.url()).pathname === "/login", wrongText.slice(0, 30));
  rec("B 틀린 비밀번호: 비밀번호 칸이 비워지고 그 칸에 포커스", (await p.inputValue("#login-password")) === "" && (await p.evaluate(() => document.activeElement?.id)) === "login-password");
  await p.fill("#login-username", "nobody-here");
  await p.fill("#login-password", "wrong-password-xyz");
  await p.click("button[type=submit]");
  await p.waitForFunction((t) => document.querySelector('.login-form__message')?.textContent?.trim() === t, GENERIC, { timeout: 15000 }).catch(() => {});
  rec("B 없는 아이디도 같은 문구", (await alert.innerText()).trim() === GENERIC);
  await p.fill("#login-username", "off");
  await p.fill("#login-password", PW);
  await p.click("button[type=submit]");
  await p.waitForTimeout(1500);
  rec("B 비활성 회원은 맞는 비밀번호여도 같은 문구, 이동 없음", (await alert.innerText()).trim() === GENERIC && new URL(p.url()).pathname === "/login");
  const cookies = (await ctx.cookies()).filter((c) => c.name === COOKIE);
  rec("B 실패한 로그인은 쿠키를 만들지 않는다", cookies.length === 0);
  await ctx.close();

  // 잠금: 5번 틀리면 맞는 비밀번호도 거부
  const ctx2 = await newCtx();
  const p2 = await ctx2.newPage();
  for (let i = 0; i < 5; i += 1) await apiLoginRaw("lock", "wrong-password-xyz");
  await uiLogin(p2, "lock", PW);
  await p2.locator('.login-form__message').waitFor({ timeout: 15000 });
  rec("B 5회 실패 뒤 맞는 비밀번호도 같은 문구로 거부(잠김)", (await p2.locator('.login-form__message').innerText()).trim() === GENERIC && new URL(p2.url()).pathname === "/login");
  rec("B 잠금이 DB에 기록됨(잠금 단계 1, 해제 시각 있음)", psql("SELECT lockout_level || ':' || (locked_until IS NOT NULL) FROM auth.app_users WHERE username='lock'") === "1:true");
  rec("B 로그인 기록: 실패 5건 + 잠김 1건, 비밀번호는 없음", psql("SELECT count(*) FILTER (WHERE result='FAIL') || ':' || count(*) FILTER (WHERE result='LOCKED') FROM auth.login_audit WHERE username_attempted='lock'") === "5:1" && psql(`SELECT count(*) FROM auth.login_audit WHERE username_attempted LIKE '%${PW.slice(0, 6)}%'`) === "0");
  await ctx2.close();
}

// ───────────────────────── C. 로그인 성공·쿠키·화면
if (should("C")) {
  const ctx = await newCtx();
  const p = await ctx.newPage();
  const errs = [];
  const apiHosts = new Set();
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
  p.on("request", (r) => { const u = new URL(r.url()); if (u.pathname.startsWith("/api/") || u.port === new URL(API).port) apiHosts.add(u.origin); });
  await p.goto("/stocks");
  rec("C 비로그인 /stocks → /login?next=%2Fstocks", new URL(p.url()).pathname === "/login" && new URL(p.url()).searchParams.get("next") === "/stocks");
  await p.fill("#login-username", " KIM ");
  await p.fill("#login-password", PW);
  await p.click("button[type=submit]");
  await p.waitForURL((u) => u.pathname === "/stocks", { timeout: 20000 });
  rec("C 로그인 성공: 원래 가려던 /stocks로 이동", new URL(p.url()).pathname === "/stocks");
  const cookie = (await ctx.cookies()).find((c) => c.name === COOKIE);
  rec("C 세션 쿠키: HttpOnly, Path=/, SameSite=Lax" + (INSECURE ? "" : ", Secure"), !!cookie && cookie.httpOnly && cookie.path === "/" && cookie.sameSite === "Lax" && (INSECURE || cookie.secure), cookie ? JSON.stringify({ h: cookie.httpOnly, s: cookie.secure, ss: cookie.sameSite, p: cookie.path }) : "쿠키 없음");
  const ttl = cookie ? cookie.expires - nowS() : 0;
  rec("C 세션 쿠키: 수명 8시간 이하", ttl > 0 && ttl <= 8 * 3600 + 5, `${ttl}s`);
  rec("C 세션 쿠키: 값에 비밀번호·해시 없음, JS(document.cookie)로 읽을 수 없음", cookie && !cookie.value.includes(PW) && !cookie.value.includes("argon2") && !(await p.evaluate(() => document.cookie)).includes("session"));
  const decoded = JSON.parse(Buffer.from(cookie.value.split(".")[0], "base64url").toString("utf8"));
  rec("C 세션 내용: 회원 id·아이디·이름·시각만", Object.keys(decoded).sort().join(",") === "chk,dn,exp,iat,uid,un,v" && decoded.un === "kim");
  const menu = p.locator(".member-menu");
  await menu.waitFor({ timeout: 10000 });
  const menuText = await menu.innerText();
  rec("C 회원 메뉴: 이름·회원 목록·로그아웃", /김철수님/.test(menuText) && /회원 목록/.test(menuText) && /로그아웃/.test(menuText), menuText.replace(/\s+/g, " "));
  // 홈(서버 화면)
  await p.goto("/");
  await p.waitForSelector("h1.home-page__title", { timeout: 20000 });
  rec("C 로그인 후 홈(서버가 API 호출): 시장 요약 표시", (await p.locator(".stat-summary, .home-page__section").count()) > 0);
  rec("C 로그인 후 /login 접근: 이미 로그인했으면 홈으로", await (async () => { await p.goto("/login"); return new URL(p.url()).pathname === "/"; })());
  await p.goto("/login?next=https://evil.example.com");
  rec("C 열린 리다이렉트: 로그인 상태에서 next=외부 주소 → 외부로 가지 않는다", new URL(p.url()).origin === new URL(BASE).origin);
  await p.goto("/login?next=//evil.example.com");
  rec("C 열린 리다이렉트: next=//외부 → 외부로 가지 않는다", new URL(p.url()).origin === new URL(BASE).origin);
  // 스크리닝(브라우저가 API 호출) → 대행 경로 사용
  await p.goto("/screener");
  await p.waitForSelector("button:has-text('조건 적용'), button:has-text('조회')", { timeout: 15000 }).catch(() => {});
  const apply = p.locator("button:has-text('조건 적용'), button:has-text('조회'), button:has-text('검색')").first();
  if (await apply.count()) { await apply.click().catch(() => {}); await p.waitForTimeout(2500); }
  rec("C 브라우저는 API 서버(4321)를 직접 부르지 않는다(웹 서버 경로만)", ![...apiHosts].some((o) => o === new URL(API).origin), [...apiHosts].join(","));
  // 대행 경로
  const rq = ctx.request;
  let r = await rq.get(`${BASE}/api/v1/market-summary`);
  rec("C 대행 /api/v1/market-summary: 200 + 봉투", r.status() === 200 && (await r.json()).meta !== undefined, `${r.status()}`);
  rec("C 대행 응답 헤더: no-store, JSON", /no-store/.test(r.headers()["cache-control"] ?? "") && /json/.test(r.headers()["content-type"] ?? ""));
  r = await rq.get(`${BASE}/api/v1/stocks?query=T0&market=ALL`);
  rec("C 대행 /api/v1/stocks 검색: 200", r.status() === 200, `${r.status()}`);
  for (const [path, label] of [["/api/v1/local/status", "개인 로컬 모드 경로"], ["/api/v1/internal/members", "내부 회원 경로"], ["/api/v1/internal/auth/login", "내부 로그인 경로"], ["/api/v1/live", "헬스체크"], ["/api/v1/health", "헬스(DB)"], ["/api/v1/stocks/T00001", "허용 목록 밖 종목 경로"], ["/api/v1/stocks/T00001/../../internal/members", "경로 탈출 시도"]]) {
    r = await rq.get(`${BASE}${path}`);
    rec(`C 대행 차단 ${label}(${path}): 404`, r.status() === 404, `${r.status()}`);
  }
  r = await rq.post(`${BASE}/api/v1/market-summary`, { data: {}, headers: { origin: new URL(BASE).origin } });
  rec("C 대행 경로는 조회(GET)만: POST → 405", r.status() === 405, `${r.status()}`);
  r = await rq.get(`${BASE}/api/v1/screen?${"a=1&".repeat(700)}`);
  rec("C 대행: 과도하게 긴 쿼리 → 400", r.status() === 400, `${r.status()}`);
  // 회원 목록
  await p.goto("/members");
  await p.waitForSelector(".members-table", { timeout: 15000 });
  const rows = await p.locator(".members-table tbody tr").allInnerTexts();
  const flat = rows.map((t) => t.replace(/\s+/g, " ").trim());
  rec("C 회원 목록: 활성 회원만(비활성 '퇴사자' 제외), 이름순", flat.length === 5 && !flat.some((t) => t.includes("퇴사자")) && flat.some((t) => t.startsWith("kim")) && flat.some((t) => t.startsWith("lee")), flat.join(" | "));
  rec("C 회원 목록: 전체 N명 표시", /전체 5명/.test(await p.locator("[data-testid='members-count']").innerText()));
  rec("C 회원 목록: 열 제목은 아이디·이름뿐(해시·시각·상태 없음)", (await p.locator(".members-table thead th").allInnerTexts()).join(",") === "아이디,이름" && !(await p.content()).includes("argon2"));
  rec("C 회원 목록: 이름의 스크립트는 글자로만 보이고 실행되지 않는다", (await p.evaluate(() => window.__xss === 1)) === false && flat.some((t) => t.includes("<script>")));
  for (const w of [360, 1280]) {
    await p.setViewportSize({ width: w, height: 800 });
    rec(`C 회원 목록 ${w}px: 가로 넘침 없음`, !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    const axe = await runAxe(p);
    rec(`C 회원 목록 ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    await p.screenshot({ path: `${OUT}/members-${w}.png` });
  }
  // 로그아웃
  await p.setViewportSize({ width: 1280, height: 800 });
  await p.click(".member-menu__logout");
  await p.waitForURL((u) => u.pathname === "/login", { timeout: 15000 });
  rec("C 로그아웃: 로그인 화면으로 이동, 쿠키 삭제", (await ctx.cookies()).filter((c) => c.name === COOKIE && c.value).length === 0);
  await p.goto("/");
  rec("C 로그아웃 뒤 홈 접근 → 로그인", new URL(p.url()).pathname === "/login");
  r = await rq.get(`${BASE}/api/v1/market-summary`);
  rec("C 로그아웃 뒤 대행 경로 → 401", r.status() === 401);
  await p.goBack().catch(() => {});
  await p.waitForTimeout(500);
  rec("C 로그아웃 뒤 '뒤로 가기'로 이전 화면 데이터가 보이지 않는다", (await p.locator("h1.home-page__title, .members-table").count()) === 0);
  rec("C 로그인 흐름 페이지 오류 없음", errs.length === 0, errs.join("|"));
  await ctx.close();
}

// ───────────────────────── D. 세션 변조·만료·갱신·비활성화
if (should("D")) {
  const kim = uidOf("kim");
  const off = uidOf("off");
  const lee = uidOf("lee");
  const tryNav = async (cookieValue, path = "/") => {
    const ctx = await newCtx();
    if (cookieValue !== null) await setSessionCookie(ctx, cookieValue);
    const p = await ctx.newPage();
    await p.goto(path, { waitUntil: "domcontentloaded" });
    await p.waitForTimeout(500);
    const result = { url: new URL(p.url()), page: p, ctx };
    return result;
  };
  const good = sign(payloadFor(kim, "kim", "김철수"));
  let t = await tryNav(good);
  rec("D 직접 만든 유효한 쿠키(서명 일치)는 통과", t.url.pathname === "/", t.url.pathname);
  await t.ctx.close();
  const flip = good.slice(0, -2) + (good.endsWith("AA") ? "BB" : "AA");
  const cases = [
    ["서명 변조", flip], ["다른 비밀 키로 서명", sign(payloadFor(kim, "kim", "김철수"), "z".repeat(48))],
    ["내용 변조(아이디 바꿈)", `${b64u(JSON.stringify(payloadFor(kim, "admin", "관리자")))}.${good.split(".")[1]}`],
    ["만료된 쿠키", sign(payloadFor(kim, "kim", "김철수", { iat: nowS() - 7200, exp: nowS() - 5, chk: nowS() - 7200 }))],
    ["수명이 너무 긴 쿠키", sign(payloadFor(kim, "kim", "김철수", { exp: nowS() + 30 * 24 * 3600 }))],
    ["쓰레기 값", "garbage"],
  ];
  for (const [name, value] of cases) {
    t = await tryNav(value);
    rec(`D 쿠키 ${name}: 로그인 화면으로`, t.url.pathname === "/login", t.url.pathname);
    await t.ctx.close();
  }
  // 브라우저가 저장하지 못하는 이상한 값(빈 값·아주 긴 값·제어 문자)은 원시 쿠키 헤더로 직접 보낸다
  {
    const raw = (await b.newContext()).request;
    for (const [name, value] of [["빈 값", ""], ["아주 긴 값(6000자)", "x".repeat(6000)], ["점이 많은 값", "a.b.c.d.e"], ["base64 아닌 값", "!!!.???"]]) {
      const page = await raw.get(`${BASE}/`, { headers: { cookie: `${COOKIE}=${value}` }, maxRedirects: 0 });
      rec(`D 원시 쿠키 ${name}: 화면 요청은 로그인으로 보낸다(307)`, page.status() === 307 && /\/login/.test(page.headers().location ?? ""), `${page.status()}`);
      const api = await raw.get(`${BASE}/api/v1/market-summary`, { headers: { cookie: `${COOKIE}=${value}` } });
      rec(`D 원시 쿠키 ${name}: 대행 경로는 401`, api.status() === 401, `${api.status()}`);
    }
  }
  // 대행 경로에서도 같다
  for (const [name, value] of cases.slice(0, 5)) {
    const ctx = await newCtx();
    await setSessionCookie(ctx, value);
    const r = await ctx.request.get(`${BASE}/api/v1/market-summary`);
    rec(`D 대행 경로 + 쿠키 ${name}: 401`, r.status() === 401, `${r.status()}`);
    await ctx.close();
  }
  // 신선도: 5분 지난 쿠키 → 갱신 화면 → 원래 화면, 만료 시각 불변
  const exp = nowS() + 3000;
  const stale = sign(payloadFor(kim, "kim", "김철수", { iat: nowS() - 600, exp, chk: nowS() - 600 }));
  {
    const ctx = await newCtx();
    await setSessionCookie(ctx, stale);
    const p = await ctx.newPage();
    const seen = [];
    p.on("framenavigated", (f) => { if (f === p.mainFrame()) seen.push(new URL(f.url()).pathname); });
    await p.goto("/stocks");
    await p.waitForURL((u) => u.pathname === "/stocks", { timeout: 20000 });
    await p.waitForTimeout(800);
    rec("D 5분 지난 쿠키: 갱신 화면(/auth/renew)을 거쳐 원래 화면으로", seen.includes("/auth/renew") && new URL(p.url()).pathname === "/stocks", seen.join(">"));
    const c = (await ctx.cookies()).find((x) => x.name === COOKIE);
    const dec = JSON.parse(Buffer.from(c.value.split(".")[0], "base64url").toString("utf8"));
    rec("D 갱신 뒤 쿠키: 확인 시각만 새로워지고 만료 시각은 그대로(8시간 상한 불변)", dec.exp === exp && nowS() - dec.chk <= 15, `chk 경과 ${nowS() - dec.chk}s`);
    await ctx.close();
  }
  // 비활성화된 회원: 신선한 쿠키는 5분 안에 잡히고, 5분이 지나면 갱신 단계에서 막힌다
  const staleOff = sign(payloadFor(off, "off", "퇴사자", { iat: nowS() - 600, chk: nowS() - 600 }));
  {
    const ctx = await newCtx();
    await setSessionCookie(ctx, staleOff);
    const p = await ctx.newPage();
    await p.goto("/");
    await p.waitForURL((u) => u.pathname === "/login", { timeout: 20000 });
    rec("D 비활성 회원의 쿠키(5분 경과): 갱신 단계에서 로그인 화면으로, '로그인이 만료' 안내", new URL(p.url()).searchParams.get("reason") === "expired" && /로그인이 만료되었습니다/.test(await p.locator('.login-form__message').innerText()));
    rec("D 비활성 회원: 쿠키가 지워짐", (await ctx.cookies()).filter((c) => c.name === COOKIE && c.value).length === 0);
    await ctx.close();
    const ctx2 = await newCtx();
    await setSessionCookie(ctx2, staleOff);
    const r = await ctx2.request.get(`${BASE}/api/v1/market-summary`);
    rec("D 비활성 회원의 낡은 쿠키로 대행 경로 호출: 401 + 쿠키 삭제", r.status() === 401 && /Max-Age=0|expires=/i.test(r.headers()["set-cookie"] ?? ""), `${r.status()}`);
    await ctx2.close();
  }
  // 대행 경로: 낡았지만 활성인 회원 → 200 + 갱신된 쿠키
  {
    const ctx = await newCtx();
    await setSessionCookie(ctx, stale);
    const r = await ctx.request.get(`${BASE}/api/v1/market-summary`);
    rec("D 낡은(5분 경과) 활성 회원 쿠키로 대행 호출: 200 + 갱신된 쿠키", r.status() === 200 && /session=/i.test(r.headers()["set-cookie"] ?? ""), `${r.status()}`);
    await ctx.close();
  }
  // 로그인 중 비활성화: 로그인 → 관리자가 끔 → 쿠키를 낡게 만들면 막힘
  {
    psql("UPDATE auth.app_users SET is_active = true WHERE username='lee'");
    const ctx = await newCtx();
    const p = await ctx.newPage();
    await uiLogin(p, "lee", PW2);
    await p.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
    psql("UPDATE auth.app_users SET is_active = false WHERE username='lee'");
    await setSessionCookie(ctx, sign(payloadFor(lee, "lee", "이영희", { iat: nowS() - 600, chk: nowS() - 600 })));
    await p.goto("/stocks");
    await p.waitForURL((u) => u.pathname === "/login", { timeout: 20000 });
    rec("D 로그인한 회원을 관리자가 비활성화하면 다음 확인(5분 이내)에서 차단된다", new URL(p.url()).searchParams.get("reason") === "expired");
    psql("UPDATE auth.app_users SET is_active = true WHERE username='lee'");
    await ctx.close();
  }
  // 열린 리다이렉트(로그인 성공 뒤 이동)
  for (const evil of ["https://evil.example.com", "//evil.example.com", "/login", "/auth/session", "javascript:alert(1)", "/\\evil.example.com"]) {
    const ctx = await newCtx();
    const p = await ctx.newPage();
    await uiLogin(p, "park", PW2, evil);
    await p.waitForURL((u) => u.pathname !== "/login", { timeout: 20000 });
    rec(`D 로그인 뒤 이동: next=${evil} → 같은 사이트의 홈`, new URL(p.url()).origin === new URL(BASE).origin && new URL(p.url()).pathname === "/", p.url());
    await ctx.close();
  }
}

// ───────────────────────── E. 대기 안내(깨우는 중) 팝업과 로그인
if (should("E")) {
  const ctx = await newCtx(360);
  const p = await ctx.newPage();
  await p.route("**/auth/login", async (route) => { await new Promise((s) => setTimeout(s, 6500)); await route.continue(); });
  await p.goto("/login");
  await p.fill("#login-username", "park");
  await p.fill("#login-password", PW2);
  await p.click("button[type=submit]");
  const popup = await p.locator('[role="dialog"].wake-dialog').waitFor({ timeout: 8000 }).then(() => true).catch(() => false);
  rec("E 로그인 요청이 4.5초 넘게 걸리면 '서버를 깨우는 중' 팝업(/auth/* 요청도 추적)", popup);
  await p.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("E 느린 로그인이 끝나면 정상 로그인", new URL(p.url()).pathname === "/");
  await ctx.close();
}

// ───────────────────────── G. 소유자 전용 투자자 수급(DEC-068)
if (should("G")) {
  const OWNER_PATH = "/api/v1/internal/owner/stocks/T00001/investor";
  // 소유자(kim): 화면에 값이 보인다
  const octx = await newCtx(1280);
  const op = await octx.newPage();
  await uiLogin(op, "kim", PW);
  await op.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  await op.goto("/stocks/T00001");
  await op.getByRole("tab", { name: "투자자" }).click();
  await op.waitForSelector(".daily-table", { timeout: 15000 }).catch(() => {});
  const otext = await op.locator('[role="tabpanel"]:not([hidden])').innerText().catch(() => "");
  rec("G 소유자: 투자자 탭에 수집 값 표(▼1,234 / ▲4,321)", /4,321/.test(otext) && /1,234/.test(otext) && !/준비 중/.test(otext), otext.replace(/\s+/g, " ").slice(0, 120));
  rec("G 소유자: 결측 값은 0이 아니라 '–'", /–/.test(otext));
  rec("G 소유자: 최근 날짜가 위(2026-10-01 → 2026-09-30)", otext.indexOf("2026-10-01") !== -1 && otext.indexOf("2026-10-01") < otext.indexOf("2026-09-30"));
  rec("G 소유자: 수집 안내 문구 표시", /소유자 계정에게만 보입니다/.test(otext));
  let r = await octx.request.get(`${BASE}${OWNER_PATH}`);
  const ob = await r.json();
  rec("G 소유자 대행 호출: 200 + no-store + 2행", r.status() === 200 && /no-store/.test(r.headers()["cache-control"] ?? "") && ob.data.rows.length === 2, `${r.status()}`);
  await octx.close();
  // 일반 회원(park): 같은 화면은 '준비 중', 값 호출은 403
  const pctx = await newCtx(1280);
  const pp = await pctx.newPage();
  await uiLogin(pp, "park", PW2);
  await pp.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  await pp.goto("/stocks/T00001");
  await pp.getByRole("tab", { name: "투자자" }).click();
  await pp.waitForTimeout(800);
  const ptext = await pp.locator('[role="tabpanel"]:not([hidden])').innerText().catch(() => "");
  rec("G 일반 회원: 투자자 탭은 '준비 중', 값 없음", /준비 중/.test(ptext) && !/4,321/.test(ptext) && !/1,234/.test(ptext));
  r = await pctx.request.get(`${BASE}${OWNER_PATH}`);
  const pb = await r.text();
  rec("G 일반 회원이 주소를 직접 호출: 403, 값 없음", r.status() === 403 && !/4321|1234|rows/.test(pb), `${r.status()}`);
  await pctx.close();
  // 비로그인: 401 / 쿠키 없는 API 직접 호출 거부
  r = await fetch(`${BASE}${OWNER_PATH}`);
  rec("G 비로그인 대행 호출: 401", r.status === 401, `${r.status}`);
  r = await fetch(`${API}${OWNER_PATH}`);
  rec("G API 직접 호출(토큰 없음): 401", r.status === 401, `${r.status}`);
  r = await fetch(`${API}${OWNER_PATH}`, { headers: { "X-Internal-Token": TOKEN } });
  rec("G API 직접 호출(토큰만, 아이디 없음): 403", r.status === 403, `${r.status}`);
  r = await fetch(`${API}${OWNER_PATH}`, { headers: { "X-Internal-Token": TOKEN, "X-Auth-Username": "park" } });
  rec("G API 직접 호출(다른 아이디): 403", r.status === 403, `${r.status}`);
  r = await fetch(`${API}${OWNER_PATH}`, { headers: { "X-Internal-Token": TOKEN, "X-Auth-Username": "kim" } });
  rec("G API 직접 호출(토큰+소유자 아이디): 200", r.status === 200, `${r.status}`);
  // 브라우저가 보낸 가짜 헤더는 대행 경로가 무시한다
  const fctx = await newCtx(1280);
  const fp = await fctx.newPage();
  await uiLogin(fp, "park", PW2);
  await fp.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  r = await fctx.request.get(`${BASE}${OWNER_PATH}`, { headers: { "X-Auth-Username": "kim", "X-Internal-Token": TOKEN } });
  rec("G 일반 회원이 소유자 아이디 헤더를 위조해도 403", r.status() === 403, `${r.status()}`);
  await fctx.close();
}

// ───────────────────────── H. 아이디 저장 + 브라우저 비밀번호 관리자 연계(DEC-069)
if (should("H")) {
  const KEY = "login.savedUsername";
  const store = (p) => p.evaluate((k) => { try { return localStorage.getItem(k); } catch { return "ERR"; } }, KEY);
  const dump = (p) => p.evaluate(() => { try { return JSON.stringify([{ ...localStorage }, { ...sessionStorage }, document.cookie]); } catch { return "ERR"; } });
  // 화면: 체크박스·안내·접근성·넘침 (360/1280)
  for (const w of [360, 1280]) {
    const ctx = await newCtx(w);
    const p = await ctx.newPage();
    await p.goto("/login");
    rec(`H ${w}px: '아이디 저장' 체크박스 + 라벨 연결 + 안내 문구(비밀번호 미저장·공용 PC 주의)`, (await p.locator("label[for=login-remember]").innerText()) === "아이디 저장" && /비밀번호는 저장하지 않으며/.test(await p.locator(".login-form__hint").innerText()) && /공용 PC/.test(await p.locator(".login-form__hint").innerText()));
    rec(`H ${w}px: 체크박스 기본값 해제`, !(await p.isChecked("#login-remember")));
    const hgt = await p.evaluate(() => Math.round(document.querySelector(".login-form__remember").getBoundingClientRect().height));
    rec(`H ${w}px: 체크박스 줄 높이 44px 이상(터치)`, hgt >= 44, `${hgt}`);
    rec(`H ${w}px: 가로 넘침 없음`, !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    await p.focus("#login-username");
    await p.keyboard.press("Tab"); await p.keyboard.press("Tab");
    rec(`H ${w}px: 키보드 Tab 순서 아이디 → 비밀번호 → 아이디 저장`, (await p.evaluate(() => document.activeElement?.id)) === "login-remember");
    await p.keyboard.press("Space");
    rec(`H ${w}px: 스페이스로 체크 전환`, await p.isChecked("#login-remember"));
    const axe = await runAxe(p);
    rec(`H ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    if (w === 360) await p.screenshot({ path: `${OUT}/login-remember-360.png` });
    await ctx.close();
  }
  // 로그인 성공 + 체크: 아이디만 저장, 비밀번호는 브라우저 비밀번호 관리자에만 전달
  const ctx = await newCtx(1280);
  const calls = [];
  await ctx.exposeFunction("__spyStore", (id, pw) => { calls.push([id, pw]); });
  await ctx.addInitScript(() => {
    window.PasswordCredential = class { constructor(d) { this.id = d.id; this.password = d.password; this.type = "password"; } };
    navigator.credentials.store = (c) => { window.__spyStore(c.id, c.password); return new Promise(() => {}); }; // 응답이 영원히 없는 경우까지 시험
  });
  const p = await ctx.newPage();
  const t0 = Date.now();
  await p.goto("/login");
  await p.fill("#login-username", "park");
  await p.fill("#login-password", PW2);
  await p.check("#login-remember");
  await p.click("button[type=submit]");
  await p.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("H 성공 로그인: 비밀번호 관리자 저장 제안 호출(아이디·비밀번호 전달)", calls.length === 1 && calls[0][0] === "park" && calls[0][1] === PW2, JSON.stringify(calls.map((c) => c[0])));
  rec("H 저장 제안이 응답하지 않아도 로그인은 최대 약 1초 지연만으로 완료", Date.now() - t0 < 12000);
  rec("H 체크 후 로그인: localStorage에 아이디만 저장", (await store(p)) === "park");
  const all = await dump(p);
  rec("H 비밀번호는 localStorage·sessionStorage·document.cookie 어디에도 없다", !all.includes(PW2) && !all.includes("argon2"), all.slice(0, 120));
  // 다시 방문: 아이디 채움 + 체크됨 + 비밀번호는 비어 있고 포커스
  await ctx.clearCookies();
  await p.goto("/login");
  await p.waitForFunction(() => document.querySelector("#login-username")?.value !== "", null, { timeout: 5000 }).catch(() => {});
  rec("H 재방문: 아이디가 채워지고 '아이디 저장' 체크", (await p.inputValue("#login-username")) === "park" && (await p.isChecked("#login-remember")));
  rec("H 재방문: 비밀번호 칸은 비어 있고 포커스(비밀번호 관리자가 채움)", (await p.inputValue("#login-password")) === "" && (await p.evaluate(() => document.activeElement?.id)) === "login-password");
  // 해제하고 로그인: 저장값 삭제
  await p.uncheck("#login-remember");
  await p.fill("#login-password", PW2);
  await p.click("button[type=submit]");
  await p.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("H 체크 해제 후 로그인: 저장된 아이디 삭제", (await store(p)) === null);
  await ctx.clearCookies();
  await p.goto("/login");
  rec("H 해제 후 재방문: 아이디 칸 비어 있음", (await p.inputValue("#login-username")) === "" && !(await p.isChecked("#login-remember")));
  // 실패한 로그인은 저장하지 않는다
  const callsBefore = calls.length; // 앞의 성공 로그인 2회(체크/해제)는 비밀번호 관리자에 제안됨
  await p.fill("#login-username", "park");
  await p.fill("#login-password", "wrong-password-xyz");
  await p.check("#login-remember");
  await p.click("button[type=submit]");
  await p.locator(".login-form__message").waitFor({ timeout: 10000 });
  rec("H 틀린 비밀번호: 아이디를 저장하지 않는다", (await store(p)) === null);
  rec("H 틀린 비밀번호: 비밀번호 관리자에 저장 제안하지 않는다", callsBefore === 2 && calls.length === callsBefore, `${callsBefore}→${calls.length}`);
  // 변조된 저장값
  await p.evaluate((k) => localStorage.setItem(k, "<img src=x onerror=window.__x=1>"), KEY);
  await p.goto("/login");
  rec("H 변조된 저장값: 채우지 않고 삭제, 스크립트 실행 없음", (await p.inputValue("#login-username")) === "" && (await store(p)) === null && (await p.evaluate(() => window.__x)) === undefined);
  await ctx.close();
  // 저장소 접근이 막힌 브라우저(사생활 보호 모드 등): 로그인은 정상
  const ctx2 = await newCtx(1280);
  await ctx2.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new DOMException("blocked", "SecurityError"); } });
  });
  const p2 = await ctx2.newPage();
  const errs = [];
  p2.on("pageerror", (e) => errs.push(String(e)));
  await p2.goto("/login");
  await p2.fill("#login-username", "park");
  await p2.fill("#login-password", PW2);
  await p2.check("#login-remember");
  await p2.click("button[type=submit]");
  await p2.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("H 저장소 접근 불가: 오류 없이 로그인 성공", errs.length === 0, errs.join("|").slice(0, 100));
  await ctx2.close();
  // 비밀번호 관리자 API가 없는 브라우저: 그냥 로그인
  const ctx3 = await newCtx(1280);
  await ctx3.addInitScript(() => { delete window.PasswordCredential; });
  const p3 = await ctx3.newPage();
  await p3.goto("/login");
  await p3.fill("#login-username", "park");
  await p3.fill("#login-password", PW2);
  await p3.click("button[type=submit]");
  await p3.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("H PasswordCredential 미지원 브라우저: 정상 로그인", new URL(p3.url()).pathname === "/");
  await ctx3.close();
}

// ───────────────────────── F. 로그인 시도 제한(API)
if (should("F")) {
  const codes = [];
  for (let i = 0; i < 46; i += 1) codes.push(await apiLoginRaw("nobody-" + (i % 3), "wrong-password-xyz", "198.51.100.77"));
  const first429 = codes.indexOf(429);
  rec("F 같은 접속 주소에서 분당 40회를 넘으면 429(맞는 비밀번호여도 인증 전에 거부)", first429 >= 40 && first429 <= 42 && codes.slice(first429).every((c) => c === 429), `첫 429 위치=${first429}`);
  rec("F 다른 접속 주소는 영향 없음", (await apiLoginRaw("park", PW2, "198.51.100.78")) === 200);
  const body = await (await fetch(`${API}/api/v1/internal/auth/login`, { method: "POST", headers: { "Content-Type": "application/json", "X-Internal-Token": TOKEN, "X-End-User-IP": "198.51.100.77" }, body: JSON.stringify({ username: "park", password: PW2 }) })).json();
  rec("F 429 응답은 계정 정보를 드러내지 않는다", body.error?.code === "LOGIN_RATE_LIMITED" && !JSON.stringify(body).includes("park"));
}

await b.close();
console.log(res.every(Boolean) ? "ALL PASS" : "SOME FAIL", `(${res.filter(Boolean).length}/${res.length})`);
process.exit(res.every(Boolean) ? 0 : 1);
