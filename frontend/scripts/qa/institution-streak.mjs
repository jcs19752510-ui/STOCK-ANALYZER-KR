// DEC-061 점검: ⑪ 기관 연속 순매수(⑥ 대안)와 ⑦ 예외를 실제 화면(조건 체크 탭, 개인 로컬 모드)에서 확인.
// 수급 API 응답을 브라우저에서 가로채 사례별 값을 주입한다(증권사 화면의 리노공업 수치 포함).
// 전제: next dev(NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true) + API(4201) 기동, 시드 T00001.
import { BASE, OUT, launch, runAxe } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const iso = (i) => `2026-${i < 20 ? "10" : "09"}-${String(((29 - i + 30) % 30) + 1).padStart(2, "0")}`;
const mkRows = (triples) => triples.map(([p, f, o], i) => ({
  date: iso(i), personal_quantity: p, foreign_quantity: f, institution_quantity: o,
  personal_amount_million: null, foreign_amount_million: null, institution_amount_million: null,
}));
const fill = (n, p, f, o) => Array.from({ length: n }, () => [p, f, o]);
const CASES = {
  // 증권사 화면(리노공업 058470) 최근 5거래일 값 + 이전 15일은 가정값(개인 +, 외국인 -, 기관 +)
  reino: [[-29687, -745781, 725502], [-268372, -191981, 439558], [102379, -159171, 59373], [5706, -127995, 118067], [172275, -116155, -57139], ...fill(15, 40000, -100000, 20000)],
  allSell: fill(20, 100, -60, -50),
  twoDays: [[0, -500, 30], [0, -500, 20], [0, -500, -1], ...fill(17, 0, -500, -1)],
  bigPersonal: [...fill(3, 100, 0, 10), ...fill(17, 100, 0, -1)],
};
const badge = (rowText) => (/미충족/.test(rowText) ? "미충족" : /충족/.test(rowText) ? "충족" : /산정 불가/.test(rowText) ? "산정 불가" : "?");

async function open(p, rows) {
  await p.route("**/api/v1/local/stocks/*/investor", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ meta: {}, data: { stock_code: "T00001", rows: mkRows(rows), source: "test" }, error: null }) }));
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
  await p.getByRole("tab", { name: "조건 체크", exact: true }).click();
  await p.waitForSelector("text=수급·실적 점검");
  await p.waitForFunction(() => [...document.querySelectorAll(".pattern-list__row")].some((r) => r.textContent.startsWith("개인 주도 아님") && /(충족|산정 불가)/.test(r.textContent)), null, { timeout: 20000 });
  const all = await p.$$eval(".pattern-list__row", (e) => e.map((x) => x.textContent.replace(/\s+/g, " ").trim()));
  return { f6: all.find((r) => r.startsWith("외국인·기관 수급")) ?? "", f7: all.find((r) => r.startsWith("개인 주도 아님")) ?? "" };
}

for (const [w, h] of [[360, 800], [1280, 800]]) {
  const errs = [];
  const ctx = await b.newContext({ viewport: { width: w, height: h } });
  const p = await ctx.newPage();
  p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
  let r = await open(p, CASES.reino);
  rec(`[${w}] 리노공업: ⑥ 충족(외국인 매도에도 기관 4일 연속)`, badge(r.f6) === "충족" && /기관 연속 순매수 4일/.test(r.f6) && /외국인이 팔아도 기관이 연속 순매수 중이라 충족/.test(r.f6), r.f6.slice(0, 120));
  rec(`[${w}] 리노공업: ⑦ 충족(기관 누적 > 개인 누적 예외)`, badge(r.f7) === "충족" && /개인 주도가 아닌 것으로 봅니다/.test(r.f7), r.f7.slice(0, 120));
  const over = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  rec(`[${w}] 조건 체크 가로 넘침 없음`, !over);
  if (w === 360) { const ax = await runAxe(p); rec(`[${w}] axe 위반 없음`, ax.length === 0, JSON.stringify(ax.map((v) => v.id))); }
  await p.locator(".pattern-list__row", { hasText: "외국인·기관 수급" }).scrollIntoViewIfNeeded();
  await p.screenshot({ path: `${OUT}/streak-${w}.png`, fullPage: false });
  if (w === 360) {
    r = await open(p, CASES.allSell);
    rec("외국인·기관 모두 순매도: ⑥ ⑦ 미충족", badge(r.f6) === "미충족" && badge(r.f7) === "미충족", `${badge(r.f6)}/${badge(r.f7)}`);
    r = await open(p, CASES.twoDays);
    rec("기관 2일 연속뿐(기준 3일 미달): ⑥ 미충족", badge(r.f6) === "미충족" && /기관 연속 순매수 2일/.test(r.f6), r.f6.slice(0, 100));
    r = await open(p, CASES.bigPersonal);
    rec("기관 3일 연속이지만 개인 누적이 더 큼: ⑥ 충족, ⑦ 미충족(예외 불가)", badge(r.f6) === "충족" && badge(r.f7) === "미충족" && /예외를 적용하지 않습니다/.test(r.f7), `${badge(r.f6)}/${badge(r.f7)}`);
  }
  rec(`[${w}] 콘솔 오류 없음`, errs.length === 0, errs[0] ?? "");
  await ctx.close();
}
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
