import { notFound, redirect } from "next/navigation";
import { SignupForm } from "@/components/SignupForm";
import copy from "@/content/copy.ko.json";
import { authEnabled } from "@/lib/auth/config";
import { readSession } from "@/lib/auth/current";

export const dynamic = "force-dynamic";

/** 회원가입 신청 화면(DEC-074). 로그인을 끈 환경(로컬)에는 없다. 이미 로그인한 회원은 홈으로 보낸다. */
export default async function SignupPage() {
  if (!authEnabled()) notFound();
  if (await readSession()) redirect("/");
  return (
    <section className="login-page">
      <h1 className="login-page__title">{copy.signup.pageTitle}</h1>
      <p className="login-page__intro">{copy.signup.intro}</p>
      <SignupForm />
    </section>
  );
}
