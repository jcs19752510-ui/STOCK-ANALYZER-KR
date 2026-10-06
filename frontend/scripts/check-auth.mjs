#!/usr/bin/env node
/**
 * 로그인(회원 인증) 순수 로직 검증(DEC-067). 실행:
 *   node --experimental-strip-types --test scripts/check-auth.mjs
 */
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import { isAdminOnlyBffPath, isAllowedBffPath, localIntradayBffEnabled, MAX_QUERY_LENGTH } from "../src/lib/auth/bffPaths.ts";
import {
  SECRET_MIN_LENGTH,
  SESSION_FRESH_SECONDS,
  REMEMBER_MAX_AGE_SECONDS,
  SESSION_MAX_AGE_SECONDS,
  authConfigProblem,
  authEnabled,
  cookieSecure,
  sessionCookieName,
} from "../src/lib/auth/config.ts";
import { classifyApiProbe, classifyLoginFailure } from "../src/lib/auth/loginFailure.ts";
import { endUserIp } from "../src/lib/auth/endUserIp.ts";
import { isSameOriginRequest } from "../src/lib/auth/origin.ts";
import { SAVED_USERNAME_KEY, loadSavedUsername, persistUsername } from "../src/lib/auth/savedUsername.ts";
import { safeNextPath } from "../src/lib/auth/redirect.ts";
import { isFresh, newSession, refreshed, remainingSeconds, signSession, verifySession } from "../src/lib/auth/session.ts";

const SECRET = "s".repeat(48);
const UID = "11111111-1111-4111-8111-111111111111";
const NOW = 1_800_000_000;
const SID = "22222222-2222-4222-8222-222222222222";
const user = { uid: UID, username: "kim", displayName: "김철수", role: "user" };
const mk = (u = user, now = NOW, o = {}) => newSession(u, now, { sessionId: SID, remember: false, ...o });
const headers = (h) => ({ get: (k) => h[k.toLowerCase()] ?? null });

// ------------------------------------------------------------------ 설정
test("authEnabled: 켜짐 값만 true, 기본은 꺼짐(로컬 동작 불변)", () => {
  for (const v of ["true", "TRUE", "1", "yes", "on", " true "]) assert.equal(authEnabled({ AUTH_REQUIRED: v }), true, v);
  for (const v of [undefined, "", "false", "0", "no", "off", "enabled", "truee"]) assert.equal(authEnabled({ AUTH_REQUIRED: v }), false, String(v));
});

test("쿠키 이름·Secure: 기본은 __Host- + Secure, 시험용 해제 스위치만 예외", () => {
  assert.equal(cookieSecure({}), true);
  assert.equal(sessionCookieName({}), "__Host-session");
  assert.equal(cookieSecure({ AUTH_COOKIE_INSECURE: "true" }), false);
  assert.equal(sessionCookieName({ AUTH_COOKIE_INSECURE: "true" }), "session");
});

test("authConfigProblem: 꺼져 있으면 문제 없음, 켜져 있으면 약한 설정을 모두 잡는다", () => {
  assert.equal(authConfigProblem({}), null);
  const good = {
    AUTH_REQUIRED: "true",
    SESSION_SECRET: "a".repeat(SECRET_MIN_LENGTH),
    PUBLIC_API_INTERNAL_TOKEN: "b".repeat(SECRET_MIN_LENGTH),
    NEXT_PUBLIC_API_BASE_URL: "https://api.example.com",
    NEXT_PUBLIC_BROWSER_API_BASE_URL: "same-origin",
    NEXT_PUBLIC_AUTH_ENABLED: "true",
  };
  assert.equal(authConfigProblem(good), null);
  for (const [key, bad] of [
    ["SESSION_SECRET", ""],
    ["SESSION_SECRET", "a".repeat(SECRET_MIN_LENGTH - 1)],
    ["PUBLIC_API_INTERNAL_TOKEN", undefined],
    ["PUBLIC_API_INTERNAL_TOKEN", "short"],
    ["NEXT_PUBLIC_API_BASE_URL", " "],
    ["NEXT_PUBLIC_BROWSER_API_BASE_URL", undefined],
    ["NEXT_PUBLIC_BROWSER_API_BASE_URL", "https://api.example.com"],
    ["NEXT_PUBLIC_AUTH_ENABLED", "false"],
  ]) {
    const problem = authConfigProblem({ ...good, [key]: bad });
    assert.ok(problem, `${key}=${bad}`);
    assert.ok(!problem.includes("a".repeat(8)), "설명에 비밀 값이 들어가면 안 된다");
  }
});

