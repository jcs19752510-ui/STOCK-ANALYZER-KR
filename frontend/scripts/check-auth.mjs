#!/usr/bin/env node
/**
 * 로그인(회원 인증) 순수 로직 검증(DEC-067). 실행:
 *   node --experimental-strip-types --test scripts/check-auth.mjs
 */
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import { isAllowedBffPath, MAX_QUERY_LENGTH } from "../src/lib/auth/bffPaths.ts";
import {
  SECRET_MIN_LENGTH,
  SESSION_FRESH_SECONDS,
  SESSION_MAX_AGE_SECONDS,
  authConfigProblem,
  authEnabled,
  cookieSecure,
  sessionCookieName,
} from "../src/lib/auth/config.ts";
import { endUserIp } from "../src/lib/auth/endUserIp.ts";
import { isSameOriginRequest } from "../src/lib/auth/origin.ts";
import { safeNextPath } from "../src/lib/auth/redirect.ts";
import { isFresh, newSession, refreshed, remainingSeconds, signSession, verifySession } from "../src/lib/auth/session.ts";

const SECRET = "s".repeat(48);
const UID = "11111111-1111-4111-8111-111111111111";
const NOW = 1_800_000_000;
const user = { uid: UID, username: "kim", displayName: "김철수" };
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
  const s = newSession(user, NOW);
  assert.equal(s.exp - s.iat, SESSION_MAX_AGE_SECONDS);
  const back = verifySession(signSession(s, SECRET), SECRET, NOW + 10);
  assert.deepEqual(back, s);
});

test("틀린 비밀 키·내용 변조·서명 변조·형식 오류는 모두 null", () => {
  const token = signSession(newSession(user, NOW), SECRET);
  assert.equal(verifySession(token, "x".repeat(48), NOW), null);
  const [body, sig] = token.split(".");
  // 내용 변조: 아이디를 바꿔 같은 서명을 붙인다
  const forged = Buffer.from(JSON.stringify({ ...newSession(user, NOW), un: "admin" }), "utf8").toString("base64url");
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
  const s = newSession(user, NOW);
  assert.ok(verifySession(signSession(s, SECRET), SECRET, s.exp - 1));
  assert.equal(verifySession(signSession(s, SECRET), SECRET, s.exp), null); // 만료 시각 정각부터 거부
  assert.equal(verifySession(signSession(s, SECRET), SECRET, s.exp + 1), null);
  assert.equal(verifySession(signSession({ ...s, iat: NOW + 3600, exp: NOW + 3600 + 100, chk: NOW + 3600 }, SECRET), SECRET, NOW), null); // 미래 발급
  assert.equal(verifySession(signSession({ ...s, exp: NOW + SESSION_MAX_AGE_SECONDS * 3 }, SECRET), SECRET, NOW), null); // 허용 수명 초과
  assert.equal(verifySession(signSession({ ...s, chk: NOW + 3600 }, SECRET), SECRET, NOW), null); // 확인 시각이 미래
  assert.equal(verifySession(signSession({ ...s, chk: NOW - 7200 }, SECRET), SECRET, NOW), null); // 발급보다 훨씬 이전
});

test("필드 형식 검사: 올바른 서명이어도 모양이 틀리면 거부", () => {
  const s = newSession(user, NOW);
  for (const bad of [
    { ...s, v: 2 }, { ...s, uid: "not-a-uuid" }, { ...s, uid: 5 }, { ...s, un: "" }, { ...s, un: "k".repeat(33) },
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
  const body = Buffer.from(JSON.stringify(newSession(user, NOW)), "utf8").toString("base64url");
  assert.equal(verifySession(`${body}.none`, SECRET, NOW), null);
  assert.equal(verifySession(`${body}.`, SECRET, NOW), null);
});

test("신선도: 5분까지는 신선, 그 뒤에는 아님 / 갱신은 만료 시각을 늘리지 않는다", () => {
  const s = newSession(user, NOW);
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
  const s = newSession({ ...user, uid: UID.toUpperCase() }, NOW);
  assert.equal(s.uid, UID);
  assert.equal(verifySession(signSession(s, SECRET), SECRET, NOW).uid, UID);
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
