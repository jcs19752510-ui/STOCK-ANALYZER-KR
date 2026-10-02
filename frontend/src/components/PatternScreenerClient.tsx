"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuotes } from "@/lib/useQuotes";
import copy from "@/content/copy.ko.json";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { EmptyState, type EmptyStateVariant } from "@/components/EmptyState";
import { ErrorState, type ErrorStateVariant } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { Pagination } from "@/components/Pagination";
import { PatternDefinitionPanel } from "@/components/PatternDefinitionPanel";
import { PatternFilterPanel } from "@/components/PatternFilterPanel";
import { PatternNotice } from "@/components/PatternNotice";
import { PatternResultsList } from "@/components/PatternResultsList";
import { PatternResultsTable } from "@/components/PatternResultsTable";
import { ReadinessNote } from "@/components/ReadinessNote";
import { ScreeningModeNav } from "@/components/ScreeningModeNav";
import { mapApiErrorCodeToDisplay } from "@/lib/errorMapping";
import { DEFAULT_PATTERN_FORM_VALUES } from "@/lib/patternDefaults";
import {
  PATTERN_PAGE_SIZE,
  fetchPatternResults,
  type PatternApiResult,
  type PatternQuery,
} from "@/lib/patternApi";
import { fillTemplate } from "@/lib/patternFormat";
import {
  PATTERN_FIELD_IDS,
  toggleRequired,
  validatePatternForm,
  type PatternFieldError,
  type PatternFormValues,
} from "@/lib/patternValidation";
import type {
  DataFreshness,
  PatternConditionId,
  PatternDefinition,
  PatternReadiness,
  PatternScreenData,
} from "@/lib/types";
import { useIsDesktopViewport } from "@/lib/useIsDesktopViewport";

type PatternState =
  | { kind: "loading" }
  | { kind: "success"; data: PatternScreenData; freshness: DataFreshness }
  | {
      kind: "empty-result";
      freshness: DataFreshness;
      definition: PatternDefinition;
      readiness: PatternReadiness;
    }
  | { kind: "empty"; variant: EmptyStateVariant }
  | { kind: "error"; variant: ErrorStateVariant };

function optionalNumber(raw: string): number | undefined {
  if (raw.trim() === "") return undefined;
  const value = Number(raw);
  return Number.isNaN(value) ? undefined : value;
}

function toQuery(values: PatternFormValues, page: number): PatternQuery {
  const volume = optionalNumber(values.volumeMin);
  return {
    market: values.market,
    marketCapMinEok: optionalNumber(values.marketCapMin),
    volumeMin: volume === undefined ? undefined : Math.trunc(volume),
    required: values.required,
    page,
  };
}

function resultToState(result: PatternApiResult): PatternState {
  if (result.kind === "error") {
    const display = mapApiErrorCodeToDisplay(result.code);
    return display.kind === "empty"
      ? { kind: "empty", variant: display.variant }
      : { kind: "error", variant: display.variant };
  }
  if (result.data.items.length === 0) {
    return {
      kind: "empty-result",
      freshness: result.freshness,
      definition: result.data.definition,
      readiness: result.data.readiness,
    };
  }
  return { kind: "success", data: result.data, freshness: result.freshness };
}

/**
 * 패턴 스크리닝 `/screener/pattern`(REQ-033, docs/pattern-screening/03-ux-design.md). 프리셋 화면이라
 * **진입 즉시 기본값으로 1회 자동 조회**한다. 클라이언트 컴포넌트인 이유는 `ScreenerClient`와 같다 —
 * 결과 영역만 갱신하고 필터는 유지해야 한다. 비예측 고지(`PatternNotice`)는 모든 상태에서 항상 렌더된다.
 * 화면 이름은 `copy.pattern.label` 한 곳에서만 가져온다(명칭 단일 출처).
 */
