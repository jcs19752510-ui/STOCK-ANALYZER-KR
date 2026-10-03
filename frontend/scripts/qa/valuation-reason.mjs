// DEC-057 점검: PER/PBR 산정 불가 사유 표시(적자·자본잠식 / 재무 데이터 없음 / 알 수 없음).
// 전제: 시드 T00001(PER 적자·PBR 데이터 없음), T00002(PER 데이터 없음·PBR 자본잠식), T00003(사유 NULL=알 수 없음)
import { BASE, launch } from "./common.mjs";
const b = await launch();
const res = [];
const rec = (n, ok, note = "") => { res.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${note}`); };
const p = await (await b.newContext({ viewport: { width: 390, height: 900 } })).newPage();
const rows = async (code) => {
  await p.goto(`${BASE}/stocks/${code}`, { waitUntil: "networkidle" });
  return p.$$eval(".valuation-card__row", (e) => e.map((x) => x.textContent.replace(/\s+/g, " ").trim()));
};
let r = await rows("T00001");
rec("T00001 PER 적자·자본잠식, PBR 데이터 없음", /PER.*산정 불가\(적자·자본잠식\)/.test(r[0]) && /PBR.*산정 불가\(재무 데이터 없음\)/.test(r[1]), r.slice(0, 2).join(" | "));
r = await rows("T00002");
rec("T00002 PER 데이터 없음, PBR 적자·자본잠식", /PER.*산정 불가\(재무 데이터 없음\)/.test(r[0]) && /PBR.*산정 불가\(적자·자본잠식\)/.test(r[1]), r.slice(0, 2).join(" | "));
r = await rows("T00003");
rec("T00003 사유 없음: 원인 단정하지 않는 문구", /산정 불가\(적자이거나 재무 데이터 없음\)/.test(r[0]) && /산정 불가\(적자이거나 재무 데이터 없음\)/.test(r[1]), r.slice(0, 2).join(" | "));
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
