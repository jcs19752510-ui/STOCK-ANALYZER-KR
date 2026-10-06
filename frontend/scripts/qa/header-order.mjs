// 상단 영역 순서 시험(DEC-082): ① 메뉴 줄 → ② 회원 메뉴 → ③ 제목, 스크롤 고정, 키보드 순서, axe. 612건.
// 실행: NEXT_PUBLIC_AUTH_ENABLED=true 로 개발 서버(4202)를 띄운 뒤 node frontend/scripts/qa/header-order.mjs (playwright-core·axe-core는 QA_PW_DIR=/tmp/claude-0/pw 에 설치, scripts/qa/README.md 참고).
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire("/tmp/claude-0/pw/package.json");
const { chromium } = require("playwright-core"); const axeP = require.resolve("axe-core");
const OUT = "/home/user/STOCK-ANALYZER-KR/docs/qa/2026-10-06"; const BASE = "http://localhost:4202";
const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-sandbox"] });
const res = []; const rec = (n, ok, d = "") => { res.push({ name: n, ok, detail: d }); if (!ok) console.log("FAIL " + n + " — " + d); };
const routes = [["/", "홈"], ["/stocks", "종목 검색"], ["/screener", "조건 스크리닝"]];
for (const [w, h] of [[320, 568], [360, 800], [412, 968], [768, 1024], [1024, 768], [1280, 800]]) {
  for (const role of ["admin", "user", "anon"]) {
    const ctx = await b.newContext({ viewport: { width: w, height: h } }); const p = await ctx.newPage();
    await p.route("**/auth/me", (r) => role === "anon" ? r.fulfill({ status: 401, contentType: "application/json", body: "{}" }) : r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ display_name: "정찬욱", role }) }));
    for (const [path, expected] of routes) {
      const tag = `${w}px ${role} ${path}`;
      await p.goto(BASE + path, { waitUntil: "domcontentloaded", timeout: 90000 });
      await p.waitForSelector(".global-nav__link", { timeout: 60000 });
      if (role !== "anon") await p.waitForSelector(".member-menu", { timeout: 60000 });
      await p.evaluate(() => { const s = document.createElement("div"); s.style.height = "3000px"; document.body.appendChild(s); });
      await p.waitForTimeout(400);
      const m = await p.evaluate(() => {
        const g = (e) => e.getBoundingClientRect(); const q = (s) => document.querySelector(s);
        const nav = q(".global-nav"), mm = q(".member-menu"), wm = q(".site-header__wordmark"), hd = q(".site-header"), bn = q(".disclaimer-banner"), mn = q("main");
        const rel = (a, c) => !!(a.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING);
        const links = [...nav.querySelectorAll(".global-nav__link")].map((a) => ({ t: a.textContent.trim(), cur: a.getAttribute("aria-current"), h: g(a).height, w: g(a).width, r: g(a).right, l: g(a).left }));
        return { bn: g(bn), nav: g(nav), mm: mm ? g(mm) : null, wm: g(wm), hd: g(hd), main: g(mn), domOK: rel(nav, hd) && (!mm || (rel(nav, mm) && rel(mm, wm))), sw: document.documentElement.scrollWidth, iw: innerWidth, ih: innerHeight, links, hdBorder: getComputedStyle(hd).borderBottomWidth, pos: getComputedStyle(nav).position, bh: getComputedStyle(document.documentElement).getPropertyValue("--banner-height") };
      });
      const stacked = w < 1024; const act = m.links.filter((l) => l.cur === "page");
      rec(`[${tag}] ① 메뉴 줄이 배너 바로 아래 맨 위`, Math.abs(m.nav.top - m.bn.bottom) <= 1.5, `banner 끝 ${Math.round(m.bn.bottom)} / nav 시작 ${Math.round(m.nav.top)}`);
      rec(`[${tag}] 문서 순서: 메뉴 → 회원 메뉴 → 제목`, m.domOK);
      if (stacked) {
        rec(`[${tag}] ① 메뉴 줄 → ③ 제목 순서`, m.nav.bottom <= m.hd.top + 1 && m.nav.bottom <= m.wm.top + 1, `nav 끝 ${Math.round(m.nav.bottom)} / 제목 시작 ${Math.round(m.wm.top)}`);
        if (m.mm) rec(`[${tag}] ① 메뉴 → ② 회원 메뉴 → ③ 제목 (위→아래)`, m.nav.bottom <= m.mm.top + 1 && m.mm.bottom <= m.wm.top + 1, `nav ${Math.round(m.nav.bottom)} 회원 ${Math.round(m.mm.top)}~${Math.round(m.mm.bottom)} 제목 ${Math.round(m.wm.top)}`);
      } else {
        rec(`[${tag}] ① 메뉴 줄이 제목·회원 메뉴 줄보다 위`, m.nav.bottom <= m.hd.top + 1);
        if (m.mm) rec(`[${tag}] 한 줄: 제목(왼쪽) → 회원 메뉴(오른쪽), 겹침 없음`, m.wm.right <= m.mm.left + 1 && Math.abs((m.wm.top + m.wm.bottom) / 2 - (m.mm.top + m.mm.bottom) / 2) < 30, `제목 끝 ${Math.round(m.wm.right)} / 회원 시작 ${Math.round(m.mm.left)}`);
      }
      rec(`[${tag}] 본문은 머리글 아래`, m.hd.bottom <= m.main.top + 1);
      rec(`[${tag}] 머리글 아래 구분선`, parseFloat(m.hdBorder) >= 1, m.hdBorder);
      rec(`[${tag}] 선택 표시 1개/대상`, act.length === 1 && act[0].t === expected, act.map((a) => a.t).join("|"));
      rec(`[${tag}] 가로 넘침·이탈 없음`, m.sw <= m.iw && m.links.every((l) => l.r <= m.iw + 0.5 && l.l >= -0.5) && m.wm.right <= m.iw + 0.5 && (!m.mm || m.mm.right <= m.iw + 0.5), `${m.sw}/${m.iw}`);
      rec(`[${tag}] 제목 터치 ≥44px, 메뉴 글자 한 줄`, m.wm.height >= 43.5 && m.links.every((l) => l.h <= 50 && l.h >= 43.5 && l.w >= 43.5));
      rec(`[${tag}] 배너 높이 변수`, Math.abs(parseFloat(m.bh) - m.bn.height) < 1.5, `${m.bh}`);
      // 스크롤 후에도 메뉴 줄이 배너 아래에 따라오는지, 제목·회원 메뉴는 올라가는지
      await p.evaluate(() => scrollTo(0, 1500)); await p.waitForTimeout(250);
      const sc = await p.evaluate(() => { const g = (s) => document.querySelector(s).getBoundingClientRect(); const n = g(".global-nav"), bnr = g(".disclaimer-banner"); const mid = document.elementFromPoint(innerWidth / 2, n.top + n.height / 2); return { gap: n.top - bnr.bottom, hit: !!mid?.closest(".global-nav"), wmGone: g(".site-header__wordmark").bottom < n.bottom, sw: document.documentElement.scrollWidth, iw: innerWidth }; });
      rec(`[${tag}] 스크롤 후 메뉴 줄만 배너 아래에 고정·눌림 가능`, Math.abs(sc.gap) <= 1.5 && sc.hit && sc.wmGone && sc.sw <= sc.iw, JSON.stringify(sc));
      if (path === "/") {
        await p.evaluate(() => scrollTo(0, 0));
        // 키보드 Tab 순서(문서 순서): 메뉴 4개 → (회원 메뉴 버튼) → 제목
        await p.evaluate(() => document.body.focus()); const seq = [];
        for (let i = 0; i < 12; i++) { await p.keyboard.press("Tab"); const t = await p.evaluate(() => { const e = document.activeElement; return e && e !== document.body ? (e.getAttribute("aria-label") || e.textContent.trim()).slice(0, 14) : ""; }); seq.push(t); }
        const idx = (k) => seq.findIndex((x) => x.includes(k));
        const expectOrder = idx("홈") >= 0 && idx("홈") < idx("조건 스크리닝") && idx("조건 스크리닝") < idx("종목 검색") && idx("종목 검색") < idx("관심종목") && (role === "anon" ? idx("관심종목") < idx("서비스") || true : idx("관심종목") < idx("로그아웃"));
        rec(`[${tag}] 키보드 Tab 순서(메뉴 → 회원 메뉴)`, expectOrder, seq.filter(Boolean).join(" > "));
        await p.evaluate(() => { document.activeElement?.blur(); scrollTo(0, 0); });
        await p.addScriptTag({ path: axeP });
        const v = await p.evaluate(async () => (await axe.run(".global-nav, .site-header, .disclaimer-banner", { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } })).violations.map((x) => x.id));
        rec(`[${tag}] axe 위반 0`, v.length === 0, v.join(","));
        if ([320, 412, 768, 1280].includes(w) && (role !== "user")) await p.screenshot({ path: `${OUT}/order-${w}-${role}.png`, clip: { x: 0, y: 0, width: w, height: Math.min(h, 440) } });
      }
    }
    await ctx.close();
  }
}
await b.close(); const f = res.filter((r) => !r.ok); console.log(`합계 ${res.length}건, 통과 ${res.length - f.length}, 실패 ${f.length}`);
fs.writeFileSync(`${OUT}/header-order-test-raw.json`, JSON.stringify(res, null, 1)); process.exit(f.length ? 1 : 0);
