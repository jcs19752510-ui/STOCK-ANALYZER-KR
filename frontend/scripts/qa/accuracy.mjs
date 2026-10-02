import { BASE, API, launch } from "./common.mjs";
const code = process.env.CODE ?? "T00001";
const api = await (await fetch(`${API}/api/v1/stocks/${code}/prices`)).json();
const prices = api.data.prices;
const last = prices.at(-1), prev = prices.at(-2);
const view = prices.slice(-61);
const hi = Math.max(...view.map((c) => c.high)), lo = Math.min(...view.map((c) => c.low));
const nf = (n) => new Intl.NumberFormat("ko-KR").format(n);
const b = await launch();
const p = await b.newPage({ viewport: { width: 390, height: 900 } });
await p.goto(`${BASE}/stocks/${code}`);
await p.waitForSelector(".stock-chart__svg");
const res = [];
const ok = (name, got, want) => res.push({ name, got, want, pass: String(got) === String(want) });
const q = (s) => p.$eval(s, (e) => e.textContent.trim());
ok("헤더 현재가", await q(".quote-band__close"), nf(last.close));
const chgTxt = (await q(".quote-band__chg")).replace(/[^0-9,]/g, "");
ok("헤더 전일대비(절대값)", chgTxt, nf(Math.abs(last.close - prev.close)));
ok("헤더 전일대비 vs API change", chgTxt, nf(Math.abs(last.change)));
ok("헤더 등락률", await q(".quote-band__pct"), Math.abs(((last.close - prev.close) / prev.close) * 100).toFixed(2) + "%");
ok("헤더 방향 클래스", await p.$eval(".quote-band", (e) => e.className.match(/--(up|down|flat)/)[1]), last.close > prev.close ? "up" : last.close < prev.close ? "down" : "flat");
const texts = await p.$$eval(".stock-chart__svg text", (t) => t.map((e) => e.textContent));
const fmt = (n) => nf(n);
const hiTxt = texts.find((t) => t.includes("(") && t.includes("%") && t.includes(fmt(hi) + "("));
const loTxt = texts.find((t) => t.includes("(") && t.includes("%") && t.includes(fmt(lo) + "("));
ok("차트 최고 표기(61봉 최고가)", hiTxt ?? "없음", `포함: ${fmt(hi)}(`);
res.at(-1).pass = !!hiTxt;
ok("차트 최저 표기(61봉 최저가)", loTxt ?? "없음", `포함: ${fmt(lo)}(`);
res.at(-1).pass = !!loTxt;
const pctOf = (v) => (((v - last.close) / last.close) * 100).toFixed(2) + "%";
if (hiTxt) { res.push({ name: "최고 % 값", got: hiTxt, want: pctOf(hi), pass: hiTxt.includes(pctOf(hi)) }); }
if (loTxt) { res.push({ name: "최저 % 값", got: loTxt, want: pctOf(lo), pass: loTxt.includes(pctOf(lo)) }); }
// 최고 봉 날짜
const hiBar = view.find((c) => c.high === hi), loBar = view.findLast((c) => c.low === lo);
const yymmdd = (d) => d.slice(2).replace(/-/g, ".");
res.push({ name: "최고 날짜", got: hiTxt, want: yymmdd(hiBar.trade_date), pass: !!hiTxt && hiTxt.includes(yymmdd(hiBar.trade_date)) });
res.push({ name: "최저 날짜", got: loTxt, want: yymmdd(loBar.trade_date), pass: !!loTxt && loTxt.includes(yymmdd(loBar.trade_date)) });
res.push({ name: "봉 수 라벨", got: texts.filter((t) => /^\d+$/.test(t.trim())).join(","), want: "61 포함", pass: texts.some((t) => t.trim() === "61") });
// 현재가 배지: 마지막 종가 텍스트 + 등락률
const badge = texts.filter((t) => t.replace(/,/g, "") === String(last.close));
res.push({ name: "현재가 배지 가격", got: badge.join("|"), want: nf(last.close), pass: badge.length >= 1 });
const lastPct = (((last.close - prev.close) / prev.close) * 100).toFixed(2);
res.push({ name: "현재가 배지 등락률", got: texts.filter((t) => t.includes("%") && !t.includes("(")).join("|"), want: lastPct, pass: texts.some((t) => t.trim() === Math.abs(+lastPct).toFixed(2) + "%") });
// 매물대 합계
const allPct = texts.filter((t) => /^\d+(\.\d+)?%$/.test(t.trim()));
// 마지막 라벨은 현재가 배지의 등락률(절대값) — 매물대 라벨에서 제외
const pctLabels = allPct.filter((t, i) => !(i === allPct.length - 1 && parseFloat(t) === Math.abs(+lastPct))).map((t) => parseFloat(t));
const sum = pctLabels.reduce((a, v) => a + v, 0);
res.push({ name: "매물대 % 합계(라벨 수=" + pctLabels.length + ": " + pctLabels.join("+") + ")", got: sum.toFixed(2), want: "100(반올림 오차 허용 ±0.5)", pass: Math.abs(sum - 100) <= 0.5 });
// readout: 마지막봉
const ro = await q(".stock-chart__readout");
res.push({ name: "읽기 줄 기본=마지막 봉", got: ro.slice(0, 60), want: last.trade_date, pass: ro.includes(last.trade_date) && ro.includes(nf(last.close)) });
// 일자별 표 첫 행
await p.getByRole("tab", { name: "일자별 시세" }).click();
await p.waitForSelector(".daily-table tbody tr");
const first = await p.$eval(".daily-table tbody tr", (r) => r.textContent);
const firstDate = await p.$eval(".daily-table tbody tr", (r) => r.querySelector("th,td").textContent.trim());
res.push({ name: "일자별 첫 행=최신일", got: firstDate, want: last.trade_date, pass: firstDate.replace(/\D/g, "").endsWith(last.trade_date.slice(2).replace(/-/g, "")) || firstDate.includes(last.trade_date) });
const rows = await p.$$eval(".daily-table tbody tr", (r) => r.map((x) => x.querySelector("th,td").textContent.trim()));
res.push({ name: "일자별 내림차순·60행", got: `${rows.length}행 ${rows[0]}..${rows.at(-1)}`, want: "60행 내림차순", pass: rows.length === 60 && rows[0] > rows.at(-1) });
res.push({ name: "일자별 첫 행 종가", got: first.slice(0, 80), want: nf(last.close), pass: first.includes(nf(last.close)) });
await b.close();
for (const r of res) console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.name}  got=${r.got}  want=${r.want}`);
console.log(`합계 PASS ${res.filter((r) => r.pass).length} / FAIL ${res.filter((r) => !r.pass).length}`);
