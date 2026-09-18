import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §4 `SearchInput` — 종목 검색 입력(자동완성 아님, 부모가
 * 디바운스 처리, §2-3). 콤보박스/리스트박스가 아닌 일반 텍스트 입력이므로
 * `role="combobox"` 등 복합 위젯 ARIA 패턴이나 포커스 트랩이 필요 없다
 * (`unit-09-note.md` 접근성 사전 점검 참조).
 */
interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
}

export function SearchInput({ value, onChange }: SearchInputProps) {
  return (
    <div className="search-input">
      <label htmlFor="stock-search-input" className="search-input__label">
        {copy.stockSearch.inputLabel}
      </label>
      <input
        id="stock-search-input"
        type="search"
        className="search-input__field"
        placeholder={copy.stockSearch.inputPlaceholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
