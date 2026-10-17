import { t } from "../i18n";

export interface PaginationProps {
  page: number;
  hasNext: boolean;
  /**
   * True while a page is loading: clicks are ignored (no double navigation); the
   * buttons stay focusable and get aria-disabled, so the focus is not lost.
   */
  busy: boolean;
  onPage: (page: number) => void;
}

export function Pagination({ page, hasNext, busy, onPage }: PaginationProps) {
  return (
    <nav aria-label={t("admin.pagination_label")} className="ui-pagination">
      <button
        type="button"
        data-action="prev-page"
        disabled={page <= 1}
        aria-disabled={busy ? true : undefined}
        onClick={() => {
          if (!busy) onPage(page - 1);
        }}
      >
        {t("admin.prev_page")}
      </button>
      <span>{t("admin.page_label", { page })}</span>
      <button
        type="button"
        data-action="next-page"
        disabled={!hasNext}
        aria-disabled={busy ? true : undefined}
        onClick={() => {
          if (!busy) onPage(page + 1);
        }}
      >
        {t("admin.next_page")}
      </button>
    </nav>
  );
}
