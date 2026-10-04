import { notFound, redirect } from "next/navigation";
import { LoginForm } from "@/components/LoginForm";
import { authEnabled } from "@/lib/auth/config";
import { readSession } from "@/lib/auth/current";
import { safeNextPath } from "@/lib/auth/redirect";
import copy from "@/content/copy.ko.json";

export const dynamic = "force-dynamic";

/** 로그인 화면(DEC-067). 로그인을 끈 환경(로컬)에는 이 화면이 없다. 이미 로그인한 회원은 원래 가려던 곳으로 보낸다. */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; reason?: string }>;
}) {
  if (!authEnabled()) notFound();
  const params = await searchParams;
  const next = safeNextPath(params.next);
  if (await readSession()) redirect(next);
  return (
    <section className="login-page">
      <h1 className="login-page__title">{copy.auth.loginTitle}</h1>
      <p className="login-page__intro">{copy.auth.loginIntro}</p>
      <LoginForm next={next} expired={params.reason === "expired"} />
    </section>
  );
}
