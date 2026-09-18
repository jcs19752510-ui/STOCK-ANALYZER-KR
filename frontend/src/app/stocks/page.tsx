import type { Metadata } from "next";
import { StockSearchClient } from "@/components/StockSearchClient";

export const metadata: Metadata = {
  title: "종목 검색 | 국내주식 조건 스크리닝 정보 서비스",
};

/**
 * 종목 검색(`/stocks`, REQ-001, 04-ux-design.md §2-3). UNIT-05가 만든 임시
 * 플레이스홀더를 실제 화면으로 교체한다(UNIT-09). "use client" 컴포넌트는
 * `metadata`를 export할 수 없어 `/screener`(UNIT-07)와 동일하게 메타데이터
 * 전용 서버 컴포넌트 셸과 실제 상호작용을 담당하는 클라이언트 컴포넌트를
 * 분리했다.
 */
export default function StocksPage() {
  return <StockSearchClient />;
}
