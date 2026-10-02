import { BASE, SHOTS, launch, devices, sleep, measureFn } from "./common.mjs";
const b = await launch();
const out = [];
const rec = (dev, name, pass, note = "") => { out.push({ dev, name, pass, note }); console.log(`${pass ? "PASS" : "FAIL"} [${dev}] ${name} ${note}`); };
for (const name of ["iPhone 13", "Pixel 7"]) {
  const ctx = await b.newContext({ ...devices[name] });
  const p = await ctx.newPage();
  const errs = [];
  p.on("response", (r) => r.status() >= 400 && console.log(`  (HTTP ${r.status()} ${r.url()})`));
  p.on("pageerror", (e) => errs.push(e.message));
  p.on("console", (m) => m.type() === "error" && errs.push(m.text()));
  await p.goto(BASE + "/stocks/T00001");
  await p.waitForSelector(".stock-chart__svg");
  const vp = p.viewportSize();
  rec(name, "뷰포트/UA", true, `${vp.width}x${vp.height} dpr=${devices[name].deviceScaleFactor} touch=${devices[name].hasTouch} mobile=${devices[name].isMobile}`);
  const m0 = await p.evaluate(measureFn);
  rec(name, "가로 넘침 없음", !m0.overflow, `sw=${m0.scrollWidth} vw=${m0.vw}`);
  // 차트 탭 → 선택봉 읽기 줄 변화
  const ro0 = await p.textContent(".stock-chart__readout");
  await p.locator(".stock-chart__svg").scrollIntoViewIfNeeded();
  await p.evaluate(() => document.querySelector(".stock-chart__svg").scrollIntoView({ block: "center" }));
  await sleep(200);
  const box = await p.locator(".stock-chart__svg").boundingBox();
  await p.touchscreen.tap(box.x + box.width * 0.3, box.y + box.height * 0.25);
  await sleep(300);
  const ro1 = await p.textContent(".stock-chart__readout");
  rec(name, "차트 탭 → 읽기 줄 변경", ro0 !== ro1, `${ro0.slice(0, 16)} -> ${ro1.slice(0, 16)}`);
  await p.touchscreen.tap(box.x + box.width * 0.6, box.y + box.height * 0.25);
  await sleep(300);
  const ro2 = await p.textContent(".stock-chart__readout");
  rec(name, "다른 위치 탭 → 다른 봉", ro2 !== ro1, `${ro2.slice(0, 16)}`);
  await p.screenshot({ path: `/tmp/claude-0/qa-out/dev-${name.replace(" ", "")}-tap.png` });
  // 일/주/월
  for (const tf of ["주", "월", "일"]) {
    await p.getByRole("button", { name: tf, exact: true }).tap();
    await sleep(300);
    const pressed = await p.getByRole("button", { name: tf, exact: true }).getAttribute("aria-pressed");
    const n = await p.$$eval(".stock-chart__svg text", (t) => t.map((e) => e.textContent.trim()).filter((x) => /^\d+$/.test(x)).join(","));
    rec(name, `${tf} 전환`, pressed === "true", `숫자라벨=${n}`);
  }
  // 요약 열기/닫기
  await p.getByRole("button", { name: "차트 요약", exact: false }).first().tap();
  await p.waitForSelector(".chart-summary li");
  rec(name, "차트 요약 열기", true, `항목 ${await p.$$eval(".chart-summary li", (l) => l.length)}`);
  await p.screenshot({ path: `/tmp/claude-0/qa-out/dev-${name.replace(" ", "")}-summary.png` });
  await p.locator(".chart-summary__close").tap();
  await sleep(200);
  rec(name, "차트 요약 닫기", (await p.locator(".chart-summary").count()) === 0);
  // 설정
  await p.getByRole("button", { name: "차트 설정" }).tap();
  await p.waitForSelector(".chart-settings");
  const cb = p.locator(".chart-settings input").first();
  const before = await cb.isChecked();
  await p.locator(".chart-settings__item").first().tap();
  rec(name, "설정 항목 토글(라벨 탭)", (await cb.isChecked()) !== before);
  await p.getByRole("button", { name: "차트 설정" }).tap();
  // 확대
  await p.locator(".chart-expand").tap();
  await sleep(300);
  const exp = await p.evaluate(() => { const e = document.querySelector(".stock-chart--expanded"); if (!e) return null; const r = e.getBoundingClientRect(); return { w: r.width, h: r.height, iw: innerWidth, ih: innerHeight }; });
  rec(name, "확대 켜짐(전체 화면)", !!exp && exp.w >= exp.iw - 1, JSON.stringify(exp));
  await p.screenshot({ path: `/tmp/claude-0/qa-out/dev-${name.replace(" ", "")}-expanded.png` });
  await p.locator(".chart-expand").tap();
  await sleep(300);
  rec(name, "확대 해제", (await p.locator(".stock-chart--expanded").count()) === 0);
  // 탭 전환
  for (const t of ["일자별 시세", "실적", "투자자", "조건 체크", "차트"]) {
    const tab = p.getByRole("tab", { name: t });
    await tab.scrollIntoViewIfNeeded();
    await tab.tap();
    await sleep(500);
    rec(name, `탭 전환 ${t}`, (await tab.getAttribute("aria-selected")) === "true");
  }
  // ⌄ 메뉴
  await p.getByRole("button", { name: "탭 전체 보기" }).tap();
  await p.getByRole("button", { name: "투자자", exact: true }).last().tap();
  await sleep(300);
  rec(name, "⌄ 전체 보기 메뉴로 탭 이동", (await p.getByRole("tab", { name: "투자자" }).getAttribute("aria-selected")) === "true");
  const m1 = await p.evaluate(measureFn);
  rec(name, "조작 후 가로 넘침 없음", !m1.overflow);
  rec(name, "콘솔/페이지 오류 없음", errs.length === 0, errs.slice(0, 2).join(" | "));
  await ctx.close();
}
await b.close();
console.log(`합계 PASS ${out.filter((o) => o.pass).length} FAIL ${out.filter((o) => !o.pass).length}`);
