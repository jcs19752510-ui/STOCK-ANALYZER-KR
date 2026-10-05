"use client";

import { useEffect, useState } from "react";
import copy from "@/content/copy.ko.json";

/**
 * 로그인 상태 갱신 화면(DEC-067). 확인한 지 5분이 지난 로그인은 이 화면에서 서버가 API에 회원이 아직 활성인지 확인한 뒤 원래 화면으로 돌아간다.
 * 확인이 오래 걸려도(무료 서버가 깨어나는 중) 대기 팝업은 띄우지 않는다(DEC-076).
 */
export function RenewSession({ next }: { next: string }) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/auth/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: "{}",
        });
        if (cancelled) return;
        if (response.ok) {
          window.location.replace(next);
        } else if (response.status === 401) {
          window.location.replace(`/login?reason=expired&next=${encodeURIComponent(next)}`);
        } else {
          setFailed(true);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [next, attempt]);

  return (
    <section className="login-page" aria-busy={!failed}>
      <h1 className="login-page__title">{copy.auth.renewTitle}</h1>
      {failed ? (
        <>
          <p role="alert">{copy.auth.renewFailed}</p>
          <button
            type="button"
            className="login-form__submit"
            onClick={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            {copy.auth.renewRetry}
          </button>
        </>
      ) : (
        <p role="status">{copy.auth.renewBody}</p>
      )}
    </section>
  );
}
