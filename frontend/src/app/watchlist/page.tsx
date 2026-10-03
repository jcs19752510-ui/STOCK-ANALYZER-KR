import type { Metadata } from "next";
import { WatchlistClient } from "@/components/WatchlistClient";

export const metadata: Metadata = {
  title: "관심종목 | 국내주식 조건 스크리닝 정보 서비스",
};

/** 관심종목(`/watchlist`, DEC-055): 이 브라우저에만 저장되는 개인 목록. 서버 호출은 시세 요약(`/stocks/quotes`)뿐이다. */
export default function WatchlistPage() {
  return <WatchlistClient />;
}
