"use client";

/**
 * 증권사 조건검색(DEC-088) React 연결: 접근 확인(조건 목록 요청)·조건 목록 상태·결과 주기 조회 훅.
 * 호출은 `fetchIntraday`와 같이 `browserApiBase()`를 거친다(로그인을 켠 로컬은 웹 서버 대행 경로, 끈 로컬은 API 직접).
 * 로컬 모드가 아니면(`localIntradayAvailable()` 거짓: 운영 빌드·공개 주소) 요청을 하나도 보내지 않는다.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { browserApiBase } from "@/lib/apiBase";
import { localIntradayAvailable } from "@/lib/localIntraday";
import { UNAVAILABLE_STATUS, errorInfo, parseConditions, type PsearchCondition, type PsearchHttp } from "./logic.ts";
import { EMPTY_PSEARCH_VIEW, PsearchPoller, type PsearchErrorInfo, type PsearchView } from "./poller.ts";

async function request(url: string, signal?: AbortSignal): Promise<PsearchHttp> {
  const res = await fetch(url, { signal, cache: "no-store" });
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

/** 브라우저에서 이 기능을 쓸 수 있는 환경인지: 서버 렌더·하이드레이션 중에는 "unknown"(아무것도 보이지 않음). */
export function useLocalMode(): "unknown" | "yes" | "no" {
  return useSyncExternalStore<"unknown" | "yes" | "no">(
    () => () => {},
    () => (localIntradayAvailable() ? "yes" : "no"),
    () => "unknown",
  );
}

// ── 조건 목록 ────────────────────────────────────────────────────────────

export type ConditionsOutcome =
  | { kind: "ok"; conditions: PsearchCondition[] }
  | { kind: "unavailable"; error: PsearchErrorInfo }
  | { kind: "error"; error: PsearchErrorInfo };

function interpretConditions(res: PsearchHttp): ConditionsOutcome {
  const { code, message } = errorInfo(res.body);
  if (UNAVAILABLE_STATUS.has(res.status)) return { kind: "unavailable", error: { status: res.status, code, message } };
  const conditions = res.status === 200 ? parseConditions(res.body) : null;
  if (conditions) return { kind: "ok", conditions };
  return { kind: "error", error: { status: res.status, code: code ?? (res.status === 200 ? "BAD_RESPONSE" : null), message } };
}

let inflight: Promise<ConditionsOutcome> | null = null;
/** 전환 항목용 접근 확인 결과(확정된 응답만 기억: 200 또는 401·403·404·503). 일시 오류는 기억하지 않아 다음 화면에서 다시 확인한다. */
let accessMemo: boolean | null = null;

/** 같은 순간에 여러 곳(전환 항목·화면)이 물어도 요청은 한 번만 보낸다. 로컬 모드가 아니면 요청 없이 접근 불가로 돌려준다. */
export function loadConditions(): Promise<ConditionsOutcome> {
  const base = browserApiBase();
  if (!localIntradayAvailable() || !base) {
    return Promise.resolve({ kind: "unavailable", error: { status: 0, code: "LOCAL_MODE_REQUIRED", message: null } });
  }
  if (inflight) return inflight;
  const url = new URL("/api/v1/local/psearch/conditions", base).toString();
  const p: Promise<ConditionsOutcome> = request(url)
    .then(interpretConditions)
    .then((o): ConditionsOutcome => {
      if (o.kind === "ok") accessMemo = true;
      else if (o.kind === "unavailable") accessMemo = o.error.code === NOT_CONFIGURED_CODE;
      return o;
    })
    .catch((): ConditionsOutcome => ({ kind: "error", error: { status: 0, code: "NETWORK_ERROR", message: null } }))
    .finally(() => {
      inflight = null;
    });
  inflight = p;
  return p;
}

/** HTS ID가 설정되지 않은 관리자(조건 목록 503 `PSEARCH_NOT_CONFIGURED`)에게는 항목을 보여 설정 안내 화면으로 안내한다(관리자 확인·로컬 모드 확인은 이미 통과한 응답이다). */
const NOT_CONFIGURED_CODE = "PSEARCH_NOT_CONFIGURED";

/** 전환 항목을 보일지: 로컬 모드이고 조건 목록이 200일 때(또는 HTS ID 미설정 안내가 필요할 때)만 true. 그 전에는 항상 false(서버 렌더에서도 false). */
export function useBrokerAccess(): boolean {
  const local = useLocalMode();
  const [result, setResult] = useState<boolean | null>(accessMemo);
  useEffect(() => {
    if (local !== "yes" || accessMemo !== null) return;
    let alive = true;
    void loadConditions().then((o) => {
      if (alive) setResult(o.kind === "ok" || (o.kind === "unavailable" && o.error.code === NOT_CONFIGURED_CODE));
    });
    return () => {
      alive = false;
    };
  }, [local]);
  return local === "yes" && (accessMemo ?? result) === true;
}

export type ConditionsState =
  | { phase: "checking" } // 서버 렌더·하이드레이션 중
  | { phase: "local-required" } // 로컬 모드가 아님(요청 없음)
  | { phase: "loading" }
  | { phase: "ready"; conditions: PsearchCondition[] }
  | { phase: "unavailable"; error: PsearchErrorInfo }
  | { phase: "error"; error: PsearchErrorInfo };

export function useConditions(): { state: ConditionsState; reload: () => void } {
  const local = useLocalMode();
  const [loaded, setLoaded] = useState<{ n: number; outcome: ConditionsOutcome } | null>(null);
  const [attempt, setAttempt] = useState(1);

  useEffect(() => {
    if (local !== "yes") return;
    let alive = true;
    void loadConditions().then((o) => {
      if (alive) setLoaded({ n: attempt, outcome: o });
    });
    return () => {
      alive = false;
    };
  }, [local, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  if (local === "unknown") return { state: { phase: "checking" }, reload };
  if (local === "no") return { state: { phase: "local-required" }, reload };
  if (!loaded || loaded.n !== attempt) return { state: { phase: "loading" }, reload };
  const o = loaded.outcome;
  if (o.kind === "ok") return { state: { phase: "ready", conditions: o.conditions }, reload };
  return { state: { phase: o.kind, error: o.error }, reload };
}

// ── 결과 주기 조회 ───────────────────────────────────────────────────────

/** 조건 하나의 결과를 주기적으로 조회한다. `seq`가 null이면 조회하지 않는다. 반환값의 `seq`가 요청한 값과 다르면 아직 바뀌는 중이다. */
export function usePsearchResults(seq: string | null): PsearchView {
  const [view, setView] = useState<PsearchView>(EMPTY_PSEARCH_VIEW);
  const pollerRef = useRef<PsearchPoller | null>(null);

  useEffect(() => {
    if (!localIntradayAvailable()) return;
    const baseUrl = browserApiBase();
    if (!baseUrl) return;
    const p = new PsearchPoller({
      request: (url, signal) => request(url, signal),
      baseUrl: baseUrl.replace(/\/$/, ""),
      onView: setView,
      setTimeout: (fn, ms) => window.setTimeout(fn, ms),
      clearTimeout: (id) => window.clearTimeout(id as number),
      isHidden: () => document.hidden,
      now: () => Date.now() / 1000,
    });
    const onVisibility = () => p.visibilityChanged();
    document.addEventListener("visibilitychange", onVisibility);
    pollerRef.current = p;
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      p.stop();
      pollerRef.current = null;
    };
  }, []);

  useEffect(() => {
    pollerRef.current?.setSeq(seq);
  }, [seq]);

  return view;
}