// ------------------------------------------------------------------ 세션 서명·검증
test("정상 왕복: 서명한 세션을 검증하면 같은 내용이 나온다", () => {
  const s = mk();
  assert.equal(s.exp - s.iat, SESSION_MAX_AGE_SECONDS);
  const back = verifySession(signSession(s, SECRET), SECRET, NOW + 10);
  assert.deepEqual(back, s);
});

test("틀린 비밀 키·내용 변조·서명 변조·형식 오류는 모두 null", () => {
  const token = signSession(mk(), SECRET);
  assert.equal(verifySession(token, "x".repeat(48), NOW), null);
  const [body, sig] = token.split(".");
  // 내용 변조: 아이디를 바꿔 같은 서명을 붙인다
  const forged = Buffer.from(JSON.stringify({ ...mk(), un: "admin" }), "utf8").toString("base64url");
  assert.equal(verifySession(`${forged}.${sig}`, SECRET, NOW), null);
  // 서명 변조(한 글자), 서명 길이 다름, 서명 없음, 구분자 여러 개
  const flipped = sig.slice(0, -1) + (sig.endsWith("A") ? "B" : "A");
  for (const bad of [`${body}.${flipped}`, `${body}.${sig}xx`, `${body}.`, `.${sig}`, body, `${body}.${sig}.${sig}`, "", "..", "garbage", "a.b"]) {
    assert.equal(verifySession(bad, SECRET, NOW), null, bad.slice(0, 30));
  }
  assert.equal(verifySession(undefined, SECRET, NOW), null);
  assert.equal(verifySession(token, "", NOW), null); // 비밀 키가 비어 있으면 어떤 것도 통과하지 않는다
  assert.equal(verifySession("x".repeat(5000), SECRET, NOW), null); // 비정상적으로 긴 입력
});

test("만료·미래 발급·과도한 수명·확인 시각 이상은 null", () => {
  const s = mk();
  assert.ok(verifySession(signSession(s, SECRET), SECRET, s.exp - 1));
  assert.equal(verifySession(signSession(s, SECRET), SECRET, s.exp), null); // 만료 시각 정각부터 거부
  assert.equal(verifySession(signSession(s, SECRET), SECRET, s.exp + 1), null);
  assert.equal(verifySession(signSession({ ...s, iat: NOW + 3600, exp: NOW + 3600 + 100, chk: NOW + 3600 }, SECRET), SECRET, NOW), null); // 미래 발급
  assert.equal(verifySession(signSession({ ...s, exp: NOW + SESSION_MAX_AGE_SECONDS * 3 }, SECRET), SECRET, NOW), null); // 허용 수명 초과
  assert.equal(verifySession(signSession({ ...s, chk: NOW + 3600 }, SECRET), SECRET, NOW), null); // 확인 시각이 미래
  assert.equal(verifySession(signSession({ ...s, chk: NOW - 7200 }, SECRET), SECRET, NOW), null); // 발급보다 훨씬 이전
});

test("필드 형식 검사: 올바른 서명이어도 모양이 틀리면 거부", () => {
  const s = mk();
  for (const bad of [
    { ...s, v: 1 }, { ...s, v: 2 }, { ...s, v: 4 }, { ...s, sid: undefined }, { ...s, sid: "nope" }, { ...s, sid: 5 }, { ...s, rm: 2 }, { ...s, rm: "1" }, { ...s, rm: undefined }, { ...s, uid: "not-a-uuid" }, { ...s, uid: 5 }, { ...s, un: "" }, { ...s, un: "k".repeat(33) },
    { ...s, dn: "" }, { ...s, dn: "가".repeat(41) }, { ...s, iat: "1" }, { ...s, exp: 1.5 }, { ...s, chk: -1 }, { ...s, exp: null },
  ]) {
    assert.equal(verifySession(signSession(bad, SECRET), SECRET, NOW), null, JSON.stringify(bad).slice(0, 60));
  }
  // 배열·문자열 본문
  for (const body of ['[1,2]', '"str"', "null", "not json"]) {
    const b = Buffer.from(body, "utf8").toString("base64url");
    const sig = createHmac("sha256", SECRET).update(b).digest("base64url");
    assert.equal(verifySession(`${b}.${sig}`, SECRET, NOW), null, body);
  }
});

