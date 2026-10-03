// DEC-063 점검: 무료 호스팅 "서버 깨우는 중" 안내. API 응답을 브라우저에서 지연시켜 표시/해제/접근성을 확인한다.
// 전제: next dev 가 NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:4201 로 4202에 기동(API 서버는 없어도 됨: 요청을 가로챈다).
import { BASE, launch, runAxe } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const okBody = JSON.stringify({ meta: { generated_at: "2026-10-03T10:00:00+09:00", data_freshness: null, disclaimer: "x" }, data: [], error: null });

async function scenario(name, w, h, delayMs, status) {
  const ctx = await b.newContext({ viewport: { width: w, height: h } });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
  await p.route("**/api/v1/**", async (r) => {
    await new Promise((s) => setTimeout(s, delayMs));
    await r.fulfill({ status, contentType: "application/json", body: okBody });
  });
  await p.goto(BASE + "/stocks", { waitUntil: "domcontentloaded" });
  const live = p.locator('[role="status"]:has(.wake-notice), div[role="status"][aria-live="polite"]').first();
  await p.waitForSelector('div[role="status"][aria-live="polite"]', { state: "attached" });
  const box = p.locator("#stock-search-input");
  await box.fill("삼성");
  await box.press("Enter").catch(() => {});
  await p.waitForTimeout(1000);
  const early = await p.locator(".wake-notice").count();
  let shown = null, axe = [];
  if (delayMs > 4500) {
    await p.waitForSelector(".wake-notice", { timeout: 8000 }).then(() => { shown = true; }).catch(() => { shown = false; });
    if (shown) {
      const txt = await p.locator(".wake-notice").innerText();
      rec(`${name} ${w}px: 안내 문구`, /서버를 깨우는 중/.test(txt) && /최대 1분/.test(txt), txt.slice(0, 40));
      const inStatus = await p.locator('div[role="status"] .wake-notice').count();
      rec(`${name} ${w}px: role=status 안에 표시`, inStatus === 1);
      const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      rec(`${name} ${w}px: 가로 넘침 없음`, !overflow);
      axe = await runAxe(p);
      rec(`${name} ${w}px: axe 위반 없음`, axe.length === 0, axe.map((v) => v.id).join(","));
    }
    rec(`${name} ${w}px: ${delayMs}ms 지연 → 안내 표시`, shown === true);
    rec(`${name} ${w}px: 1초 시점엔 아직 숨김`, early === 0);
    await p.waitForFunction(() => !document.querySelector(".wake-notice"), null, { timeout: 15000 })
      .then(() => rec(`${name} ${w}px: 응답 후 안내 사라짐`, true))
      .catch(() => rec(`${name} ${w}px: 응답 후 안내 사라짐`, false));
  } else {
    await p.waitForTimeout(delayMs + 1500);
    rec(`${name} ${w}px: 빠른 응답은 안내 없음`, (await p.locator(".wake-notice").count()) === 0 && early === 0);
  }
  rec(`${name} ${w}px: 페이지 오류 없음`, errs.length === 0, errs.join(" | "));
  await ctx.close();
}

await scenario("느린 응답(6.5초)", 360, 800, 6500, 200);
await scenario("느린 응답(6.5초)", 1280, 800, 6500, 200);
await scenario("느린 후 오류(500)", 360, 800, 6500, 500);
await scenario("빠른 응답(0.3초)", 360, 800, 300, 200);
await b.close();
console.log(res.every(Boolean) ? "ALL PASS" : "SOME FAIL", `(${res.filter(Boolean).length}/${res.length})`);
process.exit(res.every(Boolean) ? 0 : 1);
