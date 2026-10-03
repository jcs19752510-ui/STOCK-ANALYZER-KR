"use client";

import copy from "@/content/copy.ko.json";
import { useIntradayView } from "@/lib/viewBasis";

/** 종목 상세 기준 안내 문구. 로컬 모드의 장중 보기(호가·체결·분·틱)일 때만 증권사 시세 안내로 바꾼다(DEC-056). */
export function PriceBasisNote() {
  const intraday = useIntradayView();
  return <>{intraday ? copy.stockDetail.priceBasisLocalNote : copy.stockDetail.priceBasisNote}</>;
}
