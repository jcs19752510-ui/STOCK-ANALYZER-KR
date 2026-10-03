import { createRequire } from "node:module";
const require = createRequire((process.env.QA_PW_DIR ?? "/tmp/claude-0/pw") + "/package.json");
export const { chromium, devices } = require("playwright-core");
export const AXE_PATH = require.resolve("axe-core");
export const BASE = process.env.QA_BASE ?? "http://localhost:4202";
export const API = process.env.QA_API ?? "http://127.0.0.1:4201";
export const OUT = process.env.QA_OUT ?? "/tmp/claude-0/qa-out";
export const SHOTS = process.env.QA_SHOTS ?? "/home/user/STOCK-ANALYZER-KR/docs/qa/2026-10-02";
export const launch = () =>
  chromium.launch({
    executablePath: process.env.CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    args: ["--no-sandbox"],
  });
export const VIEWPORTS = [
  [320, 568], [360, 800], [375, 667], [390, 844], [414, 896], [768, 1024], [1024, 768], [1280, 800],
];
export async function runAxe(page) {
  await page.addScriptTag({ path: AXE_PATH });
  return page.evaluate(async () => {
    const r = await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
    return r.violations.map((v) => ({
      id: v.id, impact: v.impact, help: v.help,
      nodes: v.nodes.map((n) => ({ target: n.target.join(" "), html: n.html.slice(0, 160), summary: (n.any[0]?.message || n.all[0]?.message || n.none[0]?.message || "").slice(0, 200), data: n.any[0]?.data ?? null })),
    }));
  });
}
// 페이지 안에서 실행: 가로 넘침·잘림·터치 대상·겹침
export const measureFn = () => {
  const vw = window.innerWidth;
  const sel = 'a[href], button, input, select, textarea, summary, [role="tab"], [role="menuitem"], [tabindex="0"]';
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === "hidden" || cs.display === "none") return null;
    if (el.closest(".sr-only") || el.classList.contains("sr-only")) return null;
    return r;
  };
  const name = (el) => {
    const t = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 30);
    return `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/)[0] : ""}[${t}]`;
  };
  const inScroller = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if ((o === "auto" || o === "scroll" || o === "hidden") && p.scrollWidth > p.clientWidth + 1) return true;
      if (o === "auto" || o === "scroll") return true;
    }
    return false;
  };
  const els = [...document.querySelectorAll(sel)].map((el) => ({ el, r: vis(el) })).filter((x) => x.r);
  const small = [];
  for (const { el, r: r0 } of els) {
    // 체크박스·라디오는 감싸는 label 이 실제 터치 대상
    const lab = (el.type === "checkbox" || el.type === "radio") && (el.closest("label") || (el.id && document.querySelector(`label[for="${el.id}"]`)));
    const r = lab ? lab.getBoundingClientRect() : r0;
    // 본문 문장 안의 인라인 링크는 WCAG 2.5.8 예외이므로 구분 표시
    const inline = el.tagName === "A" && getComputedStyle(el).display === "inline" && el.closest("p, li");
    if (r.width < 44 - 0.5 || r.height < 44 - 0.5) small.push({ n: name(el), w: +r.width.toFixed(1), h: +r.height.toFixed(1), inline: !!inline, lt24: r.width < 24 || r.height < 24 });
  }
  const clipped = [];
  for (const el of document.body.querySelectorAll("*")) {
    const r = vis(el);
    if (!r) continue;
    if (el.closest("svg") && el.tagName.toLowerCase() !== "svg") continue;
    if (r.right > vw + 1 || r.left < -1) clipped.push({ n: name(el), left: +r.left.toFixed(1), right: +r.right.toFixed(1), inScroller: inScroller(el) });
  }
  const overlaps = [];
  for (let i = 0; i < els.length; i++)
    for (let j = i + 1; j < els.length; j++) {
      const a = els[i], b = els[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      const h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (w > 2 && h > 2) overlaps.push({ a: name(a.el), b: name(b.el), w: +w.toFixed(1), h: +h.toFixed(1) });
    }
  return {
    vw,
    scrollWidth: document.documentElement.scrollWidth,
    overflow: document.documentElement.scrollWidth > vw,
    interactive: els.length,
    small, clipped: clipped.slice(0, 30), overlaps: overlaps.slice(0, 30),
  };
};
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
