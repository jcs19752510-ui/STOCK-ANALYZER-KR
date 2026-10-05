import { createHmac, timingSafeEqual } from "node:crypto";
import { REMEMBER_MAX_AGE_SECONDS, SESSION_FRESH_SECONDS, SESSION_MAX_AGE_SECONDS } from "./config.ts";

/**
 * 서명된 세션 쿠키(상태 없는 세션, DEC-067 설계서 §4·§7). 서버가 비밀 키(`SESSION_SECRET`)로 HMAC-SHA256 서명하므로 브라우저에서 바꿀 수 없다.
 * 쿠키에는 회원 id·아이디·이름·발급/만료/마지막 확인 시각만 들어 있다(비밀번호·해시 없음).
 *
 * 서버 쪽 세션 목록(DEC-070): 쿠키의 `sid`는 API가 로그인 때 만든 세션 id다. 5분마다(`chk`) API가 "이 세션이 취소·만료되지 않았고 회원이 활성인지"를
 * 확인하므로, 로그아웃·비밀번호 변경·회원 비활성화·관리자 세션 취소가 **늦어도 5분 안에** 모든 기기에 반영된다(30일 유지 쿠키 포함).
 * 수명은 절대 만료다: 기본 8시간(`rm=0`), "로그인 상태 유지"는 30일(`rm=1`). 사용해도 늘어나지 않는다.
 */
export interface SessionPayload {
  v: 2;
  uid: string; // 회원 id(UUID)
  sid: string; // 서버 쪽 세션 id(UUID)
  rm: 0 | 1; // 1 = 로그인 상태 유지(30일)
  un: string; // 아이디
  dn: string; // 표시 이름
  iat: number; // 발급 시각(초)
  exp: number; // 만료 시각(초)
  chk: number; // API로 회원이 활성임을 마지막으로 확인한 시각(초)
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_TOKEN_LENGTH = 2048;
const CLOCK_SKEW_SECONDS = 60;

function mac(body: string, secret: string): Buffer {
  return createHmac("sha256", secret).update(body).digest();
}

export function signSession(payload: SessionPayload, secret: string): string {
  const body = Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
  return `${body}.${mac(body, secret).toString("base64url")}`;
}

function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

/** 서명·형식·만료를 모두 확인한다. 하나라도 어긋나면 null(이유는 알리지 않는다). */
export function verifySession(
  token: string | undefined | null,
  secret: string,
  nowSeconds: number,
): SessionPayload | null {
  if (!token || !secret || token.length > MAX_TOKEN_LENGTH) return null;
  const parts = token.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  const [body, signature] = parts;
  let given: Buffer;
  try {
    given = Buffer.from(signature, "base64url");
  } catch {
    return null;
  }
  const expected = mac(body, secret);
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return null;
  let data: unknown;
  try {
    data = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const p = data as Record<string, unknown>;
  if (
    p.v !== 2 ||
    typeof p.uid !== "string" ||
    !UUID.test(p.uid) ||
    typeof p.sid !== "string" ||
    !UUID.test(p.sid) ||
    (p.rm !== 0 && p.rm !== 1) ||
    typeof p.un !== "string" ||
    p.un.length < 1 ||
    p.un.length > 32 ||
    typeof p.dn !== "string" ||
    p.dn.length < 1 ||
    p.dn.length > 40 ||
    !isInt(p.iat) ||
    !isInt(p.exp) ||
    !isInt(p.chk)
  ) {
    return null;
  }
  if (p.exp <= nowSeconds) return null; // 만료
  if (p.iat > nowSeconds + CLOCK_SKEW_SECONDS) return null; // 미래에 발급된 것
  const maxLife = p.rm === 1 ? REMEMBER_MAX_AGE_SECONDS : SESSION_MAX_AGE_SECONDS;
  if (p.exp - p.iat > maxLife + CLOCK_SKEW_SECONDS) return null; // 허용된 수명보다 긴 것
  if (p.chk > nowSeconds + CLOCK_SKEW_SECONDS || p.chk < p.iat - CLOCK_SKEW_SECONDS) return null;
  return { v: 2, uid: p.uid.toLowerCase(), sid: p.sid.toLowerCase(), rm: p.rm, un: p.un, dn: p.dn, iat: p.iat, exp: p.exp, chk: p.chk };
}

export function newSession(
  user: { uid: string; username: string; displayName: string },
  nowSeconds: number,
  options: { sessionId: string; remember: boolean; lifetimeSeconds?: number },
): SessionPayload {
  const maxLife = options.remember ? REMEMBER_MAX_AGE_SECONDS : SESSION_MAX_AGE_SECONDS;
  // 수명은 API(서버 쪽 세션)가 정한 값을 따르되, 허용 상한을 넘지 않는다.
  const life = Math.min(Math.max(1, Math.floor(options.lifetimeSeconds ?? maxLife)), maxLife);
  return {
    v: 2,
    uid: user.uid.toLowerCase(),
    sid: options.sessionId.toLowerCase(),
    rm: options.remember ? 1 : 0,
    un: user.username,
    dn: user.displayName,
    iat: nowSeconds,
    exp: nowSeconds + life,
    chk: nowSeconds,
  };
}

/** 마지막 확인 시각만 갱신한다(만료 시각은 그대로 — 활성 확인으로 8시간 상한이 늘어나지 않는다). */
export function refreshed(payload: SessionPayload, nowSeconds: number): SessionPayload {
  return { ...payload, chk: nowSeconds };
}

export function isFresh(payload: SessionPayload, nowSeconds: number): boolean {
  return nowSeconds - payload.chk <= SESSION_FRESH_SECONDS;
}

/** 쿠키가 살아 있을 초(만료까지 남은 시간). */
export function remainingSeconds(payload: SessionPayload, nowSeconds: number): number {
  return Math.max(0, payload.exp - nowSeconds);
}