test("서명은 알고리즘 혼동에 안전하다: 'none' 같은 값을 받아들이지 않는다", () => {
  const body = Buffer.from(JSON.stringify(mk()), "utf8").toString("base64url");
  assert.equal(verifySession(`${body}.none`, SECRET, NOW), null);
  assert.equal(verifySession(`${body}.`, SECRET, NOW), null);
});

test("신선도: 5분까지는 신선, 그 뒤에는 아님 / 갱신은 만료 시각을 늘리지 않는다", () => {
  const s = mk();
  assert.equal(isFresh(s, NOW + SESSION_FRESH_SECONDS), true);
  assert.equal(isFresh(s, NOW + SESSION_FRESH_SECONDS + 1), false);
  const r = refreshed(s, NOW + 400);
  assert.equal(r.exp, s.exp);
  assert.equal(r.iat, s.iat);
  assert.equal(r.chk, NOW + 400);
  assert.equal(isFresh(r, NOW + 401), true);
  assert.equal(remainingSeconds(s, NOW), SESSION_MAX_AGE_SECONDS);
  assert.equal(remainingSeconds(s, s.exp + 5), 0);
  assert.ok(verifySession(signSession(r, SECRET), SECRET, NOW + 400));
});

test("회원 id는 소문자로 정규화된다", () => {
  const s = mk({ ...user, uid: UID.toUpperCase() });
  assert.equal(s.uid, UID);
  assert.equal(verifySession(signSession(s, SECRET), SECRET, NOW).uid, UID);
  const up = mk(user, NOW, { sessionId: SID.toUpperCase() });
  assert.equal(up.sid, SID);
});

// ------------------------------------------------------------------ 로그인 상태 유지 30일 (DEC-070)
test("로그인 상태 유지: 기본 8시간, 체크하면 절대 30일, 쿠키에 세션 id·유지 여부가 담긴다", () => {
  const normal = mk();
  assert.equal(normal.exp - normal.iat, SESSION_MAX_AGE_SECONDS);
  assert.deepEqual([normal.rm, normal.sid], [0, SID]);
  const kept = mk(user, NOW, { remember: true });
  assert.equal(kept.exp - kept.iat, 30 * 24 * 3600);
  assert.equal(REMEMBER_MAX_AGE_SECONDS, 30 * 24 * 3600);
  assert.equal(kept.rm, 1);
  assert.deepEqual(verifySession(signSession(kept, SECRET), SECRET, NOW + 29 * 24 * 3600), kept); // 29일째까지 유효
  assert.equal(verifySession(signSession(kept, SECRET), SECRET, NOW + 30 * 24 * 3600), null); // 30일 정각에 만료(절대 만료)
});

test("로그인 상태 유지: 서버가 정한 수명을 따르되 허용 상한을 넘지 못한다", () => {
  assert.equal(mk(user, NOW, { remember: true, lifetimeSeconds: 100 }).exp, NOW + 100);
  assert.equal(mk(user, NOW, { remember: true, lifetimeSeconds: 10 * REMEMBER_MAX_AGE_SECONDS }).exp, NOW + REMEMBER_MAX_AGE_SECONDS);
  assert.equal(mk(user, NOW, { remember: false, lifetimeSeconds: REMEMBER_MAX_AGE_SECONDS }).exp, NOW + SESSION_MAX_AGE_SECONDS); // 유지 아님 → 8시간 상한
  assert.equal(mk(user, NOW, { remember: false, lifetimeSeconds: 0 }).exp, NOW + 1); // 이상한 값도 최소 1초
});

