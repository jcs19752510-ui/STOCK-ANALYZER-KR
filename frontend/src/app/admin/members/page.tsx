import { redirect } from "next/navigation";
import { AdminMembers } from "@/components/AdminMembers";
import { ErrorState } from "@/components/ErrorState";
import copy from "@/content/copy.ko.json";
import { apiAdminMembers } from "@/lib/auth/apiClient";
import { requireAdmin } from "@/lib/auth/current";

export const dynamic = "force-dynamic";

/**
 * 관리자 회원 관리(DEC-074). 관리자 권한 쿠키가 있어야 열리고, 데이터는 API가 **매 호출마다 DB에서 관리자 권한을 확인한 뒤** 준다.
 * 권한이 바뀌었거나 세션이 취소돼 API가 거부하면 갱신 화면을 거쳐 최신 상태로 안내한다(일반 사용자가 되었으면 홈, 로그아웃되었으면 로그인).
 */
export default async function AdminMembersPage() {
  const session = await requireAdmin("/admin/members");
  const result = await apiAdminMembers(session.uid, session.sid);
  if (result.kind === "forbidden") redirect("/auth/renew?next=%2Fadmin%2Fmembers");
  if (result.kind !== "ok") return <ErrorState variant="network" retryHref="/admin/members" />;
  return (
    <section className="members-page">
      <h1 className="members-page__title">{copy.admin.pageTitle}</h1>
      <p className="members-page__intro">{copy.admin.intro}</p>
      <AdminMembers initial={result.items} self={session.un} />
    </section>
  );
}
