import type { Metadata } from "next";
import { notFound } from "next/navigation";
import copy from "@/content/copy.ko.json";
import { PatternScreenerClient } from "@/components/PatternScreenerClient";
import { PATTERN_SCREEN_ENABLED } from "@/lib/patternFeature";

// 페이지 제목은 명칭 단일 출처(`copy.pattern.label`)에서 조합한다.
export const metadata: Metadata = {
  title: `${copy.pattern.label}${copy.pattern.pageTitleSuffix}`,
};

/**
 * 패턴 스크리닝 `/screener/pattern`(REQ-033). 메타데이터·기능 스위치만 담당하는 서버 컴포넌트 셸이고
 * 실제 상호작용은 `PatternScreenerClient`가 맡는다(`/screener`와 같은 분리 이유). 스위치가 꺼져 있으면
 * (`NEXT_PUBLIC_PATTERN_SCREEN_ENABLED="false"`) 404다.
 */
export default function PatternScreenerPage() {
  if (!PATTERN_SCREEN_ENABLED) notFound();
  return <PatternScreenerClient />;
}
