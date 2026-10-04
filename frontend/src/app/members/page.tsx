import { notFound } from "next/navigation";
import { ErrorState } from "@/components/ErrorState";
import copy from "@/content/copy.ko.json";
import { apiMembers } from "@/lib/auth/apiClient";
import { authEnabled } from "@/lib/auth/config";
import { requireMember } from "@/lib/auth/current";

export const dynamic = "force-dynamic";

/** 회원 목록(DEC-067): 로그인한 모든 회원이 **아이디와 이름만** 본다. 로그인을 끈 환경(로컬)에는 없는 화면이다. */
export default async function MembersPage() {
  if (!authEnabled()) notFound();
  const member = await requireMember("/members");
  const result = member ? await apiMembers(member.uid) : ({ kind: "unavailable" } as const);
  if (result.kind !== "ok") return <ErrorState variant="network" retryHref="/members" />;
  const m = copy.members;
  return (
    <section className="members-page">
      <h1 className="members-page__title">{m.pageTitle}</h1>
      <p className="members-page__intro">{m.intro}</p>
      <p className="members-page__count" data-testid="members-count">
        {m.countLabel} {result.items.length}
        {m.countUnit}
      </p>
      {result.items.length === 0 ? (
        <p>{m.empty}</p>
      ) : (
        <div className="members-page__table-wrap">
          <table className="members-table">
            <caption className="sr-only">{m.tableCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{m.columnUsername}</th>
                <th scope="col">{m.columnName}</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((item) => (
                <tr key={item.username}>
                  <td>{item.username}</td>
                  <td>{item.displayName}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
