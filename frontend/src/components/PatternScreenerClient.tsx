"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuotes } from "@/lib/useQuotes";
import copy from "@/content/copy.ko.json";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { LiveBasisSwitch } from "@/components/LiveBasisSwitch";
import { LiveChangesList, LiveScreenPanel } from "@/components/LiveScreenPanel";
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
  buildPatternSearchParams,
  fetchPatternResults,
  type PatternApiResult,
  type PatternQuery,
} from "@/lib/patternApi";
import { stripLiveParams } from "@/lib/liveScreen/logic";
import { useLiveScreen, useLiveScreenAccess, useLiveToggle, useNewCodes } from "@/lib/liveScreen/react";
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
  // 장중 기준(DEC-089): 로컬 모드 관리자에게만 전환이 보인다. 켜면 결과·배너·자동 갱신이 `/local/screen/pattern`으로 바뀐다. 꺼져 있으면 요청도 없다.
  const liveAccess = useLiveScreenAccess();
  const [liveOn, setLiveOn] = useLiveToggle(liveAccess);
  const live = useLiveScreen<PatternScreenData>(liveOn);
  const newCodes = useNewCodes(live.view);
  const liveMarks = liveOn ? { newCodes } : undefined;
  const liveData = liveOn ? live.view.data : null;
  const quotes = useQuotes(
    liveOn
      ? (liveData?.items.map((i) => i.stock_code) ?? [])
      : state.kind === "success"
        ? state.data.items.map((i) => i.stock_code)
        : [],
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

  // 자동 갱신으로 결과가 줄어 지금 보던 쪽이 비면(총건수는 남아 있음) 마지막 쪽으로 옮긴다.
  useEffect(() => {
    if (!liveOn || !liveData || liveData.items.length > 0 || liveData.total_count === 0) return;
    const last = Math.max(1, Math.ceil(liveData.total_count / PATTERN_PAGE_SIZE));
    if (last < liveData.page) live.setPage(last);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 응답이 바뀔 때만 확인
  }, [liveData]);

  // 켜짐이 바뀔 때: 켜면 적용해 둔 조건으로 바로 장중 기준 계산을 시작하고, 끄면 같은 조건을 일봉 기준으로 다시 조회한다.
  const wasLiveRef = useRef(false);
  useEffect(() => {
    if (liveOn) live.setQuery({ kind: "pattern", params: stripLiveParams(buildPatternSearchParams(applied)) }, applied.page);
    if (!liveOn && wasLiveRef.current) void runQuery(applied);
    wasLiveRef.current = liveOn;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 켜짐이 바뀔 때만 실행
  }, [liveOn]);

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
    if (liveOn) {
      const query = toQuery(values, 1);
      setApplied(query);
      live.setQuery({ kind: "pattern", params: stripLiveParams(buildPatternSearchParams(query)) }, 1);
      return;
    }
    void runQuery(toQuery(values, 1));
  }

  function handleToggleRequired(id: PatternConditionId) {
    setValues((prev) => ({ ...prev, required: toggleRequired(prev.required, id) }));
    setErrors((prev) => prev.filter((e) => e.field !== "required"));
  }

  const handleCloseMobile = useCallback(() => setMobileFilterOpen(false), []);
  const isLoading = liveOn ? live.view.loading && live.view.data === null : state.kind === "loading";
  const handleRevert = useCallback(() => setLiveOn(false), [setLiveOn]);

  return (
    <section className="screener-page pattern-page">
      <ScreeningModeNav current="pattern" />
      <h1>{copy.pattern.label}</h1>
      <PatternNotice />
      {liveAccess && <LiveBasisSwitch on={liveOn} onChange={setLiveOn} />}

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

        <div className="screener-page__results" aria-live={liveOn ? "off" : "polite"} aria-busy={isLoading}>
          {liveOn && (
            <LiveScreenPanel
              view={live.view}
              hasQuery
              onPause={live.pause}
              onResume={live.resume}
              onRefresh={live.refreshNow}
              onRevert={handleRevert}
            />
          )}

          {liveOn && liveData === null && live.view.error === null && (
            <div className="screener-page__loading">
              <LoadingSkeleton variant="card" count={5} />
            </div>
          )}

          {liveOn && liveData && liveData.total_count === 0 && (
            <>
              <ReadinessNote readiness={liveData.readiness} />
              <EmptyState variant="pattern-no-result" />
              <PatternDefinitionPanel definition={liveData.definition} basisNote={copy.liveScreen.patternDefinitionBasis} />
            </>
          )}

          {liveOn && liveData && liveData.total_count > 0 && (
            <>
              <h2 className="screener-page__results-heading">
                {fillTemplate(copy.pattern.resultsHeading, { total_count: liveData.total_count })}
              </h2>
              <ReadinessNote readiness={liveData.readiness} />
              {isDesktopResults ? (
                <PatternResultsTable items={liveData.items} definition={liveData.definition} quotes={quotes} live={liveMarks} />
              ) : (
                <PatternResultsList items={liveData.items} definition={liveData.definition} quotes={quotes} live={liveMarks} />
              )}
              <Pagination
                page={liveData.page}
                pageSize={PATTERN_PAGE_SIZE}
                totalCount={liveData.total_count}
                onPageChange={(page) => live.setPage(page)}
                announce={false}
              />
              <PatternDefinitionPanel definition={liveData.definition} basisNote={copy.liveScreen.patternDefinitionBasis} />
            </>
          )}

          {liveOn && liveData && <LiveChangesList view={live.view} />}

          {!liveOn && state.kind === "loading" && (
            <div className="screener-page__loading">
              <LoadingSkeleton variant="card" count={5} />
            </div>
          )}

          {!liveOn && state.kind === "empty" && <EmptyState variant={state.variant} />}

          {!liveOn && state.kind === "error" && (
            <ErrorState variant={state.variant} onRetry={() => void runQuery(applied)} />
          )}

          {!liveOn && state.kind === "empty-result" && (
            <>
              <DataFreshnessBadge freshness={state.freshness} />
              <ReadinessNote readiness={state.readiness} />
              <EmptyState variant="pattern-no-result" />
              <PatternDefinitionPanel definition={state.definition} />
            </>
          )}

          {!liveOn && state.kind === "success" && (
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
