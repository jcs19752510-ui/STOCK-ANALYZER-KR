// DEC-077 점검: 잠든 API가 깨어나는 동안의 일시적 실패에도 로그인이 성공하는지(운영에서 "서버에 연결하지 못했습니다"로 실패한 상황 재현).
// 이 스크립트가 가짜 API(포트 4341)를 띄우고, 로그인을 켠 웹(4342)이 그 API를 바라보도록 미리 실행되어 있어야 한다:
//   export AUTH_REQUIRED=true SESSION_SECRET=$(openssl rand -hex 32) PUBLIC_API_INTERNAL_TOKEN=$(openssl rand -hex 32) \
//          NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:4341 NEXT_PUBLIC_BROWSER_API_BASE_URL=same-origin NEXT_PUBLIC_AUTH_ENABLED=true AUTH_COOKIE_INSECURE=true
//   npm run build && npx next start -H 127.0.0.1 -p 4342
// 실행: QA_BASE=http://127.0.0.1:4342 node scripts/qa/login-cold-start.mjs
import http from "node:http";

const BASE = process.env.QA_BASE ?? "http://127.0.0.1:4342";
const PORT = 4341;
const res = [];
const rec = (n, pass, note = "") => { res.push(pass); console.log(`${pass ? "PASS" : "FAIL"}  ${n}  ${note}`); };

const meta = { data_freshness: null, disclaimer: "x", generated_at: "2026-10-06T09:00:00+09:00" };
const okLogin = JSON.stringify({ meta, error: null, data: { user_id: "11111111-1111-4111-8111-111111111111", username: "kim", display_name: "김철수", role: "admin", session_id: "22222222-2222-4222-8222-222222222222", expires_in_seconds: 28800 } });
const err = (code) => JSON.stringify({ meta, data: null, error: { code, message: "x" } });

let plan = () => ({ kind: "ok" });
let hits = 0;
const server = http.createServer((req, res2) => {
  if (!req.url.startsWith("/api/v1/internal/auth/login")) { res2.writeHead(404); res2.end(); return; }
  const n = hits; hits += 1;
  const step = plan(n);
  if (step.kind === "reset") { req.socket.destroy(); return; }
  const status = step.status ?? 200;
  const body = step.kind === "ok" ? okLogin : err(step.code ?? "SERVICE_UNAVAILABLE");
  res2.writeHead(status, { "content-type": "application/json" });
  res2.end(body);
});
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

async function login(password = "Whatever-1234!") {
  hits = 0;
  const t0 = Date.now();
  const r = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: new URL(BASE).origin },
    body: JSON.stringify({ username: "kim", password, next: "/", remember: false }),
  });
  const body = await r.json().catch(() => ({}));
  return { status: r.status, body, hits, sec: ((Date.now() - t0) / 1000).toFixed(1), cookie: (r.headers.get("set-cookie") ?? "").includes("session=") };
}

{ plan = (n) => (n < 2 ? { status: 503 } : { kind: "ok" });
  const r = await login();
  rec("API가 503을 두 번 돌려준 뒤 성공: 로그인 성공 + 쿠키", r.status === 200 && r.body.ok === true && r.cookie, `${r.status} ${JSON.stringify(r.body)} ${r.sec}s`);
  rec("API가 503을 두 번 돌려준 뒤 성공: API 호출 3회", r.hits === 3, `hits=${r.hits}`); }
{ plan = (n) => (n < 1 ? { kind: "reset" } : { kind: "ok" });
  const r = await login();
  rec("연결이 끊긴 뒤 성공(깨어나는 중): 로그인 성공", r.status === 200 && r.body.ok === true, `${r.status} ${r.sec}s hits=${r.hits}`); }
{ plan = (n) => (n < 1 ? { status: 502 } : { kind: "ok" });
  const r = await login();
  rec("502 한 번 뒤 성공: 로그인 성공", r.status === 200 && r.body.ok === true, `${r.status} ${r.sec}s hits=${r.hits}`); }
{ plan = () => ({ status: 401, code: "INVALID_CREDENTIALS" });
  const r = await login();
  rec("틀린 비밀번호(401 INVALID_CREDENTIALS): 재시도 없이 즉시 비밀번호 오류", r.status === 401 && r.body.code === "INVALID_CREDENTIALS" && r.hits === 1, `${r.status} ${JSON.stringify(r.body)} hits=${r.hits} ${r.sec}s`); }
{ plan = () => ({ status: 401, code: "AUTH_REQUIRED" });
  const r = await login();
  rec("내부 토큰 불일치(401 AUTH_REQUIRED): 재시도 없이, 비밀번호 오류로 보이지 않음", r.status !== 200 && r.body.code !== "INVALID_CREDENTIALS" && r.hits === 1, `${r.status} ${JSON.stringify(r.body)} hits=${r.hits}`); }
{ plan = () => ({ status: 429, code: "LOGIN_RATE_LIMITED" });
  const r = await login();
  rec("429 한도 초과: 재시도 없이 즉시", r.hits === 1 && r.status !== 200, `${r.status} ${JSON.stringify(r.body)} hits=${r.hits}`); }
{ plan = () => ({ status: 503 });
  const r = await login();
  rec("계속 503: 3번 시도 뒤 '연결하지 못했습니다' 계열 오류(성공으로 보이지 않음)", r.status !== 200 && r.body.ok !== true && r.hits === 3, `${r.status} ${JSON.stringify(r.body)} hits=${r.hits} ${r.sec}s`); }

server.closeAllConnections?.();
server.close();
console.log(res.every(Boolean) ? "ALL PASS" : "SOME FAIL", `(${res.filter(Boolean).length}/${res.length})`);
process.exit(res.every(Boolean) ? 0 : 1);