test("로그인 상태 유지: 8시간 쿠키(rm=0)를 30일로 늘려 위조하거나, 30일 쿠키를 31일로 늘려도 거부", () => {
  const normal = mk();
  assert.equal(verifySession(signSession({ ...normal, exp: NOW + 30 * 24 * 3600 }, SECRET), SECRET, NOW), null); // 서명이 맞아도 rm=0이면 8시간 상한
  const kept = mk(user, NOW, { remember: true });
  assert.equal(verifySession(signSession({ ...kept, exp: NOW + 31 * 24 * 3600 }, SECRET), SECRET, NOW), null);
  assert.ok(verifySession(signSession({ ...kept, exp: NOW + 30 * 24 * 3600 + 30 }, SECRET), SECRET, NOW)); // 시계 오차 60초 이내 허용
  // 서명 없이 rm만 바꾸면 서명 불일치
  const [b, sig] = signSession(normal, SECRET).split(".");
  const tampered = Buffer.from(JSON.stringify({ ...normal, rm: 1, exp: NOW + 30 * 24 * 3600 }), "utf8").toString("base64url");
  assert.equal(verifySession(`${tampered}.${sig}`, SECRET, NOW), null);
  assert.ok(b.length > 0);
});

test("로그인 상태 유지: 5분 확인(refreshed)은 30일 만료를 늘리지 않고 세션 id를 유지한다", () => {
  const kept = mk(user, NOW, { remember: true });
  const r = refreshed(kept, NOW + 3 * 24 * 3600);
  assert.equal(r.exp, kept.exp);
  assert.equal(r.sid, SID);
  assert.equal(r.rm, 1);
  assert.ok(verifySession(signSession(r, SECRET), SECRET, NOW + 3 * 24 * 3600));
  assert.equal(isFresh(kept, NOW + 3 * 24 * 3600), false); // 3일 뒤 첫 요청은 반드시 서버 확인을 거친다
});

test("옛 형식 쿠키(v1·v2: 세션 id·권한 표시 없음)는 거부된다(배포 후 한 번 다시 로그인)", () => {
  const { sid, rm, rl, ...legacy } = mk();
  assert.ok(sid && rm === 0 && rl === "u");
  assert.equal(verifySession(signSession({ ...legacy, v: 1 }, SECRET), SECRET, NOW), null);
  assert.equal(verifySession(signSession({ ...legacy, sid, rm, v: 2 }, SECRET), SECRET, NOW), null); // v2는 권한 표시(rl)가 없다
  assert.equal(verifySession(signSession(legacy, SECRET), SECRET, NOW), null);
});

test("권한 표시(rl): 일반 u / 관리자 a만 허용하고 서명 없이 바꿀 수 없다", () => {
  assert.equal(mk().rl, "u");
  const admin = mk({ ...user, role: "admin" });
  assert.equal(admin.rl, "a");
  assert.deepEqual(verifySession(signSession(admin, SECRET), SECRET, NOW), admin);
  for (const bad of ["admin", "x", "", 1, null, undefined]) assert.equal(verifySession(signSession({ ...admin, rl: bad }, SECRET), SECRET, NOW), null, String(bad));
  // 일반 사용자 쿠키의 rl을 a로 바꿔 같은 서명을 붙이면 거부
  const [, sig] = signSession(mk(), SECRET).split(".");
  const forged = Buffer.from(JSON.stringify({ ...mk(), rl: "a" }), "utf8").toString("base64url");
  assert.equal(verifySession(`${forged}.${sig}`, SECRET, NOW), null);
  // 확인 갱신은 새 권한을 반영할 수 있다(5분 확인 때 API가 알려 준 값)
  const demoted = refreshed({ ...admin, rl: "u" }, NOW + 10);
  assert.equal(demoted.rl, "u");
});

// ------------------------------------------------------------------ 리다이렉트 안전성
test("safeNextPath: 같은 사이트의 일반 경로는 그대로", () => {
  for (const [raw, expected] of [
    ["/", "/"], ["/stocks", "/stocks"], ["/stocks/005930?date=2026-10-01", "/stocks/005930?date=2026-10-01"],
    ["/screener/pattern?market=KOSPI&x=1", "/screener/pattern?market=KOSPI&x=1"], ["/members", "/members"],
  ]) assert.equal(safeNextPath(raw), expected);
});

