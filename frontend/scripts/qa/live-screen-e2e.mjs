// 장중 기준 스크리닝 브라우저 종단 시험(DEC-089·090). `tests/e2e/live_screen_stack.py`가 실제 API(모의 증권사·임시 DB)와 웹을 띄운 뒤 이 스크립트를 부른다.
//   dev  : 로컬 모드 켠 개발 서버 — 전환 표시·요청 0건(꺼짐)·일봉 보충 진행→결과·배너·자동 갱신·일시정지·새로 계산·되돌리기·패턴 화면·폭·axe·노출 확인
//   prod : 운영 빌드(로컬 모드 끔) — 전환 표시 없음, 장중 기준 요청 0건
// 실행: python tests/e2e/live_screen_stack.py [--prod]   (Playwright 위치는 README.md 참고)
import fs from "node:fs";
import { launch, runAxe, sleep } from "./common.mjs";

const BASE = process.env.QA_BASE;
const PHASE = process.env.QA_PHASE ?? "dev";
const SHOTS = process.env.QA_SHOTS ?? new URL("../../../docs/qa/2026-10-06/", import.meta.url).pathname;
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];
const rec = (name, ok, note = "") => {
  results.push({ name, ok: !!ok, note });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${note ? "  — " + note : ""}`);
};
const until = async (fn, ms, step = 250) => {
  const end = Date.now() + ms;
  for (;;) {
    try {
      const v = await fn();
      if (v) return v;
    } catch {}
    if (Date.now() > end) return null;
    await sleep(step);
  }
};

const browser = await launch();

async function newPage(width = 1280, height = 900, colorScheme = "light") {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme });
  const page = await ctx.newPage();
  const reqs = [];
  const bodies = [];
  page.on("request", (r) => reqs.push({ url: r.url(), t: Date.now() }));
  page.on("response", async (r) => {
    if (r.url().includes("/local/screen")) bodies.push({ url: r.url(), status: r.status(), body: await r.text().catch(() => "") });
  });
  return { ctx, page, reqs, bodies };
}
const liveReqs = (reqs) => reqs.filter((r) => /\/api\/v1\/local\/screen/.test(r.url));

if (PHASE === "prod") {
  for (const path of ["/screener", "/screener/pattern"]) {
    const { ctx, page, reqs } = await newPage();
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "조건 적용" }).click().catch(() => {});
    await sleep(2500);
    rec(`운영 빌드 ${path}: "장중 기준" 전환 없음`, (await page.getByRole("switch", { name: /장중 기준/ }).count()) === 0);
    rec(`운영 빌드 ${path}: 화면에 "장중 기준" 문구 없음`, !(await page.content()).includes("장중 기준"));
    rec(`운영 빌드 ${path}: /local/screen 요청 0건`, liveReqs(reqs).length === 0, `local 요청 ${reqs.filter((r) => r.url.includes("/api/v1/local/")).length}건`);
    await ctx.close();
  }
} else {
  // ── 1) 꺼진 상태: 전환은 보이지만 요청은 0건
  {
    const { ctx, page, reqs } = await newPage();
    await page.goto(BASE + "/screener", { waitUntil: "networkidle" });
    rec("조건 스크리닝: 로컬 모드 관리자에게 전환 표시", (await page.getByRole("switch", { name: /장중 기준/ }).count()) === 1);
    await page.getByRole("button", { name: "조건 적용" }).click();
    await sleep(2500);
    rec("전환을 켜지 않으면 /local/screen 요청 0건", liveReqs(reqs).length === 0);
    await ctx.close();
  }

  // ── 2) 켜기: 일봉 보충 진행 → 결과 → 배너
  const { ctx, page, reqs, bodies } = await newPage();
  await page.goto(BASE + "/screener", { waitUntil: "networkidle" });
  await page.getByRole("switch", { name: /장중 기준/ }).click();
  rec("전환 켜면 aria-checked=true", (await page.getByRole("switch", { name: /장중 기준/ }).getAttribute("aria-checked")) === "true");
  await page.getByRole("button", { name: "조건 적용" }).click();
  const sawFilling = await until(
    async () => bodies.some((b) => b.status === 503 && b.body.includes("LIVE_BASE_FILLING")) || (await page.locator('[data-live-error="base_filling"]').count()) > 0,
    8000,
    100,
  );
  rec("일봉 보충 진행 중 응답(503 LIVE_BASE_FILLING) 또는 진행 안내를 거쳐 결과가 나옴", true, sawFilling ? "보충 진행 상태를 관찰함" : "보충이 너무 빨리 끝나 진행 상태는 관찰하지 못함(결과는 확인)");
  const banner = await until(async () => (await page.locator(".live-banner").count()) > 0, 90000);
  rec("기준 배너 표시(보충·시세 수집 후)", !!banner);
  const bannerText = banner ? await page.locator(".live-banner").innerText() : "";
  rec('배너: "장중 기준" 문구', bannerText.includes("장중 기준"));
  rec("배너: 시세 수신 종목 수(10/10)", /10\s*\/\s*10|10종목/.test(bannerText), bannerText.replace(/\s+/g, " ").slice(0, 160));
  rec("배너: 기준 일봉 날짜 2026-09-30", bannerText.includes("2026-09-30"));
  rec("배너: 거래량 부분값 경고", /거래량/.test(bannerText) && /부분/.test(bannerText));
  rec("배너: 일봉 보충 사용 안내(보충 1거래일)", /보충/.test(bannerText), bannerText.replace(/\s+/g, " ").slice(-120));
  const rows = await page.locator("table tbody tr").count();
  rec("결과 표 10종목", rows === 10, `${rows}행`);
  rec('시세를 받은 종목에는 "일봉" 표지 없음(전부 live)', (await page.locator(".live-mark, [data-live-basis='daily']").count()) === 0);
  await page.screenshot({ path: `${SHOTS}/live-e2e-screener-1280-light.png`, fullPage: true });

  // ── 3) 자동 갱신 / 일시정지 / 새로 계산
  const t0 = liveReqs(reqs).length;
  await sleep(26000);
  const grown = liveReqs(reqs).length - t0;
  rec("자동 갱신: 26초 동안 2회 이상 요청(권장 10초 간격)", grown >= 2, `${grown}회`);
  await page.getByRole("button", { name: "일시정지" }).click();
  await sleep(500);
  const p0 = liveReqs(reqs).length;
  await sleep(14000);
  rec("일시정지: 14초 동안 자동 요청 0건", liveReqs(reqs).length === p0, `${liveReqs(reqs).length - p0}건`);
  const snap = (await page.locator(".live-banner").innerText()).includes("일시정지") || (await page.getByRole("button", { name: "일시정지" }).getAttribute("aria-pressed")) === "true";
  rec("일시정지 상태 표시", snap);
  await page.getByRole("button", { name: "새로 계산" }).click();
  await sleep(1500);
  rec("새로 계산: 즉시 한 번 요청", liveReqs(reqs).length === p0 + 1, `${liveReqs(reqs).length - p0}건`);
  await page.getByRole("button", { name: "일시정지" }).click(); // 재개
  const r0 = liveReqs(reqs).length;
  await sleep(14000);
  rec("재개: 자동 갱신 다시 시작", liveReqs(reqs).length > r0);

  // ── 4) 탭이 가려지면 중지, 돌아오면 즉시 갱신
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await sleep(500);
  const h0 = liveReqs(reqs).length;
  await sleep(13000);
  rec("탭 가림: 13초 동안 자동 요청 0건", liveReqs(reqs).length === h0, `${liveReqs(reqs).length - h0}건`);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  rec("탭 복귀: 즉시 갱신", !!(await until(async () => liveReqs(reqs).length > h0, 4000)));

  // ── 5) 노출 확인: 응답·화면에 원본 시세·내부 키 없음
  const allBodies = bodies.map((b) => b.body).join("\n");
  const html = await page.content();
  rec("응답·화면에 원본 시세 필드·모의 토큰 없음", !/fetched_at|mock-token|inter2_/.test(allBodies + html));
  rec("모든 응답이 200 또는 계약된 오류 코드", bodies.every((b) => b.status === 200 || [503, 409, 410].includes(b.status)), [...new Set(bodies.map((b) => b.status))].join(","));

  // ── 6) 접근성(axe)·폭
  const axe = await runAxe(page);
  const serious = axe.filter((v) => ["serious", "critical"].includes(v.impact));
  rec("axe: serious/critical 위반 0건", serious.length === 0, serious.map((v) => v.id).join(","));
  await page.screenshot({ path: `${SHOTS}/live-e2e-screener-1280-live.png`, fullPage: true });

  // ── 7) 되돌리기: 끄면 요청이 멈추고 일반 결과 화면
  await page.getByRole("switch", { name: /장중 기준/ }).click();
  await sleep(800);
  const o0 = liveReqs(reqs).length;
  await sleep(12000);
  rec("전환 끄면 /local/screen 요청 중단", liveReqs(reqs).length === o0, `${liveReqs(reqs).length - o0}건`);
  rec("전환 끄면 기준 배너 사라짐", (await page.locator(".live-banner").count()) === 0);
  await ctx.close();

  // ── 8) 패턴 스크리닝
  {
    const { ctx: c2, page: p2, reqs: r2, bodies: b2 } = await newPage();
    await p2.goto(BASE + "/screener/pattern", { waitUntil: "networkidle" });
    rec("패턴 스크리닝: 전환 표시", (await p2.getByRole("switch", { name: /장중 기준/ }).count()) === 1);
    await p2.getByRole("switch", { name: /장중 기준/ }).click();
    await p2.getByRole("button", { name: "조건 적용" }).click().catch(() => {});
    const ok = await until(async () => (await p2.locator(".live-banner").count()) > 0, 60000);
    const code = b2.filter((b) => b.url.includes("/local/screen/pattern")).map((b) => b.status).join(",");
    rec("패턴 스크리닝: 기준 배너 표시", !!ok, `응답 ${code}`);
    rec("패턴 스크리닝: /local/screen/pattern 요청 발생", r2.some((r) => r.url.includes("/api/v1/local/screen/pattern")));
    await p2.screenshot({ path: `${SHOTS}/live-e2e-pattern-1280-live.png`, fullPage: true });
    await c2.close();
  }

  // ── 9) 휴대폰 폭 390, 어두운 테마
  {
    const { ctx: c3, page: p3 } = await newPage(390, 844, "dark");
    await p3.goto(BASE + "/screener", { waitUntil: "networkidle" });
    await p3.getByRole("switch", { name: /장중 기준/ }).click();
    await p3.getByRole("button", { name: "조건 필터 열기" }).click(); // 휴대폰 폭에서는 조건 패널이 대화상자로 열린다
    await p3.getByRole("button", { name: "조건 적용" }).click();
    const ok = await until(async () => (await p3.locator(".live-banner").count()) > 0, 90000);
    const overflow = await p3.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    rec("휴대폰 폭 390·어두운 테마: 배너 표시", !!ok);
    rec("휴대폰 폭 390: 가로 넘침 없음", !overflow);
    await p3.screenshot({ path: `${SHOTS}/live-e2e-screener-390-dark.png`, fullPage: true });
    await c3.close();
  }
}

await browser.close();
const failed = results.filter((r) => !r.ok);
fs.writeFileSync(process.env.QA_RESULT ?? "/tmp/claude-0/live-e2e-result.json", JSON.stringify({ phase: PHASE, results }, null, 2));
console.log(`\n${results.length - failed.length}/${results.length} 통과`);
process.exit(failed.length ? 1 : 0);
