import { t } from "../i18n";

export interface PaginationProps {
  page: number;
  hasNext: boolean;
  /** True while a page is loading: the buttons are off, no double navigation. */
  busy: boolean;
  onPage: (page: number) => void;
}

export function Pagination({ page, hasNext, busy, onPage }: PaginationProps) {
  return (
    <nav aria-label={t("admin.pagination_label")} className="ui-pagination">
      <button
        type="button"
        data-action="prev-page"
        disabled={busy || page <= 1}
        onClick={() => onPage(page - 1)}
      >
        {t("admin.prev_page")}
      </button>
      <span>{t("admin.page_label", { page })}</span>
      <button
        type="button"
        data-action="next-page"
        disabled={busy || !hasNext}
        onClick={() => onPage(page + 1)}
      >
        {t("admin.next_page")}
      </button>
    </nav>
  );
}