test("safeNextPath: 열린 리다이렉트 시도는 모두 기본 경로", () => {
  const attacks = [
    "https://evil.example.com", "http://evil.example.com/x", "//evil.example.com", "///evil.example.com", "/\\evil.example.com",
    "\\\\evil.example.com", "/\t/evil.example.com", "/\n/evil.example.com", "/%0a/evil.example.com".replace("%0a", "\n"), "javascript:alert(1)",
    "data:text/html,x", "evil.example.com", "", " /x", "/login", "/login?next=/", "/auth/session", "/auth", "/auth/renew?next=/x",
    "/" + "a".repeat(600), "/x\u0000y", "/x\u007fy",
  ];
  for (const raw of attacks) assert.equal(safeNextPath(raw), "/", JSON.stringify(raw).slice(0, 50));
  for (const raw of [undefined, null, 5, {}, []]) assert.equal(safeNextPath(raw), "/");
  assert.equal(safeNextPath("//x", "/members"), "/members"); // 기본 경로 지정
});

test("safeNextPath: 인코딩된 슬래시는 경로 문자일 뿐 다른 사이트로 가지 못한다", () => {
  const out = safeNextPath("/%2F%2Fevil.example.com");
  assert.ok(out.startsWith("/") && !out.startsWith("//"));
});

// ------------------------------------------------------------------ 같은 사이트 확인(CSRF)
test("isSameOriginRequest: Origin의 호스트가 Host와 같을 때만 통과", () => {
  assert.equal(isSameOriginRequest(headers({ origin: "https://web.example.com", host: "web.example.com" })), true);
  assert.equal(isSameOriginRequest(headers({ origin: "https://WEB.example.com", host: "web.example.com" })), true);
  assert.equal(isSameOriginRequest(headers({ origin: "http://localhost:4312", host: "localhost:4312" })), true);
  assert.equal(isSameOriginRequest(headers({ origin: "https://web.example.com", "x-forwarded-host": "web.example.com", host: "internal:3000" })), true);
  for (const h of [
    { origin: "https://evil.example.com", host: "web.example.com" }, { host: "web.example.com" }, { origin: "https://web.example.com" },
    { origin: "null", host: "web.example.com" }, { origin: "not a url", host: "web.example.com" }, { origin: "https://web.example.com.evil.com", host: "web.example.com" },
    { origin: "https://web.example.com:8443", host: "web.example.com" }, {},
  ]) assert.equal(isSameOriginRequest(headers(h)), false, JSON.stringify(h));
});

// ------------------------------------------------------------------ 대행 허용 경로
test("isAllowedBffPath: 조회 화면에 필요한 경로만 허용", () => {
  for (const p of [
    "/api/v1/screen", "/api/v1/screen/pattern", "/api/v1/stocks", "/api/v1/stocks/quotes", "/api/v1/stocks/005930/metrics",
    "/api/v1/stocks/005930/prices", "/api/v1/stocks/005930/earnings", "/api/v1/stocks/T00001/pattern-check", "/api/v1/market-summary",
  ]) assert.equal(isAllowedBffPath(p), true, p);
  for (const p of [
    "/api/v1/live", "/api/v1/health", "/api/v1/internal/members", "/api/v1/internal/auth/login", "/api/v1/local/status", "/api/v1/local/stocks/005930/orderbook",
    "/api/v1/stocks/005930", "/api/v1/stocks/005930/metrics/", "/api/v1/stocks/0059300/metrics", "/api/v1/stocks/00593/metrics", "/api/v1/stocks/../internal/members",
    "/api/v1/stocks/005930/../../internal/members", "/api/v1/calendar", "/api/v2/screen", "/api/v1/screen/extra", "/api/v1//screen", "/openapi.json", "/docs", "", "api/v1/screen",
    "/api/v1/stocks/%2e%2e/internal", "/api/v1/stocks/005930/metrics%2f..", "/API/V1/screen",
  ]) assert.equal(isAllowedBffPath(p), false, p);
  assert.ok(MAX_QUERY_LENGTH > 0);
});

