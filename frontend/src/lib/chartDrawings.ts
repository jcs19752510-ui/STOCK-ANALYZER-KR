/**
 * 차트 그리기 도구(추세선·수평선) 상태 변환·검증(DEC-059). 사용자가 직접 그린 선은 이 브라우저 localStorage에 종목별로만
 * 저장한다(서버 저장·계정 없음). 점은 화면 좌표가 아니라 (거래일, 가격)으로 저장해 차트 크기가 바뀌어도 같은 자리에 그려진다.
 * 이 파일은 순수 함수만 둔다(저장소 접근은 StockChart). 일봉에서만 그릴 수 있다.
 */
export const DRAWINGS_STORAGE_PREFIX = "chart.drawings.v1.";
export const MAX_DRAWINGS = 20;
const MAX_PRICE = 1_000_000_000;

export interface DrawPoint {
  date: string; // "YYYY-MM-DD" (일봉 거래일)
  price: number;
}

export type Drawing =
  | { id: string; kind: "trend"; a: DrawPoint; b: DrawPoint }
  | { id: string; kind: "hline"; price: number };

const nf = new Intl.NumberFormat("ko-KR");

export function isValidDate(s: unknown): s is string {
  if (typeof s !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

export function isValidPrice(p: unknown): p is number {
  return typeof p === "number" && Number.isFinite(p) && p > 0 && p < MAX_PRICE;
}

function cleanPoint(raw: unknown): DrawPoint | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  return isValidDate(r.date) && isValidPrice(r.price) ? { date: r.date, price: r.price } : null;
}

function cleanDrawing(raw: unknown, used: Set<string>): Drawing | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  let id = typeof r.id === "string" && /^[A-Za-z0-9_-]{1,16}$/.test(r.id) ? r.id : newId();
  while (used.has(id)) id = `${id}x`.slice(0, 16);
  if (r.kind === "hline" && isValidPrice(r.price)) {
    used.add(id);
    return { id, kind: "hline", price: r.price };
  }
  if (r.kind === "trend") {
    const a = cleanPoint(r.a);
    const b = cleanPoint(r.b);
    if (a && b && a.date !== b.date) {
      used.add(id);
      return { id, kind: "trend", a, b };
    }
  }
  return null;
}

let counter = 0;
export function newId(): string {
  counter += 1;
  return `d${Date.now().toString(36)}${counter}`.slice(0, 16);
}

/** 저장된 문자열을 믿지 않고 모양·개수·값 범위·중복 id를 바로잡는다. 읽을 수 없으면 빈 목록. */
export function parseDrawings(raw: string | null): Drawing[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  const items = typeof data === "object" && data !== null ? (data as { items?: unknown }).items : null;
  if (!Array.isArray(items)) return [];
  const used = new Set<string>();
  const out: Drawing[] = [];
  for (const it of items) {
    if (out.length >= MAX_DRAWINGS) break;
    const d = cleanDrawing(it, used);
    if (d) out.push(d);
  }
  return out;
}

export function serializeDrawings(list: readonly Drawing[]): string {
  return JSON.stringify({ version: 1, items: list });
}

export function addDrawing(
  list: readonly Drawing[],
  draft: Omit<Extract<Drawing, { kind: "trend" }>, "id"> | Omit<Extract<Drawing, { kind: "hline" }>, "id">,
): { list: Drawing[]; result: "added" | "full" | "invalid" } {
  if (list.length >= MAX_DRAWINGS) return { list: [...list], result: "full" };
  const clean = cleanDrawing({ ...draft, id: newId() }, new Set(list.map((d) => d.id)));
  if (!clean) return { list: [...list], result: "invalid" };
  return { list: [...list, clean], result: "added" };
}

export function removeDrawing(list: readonly Drawing[], id: string): Drawing[] {
  return list.filter((d) => d.id !== id);
}

/** 화면 가로 위치(viewBox 좌표) → 보이는 봉 번호(0~n-1). */
export function snapIndex(vx: number, step: number, n: number): number {
  if (n <= 0 || step <= 0) return 0;
  return Math.max(0, Math.min(n - 1, Math.floor(vx / step)));
}

/** 화면 세로 위치(viewBox 좌표) → 가격. `top`·`height`는 가격 패널 영역(위아래 8 여백 포함). */
export function priceFromY(
  vy: number,
  range: { hi: number; lo: number },
  top: number,
  height: number,
): number {
  const ratio = (vy - (top + 8)) / (height - 16);
  return range.hi - ratio * (range.hi - range.lo);
}

export function describeDrawing(d: Drawing): string {
  const short = (s: string) => `${s.slice(2, 4)}.${s.slice(5, 7)}.${s.slice(8, 10)}`;
  if (d.kind === "hline") return `수평선 ${nf.format(Math.round(d.price))}원`;
  return `추세선 ${short(d.a.date)} ${nf.format(Math.round(d.a.price))}원 → ${short(d.b.date)} ${nf.format(Math.round(d.b.price))}원`;
}
