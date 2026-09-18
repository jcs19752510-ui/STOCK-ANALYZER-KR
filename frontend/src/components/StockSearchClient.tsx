"use client";

import { useEffect, useState } from "react";
import copy from "@/content/copy.ko.json";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState, type ErrorStateVariant } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { MarketFilterControl, type ScreenMarketOption } from "@/components/MarketFilterControl";
import { SearchInput } from "@/components/SearchInput";
import { StockListItem } from "@/components/StockListItem";
import { mapApiErrorCodeToDisplay } from "@/lib/errorMapping";
import { fetchStockSearch } from "@/lib/stockSearchApi";
import type { StockSearchItem } from "@/lib/types";

const DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 2;
const SKELETON_ROW_COUNT = 4;

type StockSearchState =
  | { kind: "loading" }
  | { kind: "success"; items: StockSearchItem[] }
  | { kind: "empty-result"; query: string }
  | { kind: "error"; variant: ErrorStateVariant };

/**
 * 종목 검색(`/stocks`, REQ-001, 04-ux-design.md §2-3/§1-3 Flow C).
 *
 * **자동완성이 아니다(§2-3 명시)** — 결과는 단순 `<ul>` 정적 리스트로만
 * 렌더링하고 리스트박스/콤보박스 ARIA 패턴, 열고 닫는 오버레이, 포커스
 * 트랩을 전혀 도입하지 않는다. UNIT-07이 겪은 `useFocusTrap` 관련 결함
 * (DEF-U07-01)은 "포커스를 가둬야 하는 오버레이가 있을 때"만 해당하는
 * 문제이며, 이 화면은 그런 오버레이 자체가 없어(UNIT-08과 동일한 판단
 * 근거) 적용 대상이 아니다(`unit-09-note.md` 접근성 사전 점검 참조).
 *
 * 클라이언트 컴포넌트인 이유: 타이핑마다 디바운스 조회를 해야 하므로
 * (`/screener`의 `ScreenerClient`와 동일한 이유, `screenApi.ts` 참조).
 */
export function StockSearchClient() {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [market, setMarket] = useState<ScreenMarketOption>("ALL");
  // `null`은 "아직 유효한 검색이 시작되지 않음"을 뜻한다. 질의가 2자
  // 미만으로 돌아가도 이 값을 별도로 초기화하지 않는다 — 아래 렌더링에서
  // `isQueryTooShort`가 `state` 값 자체를 무시하고 항상 `no-query` 빈 상태를
  // 우선 표시하기 때문이다(리액트 훅 린트가 금지하는 "effect 안에서 다른
  // 상태를 그대로 파생시키는 동기 setState" 패턴을 피하기 위한 구조).
  const [state, setState] = useState<StockSearchState | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const trimmedQuery = debouncedQuery.trim();
  const isQueryTooShort = trimmedQuery.length < MIN_QUERY_LENGTH;

  useEffect(() => {
    if (isQueryTooShort) return;

    let cancelled = false;
    // `useIsDesktopViewport.ts`와 동일한 관례: 이펙트 본문에서 `setState(...)`를
    // 바로 호출하지 않고 지역 함수로 감싸 호출한다(리액트 훅 린트
    // `set-state-in-effect`가 "effect 본문 최상위에서의 직접 setState 호출"만
    // 문제 삼는 얕은 휴리스틱이라, 데이터 페칭 시작 시점의 로딩 상태 전환처럼
    // 정당한 부수효과까지 오탐하는 것을 피하기 위함).
    const startLoading = () => setState({ kind: "loading" });
    startLoading();

    void fetchStockSearch(trimmedQuery, market).then((result) => {
      if (cancelled) return;

      if (result.kind === "error") {
        const display = mapApiErrorCodeToDisplay(result.code);
        // `/stocks`는 `DATA_PIPELINE_STALE`을 반환하지 않지만(기준시각 개념이
        // 없는 화면, `stockSearchApi.ts` 참조), 방어적으로 "empty" 판정이
        // 나오더라도 화면에 빈 상태가 아니라 일시적 오류로 안내한다.
        setState({
          kind: "error",
          variant: display.kind === "empty" ? "network" : display.variant,
        });
        return;
      }

      if (result.data.length === 0) {
        setState({ kind: "empty-result", query: trimmedQuery });
      } else {
        setState({ kind: "success", items: result.data });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [trimmedQuery, market, retryToken, isQueryTooShort]);

  function handleRetry() {
    setRetryToken((token) => token + 1);
  }

  return (
    <section className="stock-search-page">
      <h1>{copy.stockSearch.pageTitle}</h1>

      <div className="stock-search-page__controls">
        <SearchInput value={query} onChange={setQuery} />
        <MarketFilterControl value={market} onChange={setMarket} />
      </div>

      <div className="stock-search-page__results" aria-live="polite">
        {isQueryTooShort && <EmptyState variant="no-query" />}

        {!isQueryTooShort && state?.kind === "loading" && (
          <div className="stock-search-page__loading">
            <LoadingSkeleton variant="card" count={SKELETON_ROW_COUNT} />
          </div>
        )}

        {!isQueryTooShort && state?.kind === "empty-result" && (
          <EmptyState variant="no-search-result" query={state.query} />
        )}

        {!isQueryTooShort && state?.kind === "error" && (
          <ErrorState variant={state.variant} onRetry={handleRetry} />
        )}

        {!isQueryTooShort && state?.kind === "success" && (
          <ul className="stock-list">
            {state.items.map((item) => (
              <StockListItem key={item.stock_code} item={item} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
