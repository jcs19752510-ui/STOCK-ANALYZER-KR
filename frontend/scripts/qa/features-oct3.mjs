// DEC-055 점검: ⑥⑦⑧ 조건 체크, 차트 패널 닫기·순서, 관심종목(추가·편집·그룹·내비), 좁은 화면 가로 넘침·콘솔 오류.
// 전제: 모의 KIS + API + next dev(NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true), 시드 T00001(+ corp_earnings 3개 연도), QA_BASE
import { BASE, OUT, launch } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const ctx = await b.newContext({ viewport: { width: 360, height: 800 } });
const p = await ctx.newPage();
const errs = [];
p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 200)); });
p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
const overflow = () => p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);

// ── 조건 체크: ⑥⑦⑧
await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
await p.getByRole("tab", { name: "조건 체크", exact: true }).click();
await p.waitForSelector("text=수급·실적 점검");
await p.waitForSelector("text=외국인·기관 수급", { timeout: 20000 });
await p.waitForFunction(() => document.querySelectorAll(".pattern-list__row .condition-status").length >= 9, null, { timeout: 20000 });
const rows = await p.$$eval(".pattern-list__row", (e) => e.map((x) => x.textContent.replace(/\s+/g, " ").trim()));
const earn = rows.find((r) => r.startsWith("실적(")) ?? "";
rec("⑧ 실적 행: 충족 + 수치 근거", /충족/.test(earn) && /2025년 영업이익 1,200억 원\(전년 800억 원\)/.test(earn), earn.slice(0, 90));
const f1 = rows.find((r) => r.startsWith("외국인·기관 수급")) ?? "";
const f2 = rows.find((r) => r.startsWith("개인 주도 아님")) ?? "";
rec("⑥ ⑦ 수급 행 표시(상태 배지+근거)", /(충족|미충족)/.test(f1) && /누적 순매수 외국인/.test(f1) && /(충족|미충족)/.test(f2) && /개인 [+-]/.test(f2), `${f1.slice(0, 70)} | ${f2.slice(0, 50)}`);
rec("조건 체크 가로 넘침 없음", !(await overflow()));
await p.screenshot({ path: `${OUT}/f-check-360.png` });

// ── 차트 패널 닫기·순서
await p.getByRole("tab", { name: "차트", exact: true }).click();
await p.waitForSelector(".stock-chart__svg");
const svgH = () => p.$eval(".stock-chart__svg", (e) => e.getBoundingClientRect().height);
const h0 = await svgH();
const order = () => p.$$eval(".chart-panel-btn[aria-label$='순서 바꾸기']", (e) => e.map((x) => x.getAttribute("aria-label").split(" ")[0] + (x.disabled ? "(비활성)" : "")));
const o0 = await order();
await p.getByRole("button", { name: /^거래량 패널 위아래 순서 바꾸기$/ }).click();
const legendY = () => p.$$eval(".stock-chart__svg text", (t) => { const v = t.find((x) => x.textContent === "거래량"); const m = t.find((x) => x.textContent?.startsWith("MACD")); return [v?.getBoundingClientRect().top ?? -1, m?.getBoundingClientRect().top ?? -1]; });
const [vy1, my1] = await legendY();
rec("≡ 순서 바꾸기: MACD가 거래량 위로", my1 > 0 && vy1 > my1, `${o0.join(",")} → 거래량 y=${vy1.toFixed(0)} MACD y=${my1.toFixed(0)}`);
await p.getByRole("button", { name: /^MACD 패널 닫기/ }).click();
const h1 = await svgH();
rec("⊠ 닫기: MACD 패널이 사라지고 차트 높이 감소", h1 < h0 && (await p.locator("text=Signal(9)").count()) === 0, `${h0.toFixed(0)}px → ${h1.toFixed(0)}px`);
rec("한 패널만 남으면 ≡ 비활성", (await p.getByRole("button", { name: /^거래량 패널 위아래 순서 바꾸기$/ }).isDisabled()));
await p.getByRole("button", { name: /^거래량 패널 닫기/ }).click();
rec("두 패널 모두 닫아도 차트(가격) 유지", (await p.locator(".stock-chart__svg").count()) === 1 && (await svgH()) < h1);
await p.getByRole("button", { name: "차트 설정" }).click();
await p.getByLabel("거래량 패널").check();
await p.getByLabel("MACD 패널").check();
const h2 = await svgH();
rec("설정에서 다시 켜면 복원", Math.abs(h2 - h0) < 1 && (await p.locator("text=Signal(9)").count()) === 1, `${h2.toFixed(0)}px`);
await p.screenshot({ path: `${OUT}/f-chart-360.png` });

