import type { Metadata } from "next";
import { BrokerScreenClient } from "@/components/BrokerScreenClient";
import copy from "@/content/copy.ko.json";

export const metadata: Metadata = {
  title: `${copy.broker.label}${copy.broker.pageTitleSuffix}`,
};

/**
 * 증권사 조건검색 `/screener/broker`(DEC-088, 로컬 모드 관리자 전용). 서버 컴포넌트 셸은 제목만 맡고,
 * 접근 확인·조회는 모두 브라우저에서 `BrokerScreenClient`가 한다(서버 렌더에는 내용이 없다).
 */
export default function BrokerScreenerPage() {
  return <BrokerScreenClient />;
}
