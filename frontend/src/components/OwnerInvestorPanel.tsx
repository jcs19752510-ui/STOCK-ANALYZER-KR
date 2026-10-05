"use client";

import { InvestorTable } from "@/components/InvestorPanel";
import copy from "@/content/copy.ko.json";
import { useLazyApi } from "@/lib/useLazyApi";
import type { IntradayInvestorData } from "@/lib/types";

/**
 * 투자자 탭(관리자 전용, DEC-074): 관리자 PC가 증권사에서 수집해 서버에 적재한 일별 순매수.
 * 관리자 권한 계정으로 로그인했을 때만 이 화면이 나온다(API가 매번 DB에서 관리자 권한을 다시 확인하므로 화면만 우회해도 값은 오지 않는다).
 * 탭을 처음 열 때 한 번 조회한다. 실시간이 아니라 수집 시점까지의 값이다.
 */
export function OwnerInvestorPanel({ stockCode }: { stockCode: string }) {
  const state = useLazyApi<IntradayInvestorData>(
    `/api/v1/internal/admin/stocks/${encodeURIComponent(stockCode)}/investor`,
    true,
  );
  if (state.kind === "idle" || state.kind === "loading") {
    return <p className="stock-tabs__pending">{copy.stockDetail.tabLoading}</p>;
  }
  if (state.kind === "error") {
    return <p className="stock-tabs__pending">{copy.stockDetail.ownerInvestorError}</p>;
  }
  return (
    <div>
      <InvestorTable rows={state.data.rows} />
      <p className="stock-tabs__note">{copy.stockDetail.investorNetBuyHint}</p>
      <p className="stock-tabs__note">{copy.stockDetail.ownerInvestorNote}</p>
    </div>
  );
}
