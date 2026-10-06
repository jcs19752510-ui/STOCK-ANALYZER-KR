// DEC-067 종단간 점검: 실제 API(내부 토큰 강제)+실제 웹 서버(로그인 켬)+실제 PostgreSQL. `tests/e2e/login_stack.py`가 서버를 띄우고 이 스크립트를 실행한다.
//   python tests/e2e/login_stack.py
import { execFileSync } from "node:child_process";
import { createHmac, randomUUID } from "node:crypto";
import fs from "node:fs";
import { launch, runAxe } from "./common.mjs";

const BASE = process.env.QA_BASE;
const API = process.env.QA_API;
const BAD_BASE = process.env.QA_BAD_BASE;
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
  return { v: 3, uid, sid: randomUUID(), rm: 0, rl: "u", un: username, dn: name, iat: t, exp: t + 3600, chk: t, ...over };
}
// 서버 쪽 세션 행을 직접 만든다(5분 확인을 통과하는 진짜 세션이 필요한 시험용). 세션 id를 돌려준다.
const realSid = (username, remember = false) =>
  psql(`INSERT INTO auth.user_sessions (user_id, remember, expires_at) SELECT user_id, ${remember}, now() + interval '${remember ? "30 days" : "8 hours"}' FROM auth.app_users WHERE username='${username}' RETURNING session_id`).split("\n")[0].trim();

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
  for (const [path, expectNext] of [["/", null], ["/stocks", "/stocks"], ["/screener", "/screener"], ["/watchlist", "/watchlist"], ["/about", "/about"], ["/members", "/members"], ["/admin/members", "/admin/members"], ["/stocks/T00001", "/stocks/T00001"], ["/screener/pattern", "/screener/pattern"]]) {
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
  const hz = await noauth.get(`${BASE}/healthz`, { maxRedirects: 0 });
  rec("A /healthz: 로그인 없이 200 'ok' (Render 상태 검사용, 리다이렉트 없음)", hz.status() === 200 && (await hz.text()) === "ok" && /no-store/.test(hz.headers()["cache-control"] ?? ""), `${hz.status()}`);
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
  for (const path of ["/api/v1/market-summary", "/api/v1/stocks?query=T0", "/api/v1/screen", "/docs", "/openapi.json", "/redoc", "/api/v1/internal/admin/members", "/api/v1/internal/auth/signup", "/api/v1/health"]) {
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
    rec(`B 로그인 화면 ${w}px: 안내 문구(가입 후 관리자 승인)`, /관리자의 승인을 받은 회원/.test(await p.locator(".login-page__intro").innerText()));
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
  rec("B 사용 중지 회원은 맞는 비밀번호일 때만 '사용 중지' 안내(DEC-074), 이동 없음", /사용이 중지된 계정/.test(await alert.innerText()) && new URL(p.url()).pathname === "/login");
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
  rec("C 세션 내용: 회원 id·아이디·이름·시각만", Object.keys(decoded).sort().join(",") === "chk,dn,exp,iat,rl,rm,sid,uid,un,v" && decoded.un === "kim" && decoded.rl === "a" && decoded.rm === 0 && /^[0-9a-f-]{36}$/.test(decoded.sid));
  const menu = p.locator(".member-menu");
  await menu.waitFor({ timeout: 10000 });
  const menuText = await menu.innerText();
  rec("C 회원 메뉴(관리자): 이름·회원 관리·로그아웃", /김철수님/.test(menuText) && /회원 관리/.test(menuText) && /로그아웃/.test(menuText), menuText.replace(/\s+/g, " "));
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
  // 운영 빌드(로컬 모드 꺼짐)에는 준실시간 시세 열·조회가 없어야 한다(DEC-084 B)
  {
    const heads = await p.$$eval(".results-table thead th", (e) => e.map((x) => x.textContent)).catch(() => []);
    const resources = await p.evaluate(() => performance.getEntriesByType("resource").map((e) => e.name));
    rec("C 운영 빌드: 스크리닝 결과에 '현재가' 열·실시간 표지 없음", !heads.includes("현재가") && (await p.locator(".quote-text--live").count()) === 0, heads.join("|"));
    rec("C 운영 빌드: 준실시간 시세 조회(/local/market) 요청 0건", resources.filter((u) => u.includes("/local/market")).length === 0);
  }
  // 운영 빌드: 스크리닝 전환에 '증권사 조건검색'이 없고 /psearch 요청도 없어야 한다(DEC-088)
  {
    await p.goto("/screener/pattern");
    await p.waitForSelector("nav.screening-mode-nav", { timeout: 15000 }).catch(() => {});
    await p.waitForTimeout(1500);
    const links = await p.$$eval("nav.screening-mode-nav a", (as) => as.map((x) => x.textContent)).catch(() => []);
    const res2 = await p.evaluate(() => performance.getEntriesByType("resource").map((e) => e.name));
    rec("C 운영 빌드: 스크리닝 전환에 '증권사 조건검색' 없음(기존 2개)", links.length === 2 && !links.includes("증권사 조건검색"), links.join("|"));
    rec("C 운영 빌드: /local/psearch 요청 0건", res2.filter((u) => u.includes("/psearch")).length === 0);
  }
  rec("C 브라우저는 API 서버(4321)를 직접 부르지 않는다(웹 서버 경로만)", ![...apiHosts].some((o) => o === new URL(API).origin), [...apiHosts].join(","));
  // 대행 경로
  const rq = ctx.request;
  let r = await rq.get(`${BASE}/api/v1/market-summary`);
  rec("C 대행 /api/v1/market-summary: 200 + 봉투", r.status() === 200 && (await r.json()).meta !== undefined, `${r.status()}`);
  rec("C 대행 응답 헤더: no-store, JSON", /no-store/.test(r.headers()["cache-control"] ?? "") && /json/.test(r.headers()["content-type"] ?? ""));
  r = await rq.get(`${BASE}/api/v1/stocks?query=T0&market=ALL`);
  rec("C 대행 /api/v1/stocks 검색: 200", r.status() === 200, `${r.status()}`);
  for (const [path, label] of [["/api/v1/local/status", "개인 로컬 모드 경로"], ["/api/v1/internal/admin/members", "내부 관리자 경로"], ["/api/v1/internal/admin/action", "내부 관리자 작업 경로"], ["/api/v1/internal/auth/login", "내부 로그인 경로"], ["/api/v1/live", "헬스체크"], ["/api/v1/health", "헬스(DB)"], ["/api/v1/stocks/T00001", "허용 목록 밖 종목 경로"], ["/api/v1/stocks/T00001/../../internal/members", "경로 탈출 시도"]]) {
    r = await rq.get(`${BASE}${path}`);
    rec(`C 대행 차단 ${label}(${path}): 404`, r.status() === 404, `${r.status()}`);
  }
  r = await rq.post(`${BASE}/api/v1/market-summary`, { data: {}, headers: { origin: new URL(BASE).origin } });
  rec("C 대행 경로는 조회(GET)만: POST → 405", r.status() === 405, `${r.status()}`);
  r = await rq.get(`${BASE}/api/v1/screen?${"a=1&".repeat(700)}`);
  rec("C 대행: 과도하게 긴 쿼리 → 400", r.status() === 400, `${r.status()}`);
  // 관리자 회원 관리 화면(옛 /members는 여기로 합쳐짐)
  await p.goto("/members");
  await p.waitForURL((u) => u.pathname === "/admin/members", { timeout: 15000 });
  rec("C 옛 /members 주소는 관리자 회원 관리로 이동", new URL(p.url()).pathname === "/admin/members");
  await p.waitForSelector(".admin-members", { timeout: 15000 });
  await p.getByRole("button", { name: /^전체/ }).click();
  await p.waitForSelector(".members-table", { timeout: 15000 });
  const rows = await p.locator(".members-table tbody tr").allInnerTexts();
  const flat = rows.map((t) => t.replace(/\s+/g, " ").trim());
  rec("C 회원 관리: 모든 상태(승인 대기·활성·사용 중지) 회원이 보인다", flat.length === 7 && flat.some((t) => t.includes("퇴사자") && t.includes("사용 중지")) && flat.some((t) => t.startsWith("kim") && t.includes("관리자") && t.includes("(나)")) && flat.some((t) => t.startsWith("wait") && t.includes("승인 대기")), flat.join(" | "));
  rec("C 회원 관리: 열 제목(아이디·이름·권한·상태·마지막 로그인·로그인 중·작업), 해시 없음", (await p.locator(".members-table thead th").allInnerTexts()).join(",") === "아이디,이름,권한,상태,마지막 로그인,로그인 중,작업" && !(await p.content()).includes("argon2"));
  rec("C 회원 관리: 이름의 스크립트는 글자로만 보이고 실행되지 않는다", (await p.evaluate(() => window.__xss === 1)) === false && flat.some((t) => t.includes("<script>")));
  rec("C 회원 관리: 본인(kim) 행에는 사용 중지·삭제·권한 변경 버튼이 없다", (await p.locator('tr[data-username="kim"] button').allInnerTexts()).every((t) => !/사용 중지|삭제|일반으로|관리자로/.test(t)));
  for (const w of [360, 1280]) {
    await p.setViewportSize({ width: w, height: 800 });
    rec(`C 회원 관리 ${w}px: 페이지 가로 넘침 없음(표는 안쪽 스크롤)`, !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    const axe = await runAxe(p);
    rec(`C 회원 관리 ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    await p.screenshot({ path: `${OUT}/admin-members-${w}.png` });
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
  const stale = sign(payloadFor(kim, "kim", "김철수", { sid: realSid("kim"), iat: nowS() - 600, exp, chk: nowS() - 600 }));
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

// ───────────────────────── E. 느린 로그인(서버가 깨어나는 중)에도 대기 팝업 없음(DEC-076)
if (should("E")) {
  const ctx = await newCtx(360);
  const p = await ctx.newPage();
  await p.route("**/auth/login", async (route) => { await new Promise((s) => setTimeout(s, 6500)); await route.continue(); });
  await p.goto("/login");
  await p.fill("#login-username", "park");
  await p.fill("#login-password", PW2);
  await p.click("button[type=submit]");
  await p.waitForTimeout(6000); // 4.5초 기준을 넘긴 뒤에도 팝업이 없어야 한다(DEC-076: 대기 팝업 제거)
  const popup = await p.locator('[role="dialog"]').count();
  const wakeText = await p.getByText("서버를 깨우는 중").count();
  rec("E 로그인 요청이 4.5초 넘게 걸려도 '서버를 깨우는 중' 팝업이 뜨지 않음", popup === 0 && wakeText === 0, `dialog=${popup} text=${wakeText}`);
  await p.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("E 느린 로그인이 끝나면 정상 로그인", new URL(p.url()).pathname === "/");
  await ctx.close();
}

// ───────────────────────── G. 관리자 전용 투자자 수급(DEC-074: 권한은 DB의 관리자 권한)
if (should("G")) {
  const PATH = "/api/v1/internal/admin/stocks/T00001/investor";
  const apiIdentity = async (username, pw, ip) => {
    const r = await fetch(`${API}/api/v1/internal/auth/login`, { method: "POST", headers: { "Content-Type": "application/json", "X-Internal-Token": TOKEN, "X-End-User-IP": ip }, body: JSON.stringify({ username, password: pw }) });
    const d = (await r.json()).data;
    return { "X-Internal-Token": TOKEN, "X-Auth-User": d.user_id, "X-Auth-Session": d.session_id };
  };
  // 관리자(kim): 화면에 값이 보인다
  const octx = await newCtx(1280);
  const op = await octx.newPage();
  await uiLogin(op, "kim", PW);
  await op.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  await op.goto("/stocks/T00001");
  await op.getByRole("tab", { name: "투자자" }).click();
  await op.waitForSelector(".daily-table", { timeout: 15000 }).catch(() => {});
  const otext = await op.locator('[role="tabpanel"]:not([hidden])').innerText().catch(() => "");
  rec("G 관리자: 투자자 탭에 수집 값 표(▼1,234 / ▲4,321)", /4,321/.test(otext) && /1,234/.test(otext) && !/준비 중/.test(otext), otext.replace(/\s+/g, " ").slice(0, 120));
  rec("G 관리자: 결측 값은 0이 아니라 '–'", /–/.test(otext));
  rec("G 관리자: 최근 날짜가 위(2026-10-01 → 2026-09-30)", otext.indexOf("2026-10-01") !== -1 && otext.indexOf("2026-10-01") < otext.indexOf("2026-09-30"));
  rec("G 관리자: 수집 안내 문구 표시", /관리자 PC에서/.test(otext));
  let r = await octx.request.get(`${BASE}${PATH}`);
  const ob = await r.json();
  rec("G 관리자 대행 호출: 200 + no-store + 2행", r.status() === 200 && /no-store/.test(r.headers()["cache-control"] ?? "") && ob.data.rows.length === 2, `${r.status()}`);
  await octx.close();
  // 일반 사용자(park): 같은 화면은 '준비 중', 값 호출은 403
  const pctx = await newCtx(1280);
  const pp = await pctx.newPage();
  await uiLogin(pp, "park", PW2);
  await pp.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  await pp.goto("/stocks/T00001");
  await pp.getByRole("tab", { name: "투자자" }).click();
  await pp.waitForTimeout(800);
  const ptext = await pp.locator('[role="tabpanel"]:not([hidden])').innerText().catch(() => "");
  rec("G 일반 사용자: 투자자 탭은 '준비 중', 값 없음", /준비 중/.test(ptext) && !/4,321/.test(ptext) && !/1,234/.test(ptext));
  r = await pctx.request.get(`${BASE}${PATH}`);
  rec("G 일반 사용자가 주소를 직접 호출: 403, 값 없음", r.status() === 403 && !/4321|1234|rows/.test(await r.text()), `${r.status()}`);
  await pctx.close();
  // 비로그인·API 직접 호출
  r = await fetch(`${BASE}${PATH}`);
  rec("G 비로그인 대행 호출: 401", r.status === 401, `${r.status}`);
  r = await fetch(`${API}${PATH}`);
  rec("G API 직접 호출(토큰 없음): 401", r.status === 401, `${r.status}`);
  const admin = await apiIdentity("kim", PW, "198.51.100.31");
  const plain = await apiIdentity("park", PW2, "198.51.100.32");
  r = await fetch(`${API}${PATH}`, { headers: { "X-Internal-Token": TOKEN } });
  rec("G API 직접 호출(토큰만, 로그인 정보 없음): 403", r.status === 403, `${r.status}`);
  r = await fetch(`${API}${PATH}`, { headers: plain });
  rec("G API 직접 호출(일반 사용자의 유효한 세션): 403", r.status === 403, `${r.status}`);
  r = await fetch(`${API}${PATH}`, { headers: admin });
  rec("G API 직접 호출(관리자의 유효한 세션): 200", r.status === 200, `${r.status}`);
  r = await fetch(`${API}${PATH}`, { headers: { ...plain, "X-Auth-User": admin["X-Auth-User"] } });
  rec("G 일반 사용자 세션에 관리자 id를 섞어도 403(세션 소유자와 id가 다름)", r.status === 403, `${r.status}`);
  r = await fetch(`${API}${PATH}`, { headers: { ...admin, "X-Auth-Username": "kim", "X-Auth-Role": "admin" } });
  rec("G 옛 방식 헤더(아이디·권한)는 아무 효과가 없다(관리자 세션이면 200, 헤더만으로는 403)", r.status === 200 && (await fetch(`${API}${PATH}`, { headers: { "X-Internal-Token": TOKEN, "X-Auth-Username": "kim", "X-Auth-Role": "admin" } })).status === 403);
  // 브라우저가 보낸 가짜 헤더는 대행 경로가 무시한다
  const fctx = await newCtx(1280);
  const fp = await fctx.newPage();
  await uiLogin(fp, "lee", PW2);
  await fp.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  r = await fctx.request.get(`${BASE}${PATH}`, { headers: { "X-Auth-Session": admin["X-Auth-Session"], "X-Auth-User": admin["X-Auth-User"], "X-Internal-Token": TOKEN, "X-Auth-Role": "admin" } });
  rec("G 일반 사용자가 관리자 세션 헤더를 위조해도 403(대행 경로가 브라우저 헤더를 무시)", r.status() === 403, `${r.status()}`);
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
    rec(`H ${w}px: '아이디 저장' 체크박스 + 라벨 연결 + 안내 문구(비밀번호 미저장·공용 PC 주의)`, (await p.locator("label[for=login-remember]").innerText()) === "아이디 저장" && /비밀번호는 저장하지 않으며/.test(await p.locator(".login-form__hint").first().innerText()) && /공용 PC/.test(await p.locator(".login-form__hint").first().innerText()));
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

// ───────────────────────── I. 로그인 상태 유지 30일 + 서버 쪽 세션 취소(DEC-070)
if (should("I")) {
  const decode = (c) => JSON.parse(Buffer.from(c.value.split(".")[0], "base64url").toString("utf8"));
  const cookieOf = async (ctx) => (await ctx.cookies()).find((c) => c.name === COOKIE);
  // 같은 세션 id로 "확인한 지 10분 지난" 쿠키를 만든다(발급·만료 시각을 함께 앞당겨 수명은 그대로).
  const staleOf = (payload) => sign({ ...payload, iat: payload.iat - 700, exp: payload.exp - 700, chk: nowS() - 600 }); // 수명(exp-iat)은 그대로 유지해야 형식 검사를 통과한다
  const dbSess = (sid) => psql(`SELECT remember, round(extract(epoch FROM (expires_at - created_at))), revoked_at IS NOT NULL FROM auth.user_sessions WHERE session_id='${sid}'`);
  // 화면
  for (const w of [360, 1280]) {
    const ctx = await newCtx(w);
    const p = await ctx.newPage();
    await p.goto("/login");
    rec(`I ${w}px: '로그인 상태 유지(30일)' 체크박스 + 라벨 연결, 기본 해제`, (await p.locator("label[for=login-keep]").innerText()) === "로그인 상태 유지(30일)" && !(await p.isChecked("#login-keep")));
    const hint = await p.locator("#login-keep-hint").innerText();
    rec(`I ${w}px: 안내(30일·공용 PC 금지·로그아웃하면 해제) + aria-describedby 연결`, /30일/.test(hint) && /공용 PC/.test(hint) && /로그아웃하면 바로 해제/.test(hint) && (await p.getAttribute("#login-keep", "aria-describedby")) === "login-keep-hint");
    rec(`I ${w}px: 가로 넘침 없음·체크박스 줄 44px 이상`, !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) && (await p.evaluate(() => Math.round(document.querySelector("#login-keep").closest(".login-form__remember").getBoundingClientRect().height))) >= 44);
    await p.focus("#login-remember");
    await p.keyboard.press("Tab");
    rec(`I ${w}px: Tab 순서 아이디 저장 → 로그인 상태 유지`, (await p.evaluate(() => document.activeElement?.id)) === "login-keep");
    const axe = await runAxe(p);
    rec(`I ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    if (w === 360) { await p.check("#login-keep"); await p.screenshot({ path: `${OUT}/login-keep-360.png` }); }
    await ctx.close();
  }
  // 입력 검증: remember는 참/거짓만
  for (const bad of ['"true"', "1", "null", "[true]", '"yes"']) {
    const r = await fetch(`${BASE}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json", Origin: BASE }, body: `{"username":"park","password":"x","remember":${bad}}` });
    rec(`I /auth/login remember=${bad}: 400`, r.status === 400, `${r.status}`);
  }
  // 유지 체크 없이 로그인: 8시간
  const c8 = await newCtx(1280);
  const p8 = await c8.newPage();
  await uiLogin(p8, "park", PW2);
  await p8.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  const ck8 = await cookieOf(c8);
  const d8 = decode(ck8);
  rec("I 유지 미체크: 쿠키 수명 8시간 이하, rm=0, 서버 세션 remember=false/8시간", d8.rm === 0 && ck8.expires - nowS() <= 8 * 3600 + 5 && dbSess(d8.sid).startsWith("f|28800"), `${ck8.expires - nowS()}s ${dbSess(d8.sid)}`);
  await c8.close();
  // 유지 체크하고 로그인: 30일
  const ctx = await newCtx(1280);
  const p = await ctx.newPage();
  await p.goto("/login");
  await p.fill("#login-username", "park");
  await p.fill("#login-password", PW2);
  await p.check("#login-keep");
  await p.click("button[type=submit]");
  await p.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  const ck = await cookieOf(ctx);
  const d = decode(ck);
  const ttl = ck.expires - nowS();
  rec("I 유지 체크: 쿠키 수명 약 30일(29.9~30일), rm=1", d.rm === 1 && ttl > 29.9 * 86400 && ttl <= 30 * 86400 + 5, `${Math.round(ttl / 86400 * 100) / 100}일`);
  rec("I 유지 체크: 쿠키 속성 HttpOnly·Path=/·SameSite=Lax" + (INSECURE ? "" : "·Secure·__Host- 접두어"), ck.httpOnly && ck.path === "/" && ck.sameSite === "Lax" && (INSECURE || (ck.secure && ck.name.startsWith("__Host-"))));
  rec("I 유지 체크: 서버 세션 remember=true, 수명 정확히 30일(2592000초), 취소 안 됨", dbSess(d.sid) === "t|2592000|f", dbSess(d.sid));
  rec("I 유지 체크: 비밀번호·해시는 쿠키에 없다", !ck.value.includes(PW2) && !Buffer.from(ck.value.split(".")[0], "base64url").toString("utf8").includes("argon2"));
  rec("I 유지 쿠키로 페이지·대행 호출 정상", (await ctx.request.get(`${BASE}/api/v1/market-summary`)).status() === 200);
  // 3일 뒤 상황(확인 시각이 오래됨): 서버가 세션을 다시 확인하고 통과
  const exp3 = nowS() - 3 * 86400 + 30 * 86400;
  await setSessionCookie(ctx, sign({ ...d, iat: nowS() - 3 * 86400, exp: exp3, chk: nowS() - 3 * 86400 }));
  await p.goto("/stocks");
  await p.waitForURL((u) => u.pathname === "/stocks", { timeout: 20000 });
  const renewed = decode(await cookieOf(ctx));
  rec("I 3일 지난 30일 쿠키: 서버 확인 후 통과, 만료 시각은 그대로(연장 없음)", new URL(p.url()).pathname === "/stocks" && renewed.exp === exp3 && nowS() - renewed.chk <= 15, `exp 불변=${renewed.exp === exp3}`);
  // 로그아웃: 서버 세션 취소 + 쿠키 삭제
  await setSessionCookie(ctx, sign(d));
  const copy = (await cookieOf(ctx)).value; // 로그아웃 직전의 쿠키 복사본(탈취 가정)
  const out = await ctx.request.post(`${BASE}/auth/logout`, { headers: { origin: new URL(BASE).origin } });
  const outBody = await out.json();
  rec("I 로그아웃: ok + 서버 세션 취소(revoked=true)", out.status() === 200 && outBody.ok === true && outBody.revoked === true, JSON.stringify(outBody));
  rec("I 로그아웃: DB 세션 revoked_at 기록", dbSess(d.sid).endsWith("|t"), dbSess(d.sid));
  rec("I 로그아웃: 쿠키 삭제", (await ctx.cookies()).filter((c) => c.name === COOKIE && c.value).length === 0);
  // 훔친 복사본: 5분 안에는 서명·만료만 보는 알려진 한계 창, 5분이 지나 서버가 확인하면 거부
  const t1 = await newCtx(1280);
  await setSessionCookie(t1, copy);
  const early = await t1.request.get(`${BASE}/api/v1/market-summary`);
  rec("I [알려진 한계] 로그아웃 직후 5분 안의 쿠키 복사본은 아직 통과(확인 주기 5분)", early.status() === 200, `${early.status()}`);
  await setSessionCookie(t1, staleOf(d));
  const late = await t1.request.get(`${BASE}/api/v1/market-summary`);
  rec("I 로그아웃한 세션의 복사본은 확인 주기(5분)가 지나면 거부(401)", late.status() === 401, `${late.status()}`);
  rec("I [시험 대조군] 같은 방식으로 만든 5분 지난 쿠키도 살아 있는 세션이면 통과(위 거부가 형식 오류 때문이 아님을 보장)", await (async () => { const sid = realSid("park", true); const c = await newCtx(1280); await setSessionCookie(c, staleOf({ ...d, sid })); const st = (await c.request.get(`${BASE}/api/v1/market-summary`)).status(); await c.close(); return st === 200; })());
  const t1p = await t1.newPage();
  await setSessionCookie(t1, staleOf(d));
  await t1p.goto("/stocks");
  await t1p.waitForURL((u) => u.pathname === "/login", { timeout: 20000 });
  rec("I 로그아웃한 세션의 복사본으로 화면 접근: 로그인 화면으로 + '만료' 안내", new URL(t1p.url()).searchParams.get("reason") === "expired");
  await t1.close(); await ctx.close();
  // 두 기기: 한쪽 로그아웃은 다른 쪽 세션을 끊지 않는다
  const mk2 = async () => { const c = await newCtx(1280); const pg = await c.newPage(); await pg.goto("/login"); await pg.fill("#login-username", "park"); await pg.fill("#login-password", PW2); await pg.check("#login-keep"); await pg.click("button[type=submit]"); await pg.waitForURL((u) => u.pathname === "/", { timeout: 20000 }); return c; };
  const home = await mk2(); const phone = await mk2();
  const dh = decode(await cookieOf(home)); const dp = decode(await cookieOf(phone));
  rec("I 기기마다 서로 다른 세션 id", dh.sid !== dp.sid);
  await home.request.post(`${BASE}/auth/logout`, { headers: { origin: new URL(BASE).origin } });
  await setSessionCookie(phone, staleOf(dp));
  rec("I 한 기기 로그아웃 후에도 다른 기기 세션은 서버 확인 통과(200)", (await phone.request.get(`${BASE}/api/v1/market-summary`)).status() === 200);
  // 관리자 취소(분실·탈취 대응): revoke → 5분 지난 확인에서 거부
  psql(`UPDATE auth.user_sessions SET revoked_at = now() WHERE session_id='${dp.sid}'`);
  await setSessionCookie(phone, staleOf(dp));
  rec("I 관리자가 세션을 취소하면 다음 서버 확인에서 거부(401)", (await phone.request.get(`${BASE}/api/v1/market-summary`)).status() === 401);
  await home.close(); await phone.close();
  // 서버 쪽 만료(30일 지남)·남의 세션 id·없는 세션 id 위조
  const sidExp = realSid("park", true);
  psql(`UPDATE auth.user_sessions SET created_at = now() - interval '31 days', expires_at = now() - interval '1 day' WHERE session_id='${sidExp}'`);
  const pk = uidOf("park");
  const forged = [
    ["서버에서 만료된 30일 세션", { sid: sidExp, rm: 1, iat: nowS() - 600, exp: nowS() + 86400, chk: nowS() - 600 }],
    ["없는 세션 id(서명은 맞음)", { sid: randomUUID(), rm: 1, iat: nowS() - 600, exp: nowS() + 86400, chk: nowS() - 600 }],
    ["다른 회원(kim)의 세션 id를 park 쿠키에 넣음", { sid: realSid("kim", true), rm: 1, iat: nowS() - 600, exp: nowS() + 86400, chk: nowS() - 600 }],
  ];
  for (const [name, over] of forged) {
    const c = await newCtx(1280);
    await setSessionCookie(c, sign(payloadFor(pk, "park", "박민수", over)));
    rec(`I 위조/무효 쿠키 ${name}: 서버 확인에서 거부(401)`, (await c.request.get(`${BASE}/api/v1/market-summary`)).status() === 401);
    await c.close();
  }
  // 로그아웃: 같은 사이트 요청만, 쿠키 없이도 안전하게 성공 응답
  const bare = await fetch(`${BASE}/auth/logout`, { method: "POST", headers: { Origin: "https://evil.example.com" } });
  rec("I 로그아웃: 다른 사이트에서 온 요청은 403(남이 몰래 로그아웃시키지 못함)", bare.status === 403, `${bare.status}`);
  const noCookie = await fetch(`${BASE}/auth/logout`, { method: "POST", headers: { Origin: BASE } });
  const nb = await noCookie.json();
  rec("I 쿠키 없는 로그아웃: 200, revoked=false(상태를 알려 주지 않음)", noCookie.status === 200 && nb.ok === true && nb.revoked === false);
  // 회원 비활성화: 30일 세션도 5분 안에 차단, 다시 활성화해도 되살아나지 않는다(CLI는 세션도 취소)
  const c9 = await newCtx(1280);
  const p9 = await c9.newPage();
  await p9.goto("/login"); await p9.fill("#login-username", "lock"); await p9.fill("#login-password", PW); await p9.check("#login-keep"); 
  psql("UPDATE auth.app_users SET failed_attempts = 0, lockout_level = 0, locked_until = NULL WHERE username='lock'");
  await p9.click("button[type=submit]");
  await p9.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  const d9 = decode(await cookieOf(c9));
  psql("UPDATE auth.app_users SET is_active = false WHERE username='lock'");
  await setSessionCookie(c9, staleOf(d9));
  rec("I 회원 비활성화: 30일 세션도 다음 서버 확인에서 거부", (await c9.request.get(`${BASE}/api/v1/market-summary`)).status() === 401);
  psql("UPDATE auth.app_users SET is_active = true WHERE username='lock'");
  await c9.close();
}

// ───────────────────────── J. 모든 기기에서 로그아웃(DEC-071)
if (should("J")) {
  const decode = (c) => JSON.parse(Buffer.from(c.value.split(".")[0], "base64url").toString("utf8"));
  const cookieOf = async (ctx) => (await ctx.cookies()).find((c) => c.name === COOKIE);
  const staleOf = (payload) => sign({ ...payload, iat: payload.iat - 700, exp: payload.exp - 700, chk: nowS() - 600 });
  const activeCount = (username) => Number(psql(`SELECT count(*) FROM auth.user_sessions s JOIN auth.app_users u USING (user_id) WHERE u.username='${username}' AND s.revoked_at IS NULL AND s.expires_at > now()`));
  const login = async (username, pw, w = 1280) => {
    const c = await newCtx(w); const pg = await c.newPage();
    await pg.goto("/login"); await pg.fill("#login-username", username); await pg.fill("#login-password", pw); await pg.check("#login-keep");
    await pg.click("button[type=submit]"); await pg.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
    return { c, pg };
  };
  psql("UPDATE auth.user_sessions SET revoked_at = now() WHERE revoked_at IS NULL"); // 다른 구역 시험이 남긴 세션 정리
  // 화면(360/1280): 메뉴에 두 버튼, 넘침·터치 크기·접근성
  for (const w of [360, 1280]) {
    const { c, pg } = await login("park", PW2, w);
    await pg.locator(".member-menu").waitFor({ timeout: 10000 });
    const names = await pg.locator(".member-menu button").allInnerTexts();
    rec(`J ${w}px: 회원 메뉴에 '로그아웃'과 '모든 기기에서 로그아웃' 버튼`, names.includes("로그아웃") && names.includes("모든 기기에서 로그아웃"), names.join("|"));
    const hs = await pg.evaluate(() => [...document.querySelectorAll(".member-menu button")].map((b) => Math.round(b.getBoundingClientRect().height)));
    rec(`J ${w}px: 버튼 높이 44px 이상·가로 넘침 없음`, hs.every((h) => h >= 44) && !(await pg.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)), hs.join(","));
    const axe = await runAxe(pg);
    rec(`J ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    if (w === 360) await pg.screenshot({ path: `${OUT}/member-menu-360.png` });
    await c.close();
  }
  psql("UPDATE auth.user_sessions SET revoked_at = now() WHERE revoked_at IS NULL");
  // 확인창에서 취소하면 아무 일도 없다
  const d1 = await login("park", PW2); const d2 = await login("park", PW2); const lee = await login("lee", PW2);
  rec("J 준비: park 두 기기·lee 한 기기 로그인", activeCount("park") === 2 && activeCount("lee") === 1, `${activeCount("park")}/${activeCount("lee")}`);
  let msg = "";
  d1.pg.once("dialog", (d) => { msg = d.message(); d.dismiss(); });
  await d1.pg.locator(".member-menu button", { hasText: "모든 기기에서 로그아웃" }).click();
  await d1.pg.waitForTimeout(800);
  rec("J 확인창 문구(모든 기기·30일 유지 해제 안내) + 취소하면 아무것도 바뀌지 않는다", /모든 기기/.test(msg) && /30일/.test(msg) && activeCount("park") === 2 && new URL(d1.pg.url()).pathname === "/", msg.slice(0, 40));
  // 서버 취소 실패: 성공처럼 보이지 않고 로그인 유지 + 오류 안내 + 다시 시도 가능
  await d1.pg.route("**/auth/logout-all", (route) => route.fulfill({ status: 503, contentType: "application/json", body: '{"ok":false,"code":"SERVICE_UNAVAILABLE"}' }));
  d1.pg.once("dialog", (d) => d.accept());
  await d1.pg.locator(".member-menu button", { hasText: "모든 기기에서 로그아웃" }).click();
  const alertText = await d1.pg.locator(".member-menu__notice").waitFor({ timeout: 8000 }).then(() => d1.pg.locator(".member-menu__notice").innerText()).catch(() => "");
  rec("J 서버 취소 실패(503): 오류 안내(role=alert)·로그인 유지·세션 그대로", /하지 못했습니다/.test(alertText) && /그대로 유지/.test(alertText) && new URL(d1.pg.url()).pathname === "/" && activeCount("park") === 2 && !!(await cookieOf(d1.c)), alertText.slice(0, 50));
  rec("J 실패 뒤 버튼이 다시 활성화(재시도 가능)", await d1.pg.locator(".member-menu button", { hasText: "모든 기기에서 로그아웃" }).isEnabled());
  await d1.pg.unroute("**/auth/logout-all");
  // 실제 실행
  const dp2 = decode(await cookieOf(d2.c)); const dl = decode(await cookieOf(lee.c));
  d1.pg.once("dialog", (d) => d.accept());
  await d1.pg.locator(".member-menu button", { hasText: "모든 기기에서 로그아웃" }).click();
  await d1.pg.waitForURL((u) => u.pathname === "/login", { timeout: 20000 });
  rec("J 실행: 이 기기는 로그인 화면으로, 쿠키 삭제", (await d1.c.cookies()).filter((c) => c.name === COOKIE && c.value).length === 0);
  rec("J 실행: park의 모든 서버 세션 취소(0건 남음), lee는 그대로(1건)", activeCount("park") === 0 && activeCount("lee") === 1, `${activeCount("park")}/${activeCount("lee")}`);
  await setSessionCookie(d2.c, staleOf(dp2));
  rec("J 다른 기기(park)는 서버 확인(5분 주기)에서 거부(401)", (await d2.c.request.get(`${BASE}/api/v1/market-summary`)).status() === 401);
  await setSessionCookie(lee.c, staleOf(dl));
  rec("J 다른 회원(lee)의 세션은 영향 없음(200)", (await lee.c.request.get(`${BASE}/api/v1/market-summary`)).status() === 200);
  // 다시 로그인하면 정상
  const again = await login("park", PW2);
  rec("J 취소 뒤 새로 로그인하면 정상 이용", activeCount("park") === 1 && (await again.c.request.get(`${BASE}/api/v1/market-summary`)).status() === 200);
  // 엔드포인트 직접 호출 보호
  const origin = new URL(BASE).origin;
  const anon = await fetch(`${BASE}/auth/logout-all`, { method: "POST", headers: { Origin: origin } });
  rec("J 로그인 없이 호출: 401", anon.status === 401, `${anon.status}`);
  const cross = await again.c.request.post(`${BASE}/auth/logout-all`, { headers: { origin: "https://evil.example.com" } });
  rec("J 다른 사이트에서 온 요청: 403이고 세션은 그대로(남이 몰래 전체 로그아웃시키지 못함)", cross.status() === 403 && activeCount("park") === 1, `${cross.status()}`);
  const ok = await again.c.request.post(`${BASE}/auth/logout-all`, { headers: { origin } });
  const okBody = await ok.json();
  rec("J 정상 호출: 200·ok·revoked_count=1, 쿠키 삭제 응답", ok.status() === 200 && okBody.ok === true && okBody.revoked_count === 1 && /no-store/.test(ok.headers()["cache-control"] ?? ""), JSON.stringify(okBody));
  // 이미 취소된 세션의 복사본으로는 호출할 수 없다
  const revokedCopy = sign(payloadFor(uidOf("park"), "park", "박민수", { sid: realSid("park", true) }));
  psql("UPDATE auth.user_sessions SET revoked_at = now() WHERE revoked_at IS NULL AND user_id = (SELECT user_id FROM auth.app_users WHERE username='park')");
  const rc = await newCtx(1280);
  await setSessionCookie(rc, revokedCopy);
  const rr = await rc.request.post(`${BASE}/auth/logout-all`, { headers: { origin } });
  rec("J 이미 취소된 세션 쿠키(5분 안의 복사본)로는 전체 로그아웃도 못 한다(401, 서버가 거부)", rr.status() === 401, `${rr.status()}`);
  await rc.close();
  for (const x of [d1, d2, lee, again]) await x.c.close();
}

// ───────────────────────── K. 회원가입 신청(승인 대기) (DEC-074)
if (should("K")) {
  const origin = new URL(BASE).origin;
  const row = (u) => psql(`SELECT role, is_active, approved_at IS NOT NULL FROM auth.app_users WHERE username='${u}'`);
  const count = (u) => Number(psql(`SELECT count(*) FROM auth.app_users WHERE username='${u}'`));
  for (const w of [360, 1280]) {
    const ctx = await newCtx(w);
    const p = await ctx.newPage();
    await p.goto("/login");
    rec(`K ${w}px: 로그인 화면에 '회원가입' 링크`, (await p.locator(".login-form__signup a").innerText()) === "회원가입");
    await p.click(".login-form__signup a");
    await p.waitForURL((u) => u.pathname === "/signup", { timeout: 10000 });
    await p.waitForSelector("#signup-username", { timeout: 15000 });
    const labels = await p.locator("label").allInnerTexts();
    rec(`K ${w}px: 가입 화면 라벨(아이디·이름·비밀번호·비밀번호 확인)`, ["아이디", "이름", "비밀번호", "비밀번호 확인"].every((l) => labels.includes(l)), labels.join(","));
    rec(`K ${w}px: 승인 후 로그인 안내 문구`, /관리자가 확인한 뒤 승인/.test(await p.locator(".login-page__intro").innerText()));
    rec(`K ${w}px: 숨긴 봇 칸은 화면 밖·키보드 불가·aria-hidden`, await p.evaluate(() => { const hp = document.querySelector(".signup-hp"); const inp = hp?.querySelector("input"); const r = hp?.getBoundingClientRect(); return !!hp && hp.getAttribute("aria-hidden") === "true" && inp?.tabIndex === -1 && r.right <= 1 && r.width <= 2; }));
    rec(`K ${w}px: 가로 넘침 없음·입력칸 44px 이상`, !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) && (await p.evaluate(() => [...document.querySelectorAll(".login-form input:not([tabindex='-1']), .login-form__submit")].every((e) => e.getBoundingClientRect().height >= 44))));
    const axe = await runAxe(p);
    rec(`K ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    if (w === 360) await p.screenshot({ path: `${OUT}/signup-360.png` });
    await ctx.close();
  }
  const ctx = await newCtx(1280);
  const p = await ctx.newPage();
  let signupCalls = 0;
  p.on("request", (rq) => { if (rq.url().endsWith("/auth/signup") && rq.method() === "POST") signupCalls += 1; });
  const fill = async (u, n, pw, pw2) => { await p.fill("#signup-username", u); await p.fill("#signup-name", n); await p.fill("#signup-password", pw); await p.fill("#signup-password-confirm", pw2); };
  await p.goto("/signup");
  await fill("newbie1", "신입사원", "Qw8!rT5zLp", "Qw8!rT5zLX");
  await p.click("button[type=submit]");
  rec("K 비밀번호 확인이 다르면 서버에 보내지 않고 안내", /서로 다릅니다/.test(await p.locator(".login-form__message").innerText()) && signupCalls === 0);
  await fill("newbie1", "신입사원", "12345678", "12345678");
  await p.click("button[type=submit]");
  await p.waitForFunction(() => /흔하거나|연속된/.test(document.querySelector(".login-form__message")?.textContent ?? ""), null, { timeout: 15000 }).catch(() => {});
  rec("K 약한 비밀번호: 서버 문구 표시, 계정 만들어지지 않음", /흔하거나|연속된/.test(await p.locator(".login-form__message").innerText()) && count("newbie1") === 0);
  await fill("ab", "신입사원", "Qw8!rT5zLp", "Qw8!rT5zLp");
  await p.click("button[type=submit]");
  await p.waitForFunction(() => /아이디는 3~32자/.test(document.querySelector(".login-form__message")?.textContent ?? ""), null, { timeout: 15000 }).catch(() => {});
  rec("K 아이디 형식 오류: 서버 문구 표시, 계정 없음", /아이디는 3~32자/.test(await p.locator(".login-form__message").innerText()) && count("ab") === 0);
  await fill("newbie1", "신입사원", "Qw8!rT5zLp", "Qw8!rT5zLp");
  await p.click("button[type=submit]");
  await p.locator(".signup-done").waitFor({ timeout: 20000 });
  rec("K 가입 신청 성공: 접수 안내(로그인되지 않음)", /가입 신청이 접수/.test(await p.locator(".signup-done").innerText()) && (await ctx.cookies()).filter((c) => c.name === COOKIE).length === 0);
  rec("K DB: 일반 권한·비활성·미승인(승인 대기)", row("newbie1") === "user|f|f", row("newbie1"));
  rec("K DB: 비밀번호는 argon2id 해시(원문 아님)", psql("SELECT password_hash FROM auth.app_users WHERE username='newbie1'").startsWith("$argon2id$"));
  // 승인 전 로그인
  const lp = await ctx.newPage();
  await lp.goto("/login");
  await lp.fill("#login-username", "newbie1");
  await lp.fill("#login-password", "Qw8!rT5zLp");
  await lp.click("button[type=submit]");
  await lp.locator(".login-form__message").waitFor({ timeout: 20000 });
  rec("K 승인 전 로그인(비밀번호 맞음): '관리자 승인 대기' 안내, 로그인 안 됨", /승인 대기/.test(await lp.locator(".login-form__message").innerText()) && (await ctx.cookies()).filter((c) => c.name === COOKIE).length === 0 && new URL(lp.url()).pathname === "/login");
  await lp.fill("#login-password", "wrong-password-xyz");
  await lp.click("button[type=submit]");
  await lp.waitForFunction(() => /올바르지 않습니다/.test(document.querySelector(".login-form__message")?.textContent ?? ""), null, { timeout: 15000 }).catch(() => {});
  rec("K 승인 전 로그인(비밀번호 틀림): 평범한 실패 문구(승인 대기 여부를 알려 주지 않음)", /올바르지 않습니다/.test(await lp.locator(".login-form__message").innerText()));
  rec("K 승인 전에는 서버 세션이 만들어지지 않는다", Number(psql("SELECT count(*) FROM auth.user_sessions s JOIN auth.app_users u USING (user_id) WHERE u.username='newbie1'")) === 0);
  // 중복
  await p.goto("/signup");
  await fill("NewBie1", "다른사람", "Zx9!kM2vBn", "Zx9!kM2vBn");
  await p.click("button[type=submit]");
  await p.locator(".login-form__message").waitFor({ timeout: 15000 });
  rec("K 아이디 중복(대소문자 무관): 안내, 처음 신청은 그대로", /이미 사용 중/.test(await p.locator(".login-form__message").innerText()) && count("newbie1") === 1);
  // 웹 가입 경로 직접 호출: 권한 주입·교차 사이트·잘못된 형식
  const post = (body, headers = {}) => fetch(`${BASE}/auth/signup`, { method: "POST", headers: { "Content-Type": "application/json", Origin: origin, ...headers }, body: JSON.stringify(body) });
  let r = await post({ username: "sneaky1", displayName: "교활", password: "Vb7!nM3xQz", role: "admin", is_active: true, approved_at: "2020-01-01" });
  rec("K 가입 요청에 role/is_active/approved_at을 넣어도 무시: 승인 대기 일반 계정으로만 생성", r.status === 200 && row("sneaky1") === "user|f|f", `${r.status} ${row("sneaky1")}`);
  r = await post({ username: "evil1", displayName: "x", password: "Vb7!nM3xQz" }, { Origin: "https://evil.example.com" });
  rec("K 다른 사이트에서 온 가입 요청: 403, 계정 없음", r.status === 403 && count("evil1") === 0);
  r = await fetch(`${BASE}/auth/signup`, { method: "POST", headers: { "Content-Type": "text/plain", Origin: origin }, body: "x" });
  rec("K JSON이 아닌 가입 요청: 415", r.status === 415);
  r = await post({ username: "x".repeat(70), displayName: "x", password: "Vb7!nM3xQz" });
  rec("K 너무 긴 아이디: 400", r.status === 400);
  r = await post({ username: "bot1", displayName: "봇", password: "Vb7!nM3xQz", website: "http://spam.example" });
  rec("K 숨긴 칸을 채운 요청(봇): 성공처럼 응답하지만 계정은 만들지 않는다", r.status === 200 && count("bot1") === 0);
  // 로그인한 사용자가 /signup을 열면 홈으로
  const lctx = await newCtx(1280);
  const lpg = await lctx.newPage();
  await uiLogin(lpg, "park", PW2);
  await lpg.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  await lpg.goto("/signup");
  rec("K 로그인한 회원이 /signup을 열면 홈으로", new URL(lpg.url()).pathname === "/");
  await lctx.close();
  // 신청 빈도 제한(접속 주소당 10분 30회, E2E 설정)
  const apiSignup = (u, ip) => fetch(`${API}/api/v1/internal/auth/signup`, { method: "POST", headers: { "Content-Type": "application/json", "X-Internal-Token": TOKEN, "X-End-User-IP": ip }, body: JSON.stringify({ username: u, display_name: "연타", password: "Vb7!nM3xQz" }) });
  const codes = [];
  for (let i = 0; i < 32; i += 1) codes.push((await apiSignup(`burst${String(i).padStart(2, "0")}x`, "198.51.100.177")).status);
  const first429 = codes.indexOf(429);
  rec("K 같은 접속 주소의 가입 신청이 10분에 30회를 넘으면 429", first429 >= 29 && first429 <= 31, `첫 429 위치 ${first429}`);
  rec("K 다른 접속 주소는 영향 없음", (await apiSignup("burst99x", "198.51.100.179")).status === 200);
  psql("DELETE FROM auth.app_users WHERE username LIKE 'burst%' OR username IN ('sneaky1')");
  await ctx.close();
}

// ───────────────────────── L. 관리자 회원 관리 화면 (DEC-074)
if (should("L")) {
  // 앞 장면들이 같은 접속 주소(127.0.0.1)에서 로그인을 많이 해 분당 40회 한도(F 장면이 시험하는 값)에 가깝다 → 한도 창이 비도록 잠시 기다린다(시험 환경 보정, 제품 동작 아님).
  if (!ONLY) await new Promise((r) => setTimeout(r, 62000));
  const origin = new URL(BASE).origin;
  const decode = (c) => JSON.parse(Buffer.from(c.value.split(".")[0], "base64url").toString("utf8"));
  const cookieOf = async (ctx) => (await ctx.cookies()).find((c) => c.name === COOKIE);
  const staleOf = (pl) => sign({ ...pl, iat: pl.iat - 700, exp: pl.exp - 700, chk: nowS() - 600 });
  const dbrow = (u) => psql(`SELECT role, is_active, approved_at IS NOT NULL, display_name FROM auth.app_users WHERE username='${u}'`);
  const exists = (u) => Number(psql(`SELECT count(*) FROM auth.app_users WHERE username='${u}'`)) === 1;
  psql("DELETE FROM auth.app_users WHERE username IN ('spam1','added1')");
  if (!exists("newbie1")) { await fetch(`${API}/api/v1/internal/auth/signup`, { method: "POST", headers: { "Content-Type": "application/json", "X-Internal-Token": TOKEN, "X-End-User-IP": "198.51.100.90" }, body: JSON.stringify({ username: "newbie1", display_name: "신입사원", password: "Qw8!rT5zLp" }) }); }
  await fetch(`${API}/api/v1/internal/auth/signup`, { method: "POST", headers: { "Content-Type": "application/json", "X-Internal-Token": TOKEN, "X-End-User-IP": "198.51.100.91" }, body: JSON.stringify({ username: "spam1", display_name: "스팸", password: "Qw8!rT5zLp" }) });
  const octx = await newCtx(1280);
  const op = await octx.newPage();
  op.on("dialog", (d) => d.accept());
  await uiLogin(op, "kim", PW);
  await op.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  await op.click(".member-menu__link");
  await op.waitForURL((u) => u.pathname === "/admin/members", { timeout: 15000 });
  await op.waitForSelector(".admin-members", { timeout: 15000 });
  rec("L 관리자 메뉴의 '회원 관리' 링크로 이동", new URL(op.url()).pathname === "/admin/members");
  rec("L 승인 대기 신청이 있으면 '승인 대기' 탭이 먼저 열린다", (await op.getByRole("button", { name: /^승인 대기/ }).getAttribute("aria-pressed")) === "true" && (await op.locator('tr[data-username="newbie1"]').count()) === 1);
  const notice = () => op.locator(".admin-members__notice");
  const act = async (u, label) => { await op.locator(`tr[data-username="${u}"]`).getByRole("button", { name: new RegExp(`${label}$`) }).click(); };
  const waitNotice = async (re) => { await op.waitForFunction((src) => new RegExp(src).test(document.querySelector(".admin-members__notice")?.textContent ?? ""), re.source, { timeout: 15000 }).catch(() => {}); return (await notice().innerText().catch(() => "")); };
  // 확인창에서 취소하면 변화 없음
  op.removeAllListeners("dialog");
  op.once("dialog", (d) => d.dismiss());
  await act("spam1", "거절");
  await op.waitForTimeout(600);
  rec("L 확인창에서 취소하면 아무 변화 없음", exists("spam1"));
  op.on("dialog", (d) => d.accept());
  // 거절
  await act("spam1", "거절");
  rec("L 가입 신청 거절: 안내 + 계정 삭제", /거절/.test(await waitNotice(/거절/)) && !exists("spam1"));
  // 승인 → 로그인 가능, 일반 사용자는 관리자 화면 접근 불가
  await act("newbie1", "승인");
  rec("L 가입 신청 승인: 안내 + DB 활성·승인됨", /승인했습니다/.test(await waitNotice(/승인했습니다/)) && dbrow("newbie1").startsWith("user|t|t"), dbrow("newbie1"));
  const nctx = await newCtx(1280);
  const np = await nctx.newPage();
  await uiLogin(np, "newbie1", "Qw8!rT5zLp");
  await np.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("L 승인된 사용자는 로그인되고 일반 권한(회원 관리 링크 없음)", (await np.locator(".member-menu").innerText()).includes("신입사원님") && (await np.locator(".member-menu__link").count()) === 0 && decode(await cookieOf(nctx)).rl === "u");
  await np.goto("/admin/members", { waitUntil: "commit" });
  await np.waitForURL((u) => u.pathname === "/", { timeout: 15000 }).catch(() => {});
  rec("L 일반 사용자가 /admin/members를 열면 홈으로", new URL(np.url()).pathname === "/");
  await np.goto("/members", { waitUntil: "commit" });
  await np.waitForURL((u) => u.pathname === "/", { timeout: 15000 }).catch(() => {});
  rec("L 일반 사용자가 옛 /members를 열어도 홈으로", new URL(np.url()).pathname === "/");
  // 회원 추가
  await op.getByRole("button", { name: /^전체/ }).click();
  await op.fill("#admin-create-username", "added1");
  await op.fill("#admin-create-name", "추가회원");
  await op.fill("#admin-create-password", "weak");
  await op.click(".admin-create button[type=submit]");
  rec("L 회원 추가: 약한 비밀번호는 서버 문구로 거부", /흔하거나|8자 이상/.test(await waitNotice(/8자|흔하거나/)) && !exists("added1"));
  await op.fill("#admin-create-password", "Add!pass77x");
  await op.click(".admin-create button[type=submit]");
  rec("L 회원 추가: 성공 안내 + 활성·승인된 일반 회원", /추가했습니다/.test(await waitNotice(/추가했습니다/)) && dbrow("added1").startsWith("user|t|t|추가회원"), dbrow("added1"));
  await op.fill("#admin-create-username", "added1");
  await op.fill("#admin-create-name", "중복");
  await op.fill("#admin-create-password", "Add!pass77x");
  await op.click(".admin-create button[type=submit]");
  rec("L 회원 추가: 아이디 중복은 거부", /이미 사용 중/.test(await waitNotice(/이미 사용 중/)));
  const actx = await newCtx(1280);
  const ap = await actx.newPage();
  await uiLogin(ap, "added1", "Add!pass77x");
  await ap.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("L 추가한 회원은 바로 로그인 가능", new URL(ap.url()).pathname === "/");
  // 이름 수정
  await act("added1", "이름 수정");
  await op.fill("#admin-editor-input", "새이름");
  await op.click(".admin-editor button[type=submit]");
  rec("L 이름 수정: 안내 + DB 반영", /수정했습니다/.test(await waitNotice(/수정했습니다/)) && dbrow("added1").endsWith("새이름"));
  // 비밀번호 초기화: 기존 로그인 끊김, 새 비밀번호 사용
  const addedSid = decode(await cookieOf(actx)).sid;
  await act("added1", "비밀번호 초기화");
  await op.fill("#admin-editor-input", "123");
  await op.click(".admin-editor button[type=submit]");
  rec("L 비밀번호 초기화: 약한 비밀번호 거부(상태 불변)", /8자|흔하거나/.test(await waitNotice(/8자|흔하거나/)) && Number(psql(`SELECT count(*) FROM auth.user_sessions WHERE session_id='${addedSid}' AND revoked_at IS NULL`)) === 1);
  await op.fill("#admin-editor-input", "Reset!pass88y");
  await op.click(".admin-editor button[type=submit]");
  rec("L 비밀번호 초기화: 안내 + 그 회원의 기존 로그인 세션 취소", /초기화했습니다/.test(await waitNotice(/초기화했습니다/)) && Number(psql(`SELECT count(*) FROM auth.user_sessions WHERE session_id='${addedSid}' AND revoked_at IS NOT NULL`)) === 1);
  const rctx = await newCtx(1280);
  const rp = await rctx.newPage();
  await uiLogin(rp, "added1", "Add!pass77x");
  await rp.locator(".login-form__message").waitFor({ timeout: 15000 });
  rec("L 초기화 뒤 옛 비밀번호는 거부", /올바르지 않습니다/.test(await rp.locator(".login-form__message").innerText()));
  await rctx.close();
  await uiLogin(await (async () => { const c = await newCtx(1280); return c.newPage(); })(), "added1", "Reset!pass88y");
  // 권한 변경: lee를 관리자로 → 서버가 즉시 인정, 화면 표시는 5분 확인 때 갱신
  const lctx = await newCtx(1280);
  const lp = await lctx.newPage();
  await uiLogin(lp, "lee", PW2);
  await lp.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  const leePl = decode(await cookieOf(lctx));
  await act("lee", "관리자로");
  rec("L 권한 변경(일반→관리자): 안내 + DB 반영", /바꿨습니다/.test(await waitNotice(/바꿨습니다/)) && dbrow("lee").startsWith("admin|t|t"), dbrow("lee"));
  await setSessionCookie(lctx, staleOf(leePl));
  await lp.goto("/stocks/T00001");
  await lp.waitForURL((u) => u.pathname === "/stocks/T00001", { timeout: 20000 });
  rec("L 5분 확인 뒤 새 권한 반영: 쿠키 rl=a, 회원 관리 링크, 투자자 탭 표", decode(await cookieOf(lctx)).rl === "a" && (await lp.locator(".member-menu__link").count()) === 1);
  await lp.getByRole("tab", { name: "투자자" }).click();
  await lp.waitForSelector(".daily-table", { timeout: 15000 }).catch(() => {});
  rec("L 새 관리자(lee)는 투자자 탭에 값이 보인다", /4,321/.test(await lp.locator('[role="tabpanel"]:not([hidden])').innerText().catch(() => "")));
  // 강등: 쿠키는 아직 rl=a여도 서버(API)가 즉시 거부
  const leeAdminCookie = (await cookieOf(lctx)).value;
  await act("lee", "일반으로");
  rec("L 권한 변경(관리자→일반): DB 반영", /바꿨습니다/.test(await waitNotice(/바꿨습니다/)) && dbrow("lee").startsWith("user|t|t"));
  await setSessionCookie(lctx, leeAdminCookie);
  let r = await lctx.request.get(`${BASE}/api/v1/internal/admin/stocks/T00001/investor`);
  rec("L 강등된 사용자의 옛 쿠키(rl=a)로도 투자자 값 요청은 403(서버가 DB로 확인)", r.status() === 403, `${r.status()}`);
  r = await lctx.request.post(`${BASE}/admin/actions`, { data: { action: "delete", username: "park" }, headers: { origin } });
  rec("L 강등된 사용자의 옛 쿠키로 관리 작업 요청도 403, 아무것도 바뀌지 않음", r.status() === 403 && exists("park"), `${r.status()}`);
  await lctx.close();
  // 사용 중지 / 다시 사용
  const pctx = await newCtx(1280);
  const pp = await pctx.newPage();
  await uiLogin(pp, "park", PW2);
  await pp.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  const parkPl = decode(await cookieOf(pctx));
  await act("park", "사용 중지");
  rec("L 사용 중지: 안내 + DB 비활성 + 그 회원의 로그인 세션 취소", /사용 중지했습니다/.test(await waitNotice(/사용 중지했습니다/)) && dbrow("park").startsWith("user|f|t") && Number(psql(`SELECT count(*) FROM auth.user_sessions WHERE session_id='${parkPl.sid}' AND revoked_at IS NOT NULL`)) === 1);
  await setSessionCookie(pctx, staleOf(parkPl));
  rec("L 사용 중지된 회원의 쿠키는 서버 확인에서 거부(401)", (await pctx.request.get(`${BASE}/api/v1/market-summary`)).status() === 401);
  const dctx = await newCtx(1280);
  const dp = await dctx.newPage();
  await uiLogin(dp, "park", PW2);
  await dp.locator(".login-form__message").waitFor({ timeout: 15000 });
  rec("L 사용 중지된 회원이 로그인(비밀번호 맞음): '사용 중지' 안내", /사용이 중지/.test(await dp.locator(".login-form__message").innerText()));
  await act("park", "다시 사용");
  rec("L 다시 사용: DB 활성(이전 로그인은 되살아나지 않음)", /다시 사용할 수 있게/.test(await waitNotice(/다시 사용할 수 있게/)) && dbrow("park").startsWith("user|t|t"));
  await dp.fill("#login-password", PW2);
  await dp.click("button[type=submit]");
  await dp.waitForURL((u) => u.pathname === "/", { timeout: 20000 });
  rec("L 다시 사용 뒤 로그인 가능", new URL(dp.url()).pathname === "/");
  await pctx.close(); await dctx.close();
  // 모든 기기 로그아웃 / 삭제
  await act("park", "모든 기기 로그아웃");
  rec("L 회원의 모든 기기 로그아웃: 안내 + 그 회원 유효 세션 0", /로그아웃시켰/.test(await waitNotice(/로그아웃시켰/)) && Number(psql("SELECT count(*) FROM auth.user_sessions s JOIN auth.app_users u USING (user_id) WHERE u.username='park' AND s.revoked_at IS NULL AND s.expires_at > now()")) === 0);
  await act("added1", "삭제");
  rec("L 회원 삭제: 안내 + 계정·세션 삭제", /삭제했습니다/.test(await waitNotice(/삭제했습니다/)) && !exists("added1") && Number(psql("SELECT count(*) FROM auth.user_sessions WHERE user_id NOT IN (SELECT user_id FROM auth.app_users)")) === 0);
  // 본인 보호
  r = await octx.request.post(`${BASE}/admin/actions`, { data: { action: "disable", username: "kim" }, headers: { origin } });
  const rb = await r.json();
  rec("L 본인 비활성화 요청(우회 호출)은 서버가 거부(409)", r.status() === 409 && rb.code === "SELF_PROTECTED" && dbrow("kim").startsWith("admin|t|t"), `${r.status()} ${rb.code}`);
  r = await octx.request.post(`${BASE}/admin/actions`, { data: { action: "set_role", username: "kim", role: "user" }, headers: { origin } });
  rec("L 본인 강등 요청(우회 호출)도 409", r.status() === 409);
  // 관리 작업 경로 보호
  const anon = await fetch(`${BASE}/admin/actions`, { method: "POST", headers: { "Content-Type": "application/json", Origin: origin }, body: JSON.stringify({ action: "delete", username: "kim" }) });
  rec("L 로그인 없이 관리 작업: 401", anon.status === 401);
  r = await octx.request.post(`${BASE}/admin/actions`, { data: { action: "delete", username: "evil" }, headers: { origin: "https://evil.example.com" } });
  rec("L 다른 사이트에서 온 관리 작업: 403, 변화 없음", r.status() === 403 && exists("evil"));
  for (const bad of [{ action: "explode", username: "evil" }, { action: "delete" }, { username: "evil" }, { action: "set_role", username: "evil", role: "root" }, { action: "delete", username: "x".repeat(70) }]) {
    r = await octx.request.post(`${BASE}/admin/actions`, { data: bad, headers: { origin } });
    rec(`L 잘못된 관리 작업 요청 ${JSON.stringify(bad).slice(0, 40)}: 400`, r.status() === 400, `${r.status()}`);
  }
  r = await octx.request.post(`${BASE}/admin/actions`, { data: "not json", headers: { origin, "content-type": "application/json" } });
  rec("L 깨진 JSON 관리 작업: 400", r.status() === 400);
  // 관리 기록
  const audit = psql("SELECT count(*) FROM auth.admin_audit");
  const secrets = psql("SELECT count(*) FROM auth.admin_audit WHERE coalesce(detail,'') ~* '(pass|argon|\\$)' OR action ~* 'pass.*[0-9]'");
  rec("L 관리 작업 기록이 남는다(비밀번호·해시는 기록 안 됨)", Number(audit) >= 10 && Number(secrets) === 0, `기록 ${audit}건`);
  await op.screenshot({ path: `${OUT}/admin-members-after-1280.png` });
  for (const x of [octx, nctx, actx]) await x.close();
}

// ───────────────────────── M. 운영 설정 오류 재현: 웹과 API의 내부 토큰이 다를 때(운영 첫 적용에서 실제 발생)
if (should("M")) {
  // 정상 웹: 연결 점검 주소가 정상을 알린다
  let r = await fetch(`${BASE}/auth/status`);
  let body = await r.json();
  rec("M 정상 설정: /auth/status → 200 {ok, web:ok, api:ok}, 값·비밀 없음", r.status === 200 && body.ok === true && body.web === "ok" && body.api === "ok" && Object.keys(body).sort().join(",") === "api,ok,web" && !JSON.stringify(body).includes(TOKEN), JSON.stringify(body));
  // 토큰이 다른 웹: 점검 주소가 정확히 원인을 알리고, 로그인 화면은 '비밀번호 오류'가 아니라 연결 오류를 보여 준다
  r = await fetch(`${BAD_BASE}/auth/status`);
  body = await r.json();
  rec("M 내부 토큰 불일치: /auth/status → 503 api=token_mismatch", r.status === 503 && body.ok === false && body.api === "token_mismatch", JSON.stringify(body));
  const auditCount = () => Number(psql("SELECT count(*) FROM auth.login_audit"));
  const auditBefore = auditCount();
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 }, baseURL: BAD_BASE });
  const p = await ctx.newPage();
  await p.goto("/login");
  await p.fill("#login-username", "kim");
  await p.fill("#login-password", PW);
  await p.click("button[type=submit]");
  await p.locator(".login-form__message").waitFor({ timeout: 20000 });
  const msg = await p.locator(".login-form__message").innerText();
  rec("M 내부 토큰 불일치 + 올바른 비밀번호: '비밀번호 오류'가 아니라 '서버에 연결하지 못했습니다'로 표시", /연결하지 못했습니다/.test(msg) && !/올바르지 않습니다/.test(msg), msg.slice(0, 60));
  rec("M 내부 토큰 불일치: 로그인 쿠키가 만들어지지 않는다", (await ctx.cookies()).filter((c) => c.name === COOKIE).length === 0);
  rec("M 내부 토큰 불일치: DB에 로그인 기록이 늘지 않는다(API 확인 단계에 도달하지 못함 — 운영 진단 단서)", auditCount() === auditBefore, `기록 ${auditBefore}→${auditCount()}`);
  await ctx.close();
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
