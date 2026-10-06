/**
 * 서버 컴포넌트가 API를 부를 때 쓰는 fetch(DEC-065). 무료 호스팅은 한동안 접속이 없으면 API 서버와 DB(Neon)가 잠들어서,
 * 첫 요청이 "깨어나는 중"에 실패(503/502/504 또는 연결 오류)할 수 있다. 이런 **일시적 실패만** 몇 번 더 시도해서
 * 첫 방문자가 곧바로 오류 화면을 보지 않게 한다. 조회(GET)에 쓰는 것이 원칙이다 — 쓰기 요청에 쓰면 중복 실행될 수 있다. 예외: 로그인(`apiLogin`, DEC-077)은 이런 일시적 실패에서 API가 비밀번호 확인까지 가지 못해 부작용이 없으므로 같은 재시도를 쓴다.
 *
 * - 재시도 대상: 연결 오류·시간 초과, HTTP 502/503/504. (API는 DB 연결 실패·요청 시간 초과를 503으로 돌려준다.)
 * - 재시도하지 않음: 200대 성공, 400대(예: 404 종목 없음, 429 한도 초과), 500(코드 오류는 반복해도 같다).
 * - 최악의 대기: 시도 3회 × 20초 + 대기 3초·6초 = 약 69초(기본값). 그 뒤에는 마지막 결과를 그대로 돌려줘서
 *   호출한 쪽이 기존처럼 오류 화면을 보여 준다.
 */
export const COLD_START_RETRY_STATUSES: ReadonlySet<number> = new Set([502, 503, 504]);
export const COLD_START_ATTEMPTS = 3;
export const COLD_START_DELAYS_MS: readonly number[] = [3000, 6000];
export const COLD_START_ATTEMPT_TIMEOUT_MS = 20_000;

export interface ColdStartRetryOptions {
  attempts?: number;
  delaysMs?: readonly number[];
  attemptTimeoutMs?: number;
  /** 시험용: 실제 네트워크 대신 쓸 fetch */
  fetchImpl?: (input: string, init: RequestInit) => Promise<Response>;
  /** 시험용: 실제로 기다리지 않고 시간을 흘려보내는 대기 함수 */
  sleep?: (ms: number) => Promise<void>;
}

const realSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function fetchWithColdStartRetry(
  input: string,
  init: RequestInit = {},
  options: ColdStartRetryOptions = {},
): Promise<Response> {
  const attempts = Math.max(1, options.attempts ?? COLD_START_ATTEMPTS);
  const delays = options.delaysMs ?? COLD_START_DELAYS_MS;
  const timeoutMs = options.attemptTimeoutMs ?? COLD_START_ATTEMPT_TIMEOUT_MS;
  const doFetch = options.fetchImpl ?? ((url: string, i: RequestInit) => fetch(url, i));
  const sleep = options.sleep ?? realSleep;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const isLast = attempt === attempts - 1;
    try {
      const response = await doFetch(input, { ...init, signal: AbortSignal.timeout(timeoutMs) });
      if (isLast || !COLD_START_RETRY_STATUSES.has(response.status)) return response;
      // 버릴 응답의 본문을 닫아 연결을 정리한다.
      await response.body?.cancel().catch(() => undefined);
    } catch (error) {
      if (isLast) throw error;
    }
    const delay = delays.length > 0 ? delays[Math.min(attempt, delays.length - 1)] : 0;
    await sleep(delay);
  }
  // 도달하지 않는다(마지막 시도에서 반드시 반환하거나 던진다). 타입 안전을 위한 방어.
  throw new Error("fetchWithColdStartRetry: unreachable");
}
