/**
 * "서버 깨우는 중" 팝업의 카운트다운·자동 새로고침 로직(DEC-066). 화면과 분리한 순수 로직이라 노드 테스트로 검증한다
 * (scripts/check-wake-countdown.mjs).
 *
 * 규칙(사용자 결정):
 *  - 팝업이 뜬 순간부터 60초를 센다(남은 초 60→00).
 *  - 그 전에 데이터가 도착하면 팝업만 닫고 새로고침하지 않는다.
 *  - 0초가 되었을 때 "서버가 화면을 불러오는 중"이면 새로고침한다(브라우저 요청이 느린 경우는 팝업만 닫는다).
 *  - 새로고침은 같은 탭에서 연속 최대 2회까지. 데이터가 도착하면 횟수를 지운다. 저장소를 못 쓰면 새로고침하지 않는다(무한 반복 방지).
 */
export const DEFAULT_WAKE_COUNTDOWN_SECONDS = 60;
export const MIN_WAKE_COUNTDOWN_SECONDS = 5;
export const MAX_WAKE_COUNTDOWN_SECONDS = 120;

/** `NEXT_PUBLIC_WAKE_COUNTDOWN_SECONDS`(시험·조정용). 숫자만, 5~120초가 아니면 기본 60초. */
export function parseCountdownSeconds(raw: string | undefined): number {
  const text = (raw ?? "").trim();
  if (!/^\d{1,3}$/.test(text)) return DEFAULT_WAKE_COUNTDOWN_SECONDS;
  const n = Number.parseInt(text, 10);
  return n >= MIN_WAKE_COUNTDOWN_SECONDS && n <= MAX_WAKE_COUNTDOWN_SECONDS ? n : DEFAULT_WAKE_COUNTDOWN_SECONDS;
}

/** 빌드 때 확정되는 값(`NEXT_PUBLIC_*`는 정적 참조여야 인라인된다). */
export const WAKE_COUNTDOWN_SECONDS = parseCountdownSeconds(process.env.NEXT_PUBLIC_WAKE_COUNTDOWN_SECONDS);

/** 남은 초를 두 자리로: 59, 08, 00 */
export function formatRemaining(seconds: number): string {
  return String(Math.max(0, Math.floor(seconds))).padStart(2, "0");
}

const kstClock = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Seoul",
  hourCycle: "h23",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/** 요청 시각을 한국 시간 HH:MM:SS로 */
export function formatClockKst(epochMs: number): string {
  return kstClock.format(new Date(epochMs));
}

export interface CountdownClock {
  now: () => number;
  setInterval: (fn: () => void, ms: number) => unknown;
  clearInterval: (handle: unknown) => void;
}

const realClock: CountdownClock = {
  now: () => Date.now(),
  setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
  clearInterval: (h) => globalThis.clearInterval(h as ReturnType<typeof setInterval>),
};

/**
 * 마감 시각 기준으로 남은 초를 센다(탭이 느려져도 어긋나지 않는다). 시작 즉시 `onTick(seconds)`, 초가 바뀔 때마다 `onTick`,
 * 0이 되면 `onDone`을 정확히 한 번 호출한다. `stop()` 뒤에는 아무것도 호출하지 않는다.
 */
export function createCountdown(options: {
  seconds: number;
  onTick: (remaining: number) => void;
  onDone: () => void;
  clock?: CountdownClock;
  intervalMs?: number;
}) {
  const clock = options.clock ?? realClock;
  const deadline = clock.now() + options.seconds * 1000;
  let last = options.seconds;
  let finished = false;
  options.onTick(options.seconds);
  const handle = clock.setInterval(() => {
    if (finished) return;
    const remaining = Math.max(0, Math.ceil((deadline - clock.now()) / 1000));
    if (remaining !== last) {
      last = remaining;
      options.onTick(remaining);
    }
    if (remaining === 0) {
      finished = true;
      clock.clearInterval(handle);
      options.onDone();
    }
  }, options.intervalMs ?? 250);
  return {
    stop() {
      if (finished) return;
      finished = true;
      clock.clearInterval(handle);
    },
  };
}

export const AUTO_RELOAD_KEY = "wake-auto-reloads";
export const MAX_AUTO_RELOADS = 2;

export interface KeyValueStore {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
}

/** 지금까지 자동 새로고침한 횟수. 읽을 수 없으면 한도에 도달한 것으로 본다(무한 새로고침 방지, fail closed). */
export function readAutoReloads(store: KeyValueStore): number {
  try {
    const n = Number.parseInt(store.getItem(AUTO_RELOAD_KEY) ?? "0", 10);
    return Number.isFinite(n) && n >= 0 ? n : MAX_AUTO_RELOADS;
  } catch {
    return MAX_AUTO_RELOADS;
  }
}

/** 새로고침해도 되면 횟수를 1 올리고 true. 한도 초과·저장 실패면 false. */
export function tryConsumeAutoReload(store: KeyValueStore): boolean {
  const used = readAutoReloads(store);
  if (used >= MAX_AUTO_RELOADS) return false;
  try {
    store.setItem(AUTO_RELOAD_KEY, String(used + 1));
  } catch {
    return false;
  }
  return true;
}

/** 데이터가 도착했을 때 횟수를 지운다. */
export function resetAutoReloads(store: KeyValueStore): void {
  try {
    store.removeItem(AUTO_RELOAD_KEY);
  } catch {
    /* 저장소를 못 쓰면 tryConsumeAutoReload가 새로고침을 막는다 */
  }
}
