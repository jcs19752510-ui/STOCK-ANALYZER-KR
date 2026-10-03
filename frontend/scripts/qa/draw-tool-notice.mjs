// 그리기 도구(✎) 버튼: 눌렀을 때 무반응이 아니라 사유 안내가 보이고, 다시 누르면 닫히며, 접근성 속성이 맞는지 점검.
import { BASE, launch, runAxe } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
for (const w of [320, 360, 1280]) {
  const p = await (await b.newContext({ viewport: { width: w, height: 800 } })).newPage();
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
  await p.waitForSelector(".stock-chart__svg");
  const btn = p.getByRole("button", { name: "그리기 도구는 제공하지 않습니다" });
  rec(`[${w}] 버튼이 눌릴 수 있음(aria-disabled만, disabled 속성 없음)`, (await btn.getAttribute("aria-disabled")) === "true" && (await btn.evaluate((e) => !e.hasAttribute("disabled"))));
  await btn.click({ force: true }); // aria-disabled 는 Playwright 가 비활성으로 보지만 실제 사용자는 누를 수 있다
  const note = p.locator("#chart-draw-notice");
  rec(`[${w}] 클릭 시 사유 안내 표시`, (await note.count()) === 1 && /그리기 도구.*제공하지 않습니다/.test(await note.textContent()), (await note.textContent())?.slice(0, 40));
  rec(`[${w}] aria-expanded=true`, (await btn.getAttribute("aria-expanded")) === "true");
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  rec(`[${w}] 가로 넘침 없음`, !overflow);
  if (w === 360) { const v = await runAxe(p); rec(`[${w}] axe 위반 없음`, v.length === 0, v.map((x) => x.id).join(",")); }
  await btn.click({ force: true });
  rec(`[${w}] 다시 누르면 닫힘`, (await p.locator("#chart-draw-notice").count()) === 0);
  await p.close();
}
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
