"use client";

import copy from "@/content/copy.ko.json";
import { useIntradayView, useLiveView } from "@/lib/viewBasis";

/**
 * 종목 상세 기준 안내 문구. 로컬 모드의 장중 보기(호가·체결·분·틱)일 때는 증권사 시세 안내로(DEC-056),
 * 실시간 스트림이 현재가를 갱신하는 동안에는 "내 증권사 실시간 시세(본인 전용)" 안내로 바꾼다(DEC-084).
 * `tradeDate`를 주면 "{date} 종가 기준 ·" 머리말까지 함께 그린다(라이브일 때는 종가 기준이 아니므로 머리말을 뺀다).
 */
export function PriceBasisNote({ tradeDate }: { tradeDate?: string }) {
  const intraday = useIntradayView();
  const live = useLiveView();
  const head = tradeDate ? `${copy.stockDetail.priceBasis.replace("{date}", tradeDate)} · ` : "";
  if (live) return <>{copy.stockDetail.priceBasisLiveNote}</>;
  return <>{head}{intraday ? copy.stockDetail.priceBasisLocalNote : copy.stockDetail.priceBasisNote}</>;
}
