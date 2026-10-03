// 새 화면(관심종목·조건 체크 수급/실적·차트 패널) 접근성·테마 점검: axe(라이트/다크/고대비), 저장소 차단 환경.
// 전제: features-oct3.mjs 와 같다. 실행: QA_PW_DIR=… QA_BASE=http://localhost:4202 node scripts/qa/new-screens-a11y.mjs
import { BASE, OUT, launch, runAxe } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const summarize = (v) => v.map((x) => `${x.id}(${x.impact}) ${x.nodes[0]?.target}`).join(" | ").slice(0, 300);

for (const scheme of ["light", "dark"]) {
  const ctx = await b.newContext({ viewport: { width: 360, height: 800 }, colorScheme: scheme });
  const p = await ctx.newPage();
  // 관심종목: 채우기 → 목록/편집 모드
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
  await p.getByRole("button", { name: /관심종목에 추가: / }).click();
  await p.goto(BASE + "/watchlist", { waitUntil: "networkidle" });
  await p.waitForSelector(".stock-list__item");
  let v = await runAxe(p);
  rec(`[${scheme}] 관심종목 목록 axe`, v.length === 0, summarize(v));
  await p.getByRole("button", { name: "편집", exact: true }).click();
  await p.getByLabel("새 그룹 이름").fill("테스트");
  await p.getByRole("button", { name: "그룹 추가" }).click();
  await p.getByRole("tab", { name: "관심종목", exact: true }).click();
  v = await runAxe(p);
  rec(`[${scheme}] 관심종목 편집 모드 axe`, v.length === 0, summarize(v));
  if (scheme === "dark") await p.screenshot({ path: `${OUT}/a11y-watch-dark.png` });
  // 조건 체크
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
  await p.getByRole("tab", { name: "조건 체크", exact: true }).click();
  await p.waitForFunction(() => document.querySelectorAll(".pattern-list__row .condition-status").length >= 9, null, { timeout: 20000 });
  v = await runAxe(p);
  rec(`[${scheme}] 조건 체크(수급·실적) axe`, v.length === 0, summarize(v));
  if (scheme === "dark") await p.screenshot({ path: `${OUT}/a11y-check-dark.png` });
  // 차트 패널 버튼
  await p.getByRole("tab", { name: "차트", exact: true }).click();
  await p.waitForSelector(".stock-chart__svg");
  v = await runAxe(p);
  rec(`[${scheme}] 차트(패널 ≡⊠) axe`, v.length === 0, summarize(v));
  if (scheme === "dark") await p.screenshot({ path: `${OUT}/a11y-chart-dark.png` });
  await ctx.close();
}

// 고대비(forced-colors): 별·≡⊠·탭이 보이는지(윤곽·글자색이 시스템 색을 따르는지) 스크린샷으로 남긴다
{
  const ctx = await b.newContext({ viewport: { width: 360, height: 800 }, forcedColors: "active" });
  const p = await ctx.newPage();
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
  await p.waitForSelector(".stock-chart__svg");
  const vis = await p.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const col = (e) => (e ? getComputedStyle(e).color : "none");
    return { star: col(q(".watch-star")), panel: col(q(".chart-panel-btn")), bg: getComputedStyle(document.body).backgroundColor };
  });
  rec("[고대비] 별·패널 버튼 색이 배경과 다름", vis.star !== vis.bg && vis.panel !== vis.bg, JSON.stringify(vis));
  await p.screenshot({ path: `${OUT}/a11y-forced.png` });
  await ctx.close();
}

// 저장소 차단(시크릿 창 유사): localStorage 접근 시 예외 → 화면은 동작하고 세션 동안만 유지
{
  const ctx = await b.newContext({ viewport: { width: 360, height: 800 } });
  await ctx.addInitScript(() => {
    const deny = () => { throw new DOMException("denied", "SecurityError"); };
    Object.defineProperty(window, "localStorage", { get: deny, configurable: true });
  });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 160)));
  p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 160)); });
  await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
  await p.getByRole("button", { name: /관심종목에 추가: / }).click();
  rec("[저장소 차단] 별 켜기 동작(aria-pressed)", (await p.getByRole("button", { name: /관심종목에서 제거: / }).getAttribute("aria-pressed")) === "true");
  await p.getByRole("link", { name: "관심종목", exact: true }).click();
  await p.locator(".stock-list__item").or(p.getByText("아직 관심종목이 없습니다")).first().waitFor();
  rec("[저장소 차단] 같은 화면 세션 안에서는 목록 유지", (await p.locator(".stock-list__item").count()) === 1);
  rec("[저장소 차단] 오류 없음", errs.length === 0, errs[0] ?? "");
  await ctx.close();
}
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
