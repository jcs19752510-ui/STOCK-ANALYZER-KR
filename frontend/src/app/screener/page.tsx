import type { Metadata } from "next";
import { ScreenerClient } from "@/components/ScreenerClient";

export const metadata: Metadata = {
  title: "조건 스크리닝 | 국내주식 조건 스크리닝 정보 서비스",
};

/**
 * 조건 기반 스크리닝(`/screener`, REQ-003, 04-ux-design.md §2-2). UNIT-05가
 * 만든 임시 플레이스홀더를 실제 화면으로 교체한다. 이 파일은 메타데이터만
 * 담당하는 서버 컴포넌트 셸이고, 실제 상호작용(조건 폼/결과 갱신)은
 * `ScreenerClient`(클라이언트 컴포넌트)가 담당한다 — "use client" 컴포넌트는
 * `metadata`를 export할 수 없기 때문에 이렇게 분리했다.
 */
export default function ScreenerPage() {
  return <ScreenerClient />;
}