test("관리자 전용 투자자 경로: 정확한 형식만 대행 허용(그 밖의 internal 경로는 계속 막힘)", () => {
  assert.equal(isAllowedBffPath("/api/v1/internal/admin/stocks/005930/investor"), true);
  for (const p of [
    "/api/v1/internal/admin/stocks/005930", "/api/v1/internal/admin/stocks/0059301/investor", "/api/v1/internal/admin/stocks/005930/investor/",
    "/api/v1/internal/admin/stocks/../investor", "/api/v1/internal/admin", "/api/v1/internal/admin/members", "/api/v1/internal/admin/action",
    "/api/v1/internal/owner/stocks/005930/investor", "/api/v1/internal/members", "/api/v1/internal/auth/signup", "/api/v1/internal/auth/session-check",
  ]) assert.equal(isAllowedBffPath(p), false, p);
});

// ------------------------------------------------------------------ 방문자 IP
test("endUserIp: 신뢰 프록시 단수를 알 때만 오른쪽에서 N번째, 아니면 null", () => {
  const h = headers({ "x-forwarded-for": "9.9.9.9, 203.0.113.5, 10.0.0.1" });
  assert.equal(endUserIp(h, {}), null);
  assert.equal(endUserIp(h, { FRONTEND_TRUSTED_PROXY_HOPS: "0" }), null);
  assert.equal(endUserIp(h, { FRONTEND_TRUSTED_PROXY_HOPS: "1" }), "10.0.0.1");
  assert.equal(endUserIp(h, { FRONTEND_TRUSTED_PROXY_HOPS: "2" }), "203.0.113.5");
  assert.equal(endUserIp(h, { FRONTEND_TRUSTED_PROXY_HOPS: "9" }), null);
  assert.equal(endUserIp(headers({}), { FRONTEND_TRUSTED_PROXY_HOPS: "1" }), null);
});

// ------------------------------------------------------------------ 아이디 저장
const memStore = (init = {}) => {
  const m = new Map(Object.entries(init));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => void m.set(k, v), removeItem: (k) => void m.delete(k), _m: m };
};

test("아이디 저장: 체크하면 아이디만 저장, 해제하면 지운다", () => {
  const st = memStore();
  assert.equal(persistUsername(st, " jcs1973 ", true), true);
  assert.equal(st.getItem(SAVED_USERNAME_KEY), "jcs1973");
  assert.equal(loadSavedUsername(st), "jcs1973");
  assert.equal(persistUsername(st, "jcs1973", false), false);
  assert.equal(st.getItem(SAVED_USERNAME_KEY), null);
  assert.equal([...st._m.keys()].length, 0);
});

test("아이디 저장: 형식이 틀린 값은 저장하지 않고, 저장소의 변조 값은 지우고 무시", () => {
  const st = memStore();
  for (const bad of ["", "   ", "한글", "a b", "<script>", "x".repeat(65), "-start", "a\nb"]) {
    assert.equal(persistUsername(st, bad, true), false, JSON.stringify(bad));
    assert.equal(st.getItem(SAVED_USERNAME_KEY), null);
  }
  for (const tampered of ["<img src=x onerror=1>", "a b", "", "x".repeat(65)]) {
    const t = memStore({ [SAVED_USERNAME_KEY]: tampered });
    assert.equal(loadSavedUsername(t), null, JSON.stringify(tampered));
    assert.equal(t.getItem(SAVED_USERNAME_KEY), null); // 변조 값 삭제
  }
});

test("아이디 저장: 저장소가 없거나 예외를 던져도 조용히 동작", () => {
  assert.equal(loadSavedUsername(null), null);
  assert.equal(loadSavedUsername(undefined), null);
  assert.equal(persistUsername(null, "kim", true), false);
  const boom = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("quota"); }, removeItem() { throw new Error("blocked"); } };
  assert.equal(loadSavedUsername(boom), null);
  assert.equal(persistUsername(boom, "kim", true), false);
  assert.equal(persistUsername(boom, "kim", false), false);
});

test("아이디 저장: 비밀번호를 저장하는 코드 경로가 없다(소스에 password 저장 호출 없음)", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../src/lib/auth/savedUsername.ts", import.meta.url), "utf8");
  assert.ok(!/setItem\([^)]*password/i.test(src));
  const form = readFileSync(new URL("../src/components/LoginForm.tsx", import.meta.url), "utf8");
  assert.ok(!/(localStorage|sessionStorage|document\.cookie)[^;\n]*password/i.test(form));
});

