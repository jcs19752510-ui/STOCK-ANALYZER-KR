import Link from "next/link";
import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §4 `ErrorState` 공통 컴포넌트, §1-4 Flow D 매핑.
 *
 * `not-found`(404 STOCK_NOT_FOUND)는 이 컴포넌트가 아니라 Next.js의
 * `notFound()` + 라우트 전용 `not-found.tsx`로 처리한다(`app/stocks/[code]/
 * not-found.tsx`) — 04-ux-design.md §2-4가 요구하는 "종목 검색으로 돌아가기"
 * CTA가 있는 전체 화면 대체를 프레임워크 관용구로 구현하는 것이 더 안전하다고
 * 판단했다(unit-06-note.md §2 참조). 그래서 이 컴포넌트의 변형은 3종
 * (`network`/`calendar-not-confirmed`/`rate-limited`)만 다룬다.
 */
export type ErrorStateVariant = "network" | "calendar-not-confirmed" | "rate-limited";

interface ErrorStateProps {
  variant: ErrorStateVariant;
  /** "다시 시도" 링크가 이동할 경로. 서버 컴포넌트 재요청을 위해 현재 경로를 그대로 쓴다. */
  retryHref: string;
}

const VARIANT_MESSAGE: Record<ErrorStateVariant, string> = {
  network: copy.errorState.networkTitle,
  "calendar-not-confirmed": copy.errorState.calendarNotConfirmedTitle,
  "rate-limited": copy.errorState.rateLimitedTitle,
};

export function ErrorState({ variant, retryHref }: ErrorStateProps) {
  return (
    <div className="error-state" role="alert">
      <p className="error-state__message">{VARIANT_MESSAGE[variant]}</p>
      <Link href={retryHref} className="error-state__retry">
        {copy.errorState.retryButtonLabel}
      </Link>
    </div>
  );
}
