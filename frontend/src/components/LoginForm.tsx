"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import copy from "@/content/copy.ko.json";
import { browserStorage, loadSavedUsername, persistUsername } from "@/lib/auth/savedUsername";

/**
 * 브라우저 비밀번호 관리자에 저장을 제안한다(Credential Management API, Chrome·Edge). 앱은 비밀번호를 저장하지 않고 브라우저에 넘길 뿐이며
 * 저장 여부는 사용자가 브라우저 창에서 정한다. 미지원 브라우저는 폼의 autocomplete 속성으로 브라우저가 알아서 제안한다. 최대 1초만 기다린다.
 */
async function offerPasswordToBrowser(username: string, password: string): Promise<void> {
  try {
    const w = window as unknown as { PasswordCredential?: new (data: { id: string; password: string; name?: string }) => Credential };
    if (!w.PasswordCredential || !navigator.credentials?.store) return;
    const credential = new w.PasswordCredential({ id: username.trim(), password });
    await Promise.race([navigator.credentials.store(credential), new Promise((resolve) => setTimeout(resolve, 1000))]);
  } catch {
    // 저장 제안 실패는 로그인에 영향을 주지 않는다
  }
}

/**
 * 로그인 입력 폼(DEC-067). 제출은 같은 사이트의 `POST /auth/login`(JSON)으로 보내고, 성공하면 **전체 화면 이동**으로 돌아갈 곳을 연다
 * (쿠키가 서버 화면에 바로 적용되도록). 실패 문구는 서버가 알려 준 세 가지(틀림·시도 많음·서버 문제)뿐이며, 비밀번호 칸은 실패하면 비운다.
 */
export function LoginForm({ next, expired }: { next: string; expired: boolean }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(expired ? copy.auth.expiredNotice : null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const usernameRef = useRef<HTMLInputElement>(null);
  const rememberRef = useRef<HTMLInputElement>(null);
  const keepRef = useRef<HTMLInputElement>(null);
  const [failures, setFailures] = useState(0);

  // "아이디 저장": 저장된 아이디가 있으면 채우고 비밀번호 칸으로 포커스(비밀번호는 브라우저 비밀번호 관리자가 채운다).
  useEffect(() => {
    const saved = loadSavedUsername(browserStorage());
    if (saved && usernameRef.current && rememberRef.current && usernameRef.current.value === "") {
      usernameRef.current.value = saved;
      rememberRef.current.checked = true;
      passwordRef.current?.focus();
    }
  }, []);

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
        body: JSON.stringify({ username, password, next, remember: keepRef.current?.checked === true }),
      });
      const body = (await response.json().catch(() => null)) as { ok?: boolean; next?: unknown } | null;
      if (response.ok && body?.ok) {
        const target = typeof body.next === "string" && body.next.startsWith("/") && !body.next.startsWith("//") ? body.next : "/";
        persistUsername(browserStorage(), username, rememberRef.current?.checked === true);
        await offerPasswordToBrowser(username, password);
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
          ref={usernameRef}
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
      <div className="login-form__remember">
        <input id="login-remember" name="remember" type="checkbox" disabled={pending} ref={rememberRef} />
        <label htmlFor="login-remember">{copy.auth.rememberLabel}</label>
      </div>
      <div className="login-form__remember">
        <input id="login-keep" name="keep" type="checkbox" disabled={pending} ref={keepRef} aria-describedby="login-keep-hint" />
        <label htmlFor="login-keep">{copy.auth.keepLabel}</label>
      </div>
      <p className="login-form__hint">{copy.auth.rememberHint}</p>
      <p className="login-form__hint" id="login-keep-hint">
        {copy.auth.keepHint}
      </p>
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
