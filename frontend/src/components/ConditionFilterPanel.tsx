"use client";

import { useRef } from "react";
import copy from "@/content/copy.ko.json";
import { ConditionField } from "@/components/ConditionField";
import { MarketFilterControl } from "@/components/MarketFilterControl";
import { SortControl } from "@/components/SortControl";
import { SCREEN_FIELD_IDS } from "@/lib/screenFieldIds";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useIsDesktopViewport } from "@/lib/useIsDesktopViewport";
import type { ScreenSortBy, ScreenSortDir } from "@/lib/screenApi";
import type { FieldError, ScreenFormValues } from "@/lib/screenValidation";

/**
 * 04-ux-design.md §2-2 `ConditionFilterPanel` — 데스크톱(≥1024px, §6 `lg`)은
 * 좌측 사이드 패널로 상시 노출, 모바일은 바텀시트(토글 오픈). §5-3 포커스
 * 트랩/Esc 닫기/포커스 복귀는 모바일 바텀시트로 열렸을 때만 적용한다
 * (unit-05-note.md §2 편차1이 이 유닛에 이행을 위임한 요구사항).
 */
interface ConditionFilterPanelProps {
  values: ScreenFormValues;
  fieldErrors: FieldError[];
  onFieldChange: (field: keyof ScreenFormValues, value: string) => void;
  onMarketChange: (value: ScreenFormValues["market"]) => void;
  onSortByChange: (value: ScreenSortBy) => void;
  onSortDirChange: (value: ScreenSortDir) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  isMobileOpen: boolean;
  onCloseMobile: () => void;
}

function errorFor(fieldErrors: FieldError[], field: keyof ScreenFormValues): string | undefined {
  return fieldErrors.find((e) => e.field === field)?.message;
}

export function ConditionFilterPanel({
  values,
  fieldErrors,
  onFieldChange,
  onMarketChange,
  onSortByChange,
  onSortDirChange,
  onSubmit,
  isSubmitting,
  isMobileOpen,
  onCloseMobile,
}: ConditionFilterPanelProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const isDesktop = useIsDesktopViewport(1024);
  const trapActive = isMobileOpen && !isDesktop;

  useFocusTrap(panelRef, trapActive, onCloseMobile);

  const panelClassName = isMobileOpen
    ? "condition-filter-panel condition-filter-panel--mobile-open"
    : "condition-filter-panel";

  return (
    <>
      {trapActive && (
        <div
          className="condition-filter-panel__overlay"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}
      <div
        ref={panelRef}
        className={panelClassName}
        role={trapActive ? "dialog" : undefined}
        aria-modal={trapActive ? true : undefined}
        aria-label={trapActive ? copy.nav.screener : undefined}
      >
        {trapActive && (
          <button
            type="button"
            className="condition-filter-panel__close"
            onClick={onCloseMobile}
          >
            {copy.screener.mobileCloseFilterLabel}
          </button>
        )}

        <form
          className="condition-filter-panel__form"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <MarketFilterControl value={values.market} onChange={onMarketChange} />

          <fieldset className="condition-field-group">
            <legend className="condition-field-group__legend">
              {copy.screener.marketCapLabel}
            </legend>
            <div className="condition-field-group__row">
              <ConditionField
                id={SCREEN_FIELD_IDS.marketCapMin!}
                label={copy.screener.marketCapMinPlaceholder}
                value={values.marketCapMin}
                onChange={(v) => onFieldChange("marketCapMin", v)}
                placeholder={copy.screener.marketCapMinPlaceholder}
                errorMessage={errorFor(fieldErrors, "marketCapMin")}
              />
              <ConditionField
                id={SCREEN_FIELD_IDS.marketCapMax!}
                label={copy.screener.marketCapMaxPlaceholder}
                value={values.marketCapMax}
                onChange={(v) => onFieldChange("marketCapMax", v)}
                placeholder={copy.screener.marketCapMaxPlaceholder}
                errorMessage={errorFor(fieldErrors, "marketCapMax")}
              />
            </div>
          </fieldset>

          <ConditionField
            id={SCREEN_FIELD_IDS.volumeMin!}
            label={copy.screener.volumeLabel}
            value={values.volumeMin}
            onChange={(v) => onFieldChange("volumeMin", v)}
            suffix={copy.screener.volumeMinSuffix}
            errorMessage={errorFor(fieldErrors, "volumeMin")}
          />

          <fieldset className="condition-field-group">
            <legend className="condition-field-group__legend">
              {copy.screener.returnPctLabel}
            </legend>
            <div className="condition-field-group__row">
              <ConditionField
                id={SCREEN_FIELD_IDS.returnPctMin!}
                label={copy.screener.marketCapMinPlaceholder}
                value={values.returnPctMin}
                onChange={(v) => onFieldChange("returnPctMin", v)}
                placeholder={copy.screener.marketCapMinPlaceholder}
                errorMessage={errorFor(fieldErrors, "returnPctMin")}
              />
              <ConditionField
                id={SCREEN_FIELD_IDS.returnPctMax!}
                label={copy.screener.marketCapMaxPlaceholder}
                value={values.returnPctMax}
                onChange={(v) => onFieldChange("returnPctMax", v)}
                placeholder={copy.screener.marketCapMaxPlaceholder}
                errorMessage={errorFor(fieldErrors, "returnPctMax")}
              />
            </div>
          </fieldset>

          <ConditionField
            id={SCREEN_FIELD_IDS.perMax!}
            label={copy.screener.perLabel}
            value={values.perMax}
            onChange={(v) => onFieldChange("perMax", v)}
            suffix={copy.screener.perSuffix}
            errorMessage={errorFor(fieldErrors, "perMax")}
          />

          <ConditionField
            id={SCREEN_FIELD_IDS.pbrMax!}
            label={copy.screener.pbrLabel}
            value={values.pbrMax}
            onChange={(v) => onFieldChange("pbrMax", v)}
            suffix={copy.screener.pbrSuffix}
            errorMessage={errorFor(fieldErrors, "pbrMax")}
          />

          <SortControl
            sortBy={values.sortBy as ScreenSortBy}
            sortDir={values.sortDir}
            onSortByChange={onSortByChange}
            onSortDirChange={onSortDirChange}
          />

          <button
            type="submit"
            className="condition-filter-panel__submit"
            disabled={isSubmitting}
          >
            {isSubmitting && <span className="condition-filter-panel__spinner" aria-hidden="true" />}
            <span>{copy.screener.submitButtonLabel}</span>
          </button>
        </form>
      </div>
    </>
  );
}
