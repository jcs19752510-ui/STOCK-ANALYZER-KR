"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import copy from "@/content/copy.ko.json";
import { ConditionFilterPanel } from "@/components/ConditionFilterPanel";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState, type ErrorStateVariant } from "@/components/ErrorState";
import { LiveBasisSwitch } from "@/components/LiveBasisSwitch";
import { LiveChangesList, LiveScreenPanel } from "@/components/LiveScreenPanel";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { Pagination } from "@/components/Pagination";
import { ResultsList } from "@/components/ResultsList";
import { ResultsTable } from "@/components/ResultsTable";
import { mapApiErrorCodeToDisplay } from "@/lib/errorMapping";
import { buildSearchParams, fetchScreenResults, type ScreenQuery, type ScreenSortBy, type ScreenSortDir } from "@/lib/screenApi";
import { stripLiveParams } from "@/lib/liveScreen/logic";
import { useLiveScreen, useLiveScreenAccess, useLiveToggle, useNewCodes } from "@/lib/liveScreen/react";
import { SCREEN_FIELD_IDS } from "@/lib/screenFieldIds";
import { orderMatchedMetricKeys } from "@/lib/screenMetricFormat";
import { useIsDesktopViewport } from "@/lib/useIsDesktopViewport";
import { useLocalQuotes } from "@/lib/useQuotes";
import {
  DEFAULT_SCREEN_FORM_VALUES,
  defaultScreenFormValuesFor,
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
    ma5GapPctMin: parseOptionalFloat(values.ma5GapPctMin),
    ma5GapPctMax: parseOptionalFloat(values.ma5GapPctMax),
    ma20GapPctMin: parseOptionalFloat(values.ma20GapPctMin),
    ma20GapPctMax: parseOptionalFloat(values.ma20GapPctMax),
    volumeAnomalyScoreMin: parseOptionalFloat(values.volumeAnomalyScoreMin),
    volumeAnomalyScoreMax: parseOptionalFloat(values.volumeAnomalyScoreMax),
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
  // 개인 로컬 모드(내 PC, 관리자)에서만 결과 옆에 현재가(준실시간)를 보인다. 조건 판정은 일봉 기준 그대로(DEC-084 B).
  // 장중 기준(DEC-089): 로컬 모드 관리자에게만 전환이 보이고, 켜면 결과·배너·자동 갱신이 `/local/screen`으로 바뀐다. 꺼져 있으면 아래 코드는 아무 요청도 하지 않는다.
  const liveAccess = useLiveScreenAccess();
  const [liveOn, setLiveOn] = useLiveToggle(liveAccess);
  const live = useLiveScreen<ScreenData>(liveOn);
  const newCodes = useNewCodes(live.view);
  const liveMarks = liveOn ? { newCodes } : undefined;
  const liveData = liveOn ? live.view.data : null;
  const resultCodes = liveOn
    ? (liveData?.items.map((item) => item.stock_code) ?? [])
    : state.kind === "success"
      ? state.data.items.map((item) => item.stock_code)
      : [];
  const { quotes: resultQuotes, enabled: showQuotes } = useLocalQuotes(resultCodes);

  function updateField(field: keyof ScreenFormValues, value: string) {
    setFormValues((prev) => ({ ...prev, [field]: value }));
  }

  /**
   * 시장 탭(전체/코스피/코스닥) 전환 시 폼 전체를 기본값으로 되돌린다
   * (2026-09-22 사용자 결정 — "조건을 몰라도 [조건 적용]을 누르면 바로
   * 유의미한 결과가 나오게" 해달라는 요청). `updateField`처럼 market 필드만
   * 바꾸지 않고 전체를 리셋하는 이유: 이전 탭에서 입력해둔 조건이 새 시장
   * 범위에서도 그대로 유효하다고 보장할 수 없고(예: PER 조건은 괜찮지만
   * 시가총액 조건은 시장마다 분포가 다름), 탭 전환 자체가 "새로 시작"이라는
   * 사용자 기대에 더 맞는다.
   */
  function handleMarketChange(market: ScreenFormValues["market"]) {
    setFormValues(defaultScreenFormValuesFor(market));
    setFieldErrors([]);
  }

  // 자동 갱신으로 결과가 줄어 지금 보던 쪽이 비면(총건수는 남아 있음) 마지막 쪽으로 옮긴다.
  useEffect(() => {
    if (!liveOn || !liveData || liveData.items.length > 0 || liveData.total_count === 0) return;
    const last = Math.max(1, Math.ceil(liveData.total_count / PAGE_SIZE));
    if (last < liveData.page) live.setPage(last);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 응답이 바뀔 때만 확인
  }, [liveData]);

  // 켜짐이 바뀔 때: 켜면 적용해 둔 조건으로 바로 장중 기준 계산을 시작하고, 끄면 같은 조건을 일봉 기준으로 다시 조회한다.
  const wasLiveRef = useRef(false);
  useEffect(() => {
    if (liveOn && appliedQuery) live.setQuery({ kind: "screen", params: stripLiveParams(buildSearchParams(appliedQuery)) }, appliedQuery.page);
    if (!liveOn && wasLiveRef.current && appliedQuery) void runQuery(appliedQuery);
    wasLiveRef.current = liveOn;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 켜짐이 바뀔 때만 실행
  }, [liveOn]);

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
    if (liveOn) {
      const query = toScreenQuery(formValues, 1);
      setAppliedQuery(query);
      live.setQuery({ kind: "screen", params: stripLiveParams(buildSearchParams(query)) }, 1);
      return;
    }
    void runQuery(toScreenQuery(formValues, 1));
  }

  function handlePageChange(page: number) {
    if (!appliedQuery) return;
    if (liveOn) {
      setAppliedQuery({ ...appliedQuery, page });
      live.setPage(page); // 일시정지 중이면 같은 snapshot_id, 아니면 최신
      return;
    }
    void runQuery({ ...appliedQuery, page });
  }

  function handleRetry() {
    if (!appliedQuery) return;
    void runQuery(appliedQuery);
  }

  const handleRevert = useCallback(() => setLiveOn(false), [setLiveOn]);

  // DEF-U07-01 원인(b) 이중 방어: `useFocusTrap`이 `onEscape`를 ref로
  // 추적해 불안정한 참조에 더 이상 영향받지 않지만, 이 콜백 자체도
  // 매 렌더마다 새로 만들 이유가 없으므로 안정화한다.
  const handleCloseMobile = useCallback(() => setMobileFilterOpen(false), []);

  const isSubmitting = liveOn ? live.view.loading && live.view.data === null : state.kind === "loading";
  const showPercentileScopeNotice = appliedQuery !== null && appliedQuery.market !== "ALL";

  /** 제목·표(또는 카드)·페이지 이동. 일봉 기준과 장중 기준이 같은 모양을 쓴다(장중 기준은 `liveMarks`로 "신규"·"일봉" 표지를 더한다). */
  function renderResults(data: ScreenData) {
    const metricKeys = orderMatchedMetricKeys(Object.keys(data.items[0]?.matched_metrics ?? {}));
    const heading = `${copy.screener.resultsHeadingPrefix} ${data.total_count}${copy.screener.resultsHeadingSuffix}`;
    return (
      <>
        <h2 className="screener-page__results-heading">{heading}</h2>
        {isDesktopResults ? (
          <ResultsTable
            items={data.items}
            metricKeys={metricKeys}
            captionText={heading}
            quotes={showQuotes ? resultQuotes : undefined}
            live={liveMarks}
          />
        ) : (
          <ResultsList items={data.items} metricKeys={metricKeys} quotes={showQuotes ? resultQuotes : undefined} live={liveMarks} />
        )}
        <Pagination
          page={data.page}
          pageSize={PAGE_SIZE}
          totalCount={data.total_count}
          onPageChange={handlePageChange}
          announce={!liveOn}
        />
      </>
    );
  }

  return (
    <section className="screener-page">
      <h1>{copy.nav.screener}</h1>
      {liveAccess && <LiveBasisSwitch on={liveOn} onChange={setLiveOn} />}

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
          onMarketChange={handleMarketChange}
          onSortByChange={(value) => updateField("sortBy", value)}
          onSortDirChange={(value: ScreenSortDir) => updateField("sortDir", value)}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          isMobileOpen={mobileFilterOpen}
          onCloseMobile={handleCloseMobile}
        />

        <div className="screener-page__results" aria-live={liveOn ? "off" : "polite"}>
          {liveOn && (
            <LiveScreenPanel
              view={live.view}
              hasQuery={appliedQuery !== null}
              onPause={live.pause}
              onResume={live.resume}
              onRefresh={live.refreshNow}
              onRevert={handleRevert}
            />
          )}

          {liveOn && appliedQuery === null && <EmptyState variant="no-screen-conditions" />}

          {liveOn && appliedQuery !== null && liveData === null && live.view.error === null && (
            <div className="screener-page__loading" aria-busy="true">
              <LoadingSkeleton variant="card" count={5} />
            </div>
          )}

          {liveOn && liveData && liveData.total_count === 0 && <EmptyState variant="no-screen-result" />}

          {liveOn && liveData && liveData.total_count > 0 && (
            <>
              {showPercentileScopeNotice && (
                <p className="inline-notice inline-notice--info">{copy.screener.percentileScopeNotice}</p>
              )}
              {renderResults(liveData)}
            </>
          )}

          {liveOn && liveData && <LiveChangesList view={live.view} />}

          {!liveOn && state.kind === "idle" && <EmptyState variant="no-screen-conditions" />}

          {!liveOn && state.kind === "loading" && (
            <div className="screener-page__loading">
              <LoadingSkeleton variant="card" count={5} />
            </div>
          )}

          {!liveOn && state.kind === "empty-no-data" && <EmptyState variant="no-data-yet" />}

          {!liveOn && state.kind === "error" && (
            <ErrorState variant={state.variant} onRetry={handleRetry} />
          )}

          {!liveOn && state.kind === "empty-result" && (
            <>
              <DataFreshnessBadge freshness={state.freshness} />
              <EmptyState variant="no-screen-result" />
            </>
          )}

          {!liveOn && state.kind === "success" && (
            <>
              <DataFreshnessBadge freshness={state.freshness} />
              {showPercentileScopeNotice && (
                <p className="inline-notice inline-notice--info">
                  {copy.screener.percentileScopeNotice}
                </p>
              )}
              {showQuotes && (
                <p className="inline-notice inline-notice--info">{copy.screener.liveQuoteNotice}</p>
              )}
              {renderResults(state.data)}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
