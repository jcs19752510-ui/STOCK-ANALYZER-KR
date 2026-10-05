import { notFound, redirect } from "next/navigation";
import { authEnabled } from "@/lib/auth/config";

export const dynamic = "force-dynamic";

/** 옛 "회원 목록" 주소(DEC-067)는 관리자 회원 관리 화면으로 합쳐졌다(DEC-074). 일반 사용자는 홈으로 이동한다(관리자 화면이 권한을 확인한다). */
export default function MembersPage() {
  if (!authEnabled()) notFound();
  redirect("/admin/members");
}
