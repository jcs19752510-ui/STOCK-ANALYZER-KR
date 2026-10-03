import { BASE, launch, sleep } from "./common.mjs";
const b = await launch();
const p = await b.newPage({ viewport: { width: 1024, height: 900 } });
await p.goto(BASE + "/stocks/T00001");
await p.waitForSelector(".stock-chart__svg");
const res = [];
const rec = (name, pass, note = "") => { res.push({ name, pass, note }); console.log(`${pass ? "PASS" : "FAIL"}  ${name}  ${note}`); };
const desc = () => p.evaluate(() => {
  const e = document.activeElement;
  if (!e || e === document.body) return null;
  const cs = getComputedStyle(e);
  const label = (e.getAttribute("aria-label") || e.textContent || e.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 28);
  const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
  const shadow = cs.boxShadow !== "none";
  const r = e.getBoundingClientRect();
  return { tag: e.tagName.toLowerCase(), role: e.getAttribute("role") || "", label, outline, shadow, outlineCss: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}`, visible: r.width > 0 && r.height > 0 };
});
// 모든 대화형 요소(탭 순서에 들어가야 하는 것)
const expected = await p.evaluate(() =>
  [...document.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), [tabindex="0"]')]
    .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; })
    .map((e) => (e.getAttribute("aria-label") || e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 28) + "|" + e.tagName.toLowerCase()),
);
const seq = [];
for (let i = 0; i < 60; i++) {
  await p.keyboard.press("Tab");
  const d = await desc();
  if (!d) break;
  seq.push(d);
  if (seq.length > 3 && seq.slice(0, -1).some((s) => s.label === d.label && s.tag === d.tag && s.role === d.role) && seq.filter((s) => s.label === d.label).length > 1 && d.label === seq[0].label) break;
}
console.log("Tab 순서:\n" + seq.map((s, i) => `${i + 1}. ${s.tag}${s.role ? "[" + s.role + "]" : ""} ${s.label} ${s.outline ? "outline" : s.shadow ? "shadow" : "NO-FOCUS-STYLE"}`).join("\n"));
const noStyle = seq.filter((s) => !s.outline && !s.shadow);
rec("Tab으로 도달한 요소 모두 포커스 표시(outline/box-shadow) 존재", noStyle.length === 0, noStyle.map((s) => s.label).join(",") );
const reached = new Set(seq.map((s) => s.label + "|" + s.tag));
const roving = (l) => /^(일자별 시세|실적|투자자|조건 체크)\|button$/.test(l);
const missing = expected.filter((e) => !reached.has(e) && !roving(e));
rec("가시 대화형 요소 전부 Tab 도달(탭 목록 비선택 탭은 roving이라 제외)", missing.length === 0, "미도달: " + missing.join(", "));
rec("탭 목록은 roving tabindex(Tab 한 번에 선택된 탭만)", seq.filter((s) => s.role === "tab").length === 1, `tab 정지 ${seq.filter((s) => s.role === "tab").length}회`);
// 탭 목록 방향키
await p.getByRole("tab", { name: "차트" }).focus();
await p.keyboard.press("ArrowRight");
let sel = await p.evaluate(() => document.activeElement.textContent);
rec("탭 → 키: 다음 탭으로 이동", sel === "일자별 시세", sel);
await p.keyboard.press("ArrowRight"); await p.keyboard.press("ArrowRight"); await p.keyboard.press("ArrowRight");
sel = await p.evaluate(() => document.activeElement.textContent);
rec("탭 → 키 4회: 조건 체크", sel === "조건 체크", sel);
await p.keyboard.press("ArrowRight");
sel = await p.evaluate(() => document.activeElement.textContent);
rec("마지막에서 → : 처음으로 순환", sel === "차트", sel);
await p.keyboard.press("ArrowLeft");
sel = await p.evaluate(() => document.activeElement.textContent);
rec("← 키: 마지막으로 순환", sel === "조건 체크", sel);
await p.keyboard.press("Home");
sel = await p.evaluate(() => document.activeElement.textContent);
rec("Home 키: 첫 탭(WAI-ARIA 권장, 선택사항)", sel === "차트", sel);
await p.keyboard.press("End");
sel = await p.evaluate(() => document.activeElement.textContent);
rec("End 키: 마지막 탭(WAI-ARIA 권장, 선택사항)", sel === "조건 체크", sel);
await p.getByRole("tab", { name: "차트" }).click();
await p.waitForSelector(".stock-chart__svg");
// ⌄ 메뉴
const more = p.getByRole("button", { name: "탭 전체 보기" });
await more.focus(); await p.keyboard.press("Enter");
rec("⌄ 메뉴 Enter로 열림", (await p.locator(".stock-tabs__menu").count()) === 1);
await p.keyboard.press("Tab");
const f1 = await p.evaluate(() => document.activeElement.className);
rec("메뉴 열면 Tab이 메뉴 항목으로 이동", f1.includes("stock-tabs__menu-item"), f1);
await p.keyboard.press("Escape");
const menuAfterEsc = await p.locator(".stock-tabs__menu").count();
rec("⌄ 메뉴 Esc로 닫힘", menuAfterEsc === 0, `Esc 후 메뉴 ${menuAfterEsc}개 (WAI-ARIA 메뉴 버튼 권장)`);
if (menuAfterEsc) await more.click();
// 차트 프레임 ←→
const frame = p.locator(".stock-chart__frame");
await frame.focus();
const r0 = await p.textContent(".stock-chart__readout");
await p.keyboard.press("ArrowLeft");
const r1 = await p.textContent(".stock-chart__readout");
await p.keyboard.press("ArrowLeft");
const r2 = await p.textContent(".stock-chart__readout");
await p.keyboard.press("ArrowRight");
const r3 = await p.textContent(".stock-chart__readout");
rec("차트 프레임 ← : 이전 봉 선택", r0 !== r1 && r1 !== r2, `${r0.slice(0, 10)} → ${r1.slice(0, 10)} → ${r2.slice(0, 10)}`);
rec("차트 프레임 → : 다음 봉(이전 선택으로 복귀)", r3 === r1);
const fr = await p.evaluate(() => { const cs = getComputedStyle(document.querySelector(".stock-chart__frame")); return `${cs.outlineStyle} ${cs.outlineWidth} | shadow ${cs.boxShadow}`; });
rec("차트 프레임 포커스 표시", !fr.startsWith("none") || !fr.includes("shadow none"), fr);
await p.keyboard.press("Home");
// 읽기 줄 aria-live
rec("읽기 줄 aria-live=polite", (await p.getAttribute(".stock-chart__readout", "aria-live")) === "polite");
// 요약 열기: 포커스 이동?
const sumBtn = p.getByRole("button", { name: "차트 요약" });
await sumBtn.focus(); await p.keyboard.press("Enter");
await p.waitForSelector(".chart-summary");
const af = await p.evaluate(() => document.activeElement.className || document.activeElement.tagName);
rec("차트 요약 키보드로 열림", true, `열린 뒤 포커스=${af}`);
await p.keyboard.press("Escape");
rec("차트 요약 Esc로 닫힘(권장)", (await p.locator(".chart-summary").count()) === 0, "Esc 후 " + (await p.locator(".chart-summary").count()));
await sumBtn.focus(); await p.keyboard.press("Enter"); await p.waitForSelector(".chart-summary__close");
await p.locator(".chart-summary__close").focus();
await p.keyboard.press("Enter");
rec("요약 닫기 버튼 Enter", (await p.locator(".chart-summary").count()) === 0);
// 설정 패널
const setBtn = p.getByRole("button", { name: "차트 설정" });
await setBtn.focus(); await p.keyboard.press("Space");
await p.waitForSelector(".chart-settings");
await p.keyboard.press("Tab");
const sf = await p.evaluate(() => ({ t: document.activeElement.type, label: document.activeElement.closest("label")?.textContent.trim() }));
rec("설정 패널 키보드 접근(Tab→체크박스)", sf.t === "checkbox", JSON.stringify(sf));
const cb0 = await p.evaluate(() => document.activeElement.checked);
await p.keyboard.press("Space");
rec("체크박스 Space 토글", (await p.evaluate(() => document.activeElement.checked)) !== cb0);
const cbOutline = await desc();
rec("체크박스 포커스 표시", !!(cbOutline && (cbOutline.outline || cbOutline.shadow)), cbOutline?.outlineCss);
await setBtn.click();
// 확대 + Esc
const exp = p.locator(".chart-expand");
await exp.focus(); await p.keyboard.press("Enter");
rec("확대 키보드(Enter)로 켜짐", (await p.locator(".stock-chart--expanded").count()) === 1);
const focusAfter = await p.evaluate(() => document.activeElement.className);
rec("확대 후 포커스가 확대 버튼에 유지", focusAfter.includes("chart-expand"), focusAfter);
await p.keyboard.press("Escape");
rec("Esc로 확대 닫힘", (await p.locator(".stock-chart--expanded").count()) === 0);
// 일/주/월 aria-pressed
await p.getByRole("button", { name: "주", exact: true }).focus(); await p.keyboard.press("Enter");
rec("주 버튼 Enter → aria-pressed", (await p.getByRole("button", { name: "주", exact: true }).getAttribute("aria-pressed")) === "true");
// 스킵 링크
await p.goto(BASE + "/stocks/T00001"); await p.waitForSelector(".stock-chart__svg");
await p.keyboard.press("Tab");
const first = await desc();
rec("첫 Tab = 본문 건너뛰기 링크", /건너|본문|skip/i.test(first?.label ?? ""), first?.label);
await p.keyboard.press("Enter"); await sleep(200);
const hash = await p.evaluate(() => location.hash);
rec("스킵 링크 동작(해시 이동)", hash.length > 1, hash);
await b.close();
console.log(`합계 PASS ${res.filter((r) => r.pass).length} FAIL ${res.filter((r) => !r.pass).length}`);
