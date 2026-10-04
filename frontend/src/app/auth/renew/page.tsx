import { notFound } from "next/navigation";
import { RenewSession } from "@/components/RenewSession";
import { authEnabled } from "@/lib/auth/config";
import { safeNextPath } from "@/lib/auth/redirect";

export const dynamic = "force-dynamic";

export default async function RenewPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  if (!authEnabled()) notFound();
  const params = await searchParams;
  return <RenewSession next={safeNextPath(params.next)} />;
}
