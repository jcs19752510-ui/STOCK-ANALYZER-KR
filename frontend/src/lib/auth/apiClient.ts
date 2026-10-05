import { fetchWithColdStartRetry } from "@/lib/serverFetch";

/**
 * 웹 서버가 API의 **내부 전용 경로**(로그인 확인·활성 확인·회원 목록)를 부르는 클라이언트(DEC-067). 서버에서만 실행되며 내부 토큰이 브라우저로 나가지 않는다.
 * 로그인(POST)은 실패 횟수를 세므로 **재시도하지 않는다**(깨어나는 중이면 길게 기다린다). 활성 확인·회원 목록은 조회라 일시적 실패를 재시도한다.
 */
export interface MemberInfo {
  uid: string;
  username: string;
  displayName: string;
}

export type LoginResult =
  | { kind: "ok"; user: MemberInfo; sessionId: string; expiresInSeconds: number }
  | { kind: "invalid" }
  | { kind: "rate_limited" }
  | { kind: "unavailable" };

export type SessionCheckResult =
  | { kind: "active"; user: Omit<MemberInfo, "uid"> }
  | { kind: "inactive" }
  | { kind: "unavailable" };

export type MembersResult =
  | { kind: "ok"; items: { username: string; displayName: string }[] }
  | { kind: "unavailable" };

const LOGIN_TIMEOUT_MS = 65_000;
const LOGOUT_TIMEOUT_MS = 8_000;
const LOGOUT_ALL_TIMEOUT_MS = 30_000; // 잠든 API가 깨어나는 시간을 기다린다(실패를 성공으로 보이지 않기 위해 재시도는 하지 않는다)

function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
}

function internalHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    "X-Internal-Token": (process.env.PUBLIC_API_INTERNAL_TOKEN ?? "").trim(),
    Accept: "application/json",
    "Content-Type": "application/json",
    ...extra,
  };
}

async function readJson(response: Response): Promise<Record<string, unknown> | null> {
  try {
    const body: unknown = await response.json();
    return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export async function apiLogin(username: string, password: string, ip: string | null, remember = false): Promise<LoginResult> {
  try {
    const response = await fetch(`${apiBase()}/api/v1/internal/auth/login`, {
      method: "POST",
      headers: internalHeaders(ip ? { "X-End-User-IP": ip } : {}),
      body: JSON.stringify({ username, password, remember }),
      cache: "no-store",
      signal: AbortSignal.timeout(LOGIN_TIMEOUT_MS),
    });
    if (response.status === 401) return { kind: "invalid" };
    if (response.status === 429) return { kind: "rate_limited" };
    if (response.status !== 200) return { kind: "unavailable" };
    const data = ((await readJson(response))?.data ?? null) as Record<string, unknown> | null;
    const uid = asString(data?.user_id);
    const name = asString(data?.username);
    const display = asString(data?.display_name);
    const sessionId = asString(data?.session_id);
    const expires = data?.expires_in_seconds;
    if (!uid || !name || !display || !sessionId || typeof expires !== "number" || !Number.isFinite(expires)) return { kind: "unavailable" };
    return { kind: "ok", user: { uid, username: name, displayName: display }, sessionId, expiresInSeconds: expires };
  } catch {
    return { kind: "unavailable" };
  }
}

export async function apiSessionCheck(uid: string, sessionId: string): Promise<SessionCheckResult> {
  try {
    const response = await fetchWithColdStartRetry(`${apiBase()}/api/v1/internal/auth/session-check`, {
      method: "POST",
      headers: internalHeaders({ "X-Auth-User": uid }),
      body: JSON.stringify({ user_id: uid, session_id: sessionId }),
      cache: "no-store",
    });
    if (response.status !== 200) return { kind: "unavailable" };
    const data = ((await readJson(response))?.data ?? null) as Record<string, unknown> | null;
    if (data?.active === true) {
      const username = asString(data.username);
      const display = asString(data.display_name);
      return username && display ? { kind: "active", user: { username, displayName: display } } : { kind: "unavailable" };
    }
    return data?.active === false ? { kind: "inactive" } : { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}

/** 로그아웃 때 서버 쪽 세션을 취소한다. 실패해도 쿠키는 지우므로 결과(취소했는지)만 알려 준다. 재시도 없이 짧게 기다린다. */
export async function apiLogout(uid: string, sessionId: string): Promise<boolean> {
  try {
    const response = await fetch(`${apiBase()}/api/v1/internal/auth/logout`, {
      method: "POST",
      headers: internalHeaders({ "X-Auth-User": uid }),
      body: JSON.stringify({ user_id: uid, session_id: sessionId }),
      cache: "no-store",
      signal: AbortSignal.timeout(LOGOUT_TIMEOUT_MS),
    });
    return response.status === 200;
  } catch {
    return false;
  }
}

/** "모든 기기에서 로그아웃": 이 회원의 모든 서버 세션을 취소한다. 취소한 건수를 돌려주고, 이미 취소·만료된 세션이면 "invalid", 서버 장애는 null. 재시도하지 않는다(결과를 사용자에게 그대로 알린다). */
export async function apiLogoutAll(uid: string, sessionId: string): Promise<number | "invalid" | null> {
  try {
    const response = await fetch(`${apiBase()}/api/v1/internal/auth/logout-all`, {
      method: "POST",
      headers: internalHeaders({ "X-Auth-User": uid }),
      body: JSON.stringify({ user_id: uid, session_id: sessionId }),
      cache: "no-store",
      signal: AbortSignal.timeout(LOGOUT_ALL_TIMEOUT_MS),
    });
    if (response.status === 401) return "invalid";
    if (response.status !== 200) return null;
    const count = (((await readJson(response))?.data ?? null) as Record<string, unknown> | null)?.revoked_count;
    return typeof count === "number" && Number.isInteger(count) && count >= 0 ? count : null;
  } catch {
    return null;
  }
}

export async function apiMembers(uid: string): Promise<MembersResult> {
  try {
    const response = await fetchWithColdStartRetry(`${apiBase()}/api/v1/internal/members`, {
      method: "GET",
      headers: internalHeaders({ "X-Auth-User": uid }),
      cache: "no-store",
    });
    if (response.status !== 200) return { kind: "unavailable" };
    const items = ((await readJson(response))?.data as { items?: unknown } | null)?.items;
    if (!Array.isArray(items)) return { kind: "unavailable" };
    const rows: { username: string; displayName: string }[] = [];
    for (const item of items) {
      const r = item as Record<string, unknown>;
      const username = asString(r?.username);
      const display = asString(r?.display_name);
      if (username && display) rows.push({ username, displayName: display });
    }
    return { kind: "ok", items: rows };
  } catch {
    return { kind: "unavailable" };
  }
}
