// 로그인 켠 로컬 + 개발 서버(`next dev`)에서 "로그인 상태를 확인하는 중" 갱신 화면이 끝까지 가는지 확인(사용자 PC 증상 재현용).
// `python tests/e2e/local_mode_stack.py --mode on --dev`가 부른다(QA_SCRIPT). 로그인 → 갱신 화면을 직접 열기 → 원래 화면으로 돌아오는지 + 콘솔 오류·실패 요청을 출력한다.
import { BASE, launch, OUT } from "./common.mjs";
import fs from "node:fs";

const PW = process.env.QA_PW;
const b = await launch();
const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, baseURL: BASE });
const page = await ctx.newPage();
const errs = [];
const fails = [];
page.on("console", (m) => m.type() === "error" && errs.push(m.text().slice(0, 300)));
page.on("pageerror", (e) => errs.push("pageerror: " + String(e).slice(0, 300)));
page.on("requestfailed", (r) => fails.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`));
page.on("response", (r) => r.status() >= 400 && fails.push(`HTTP ${r.status()} ${r.url()}`));
fs.mkdirSync(OUT, { recursive: true });

await page.goto("/login");
await page.fill("#login-username", "kim");
await page.fill("#login-password", PW);
await Promise.all([page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 60000 }), page.click("button[type=submit]")]);
console.log("로그인 후 주소:", page.url());

const t0 = Date.now();
await page.goto("/auth/renew?next=%2Fscreener%2Fpattern");
let ok = false;
try {
  await page.waitForURL((u) => u.pathname === "/screener/pattern", { timeout: 90000 });
  await page.getByText("급등 전 압축주").first().waitFor({ timeout: 60000 });
  ok = true;
} catch (e) {
  console.log("대기 실패:", String(e).slice(0, 160));
}
console.log(`갱신 화면 → 원래 화면: ${ok ? "성공" : "실패"} (${((Date.now() - t0) / 1000).toFixed(1)}초), 최종 주소 ${page.url()}`);
console.log("본문 앞부분:", (await page.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 160));
await page.screenshot({ path: `${OUT}/renew-dev.png` });
console.log("콘솔 오류:", errs.length ? errs.join("\n  ") : "없음");
console.log("실패 요청:", fails.length ? fails.slice(0, 8).join("\n  ") : "없음");
await b.close();
process.exit(ok ? 0 : 1);
