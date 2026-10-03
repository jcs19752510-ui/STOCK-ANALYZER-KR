// 레이아웃 겹침·넘침 점검: 여러 화면 × 여러 폭(브라우저 확대 125%·150% 상당 폭 포함)에서
// (1) 페이지 가로 스크롤 없음 (2) 자식 요소가 부모 영역 밖으로 삐져나가 옆 영역을 덮는 곳 없음.
// 가로 스크롤 컨테이너(표 등)·SVG·화면 밖 고정 패널은 제외한다. 실행: QA_PW_DIR=… QA_BASE=… node scripts/qa/layout-overflow.mjs
import { BASE, launch } from "./common.mjs";
const WIDTHS = [320, 360, 390, 768, 910, 1024, 1093, 1280, 1366, 1600];
const PAGES = [
  { path: "/", name: "홈" },
  { path: "/screener", name: "조건 스크리닝", submit: true },
  { path: "/screener/pattern", name: "패턴 스크리닝", submit: true },
  { path: "/stocks", name: "종목 검색" },
  { path: "/stocks/T00001", name: "종목 상세" },
  { path: "/watchlist", name: "관심종목" },
  { path: "/about", name: "이용안내" },
];
const b = await launch();
let fail = 0;
const detect = () => {
  const out = [];
  const main = document.querySelector("main") ?? document.body;
  const skip = (e) => {
    for (let a = e; a && a !== document.body; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (a.tagName === "svg" || a.closest("svg")) return true;
      if (cs.position === "fixed") return true;
      if (a !== e && /(auto|scroll)/.test(cs.overflowX)) return true;
      if (cs.visibility === "hidden" || cs.display === "none") return true;
    }
    return false;
  };
  for (const e of main.querySelectorAll("*")) {
    const r = e.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || skip(e)) continue;
    const p = e.parentElement;
    if (!p || p === main) continue;
    const pr = p.getBoundingClientRect();
    if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(p).overflowX)) continue;
    if (r.right > pr.right + 1.5 && pr.width > 0) {
      out.push(`${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]} 오른쪽 ${Math.round(r.right - pr.right)}px 넘침(부모 ${String(p.className).split(" ")[0]})`);
    }
  }
  return out.slice(0, 5);
};
for (const pg of PAGES) {
  const issues = [];
  for (const w of WIDTHS) {
    const ctx = await b.newContext({ viewport: { width: w, height: 800 } });
    const p = await ctx.newPage();
    await p.goto(BASE + pg.path, { waitUntil: "networkidle" });
    if (pg.submit && w >= 1024) {
      const btn = p.locator('form button[type="submit"]').first();
      if (await btn.count()) { await btn.click(); await p.waitForTimeout(1500); }
    }
    const sw = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const found = await p.evaluate(detect);
    if (sw > 0) issues.push(`[${w}] 페이지 가로 스크롤 +${sw}px`);
    for (const f of found) issues.push(`[${w}] ${f}`);
    await ctx.close();
  }
  console.log(`${issues.length === 0 ? "PASS" : "FAIL"}  ${pg.name}  ${issues.slice(0, 4).join(" | ")}`);
  if (issues.length) fail++;
}
await b.close();
process.exit(fail === 0 ? 0 : 1);
