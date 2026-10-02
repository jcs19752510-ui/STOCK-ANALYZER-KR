import { writeFileSync, mkdirSync } from "node:fs";
import { BASE, OUT, VIEWPORTS, launch, runAxe, measureFn, sleep } from "./common.mjs";
mkdirSync(OUT, { recursive: true });
const PAGES = [
  { id: "home", path: "/" },
  { id: "screener", path: "/screener" },
  { id: "pattern", path: "/screener/pattern" },
  { id: "stocks", path: "/stocks" },
  { id: "stocks-search", path: "/stocks", act: async (p) => { await p.fill('input[type="search"], input[name="q"], input', "픽스처"); await p.keyboard.press("Enter"); await p.waitForSelector("a[href^='/stocks/T']", { timeout: 15000 }); } },
  { id: "detail-chart", path: "/stocks/T00001", wait: ".stock-chart__svg" },
  { id: "detail-daily", path: "/stocks/T00001", wait: ".stock-chart__svg", tab: "일자별 시세", waitAfter: ".daily-table tbody tr" },
  { id: "detail-earnings", path: "/stocks/T00001", wait: ".stock-chart__svg", tab: "실적", waitAfter: ".daily-table, .stock-tabs__pending" },
  { id: "detail-investor", path: "/stocks/T00001", wait: ".stock-chart__svg", tab: "투자자", waitAfter: ".stock-tabs__pending" },
  { id: "detail-check", path: "/stocks/T00001", wait: ".stock-chart__svg", tab: "조건 체크", waitAfter: ".pattern-check, .stock-tabs__pending" },
  { id: "detail-summary", path: "/stocks/T00001", wait: ".stock-chart__svg", act: async (p) => { await p.getByRole("button", { name: /차트 요약/ }).click(); await p.waitForSelector(".chart-summary li"); } },
  { id: "detail-settings", path: "/stocks/T00001", wait: ".stock-chart__svg", act: async (p) => { await p.getByRole("button", { name: /설정/ }).first().click(); await p.waitForSelector(".chart-settings"); } },
  { id: "detail-404", path: "/stocks/ZZZZZZ" },
];
const only = process.env.ONLY?.split(",");
const b = await launch();
const results = [];
for (const [w, h] of VIEWPORTS) {
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  for (const pg of PAGES) {
    if (only && !only.includes(pg.id)) continue;
    const p = await ctx.newPage();
    try {
      await p.goto(BASE + pg.path, { waitUntil: "load" });
      if (pg.wait) await p.waitForSelector(pg.wait, { timeout: 20000 });
      if (pg.tab) { await p.getByRole("tab", { name: pg.tab }).click(); if (pg.waitAfter) await p.waitForSelector(pg.waitAfter, { timeout: 15000 }); }
      if (pg.act) await pg.act(p);
      await sleep(400);
      const m = await p.evaluate(measureFn);
      const axe = await runAxe(p);
      results.push({ page: pg.id, w, h, ...m, axe });
      if (process.env.SHOTS_ALL) await p.screenshot({ path: `${OUT}/${pg.id}-${w}.png` });
    } catch (e) {
      results.push({ page: pg.id, w, h, error: String(e).slice(0, 300) });
    }
    await p.close();
  }
  await ctx.close();
}
await b.close();
writeFileSync(`${OUT}/matrix.json`, JSON.stringify(results, null, 1));
for (const r of results) {
  if (r.error) { console.log(r.page, r.w, "ERROR", r.error); continue; }
  const small = r.small.filter((s) => !s.inline);
  console.log(`${r.page.padEnd(15)} ${String(r.w).padStart(4)} overflow=${r.overflow ? "Y" : "n"} sw=${r.scrollWidth} small44=${small.length} (<24:${small.filter((s) => s.lt24).length}) clipped=${r.clipped.filter((c) => !c.inScroller).length} overlap=${r.overlaps.length} axe=${r.axe.length}(${r.axe.reduce((a, v) => a + v.nodes.length, 0)})`);
}