// ------------------------------------------------------------------ 로그인 실패 분류(내부 토큰 불일치를 비밀번호 오류로 오인하지 않는다)
test("classifyLoginFailure: 401은 오류 코드가 INVALID_CREDENTIALS일 때만 비밀번호 오류", () => {
  assert.equal(classifyLoginFailure(401, "INVALID_CREDENTIALS"), "invalid");
  for (const code of ["AUTH_REQUIRED", undefined, null, "", "FEATURE_DISABLED", 5]) assert.equal(classifyLoginFailure(401, code), "unavailable", String(code)); // 토큰 불일치 등 서버 설정 오류
});

test("classifyLoginFailure: 승인 대기·사용 중지·시도 제한·그 밖의 오류", () => {
  assert.equal(classifyLoginFailure(403, "PENDING_APPROVAL"), "pending");
  assert.equal(classifyLoginFailure(403, "ACCOUNT_DISABLED"), "disabled");
  assert.equal(classifyLoginFailure(403, "FORBIDDEN"), "unavailable");
  assert.equal(classifyLoginFailure(429, "LOGIN_RATE_LIMITED"), "rate_limited");
  for (const st of [400, 404, 500, 502, 503]) assert.equal(classifyLoginFailure(st, "INVALID_CREDENTIALS"), "unavailable", String(st));
});

test("classifyApiProbe: 200 정상 / 401 토큰 불일치 / 404 회원 DB 설정 없음 / 그 밖 연결 불가", () => {
  assert.equal(classifyApiProbe(200), "ok");
  assert.equal(classifyApiProbe(401), "token_mismatch");
  assert.equal(classifyApiProbe(404), "auth_not_configured");
  for (const st of [null, 0, 400, 403, 429, 500, 502, 503]) assert.equal(classifyApiProbe(st), "unreachable", String(st));
});

// ------------------------------------------------------------------ 로컬 서버 로그인(DEC-075): 개인 로컬 모드 경로는 로컬 빌드에서만 대행 허용
const LOCAL_ON = { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "true" };
const LOCAL_PATHS = [
  "/api/v1/local/status", "/api/v1/local/stocks/005930/minutes", "/api/v1/local/stocks/005930/ticks",
  "/api/v1/local/stocks/005930/orderbook", "/api/v1/local/stocks/T00001/investor",
];

test("개인 로컬 모드 경로: 운영 빌드(스위치 없음/false)에서는 계속 막힘", () => {
  for (const env of [{}, { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "false" }, { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "" }, { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "1" }]) {
    for (const p of LOCAL_PATHS) assert.equal(isAllowedBffPath(p, env), false, `${p} ${JSON.stringify(env)}`);
    assert.equal(localIntradayBffEnabled(env), false);
  }
});

test("개인 로컬 모드 경로: 로컬 빌드(true)에서만 정확한 형식이 열림", () => {
  assert.equal(localIntradayBffEnabled(LOCAL_ON), true);
  for (const p of LOCAL_PATHS) assert.equal(isAllowedBffPath(p, LOCAL_ON), true, p);
  for (const p of [
    "/api/v1/local", "/api/v1/local/", "/api/v1/local/stocks/005930", "/api/v1/local/stocks/005930/other", "/api/v1/local/stocks/00593/ticks",
    "/api/v1/local/stocks/0059300/ticks", "/api/v1/local/stocks/005930/ticks/", "/api/v1/local/../internal/members", "/api/v1/local/stocks/../../internal/auth/login",
    "/api/v1/local/status/extra", "/api/v1/LOCAL/status", "/api/v1/local/stocks/%2e%2e/ticks",
    "/api/v1/internal/auth/login", "/api/v1/live", "/docs",
  ]) assert.equal(isAllowedBffPath(p, LOCAL_ON), false, p);
  // 기존 허용 경로는 스위치와 무관하게 그대로
  assert.equal(isAllowedBffPath("/api/v1/screen", {}), true);
  assert.equal(isAllowedBffPath("/api/v1/screen", LOCAL_ON), true);
});

