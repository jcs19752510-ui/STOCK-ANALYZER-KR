import copy from "@/content/copy.ko.json";

/**
 * 04-ux-design.md §2-2/§4 `Pagination` — "총 N건 중 1–50건" + 다음/이전
 * (`page_size`는 고정 50, 사용자가 조절하는 UI 없음 — MVP 단순화).
 */
interface PaginationProps {
  page: number;
  pageSize: number;
  totalCount: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, pageSize, totalCount, onPageChange }: PaginationProps) {
  const from = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, totalCount);
  const hasPrev = page > 1;
  const hasNext = to < totalCount;

  return (
    <nav className="pagination" aria-label="페이지 이동">
      <p className="pagination__summary" aria-live="polite">
        총 {totalCount}건 중 {from}–{to}건
      </p>
      <div className="pagination__controls">
        <button
          type="button"
          className="pagination__button"
          disabled={!hasPrev}
          onClick={() => onPageChange(page - 1)}
        >
          {copy.screener.paginationPrev}
        </button>
        <button
          type="button"
          className="pagination__button"
          disabled={!hasNext}
          onClick={() => onPageChange(page + 1)}
        >
          {copy.screener.paginationNext}
        </button>
      </div>
    </nav>
  );
}
