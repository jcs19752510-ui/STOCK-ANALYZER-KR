// 투자자(수급) 탭 점검(개인 로컬 모드): 표 표시·부호·빈 값·좁은 화면 가로 넘침·콘솔 오류.
// 전제: 모의 KIS + API + next dev(NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true), 접속 QA_BASE
import { BASE, OUT, launch } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
for (const [w, h] of [[320, 568], [360, 800], [1280, 800]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  const errs = [];
  p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
  await p.getByRole("tab", { name: "투자자", exact: true }).click();
  await p.waitForSelector(".daily-table tbody tr", { timeout: 20000 });
  const info = await p.evaluate(() => {
    const rows = [...document.querySelectorAll(".daily-table tbody tr")];
    const first = rows[0].textContent;
    return {
      n: rows.length, first,
      cols: document.querySelectorAll(".daily-table thead th").length,
      up: document.querySelectorAll(".daily-table .price-up").length,
      down: document.querySelectorAll(".daily-table .price-down").length,
      notice: !!document.querySelector(".local-notice"),
      overflowX: document.documentElement.scrollWidth > window.innerWidth,
      pending: document.body.textContent.includes("준비 중입니다"),
    };
  });
  rec(`[${w}] 표 29~30일(장중 빈 당일 행 제외)·4열`, info.n >= 29 && info.n <= 30 && info.cols === 4, `행 ${info.n} 열 ${info.cols}`);
  rec(`[${w}] 순매수/순매도 색·기호`, info.up > 0 && info.down > 0 && /[▲▼]/.test(info.first), info.first.slice(0, 40));
  rec(`[${w}] 로컬 모드 안내·준비중 문구 없음`, info.notice && !info.pending);
  rec(`[${w}] 페이지 가로 넘침 없음`, !info.overflowX);
  rec(`[${w}] 콘솔 오류 없음`, errs.length === 0, errs[0] ?? "");
  if (w === 360) await p.screenshot({ path: `${OUT}/investor-360.png`, fullPage: false });
  await p.close();
}
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