// ── 관심종목
const nav = await p.$$eval(".global-nav__link", (e) => e.map((x) => x.textContent));
rec("내비 4항목", nav.join(",") === "홈,조건 스크리닝,종목 검색,관심종목", nav.join(","));
await p.getByRole("link", { name: "관심종목", exact: true }).click();
await p.waitForSelector("text=아직 관심종목이 없습니다");
rec("빈 상태 + 안내", true);
await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
const star = p.getByRole("button", { name: /관심종목에 추가: / });
await star.click();
rec("별 켜기(aria-pressed)", (await p.getByRole("button", { name: /관심종목에서 제거: / }).getAttribute("aria-pressed")) === "true");
await p.goto(BASE + "/stocks", { waitUntil: "networkidle" });
await p.getByRole("searchbox").or(p.getByRole("textbox")).first().fill("픽스처0");
await p.waitForSelector(".stock-list__item");
await p.locator(".stock-list__item").nth(1).getByRole("button", { name: /관심종목에 추가: / }).click();
await p.goto(BASE + "/watchlist", { waitUntil: "networkidle" });
const n1 = await p.locator(".stock-list__item").count();
rec("목록에 2종목(검색 별 + 상세 별)", n1 === 2, `행 ${n1}`);
rec("관심종목 가로 넘침 없음", !(await overflow()));
await p.reload({ waitUntil: "networkidle" });
rec("새로고침 후에도 유지(localStorage)", (await p.locator(".stock-list__item").count()) === 2);
await p.getByRole("button", { name: "편집", exact: true }).click();
await p.getByLabel("새 그룹 이름").fill("양자컴퓨터 관련주");
await p.getByRole("button", { name: "그룹 추가" }).click();
await p.getByRole("tab", { name: "관심종목", exact: true }).click();
const first = await p.locator(".stock-list__name").first().textContent();
await p.locator(".stock-list__item").first().getByRole("combobox", { name: /그룹 이동$/ }).selectOption({ label: "양자컴퓨터 관련주" });
rec("그룹 이동", (await p.locator(".stock-list__item").count()) === 1);
await p.getByRole("tab", { name: "양자컴퓨터 관련주" }).click();
rec("이동한 그룹에 표시", (await p.locator(".stock-list__name").first().textContent()) === first, first ?? "");
await p.getByRole("tab", { name: "통합", exact: true }).click();
rec("통합 보기에 합쳐서 표시", (await p.locator(".stock-list__item").count()) === 2);
await p.screenshot({ path: `${OUT}/f-watch-360.png` });
await p.getByRole("tab", { name: "양자컴퓨터 관련주" }).click();
await p.getByRole("button", { name: "그룹 삭제" }).click();
rec("그룹 삭제는 2단계(확인 버튼)", (await p.getByRole("button", { name: "정말 삭제" }).count()) === 1);
await p.getByRole("button", { name: "정말 삭제" }).click();
await p.getByRole("tab", { name: "통합", exact: true }).click();
rec("그룹 삭제 후 종목도 제거", (await p.locator(".stock-list__item").count()) === 1);
await p.goto(BASE + "/stocks/T00001", { waitUntil: "networkidle" });
// 320 폭 내비 넘침
await p.setViewportSize({ width: 320, height: 568 });
rec("320폭 가로 넘침 없음", !(await overflow()));
rec("콘솔 오류 없음", errs.length === 0, errs[0] ?? "");
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
