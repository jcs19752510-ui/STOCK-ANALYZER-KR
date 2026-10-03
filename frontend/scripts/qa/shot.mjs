// 사용: node shot.mjs <path> <width> <height> <out.png> [tab] [fullPage]
import { BASE, launch, sleep } from "./common.mjs";
const [path, w, h, out, tab, full] = process.argv.slice(2);
const b = await launch();
const p = await b.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1, colorScheme: process.env.SCHEME ?? "light" });
await p.goto(BASE + path);
await p.waitForSelector(".stock-chart__svg, main", { timeout: 20000 });
if (tab) await p.getByRole("tab", { name: tab }).click();
await sleep(500);
await p.screenshot({ path: out, fullPage: full === "1" });
await b.close();
