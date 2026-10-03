// NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true 로 빌드한 프론트 + LOCAL_INTRADAY_ENABLED API + 모의 KIS 전제
import { BASE, SHOTS, OUT, launch, runAxe, measureFn, sleep } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (name, pass, note = "") => { res.push(pass); console.log(`${pass ? "PASS" : "FAIL"}  ${name}  ${note}`); };
for (const [w, h] of [[320, 568], [360, 800], [390, 844], [414, 896], [768, 1024], [1280, 800]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message));
  await p.goto(BASE + "/stocks/T00001");
  await p.waitForSelector(".stock-chart__svg");
  const tabs = await p.$$eval('[role="tab"]', (e) => e.map((x) => x.textContent));
  rec(`[${w}] 탭 구성`, tabs.includes("호가") && tabs.includes("체결"), tabs.join("|"));
  const tb = await p.evaluate(() => {
    const t = document.querySelector(".stock-chart__toolbar");
    const kids = [...t.querySelectorAll("button")].filter((e) => e.getBoundingClientRect().width > 0);
    const tops = kids.map((e) => { const r = e.getBoundingClientRect(); return Math.round((r.top + r.bottom) / 2 / 20); });
    return { h: Math.round(t.getBoundingClientRect().height), rows: new Set(tops).size, n: kids.length };
  });
  rec(`[${w}] 도구 줄 한 줄 유지`, tb.rows === 1, `높이 ${tb.h}px 줄수 ${tb.rows} 버튼 ${tb.n}`);
  // 분 메뉴
  await p.getByRole("button", { name: "분봉 간격 선택" }).click();
  const items = await p.$$eval('[role="menuitem"]', (e) => e.map((x) => x.textContent));
  const menuBox = await p.evaluate(() => { const m = document.querySelector(".chart-seg__menu").getBoundingClientRect(); return { l: m.left, r: m.right, vw: innerWidth, h: m.height, sh: [...document.querySelectorAll('.chart-seg__menu button')].map((b) => b.getBoundingClientRect().height) }; });
  rec(`[${w}] 분 메뉴 항목·화면 안`, items.length > 0 && menuBox.l >= 0 && menuBox.r <= menuBox.vw, `${items.length}개 l=${menuBox.l.toFixed(0)} r=${menuBox.r.toFixed(0)} 항목높이=${Math.min(...menuBox.sh)}`);
  if (w === 360) await p.screenshot({ path: `${OUT}/local-menu-360.png` });
  await p.keyboard.press("Escape");
  rec(`[${w}] 분 메뉴 Esc 닫힘`, (await p.locator(".chart-seg__menu").count()) === 0);
  await p.getByRole("button", { name: "틱 묶음 선택" }).click();
  await p.mouse.click(w / 2, 40);
  rec(`[${w}] 틱 메뉴 바깥 클릭 닫힘`, (await p.locator(".chart-seg__menu").count()) === 0);
  await p.getByRole("button", { name: "분봉 간격 선택" }).click();
  await p.getByRole("menuitem", { name: "5분", exact: true }).click();
  await p.waitForFunction(() => /\d\d:\d\d/.test(document.querySelector(".stock-chart__svg")?.textContent || ""), null, { timeout: 20000 });
  const tbAfter = await p.evaluate(() => { const t = document.querySelector(".stock-chart__toolbar"); return { h: Math.round(t.getBoundingClientRect().height), seg: [...document.querySelectorAll(".chart-seg__btn")].map((x) => x.textContent) }; });
  rec(`[${w}] 5분 선택 후 도구 줄 높이 유지`, tbAfter.h === tb.h, `${tb.h} → ${tbAfter.h} ${tbAfter.seg.join(",")}`);
  const axe1 = await runAxe(p);
  // 호가
  await p.getByRole("tab", { name: "호가" }).click();
  await p.waitForSelector(".orderbook__table tbody tr");
  const ob = await p.evaluate(() => {
    const t = document.querySelector(".orderbook__table");
    const cs = getComputedStyle(t.querySelector("td"));
    const wrap = t.parentElement;
    return { rows: t.querySelectorAll("tbody tr").length, fs: cs.fontSize, tw: Math.round(t.getBoundingClientRect().width), vw: innerWidth, sw: document.documentElement.scrollWidth, wrapScroll: wrap.scrollWidth > wrap.clientWidth + 1, th: [...t.querySelectorAll("th")].map((x) => x.textContent.trim()).join("/"), minRowH: Math.min(...[...t.querySelectorAll("tbody tr")].map((r) => Math.round(r.getBoundingClientRect().height))) };
  });
  rec(`[${w}] 호가 표 가독성`, ob.rows >= 10 && parseFloat(ob.fs) >= 12 && ob.sw <= ob.vw && !ob.wrapScroll, JSON.stringify(ob));
  if ([360, 1280].includes(w)) await p.screenshot({ path: `${OUT}/local-book-${w}.png` });
  const axe2 = await runAxe(p);
  // 체결
  await p.getByRole("tab", { name: "체결" }).click();
  await p.waitForSelector(".daily-table tbody tr");
  const m = await p.evaluate(measureFn);
  rec(`[${w}] 체결 표 로드·가로 넘침 없음`, !m.overflow, `rows ${await p.$$eval(".daily-table tbody tr", (r) => r.length)} sw=${m.scrollWidth}`);
  if (w === 360) await p.screenshot({ path: `${OUT}/local-ticks-360.png` });
  const axe3 = await runAxe(p);
  const all = [...axe1, ...axe2, ...axe3].map((v) => `${v.id}:${v.nodes.length}`);
  rec(`[${w}] 로컬 모드 axe`, all.length === 0, all.join(",") + " " + [...axe1, ...axe2, ...axe3].flatMap((v) => v.nodes.slice(0, 3).map((n) => n.target.slice(0, 40) + " " + n.summary.slice(0, 90))).slice(0, 4).join(" || "));
  rec(`[${w}] 페이지 오류 없음`, errs.length === 0, errs.join("|"));
  await p.close();
}
await b.close();
console.log(`합계 PASS ${res.filter(Boolean).length} FAIL ${res.filter((x) => !x).length}`);
