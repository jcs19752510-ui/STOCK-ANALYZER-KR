import { classifyLoginFailure } from "@/lib/auth/loginFailure";
import { fetchWithColdStartRetry } from "@/lib/serverFetch";

/**
 * 웹 서버가 API의 **내부 전용 경로**(로그인 확인·활성 확인·회원 목록)를 부르는 클라이언트(DEC-067). 서버에서만 실행되며 내부 토큰이 브라우저로 나가지 않는다.
 * 로그인(POST)은 실패 횟수를 세므로 **재시도하지 않는다**(깨어나는 중이면 길게 기다린다). 활성 확인·회원 목록은 조회라 일시적 실패를 재시도한다.
 */
export type Role = "user" | "admin";

export interface MemberInfo {
  uid: string;
  username: string;
  displayName: string;
  role: Role;
}

export type LoginResult =
  | { kind: "ok"; user: MemberInfo; sessionId: string; expiresInSeconds: number }
  | { kind: "invalid" }
  | { kind: "pending" } // 비밀번호는 맞지만 관리자 승인 대기 중
  | { kind: "disabled" } // 비밀번호는 맞지만 사용 중지된 계정
  | { kind: "rate_limited" }
  | { kind: "unavailable" };

export type SessionCheckResult =
  | { kind: "active"; user: Omit<MemberInfo, "uid"> }
  | { kind: "inactive" }
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