test("전 종목 준실시간 시세 경로: 로컬 빌드에서만 열리고 관리자 전용(DEC-084)", () => {
  const MARKET = ["/api/v1/local/market/quotes", "/api/v1/local/market/status"];
  for (const p of MARKET) {
    assert.equal(isAllowedBffPath(p, {}), false, p);
    assert.equal(isAllowedBffPath(p, { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "false" }), false, p);
    assert.equal(isAllowedBffPath(p, LOCAL_ON), true, p);
    assert.equal(isAdminOnlyBffPath(p), true, p);
  }
  for (const p of ["/api/v1/local/market", "/api/v1/local/market/", "/api/v1/local/market/quotes/", "/api/v1/local/market/other", "/api/v1/local/market/quotes/x", "/api/v1/local/market/../status"]) {
    assert.equal(isAllowedBffPath(p, LOCAL_ON), false, p);
    assert.equal(isAdminOnlyBffPath(p), false, p);
  }
});

test("증권사 조건검색 경로: 로컬 빌드에서만 열리고 관리자 전용(DEC-088)", () => {
  const PSEARCH = ["/api/v1/local/psearch/conditions", "/api/v1/local/psearch/results"];
  for (const p of PSEARCH) {
    assert.equal(isAllowedBffPath(p, {}), false, p);
    assert.equal(isAllowedBffPath(p, { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "false" }), false, p);
    assert.equal(isAllowedBffPath(p, LOCAL_ON), true, p); // 쿼리(?seq=)는 경로 판정에 넣지 않는다(pathname만 검사, quotes?codes=와 같다)
    assert.equal(isAdminOnlyBffPath(p), true, p);
  }
  for (const p of ["/api/v1/local/psearch", "/api/v1/local/psearch/", "/api/v1/local/psearch/results/", "/api/v1/local/psearch/other", "/api/v1/local/psearch/results/x", "/api/v1/local/psearch/../status"]) {
    assert.equal(isAllowedBffPath(p, LOCAL_ON), false, p);
    assert.equal(isAdminOnlyBffPath(p), false, p);
  }
});

test("장중 기준 스크리닝 경로: 로컬 빌드에서만 열리고 관리자 전용(DEC-089)", () => {
  const SCREEN = ["/api/v1/local/screen", "/api/v1/local/screen/pattern"];
  for (const p of SCREEN) {
    assert.equal(isAllowedBffPath(p, {}), false, p);
    assert.equal(isAllowedBffPath(p, { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "false" }), false, p);
    assert.equal(isAllowedBffPath(p, { NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED: "1" }), false, p);
    assert.equal(isAllowedBffPath(p, LOCAL_ON), true, p); // 쿼리(?snapshot_id=)는 경로 판정에 넣지 않는다
    assert.equal(isAdminOnlyBffPath(p), true, p);
  }
  for (const p of [
    "/api/v1/local/screen/", "/api/v1/local/screen/pattern/", "/api/v1/local/screen/other", "/api/v1/local/screen/pattern/x", "/api/v1/local/screens",
    "/api/v1/local/screen/../status", "/api/v1/local/screen/%2e%2e/status", "/api/v1/local/Screen", "/api/v1/LOCAL/screen", "/api/v1/local/screenpattern", "/api/v1/local//screen",
  ]) {
    assert.equal(isAllowedBffPath(p, LOCAL_ON), false, p);
    assert.equal(isAdminOnlyBffPath(p), false, p);
  }
  // 기존 일봉 경로는 그대로 열려 있고 관리자 전용이 아니다
  for (const p of ["/api/v1/screen", "/api/v1/screen/pattern"]) {
    assert.equal(isAllowedBffPath(p, {}), true, p);
    assert.equal(isAdminOnlyBffPath(p), false, p);
  }
});

test("로컬 투자자 수급 경로는 관리자 전용으로 분류(DEC-074와 같은 규칙)", () => {
  assert.equal(isAdminOnlyBffPath("/api/v1/local/stocks/005930/investor"), true);
  for (const p of ["/api/v1/local/stocks/005930/ticks", "/api/v1/local/stocks/005930/orderbook", "/api/v1/screen", "/api/v1/local/stocks/005930/investor/x"]) {
    assert.equal(isAdminOnlyBffPath(p), false, p);
  }
});