export function PatternScreenerClient() {
  const initialQuery = toQuery(DEFAULT_PATTERN_FORM_VALUES, 1);
  const [values, setValues] = useState<PatternFormValues>(DEFAULT_PATTERN_FORM_VALUES);
  const [errors, setErrors] = useState<PatternFieldError[]>([]);
  const [applied, setApplied] = useState<PatternQuery>(initialQuery);
  const [state, setState] = useState<PatternState>({ kind: "loading" });
  const [mobileFilterOpen, setMobileFilterOpen] = useState(false);
  const quotes = useQuotes(
    state.kind === "success" ? state.data.items.map((i) => i.stock_code) : [],
  );
  const isDesktopResults = useIsDesktopViewport(1024);
  const startedRef = useRef(false);

  // 진입 시 자동 1회 조회(StrictMode 이중 실행 방지). 상태 갱신은 응답을 받은 뒤에만 한다.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void fetchPatternResults(initialQuery).then((result) => setState(resultToState(result)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 마운트 시 1회만 실행
  }, []);

  async function runQuery(query: PatternQuery) {
    setApplied(query);
    setState({ kind: "loading" });
    setState(resultToState(await fetchPatternResults(query)));
  }

  function handleSubmit() {
    const found = validatePatternForm(values, {
      requiredError: copy.pattern.requiredError,
      numberError: copy.pattern.numberError,
    });
    if (found.length > 0) {
      setErrors(found);
      document.getElementById(PATTERN_FIELD_IDS[found[0].field])?.focus();
      return; // 요청을 보내지 않는다
    }
    setErrors([]);
    setMobileFilterOpen(false);
    void runQuery(toQuery(values, 1));
  }

  function handleToggleRequired(id: PatternConditionId) {
    setValues((prev) => ({ ...prev, required: toggleRequired(prev.required, id) }));
    setErrors((prev) => prev.filter((e) => e.field !== "required"));
  }

  const handleCloseMobile = useCallback(() => setMobileFilterOpen(false), []);
  const isLoading = state.kind === "loading";

  return (
    <section className="screener-page pattern-page">
      <ScreeningModeNav current="pattern" />
      <h1>{copy.pattern.label}</h1>
      <PatternNotice />

      <button
        type="button"
        className="screener-page__mobile-filter-trigger"
        onClick={() => setMobileFilterOpen(true)}
      >
        {copy.pattern.mobileOpenFilterLabel}
      </button>

      <div className="screener-page__layout">
        <PatternFilterPanel
          values={values}
          errors={errors}
          onMarketChange={(market) => setValues((prev) => ({ ...prev, market }))}
          onFieldChange={(field, value) => {
            setValues((prev) => ({ ...prev, [field]: value }));
            setErrors((prev) => prev.filter((e) => e.field !== field));
          }}
          onToggleRequired={handleToggleRequired}
          onSubmit={handleSubmit}
          isSubmitting={isLoading}
          isMobileOpen={mobileFilterOpen}
          onCloseMobile={handleCloseMobile}
        />

        <div className="screener-page__results" aria-live="polite" aria-busy={isLoading}>
          {state.kind === "loading" && (
            <div className="screener-page__loading">
              <LoadingSkeleton variant="card" count={5} />
            </div>
          )}

          {state.kind === "empty" && <EmptyState variant={state.variant} />}

          {state.kind === "error" && (
            <ErrorState variant={state.variant} onRetry={() => void runQuery(applied)} />
          )}

          {state.kind === "empty-result" && (
            <>
              <DataFreshnessBadge freshness={state.freshness} />
              <ReadinessNote readiness={state.readiness} />
              <EmptyState variant="pattern-no-result" />
              <PatternDefinitionPanel definition={state.definition} />
            </>
          )}

          {state.kind === "success" && (
            <>
              <DataFreshnessBadge freshness={state.freshness} />
              <h2 className="screener-page__results-heading">
                {fillTemplate(copy.pattern.resultsHeading, {
                  total_count: state.data.total_count,
                })}
              </h2>
              <ReadinessNote readiness={state.data.readiness} />
              {isDesktopResults ? (
                <PatternResultsTable
                  items={state.data.items}
                  definition={state.data.definition}
                  quotes={quotes}
                />
              ) : (
                <PatternResultsList
                  items={state.data.items}
                  definition={state.data.definition}
                  quotes={quotes}
                />
              )}
              <Pagination
                page={state.data.page}
                pageSize={PATTERN_PAGE_SIZE}
                totalCount={state.data.total_count}
                onPageChange={(page) => void runQuery({ ...applied, page })}
              />
              <PatternDefinitionPanel definition={state.data.definition} />
            </>
          )}
        </div>
      </div>
    </section>
  );
}
