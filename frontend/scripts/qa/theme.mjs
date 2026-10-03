import { BASE, OUT, launch, runAxe, measureFn, sleep } from "./common.mjs";
import { mkdirSync } from "node:fs";
mkdirSync(OUT, { recursive: true });
const b = await launch();
const log = (...a) => console.log(...a);
const PAGES = ["/", "/screener", "/stocks", "/stocks/T00001"];
async function open(ctx, path) {
  const p = await ctx.newPage();
  await p.goto(BASE + path);
  await p.waitForSelector("main");
  if (path.includes("T00001")) await p.waitForSelector(".stock-chart__svg");
  await sleep(300);
  return p;
}
// 1) 다크 모드
{
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, colorScheme: "dark" });
  for (const path of PAGES) {
    const p = await open(ctx, path);
    const info = await p.evaluate(() => ({ bg: getComputedStyle(document.body).backgroundColor, fg: getComputedStyle(document.body).color, scheme: getComputedStyle(document.documentElement).colorScheme, mq: matchMedia("(prefers-color-scheme: dark)").matches }));
    const axe = await runAxe(p);
    log(`[dark] ${path} prefers-dark=${info.mq} body bg=${info.bg} fg=${info.fg} color-scheme=${info.scheme} axe=${axe.map((v) => v.id + ":" + v.nodes.length).join(",")}`);
    await p.screenshot({ path: `${OUT}/dark-${path.replace(/\W+/g, "_")}.png` });
    await p.close();
  }
  await ctx.close();
}
// 2) forced colors
{
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, forcedColors: "active" });
  for (const path of PAGES) {
    const p = await open(ctx, path);
    const fc = await p.evaluate(() => matchMedia("(forced-colors: active)").matches);
    // 시각 상태 표시(선택된 탭·버튼)가 forced-colors에서도 구분되는지: 선택 탭과 비선택 탭의 색/테두리
    const st = await p.evaluate(() => {
      const f = (s) => { const e = document.querySelector(s); if (!e) return null; const c = getComputedStyle(e); return { color: c.color, bg: c.backgroundColor, bb: c.borderBottomColor + " " + c.borderBottomWidth, outline: c.outlineStyle }; };
      return { selTab: f('[role="tab"][aria-selected="true"]'), tab: f('[role="tab"][aria-selected="false"]'), segOn: f('.chart-seg__btn[aria-pressed="true"]'), segOff: f('.chart-seg__btn[aria-pressed="false"]') };
    });
    log(`[forced] ${path} active=${fc} ${JSON.stringify(st)}`);
    await p.screenshot({ path: `${OUT}/forced-${path.replace(/\W+/g, "_")}.png` });
    await p.close();
  }
  await ctx.close();
}
// 3) 줌 200%/400%
for (const [w, h, label] of [[640, 400, "1280px@200%"], [320, 256, "1280px@400%(WCAG 1.4.10 리플로)"], [512, 400, "1024px@200%"], [195, 422, "390px@200%"]]) {
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
  for (const path of ["/", "/screener", "/screener/pattern", "/stocks/T00001"]) {
    const p = await open(ctx, path);
    const m = await p.evaluate(measureFn);
    log(`[zoom ${label}] ${path} sw=${m.scrollWidth} vw=${m.vw} overflow=${m.overflow} clippedNotInScroller=${m.clipped.filter((c) => !c.inScroller).map((c) => c.n + "@" + c.right).slice(0, 4).join(";")}`);
    if (path.includes("T00001") && w === 640) await p.screenshot({ path: `${OUT}/zoom200-detail.png` });
    await p.close();
  }
  await ctx.close();
}
// 4) reduced motion
for (const rm of ["reduce", "no-preference"]) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: rm });
  const p = await ctx.newPage();
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "domcontentloaded" });
  await sleep(100);
  const anims = await p.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").map((a) => a.animationName || a.transitionProperty || a.constructor.name));
  await p.waitForSelector(".stock-chart__svg");
  const after = await p.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length);
  log(`[motion ${rm}] matchMedia=${await p.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)} 로딩 중 실행 애니메이션=${JSON.stringify(anims)} 로딩 후=${after}`);
  await ctx.close();
}
await b.close();
