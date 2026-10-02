"use client";

import { useRef } from "react";
import copy from "@/content/copy.ko.json";
import { ConditionField } from "@/components/ConditionField";
import { MarketFilterControl } from "@/components/MarketFilterControl";
import { PATTERN_CONDITION_IDS } from "@/lib/patternApi";
import { conditionTitle } from "@/lib/patternFormat";
import {
  PATTERN_FIELD_IDS,
  type PatternFieldError,
  type PatternFormField,
  type PatternFormValues,
} from "@/lib/patternValidation";
import type { PatternConditionId } from "@/lib/types";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useIsDesktopViewport } from "@/lib/useIsDesktopViewport";

/**
 * 패턴 스크리닝 필터 패널(03-ux-design.md §2·§4). 시장·최소 시가총액·최소 거래량·필수 조건 체크.
 * 임계값 입력은 없다(서버 고정 — 사용자가 바꿀 수 없다). 데스크톱(≥1024px)은 좌측 사이드 패널, 모바일은
 * 바텀시트이며 시트가 열려 있을 때만 포커스 트랩·Esc 닫기·포커스 복귀를 적용한다(`ConditionFilterPanel`과 동일 패턴/CSS).
 */
interface PatternFilterPanelProps {
  values: PatternFormValues;
  errors: PatternFieldError[];
  onMarketChange: (value: PatternFormValues["market"]) => void;
  onFieldChange: (field: "marketCapMin" | "volumeMin", value: string) => void;
  onToggleRequired: (id: PatternConditionId) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  isMobileOpen: boolean;
  onCloseMobile: () => void;
}

function errorFor(errors: PatternFieldError[], field: PatternFormField): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}

const REQUIRED_ERROR_ID = "pattern-required-error";

export function PatternFilterPanel({
  values,
  errors,
  onMarketChange,
  onFieldChange,
  onToggleRequired,
  onSubmit,
  isSubmitting,
  isMobileOpen,
  onCloseMobile,
}: PatternFilterPanelProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const isDesktop = useIsDesktopViewport(1024);
  const trapActive = isMobileOpen && !isDesktop;
  useFocusTrap(panelRef, trapActive, onCloseMobile);

  const requiredError = errorFor(errors, "required");
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
        aria-label={trapActive ? copy.pattern.mobileOpenFilterLabel : undefined}
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
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <MarketFilterControl value={values.market} onChange={onMarketChange} />

          <ConditionField
            id={PATTERN_FIELD_IDS.marketCapMin}
            label={copy.pattern.filterMarketCapLabel}
            value={values.marketCapMin}
            onChange={(v) => onFieldChange("marketCapMin", v)}
            suffix={copy.pattern.filterMarketCapSuffix}
            errorMessage={errorFor(errors, "marketCapMin")}
          />

          <ConditionField
            id={PATTERN_FIELD_IDS.volumeMin}
            label={copy.pattern.filterVolumeLabel}
            value={values.volumeMin}
            onChange={(v) => onFieldChange("volumeMin", v)}
            suffix={copy.pattern.filterVolumeSuffix}
            errorMessage={errorFor(errors, "volumeMin")}
          />

          <fieldset className="condition-field-group pattern-required">
            <legend className="condition-field-group__legend">
              {copy.pattern.requiredHeading}
            </legend>
            {PATTERN_CONDITION_IDS.map((id) => {
              const inputId = `pattern-required-${id}`;
              return (
                <label key={id} htmlFor={inputId} className="pattern-required__option">
                  <input
                    id={inputId}
                    type="checkbox"
                    className="pattern-required__checkbox"
                    checked={values.required.includes(id)}
                    onChange={() => onToggleRequired(id)}
                    aria-invalid={requiredError ? true : undefined}
                    aria-describedby={requiredError ? REQUIRED_ERROR_ID : undefined}
                  />
                  <span>{conditionTitle(id)}</span>
                </label>
              );
            })}
            {requiredError && (
              <p id={REQUIRED_ERROR_ID} className="condition-field__error" role="alert">
                {requiredError}
              </p>
            )}
          </fieldset>

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
