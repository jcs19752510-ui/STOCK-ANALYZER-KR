// 그리기 도구(추세선·수평선, DEC-059) 점검: 열기/닫기, 수평선(클릭·가격 입력), 추세선(두 번 클릭), 저장·복원, 삭제, 모두 지우기,
// 일봉 밖에서는 안내, Esc 취소, 좁은 화면 넘침, axe. 전제: features-oct3.mjs 와 같다(시드 T00001).
import { BASE, launch, runAxe } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const ctx = await b.newContext({ viewport: { width: 390, height: 1900 } /* 패널이 열려도 차트 전체가 화면 안에 보이게 */ });
const p = await ctx.newPage();
const errs = [];
p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
await p.waitForSelector(".stock-chart__svg");
const svg = p.locator(".stock-chart__svg");
const lineCount = () => p.locator('.stock-chart__svg g[aria-hidden="true"] line[stroke="#0f766e"]').count();
const clickAt = async (fx, fy) => { const bb = await svg.boundingBox(); await p.mouse.click(bb.x + bb.width * fx, bb.y + bb.height * fy); };
const listItems = () => p.locator(".chart-draw__list li").count();

await p.getByRole("button", { name: "그리기 도구 열기" }).click();
rec("패널 열림(aria-expanded)", (await p.getByRole("button", { name: "그리기 도구 닫기" }).getAttribute("aria-expanded")) === "true");
rec("처음엔 그린 선 없음 안내", await p.getByText("아직 그린 선이 없습니다").count() === 1);
// 수평선: 가격으로 추가
await p.getByLabel("가격으로 수평선 추가(원)").fill("-5");
await p.getByRole("button", { name: "추가", exact: true }).click();
rec("잘못된 가격은 거절 안내", await p.getByText("올바른 가격").first().isVisible());
await p.getByLabel("가격으로 수평선 추가(원)").fill("10000");
await p.getByRole("button", { name: "추가", exact: true }).click();
rec("가격으로 수평선 추가", (await listItems()) === 1 && /수평선 10,000원/.test(await p.locator(".chart-draw__list").textContent()));
// 수평선: 차트 클릭
await p.getByRole("button", { name: "수평선", exact: true }).click();
rec("수평선 도구 안내 문구", await p.getByText("수평선: 차트에서 가격 위치를 누르세요").isVisible());
await clickAt(0.4, 0.2);
rec("차트 클릭으로 수평선 추가(도구 자동 해제)", (await listItems()) === 2 && (await p.getByRole("button", { name: "수평선", exact: true }).getAttribute("aria-pressed")) === "false");
// 추세선: 두 번 클릭
await p.getByRole("button", { name: "추세선", exact: true }).click();
await clickAt(0.2, 0.3);
rec("추세선 시작점 안내", await p.getByText("끝점을 누르세요").first().isVisible());
await clickAt(0.2, 0.35); // 같은 봉 → 거절
rec("같은 날짜 끝점은 거절", await p.getByText("날짜가 달라야 합니다").first().isVisible() && (await listItems()) === 2);
await clickAt(0.6, 0.15);
rec("추세선 완성", (await listItems()) === 3 && /추세선 \d\d\.\d\d\.\d\d/.test(await p.locator(".chart-draw__list").textContent()));
rec("차트에 선 렌더(수평선 2 + 추세선 1 이상)", (await lineCount()) >= 3, `선 ${await lineCount()}`);
// Esc 취소
await p.getByRole("button", { name: "추세선", exact: true }).click();
await clickAt(0.3, 0.3);
await p.keyboard.press("Escape");
rec("Esc로 그리기 취소(점 버림)", (await p.getByRole("button", { name: "추세선", exact: true }).getAttribute("aria-pressed")) === "false" && (await listItems()) === 3);
// 저장·복원
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".stock-chart__svg");
await p.getByRole("button", { name: "그리기 도구 열기" }).click();
rec("새로고침 후에도 유지(localStorage)", (await listItems()) === 3 && (await lineCount()) >= 3);
const stored = await p.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("chart.drawings.v1.")));
rec("종목별 키로 저장", stored.length === 1 && stored[0].endsWith("T00001"), stored.join(","));
await p.goto(BASE + "/stocks/T00002", { waitUntil: "networkidle" });
await p.waitForSelector(".stock-chart__svg");
await p.getByRole("button", { name: "그리기 도구 열기" }).click();
rec("다른 종목에는 보이지 않음", (await listItems()) === 0);
await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
await p.waitForSelector(".stock-chart__svg");
await p.getByRole("button", { name: "그리기 도구 열기" }).click();
// 주봉에서는 안내
await p.getByRole("button", { name: "주", exact: true }).click();
rec("일봉이 아니면 안내(그리기 불가)", await p.getByText("일봉에서만 사용할 수 있습니다").first().isVisible() && (await p.locator('.stock-chart__svg g[aria-hidden="true"] line[stroke="#0f766e"]').count()) === 0);
await p.getByRole("button", { name: "일", exact: true }).click();
rec("일봉으로 돌아오면 선이 다시 보임", (await lineCount()) >= 3);
// 가로 넘침·axe
rec("가로 넘침 없음", !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)));
const v = await runAxe(p);
rec("axe 위반 없음", v.length === 0, v.map((x) => `${x.id}:${x.nodes[0]?.target}`).join(" | ").slice(0, 200));
await p.screenshot({ path: "/tmp/claude-0/qa-out/draw-390.png" });
// 삭제·모두 지우기
await p.getByRole("button", { name: /수평선 10,000원 삭제/ }).click();
rec("개별 삭제", (await listItems()) === 2);
await p.getByRole("button", { name: "모두 지우기" }).click();
rec("모두 지우기는 2단계 확인", (await p.getByRole("button", { name: "정말 지우기" }).count()) === 1 && (await listItems()) === 2);
await p.getByRole("button", { name: "정말 지우기" }).click();
rec("모두 지움 + 저장소 정리", (await listItems()) === 0 && (await p.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("chart.drawings.v1.")).length)) === 0);
rec("콘솔 오류 없음", errs.length === 0, errs[0] ?? "");
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
