"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import copy from "@/content/copy.ko.json";

/**
 * 회원가입 신청 폼(DEC-074). 제출은 같은 사이트의 `POST /auth/signup`(JSON)이고, 성공하면 **승인 대기 안내**만 보여 준다(로그인되지 않는다).
 * 입력 규칙 위반·아이디 중복·신청 마감·횟수 제한은 서버가 준 문구를 그대로 보여 준다. 숨긴 칸(`website`)은 봇 걸러내기용이라 사람은 보지도 채우지도 않는다.
 */
export function SignupForm() {
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const username = String(form.get("username") ?? "").trim();
    const displayName = String(form.get("displayName") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("passwordConfirm") ?? "");
    const website = String(form.get("website") ?? "");
    if (!username || !displayName || !password) return setMessage(copy.signup.required);
    if (password !== confirm) return setMessage(copy.signup.mismatch);
    setPending(true);
    setMessage(null);
    try {
      const response = await fetch("/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username, displayName, password, website }),
      });
      const body = (await response.json().catch(() => null)) as { ok?: boolean; message?: unknown } | null;
      if (response.ok && body?.ok) {
        setDone(true);
        return;
      }
      setMessage(typeof body?.message === "string" && body.message ? body.message : copy.signup.errorUnavailable);
    } catch {
      setMessage(copy.signup.errorUnavailable);
    }
    setPending(false);
  }

  if (done) {
    return (
      <div className="signup-done" role="status">
        <h2 className="signup-done__title">{copy.signup.doneTitle}</h2>
        <p>{copy.signup.doneBody}</p>
        <Link href="/login" className="signup-done__link">
          {copy.signup.backToLogin}
        </Link>
      </div>
    );
  }

  return (
    <form className="login-form" onSubmit={onSubmit} noValidate>
      <div className="login-form__field">
        <label htmlFor="signup-username">{copy.signup.usernameLabel}</label>
        <input id="signup-username" name="username" type="text" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} maxLength={64} required disabled={pending} aria-describedby="signup-username-hint" />
        <p className="login-form__hint" id="signup-username-hint">{copy.signup.usernameHint}</p>
      </div>
      <div className="login-form__field">
        <label htmlFor="signup-name">{copy.signup.displayNameLabel}</label>
        <input id="signup-name" name="displayName" type="text" autoComplete="name" maxLength={100} required disabled={pending} aria-describedby="signup-name-hint" />
        <p className="login-form__hint" id="signup-name-hint">{copy.signup.displayNameHint}</p>
      </div>
      <div className="login-form__field">
        <label htmlFor="signup-password">{copy.signup.passwordLabel}</label>
        <input id="signup-password" name="password" type="password" autoComplete="new-password" maxLength={1024} required disabled={pending} aria-describedby="signup-password-hint" />
        <p className="login-form__hint" id="signup-password-hint">{copy.signup.passwordHint}</p>
      </div>
      <div className="login-form__field">
        <label htmlFor="signup-password-confirm">{copy.signup.passwordConfirmLabel}</label>
        <input id="signup-password-confirm" name="passwordConfirm" type="password" autoComplete="new-password" maxLength={1024} required disabled={pending} />
      </div>
      {/* 봇 걸러내기용 숨긴 칸: 사람에게 보이지 않고 키보드로도 닿지 않는다. 채워져 있으면 서버가 접수한 척하고 버린다. */}
      <div className="signup-hp" aria-hidden="true">
        <label htmlFor="signup-website">Website</label>
        <input id="signup-website" name="website" type="text" tabIndex={-1} autoComplete="off" />
      </div>
      {message ? (
        <p className="login-form__message" role="alert">
          {message}
        </p>
      ) : null}
      <button type="submit" className="login-form__submit" disabled={pending}>
        {pending ? copy.signup.submitting : copy.signup.submit}
      </button>
      <p className="login-form__signup">
        {copy.signup.haveAccount} <Link href="/login">{copy.signup.backToLogin}</Link>
      </p>
    </form>
  );
}
