/**
 * "아이디 저장"(로그인 편의, DEC-069): 아이디만 이 브라우저의 localStorage에 둔다. **비밀번호는 어디에도 저장하지 않는다**
 * (JS가 읽을 수 있는 저장소에 비밀번호를 두면 XSS 한 번으로 탈취된다). 비밀번호 저장은 브라우저·OS의 비밀번호 관리자에 맡긴다.
 * 저장소가 막힌 환경(사생활 보호 모드 등)에서는 조용히 아무것도 하지 않는다.
 */
export const SAVED_USERNAME_KEY = "login.savedUsername";
const VALID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** 저장된 아이디가 있으면 돌려주고, 형식이 이상한 값(변조 등)은 지우고 null. */
export function loadSavedUsername(storage: StorageLike | null | undefined): string | null {
  try {
    const raw = storage?.getItem(SAVED_USERNAME_KEY);
    if (raw == null) return null;
    if (VALID.test(raw)) return raw;
    storage?.removeItem(SAVED_USERNAME_KEY);
  } catch {
    // 저장소 접근 불가: 저장 기능만 포기한다
  }
  return null;
}

/** remember가 true이고 아이디 형식이 맞을 때만 저장, 아니면 지운다. 저장했으면 true. */
export function persistUsername(storage: StorageLike | null | undefined, username: string, remember: boolean): boolean {
  try {
    const value = username.trim();
    if (remember && VALID.test(value)) {
      storage?.setItem(SAVED_USERNAME_KEY, value);
      return storage != null;
    }
    storage?.removeItem(SAVED_USERNAME_KEY);
  } catch {
    // 저장소 접근 불가
  }
  return false;
}

/** 안전하게 localStorage를 얻는다(접근만 해도 예외가 날 수 있다). */
export function browserStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}
