import type { RefObject } from "react";

/**
 * 04-ux-design.md §4 `ConditionField` — 개별 조건 입력행(최소/최대 또는
 * 단일값). §5-5 "폼 오류 처리": 오류 필드에 `aria-invalid`/`aria-describedby`
 * 연결. placeholder만으로 라벨을 대체하지 않는다(§5-4, `<label>` 명시 연결).
 */
interface ConditionFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  suffix?: string;
  placeholder?: string;
  errorMessage?: string;
  inputRef?: RefObject<HTMLInputElement | null>;
}

export function ConditionField({
  id,
  label,
  value,
  onChange,
  suffix,
  placeholder,
  errorMessage,
  inputRef,
}: ConditionFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div className="condition-field">
      <label htmlFor={id} className="condition-field__label">
        {label}
      </label>
      <div className="condition-field__input-row">
        <input
          ref={inputRef}
          id={id}
          type="number"
          inputMode="decimal"
          className="condition-field__input"
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={errorMessage ? true : undefined}
          aria-describedby={errorMessage ? errorId : undefined}
        />
        {suffix && <span className="condition-field__suffix">{suffix}</span>}
      </div>
      {errorMessage && (
        <p id={errorId} className="condition-field__error" role="alert">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
