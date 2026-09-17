"use client";

import { useCallback, useState } from "react";
import copy from "@/content/copy.ko.json";
import { ConditionFilterPanel } from "@/components/ConditionFilterPanel";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState, type ErrorStateVariant } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { Pagination } from "@/components/Pagination";
import { ResultsList } from "@/components/ResultsList";
import { ResultsTable } from "@/components/ResultsTable";
import { mapApiErrorCodeToDisplay } from "@/lib/errorMapping";
import { fetchScreenResults, type ScreenQuery, type ScreenSortBy, type ScreenSortDir } from "@/lib/screenApi";
import { SCREEN_FIELD_IDS } from "@/lib/screenFieldIds";
import { orderMatchedMetricKeys } from "@/lib/screenMetricFormat";
import { useIsDesktopViewport } from "@/lib/useIsDesktopViewport";
import {
  DEFAULT_SCREEN_FORM_VALUES,
  validateScreenForm,
  type FieldError,
  type ScreenFormValues,
} from "@/lib/screenValidation";
import type { DataFreshness, ScreenData } from "@/lib/types";

const PAGE_SIZE = 50;

type ScreenerState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: ScreenData; freshness: DataFreshness }
  | { kind: "empty-result"; freshness: DataFreshness }
  | { kind: "empty-no-data" }
  | { kind: "error"; variant: ErrorStateVariant };

function parseOptionalFloat(raw: string): number | undefined {
  if (raw.trim() === "") return undefined;
  const value = Number(raw);
  return Number.isNaN(value) ? undefined : value;
}

function parseOptionalInt(raw: string): number | undefined {
  const value = parseOptionalFloat(raw);
  return value === undefined ? undefined : Math.trunc(value);
}

function toScreenQuery(values: ScreenFormValues, page: number): ScreenQuery {
  return {
    market: values.market,
    marketCapMinEok: parseOptionalFloat(values.marketCapMin),
    marketCapMaxEok: parseOptionalFloat(values.marketCapMax),
    volumeMin: parseOptionalInt(values.volumeMin),
    returnPctMin: parseOptionalFloat(values.returnPctMin),
    returnPctMax: parseOptionalFloat(values.returnPctMax),
    perMax: parseOptionalFloat(values.perMax),
    pbrMax: parseOptionalFloat(values.pbrMax),
    sortBy: values.sortBy as ScreenSortBy,
    sortDir: values.sortDir,
    page,
  };
}

/**
 * 04-ux-design.md §2-2 `/screener` — 클라이언트 컴포넌트인 이유: "로딩:
 * 결과 영역만 스켈레톤, 조건 폼은 그대로 유지"를 만족하려면 페이지 전체를
 * 다시 내비게이션하지 않고 결과 영역만 갱신해야 한다(`/stocks/[code]`의
 * 서버 컴포넌트 fetch 패턴과 다른 이유, `screenApi.ts` 참조).
 */