function asRole(value: unknown): Role | null {
  return value === "admin" || value === "user" ? value : null;
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
    if (response.status !== 200) {
      const code = ((await readJson(response))?.error as { code?: unknown } | null)?.code;
      return { kind: classifyLoginFailure(response.status, code) };
    }
    const data = ((await readJson(response))?.data ?? null) as Record<string, unknown> | null;
    const uid = asString(data?.user_id);
    const name = asString(data?.username);
    const display = asString(data?.display_name);
    const role = asRole(data?.role);
    const sessionId = asString(data?.session_id);
    const expires = data?.expires_in_seconds;
    if (!uid || !name || !display || !role || !sessionId || typeof expires !== "number" || !Number.isFinite(expires)) return { kind: "unavailable" };
    return { kind: "ok", user: { uid, username: name, displayName: display, role }, sessionId, expiresInSeconds: expires };
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
      const role = asRole(data.role);
      return username && display && role ? { kind: "active", user: { username, displayName: display, role } } : { kind: "unavailable" };
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

export type SignupResult =
  | { kind: "ok" }
  | { kind: "rejected"; status: number; code: string; message: string } // 입력 오류·아이디 중복·신청 마감·횟수 제한(사용자에게 그대로 보여 줄 문구)
  | { kind: "unavailable" };

/** 회원가입 신청(승인 대기 계정 생성). 비밀번호 해시 계산이 있어 재시도하지 않고 길게 기다린다. */
export async function apiSignup(
  input: { username: string; displayName: string; password: string; website: string },
  ip: string | null,
): Promise<SignupResult> {
  try {
    const response = await fetch(`${apiBase()}/api/v1/internal/auth/signup`, {
      method: "POST",
      headers: internalHeaders(ip ? { "X-End-User-IP": ip } : {}),
      body: JSON.stringify({ username: input.username, display_name: input.displayName, password: input.password, website: input.website }),
      cache: "no-store",
      signal: AbortSignal.timeout(LOGIN_TIMEOUT_MS),
    });
    if (response.status === 200) return { kind: "ok" };
    const err = ((await readJson(response))?.error ?? null) as { code?: unknown; message?: unknown } | null;
    const code = asString(err?.code);
    const message = asString(err?.message);
    if ([400, 409, 429, 503].includes(response.status) && code && message && code !== "FEATURE_DISABLED") {
      return { kind: "rejected", status: response.status, code, message };
    }
    return { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}

export interface AdminMember {
  username: string;
  displayName: string;
  role: Role;
  status: "pending" | "active" | "disabled";
  createdAt: string;
  lastLoginAt: string | null;
  locked: boolean;
  activeSessions: number;
}

export type AdminMembersResult =
  | { kind: "ok"; items: AdminMember[]; pending: number }
  | { kind: "forbidden" }
  | { kind: "unavailable" };

function adminHeaders(uid: string, sessionId: string): Record<string, string> {
  return internalHeaders({ "X-Auth-User": uid, "X-Auth-Session": sessionId });
}

/** 관리자 화면의 회원 목록. API가 매번 DB에서 "유효한 세션 + 활성 + 관리자"를 다시 확인하고 아니면 403(forbidden). */
export async function apiAdminMembers(uid: string, sessionId: string): Promise<AdminMembersResult> {
  try {
    const response = await fetchWithColdStartRetry(`${apiBase()}/api/v1/internal/admin/members`, {
      method: "GET",
      headers: adminHeaders(uid, sessionId),
      cache: "no-store",
    });
    if (response.status === 403 || response.status === 401) return { kind: "forbidden" };
    if (response.status !== 200) return { kind: "unavailable" };
    const data = ((await readJson(response))?.data ?? null) as { items?: unknown; pending?: unknown } | null;
    if (!data || !Array.isArray(data.items)) return { kind: "unavailable" };
    const items: AdminMember[] = [];
    for (const raw of data.items) {
      const r = raw as Record<string, unknown>;
      const username = asString(r.username);
      const display = asString(r.display_name);
      const role = asRole(r.role);
      const status = r.status === "pending" || r.status === "active" || r.status === "disabled" ? r.status : null;
      const created = asString(r.created_at);
      if (!username || !display || !role || !status || !created) continue;
      items.push({
        username,
        displayName: display,
        role,
        status,
        createdAt: created,
        lastLoginAt: asString(r.last_login_at),
        locked: r.locked === true,
        activeSessions: typeof r.active_sessions === "number" ? r.active_sessions : 0,
      });
    }
    return { kind: "ok", items, pending: typeof data.pending === "number" ? data.pending : items.filter((i) => i.status === "pending").length };
  } catch {
    return { kind: "unavailable" };
  }
}

export type AdminActionName = "create" | "approve" | "reject" | "enable" | "disable" | "set_role" | "rename" | "reset_password" | "revoke_sessions" | "delete";

export type AdminActionResult =
  | { kind: "ok"; result: string }
  | { kind: "rejected"; status: number; code: string; message: string }
  | { kind: "forbidden" }
  | { kind: "unavailable" };

/** 관리자 작업 하나를 API로 보낸다(재시도 없음 — 결과를 그대로 알린다). */
export async function apiAdminAction(
  uid: string,
  sessionId: string,
  body: { action: AdminActionName; username: string; role?: Role; displayName?: string; password?: string },
): Promise<AdminActionResult> {
  try {
    const response = await fetch(`${apiBase()}/api/v1/internal/admin/action`, {
      method: "POST",
      headers: adminHeaders(uid, sessionId),
      body: JSON.stringify({
        action: body.action,
        username: body.username,
        ...(body.role ? { role: body.role } : {}),
        ...(body.displayName !== undefined ? { display_name: body.displayName } : {}),
        ...(body.password !== undefined ? { password: body.password } : {}),
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(LOGIN_TIMEOUT_MS),
    });
    const json = await readJson(response);
    if (response.status === 200) {
      const result = asString((json?.data as { result?: unknown } | null)?.result);
      return result ? { kind: "ok", result } : { kind: "unavailable" };
    }
    if (response.status === 403 || response.status === 401) return { kind: "forbidden" };
    const err = (json?.error ?? null) as { code?: unknown; message?: unknown } | null;
    const code = asString(err?.code);
    const message = asString(err?.message);
    if ([400, 404, 409].includes(response.status) && code && message) return { kind: "rejected", status: response.status, code, message };
    return { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}
