// 분·틱 선택 회귀 점검: 선택 표시, 중복 key/콘솔 오류 없음, 개발 모드 Issues 표시 없음.
// 전제: 모의 KIS + API + `next dev`(NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true), 접속 QA_BASE (기본 4202)
import { BASE, launch } from "./common.mjs";
const b = await launch();
const p = await b.newPage({ viewport: { width: 520, height: 1100 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const pressed = () => p.$$eval(".chart-seg__btn", (e) => e.filter((x) => x.getAttribute("aria-pressed") === "true").map((x) => x.textContent.trim()).join(""));
const issues = () => p.evaluate(() => (document.querySelector("nextjs-portal")?.shadowRoot?.textContent || "").match(/\d+\s*Issues?/i)?.[0] ?? "none");
await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
await p.waitForSelector(".stock-chart__svg");
for (const n of ["1분", "5분", "15분", "60분"]) {
  await p.getByRole("button", { name: "분봉 간격 선택" }).click();
  await p.getByRole("menuitem", { name: n, exact: true }).click();
  await p.waitForFunction(() => /\d\d:\d\d/.test(document.querySelector(".stock-chart__svg")?.textContent || ""), null, { timeout: 20000 });
  rec(`${n} 선택 표시`, (await pressed()) === n, await pressed());
}
await p.getByRole("button", { name: "틱 묶음 선택" }).click();
await p.getByRole("menuitem", { name: "5틱", exact: true }).click();
await p.waitForTimeout(6000);
rec("5틱 선택 표시", (await pressed()) === "5틱");
await p.getByRole("button", { name: "일", exact: true }).click();
rec("일봉 복귀 시 일만 선택", (await pressed()) === "일");
await p.waitForTimeout(2000);
rec("콘솔 오류(중복 key 등) 없음", errs.length === 0, errs[0] ?? "");
rec("개발 모드 Issues 표시 없음", (await issues()) === "none", await issues());
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
