"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import copy from "@/content/copy.ko.json";

/**
 * 로그인 입력 폼(DEC-067). 제출은 같은 사이트의 `POST /auth/login`(JSON)으로 보내고, 성공하면 **전체 화면 이동**으로 돌아갈 곳을 연다
 * (쿠키가 서버 화면에 바로 적용되도록). 실패 문구는 서버가 알려 준 세 가지(틀림·시도 많음·서버 문제)뿐이며, 비밀번호 칸은 실패하면 비운다.
 */
export function LoginForm({ next, expired }: { next: string; expired: boolean }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(expired ? copy.auth.expiredNotice : null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const [failures, setFailures] = useState(0);

  // 실패한 뒤 비밀번호 칸에 포커스를 돌려준다. 입력칸은 제출하는 동안 비활성이라, 다시 활성화된 **다음 렌더 뒤**에 포커스해야 먹힌다.
  useEffect(() => {
    if (failures > 0) passwordRef.current?.focus();
  }, [failures]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const username = String(form.get("username") ?? "");
    const password = String(form.get("password") ?? "");
    setPending(true);
    setMessage(null);
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username, password, next }),
      });
      const body = (await response.json().catch(() => null)) as { ok?: boolean; next?: unknown } | null;
      if (response.ok && body?.ok) {
        const target = typeof body.next === "string" && body.next.startsWith("/") && !body.next.startsWith("//") ? body.next : "/";
        window.location.assign(target);
        return; // 화면이 바뀌므로 입력 잠금은 그대로 둔다
      }
      if (response.status === 401) setMessage(copy.auth.errorInvalid);
      else if (response.status === 429) setMessage(copy.auth.errorRateLimited);
      else if (response.status === 400) setMessage(copy.auth.errorBadRequest);
      else setMessage(copy.auth.errorUnavailable);
    } catch {
      setMessage(copy.auth.errorUnavailable);
    }
    if (passwordRef.current) passwordRef.current.value = "";
    setPending(false);
    setFailures((n) => n + 1);
  }

  return (
    <form className="login-form" onSubmit={onSubmit} noValidate>
      <div className="login-form__field">
        <label htmlFor="login-username">{copy.auth.usernameLabel}</label>
        <input
          id="login-username"
          name="username"
          type="text"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          maxLength={64}
          required
          disabled={pending}
        />
      </div>
      <div className="login-form__field">
        <label htmlFor="login-password">{copy.auth.passwordLabel}</label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          maxLength={1024}
          required
          disabled={pending}
          ref={passwordRef}
        />
      </div>
      {message ? (
        <p className="login-form__message" role="alert">
          {message}
        </p>
      ) : null}
      <button type="submit" className="login-form__submit" disabled={pending}>
        {pending ? copy.auth.submitting : copy.auth.submit}
      </button>
    </form>
  );
}