export function ScreenerClient() {
  const [formValues, setFormValues] = useState<ScreenFormValues>(DEFAULT_SCREEN_FORM_VALUES);
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const [appliedQuery, setAppliedQuery] = useState<ScreenQuery | null>(null);
  const [state, setState] = useState<ScreenerState>({ kind: "idle" });
  const [mobileFilterOpen, setMobileFilterOpen] = useState(false);
  const isDesktopResults = useIsDesktopViewport(768);

  function updateField(field: keyof ScreenFormValues, value: string) {
    setFormValues((prev) => ({ ...prev, [field]: value }));
  }

  async function runQuery(query: ScreenQuery) {
    setAppliedQuery(query);
    setState({ kind: "loading" });

    const result = await fetchScreenResults(query);

    if (result.kind === "error") {
      const display = mapApiErrorCodeToDisplay(result.code);
      if (display.kind === "empty") {
        setState({ kind: "empty-no-data" });
      } else {
        setState({ kind: "error", variant: display.variant });
      }
      return;
    }

    if (result.data.items.length === 0) {
      setState({ kind: "empty-result", freshness: result.freshness });
    } else {
      setState({ kind: "success", data: result.data, freshness: result.freshness });
    }
  }

  function handleSubmit() {
    const errors = validateScreenForm(formValues);
    if (errors.length > 0) {
      setFieldErrors(errors);
      const firstFieldId = SCREEN_FIELD_IDS[errors[0].field];
      if (firstFieldId) {
        document.getElementById(firstFieldId)?.focus();
      }
      return;
    }
    setFieldErrors([]);
    setMobileFilterOpen(false);
    void runQuery(toScreenQuery(formValues, 1));
  }

  function handlePageChange(page: number) {
    if (!appliedQuery) return;
    void runQuery({ ...appliedQuery, page });
  }

  function handleRetry() {
    if (!appliedQuery) return;
    void runQuery(appliedQuery);
  }

  // DEF-U07-01 원인(b) 이중 방어: `useFocusTrap`이 `onEscape`를 ref로
  // 추적해 불안정한 참조에 더 이상 영향받지 않지만, 이 콜백 자체도
  // 매 렌더마다 새로 만들 이유가 없으므로 안정화한다.
  const handleCloseMobile = useCallback(() => setMobileFilterOpen(false), []);

  const isSubmitting = state.kind === "loading";
  const showPercentileScopeNotice = appliedQuery !== null && appliedQuery.market !== "ALL";

  return (
    <section className="screener-page">
      <h1>{copy.nav.screener}</h1>

      <button
        type="button"
        className="screener-page__mobile-filter-trigger"
        onClick={() => setMobileFilterOpen(true)}
      >
        {copy.screener.mobileOpenFilterLabel}
      </button>

      <div className="screener-page__layout">
        <ConditionFilterPanel
          values={formValues}
          fieldErrors={fieldErrors}
          onFieldChange={updateField}
          onMarketChange={(value) => updateField("market", value)}
          onSortByChange={(value) => updateField("sortBy", value)}
          onSortDirChange={(value: ScreenSortDir) => updateField("sortDir", value)}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          isMobileOpen={mobileFilterOpen}
          onCloseMobile={handleCloseMobile}
        />

        <div className="screener-page__results" aria-live="polite">
          {state.kind === "idle" && <EmptyState variant="no-screen-conditions" />}

          {state.kind === "loading" && (
            <div className="screener-page__loading">
              <LoadingSkeleton variant="card" count={5} />
            </div>
          )}

          {state.kind === "empty-no-data" && <EmptyState variant="no-data-yet" />}

          {state.kind === "error" && (
            <ErrorState variant={state.variant} onRetry={handleRetry} />
          )}

          {state.kind === "empty-result" && (
            <>
              <DataFreshnessBadge freshness={state.freshness} />
              <EmptyState variant="no-screen-result" />
            </>
          )}

          {state.kind === "success" && (
            <>
              <DataFreshnessBadge freshness={state.freshness} />
              {showPercentileScopeNotice && (
                <p className="inline-notice inline-notice--info">
                  {copy.screener.percentileScopeNotice}
                </p>
              )}
              <h2 className="screener-page__results-heading">
                {copy.screener.resultsHeadingPrefix} {state.data.total_count}
                {copy.screener.resultsHeadingSuffix}
              </h2>
              {(() => {
                const metricKeys = orderMatchedMetricKeys(
                  Object.keys(state.data.items[0]?.matched_metrics ?? {})
                );
                return isDesktopResults ? (
                  <ResultsTable
                    items={state.data.items}
                    metricKeys={metricKeys}
                    captionText={`${copy.screener.resultsHeadingPrefix} ${state.data.total_count}${copy.screener.resultsHeadingSuffix}`}
                  />
                ) : (
                  <ResultsList items={state.data.items} metricKeys={metricKeys} />
                );
              })()}
              <Pagination
                page={state.data.page}
                pageSize={PAGE_SIZE}
                totalCount={state.data.total_count}
                onPageChange={handlePageChange}
              />
            </>
          )}
        </div>
      </div>
    </section>
  );
}
