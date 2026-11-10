// The /summary screen (008): tiles, filters, task list with the "hot" mark, empty state.
// FR-1...FR-12; mockup Shared/Design/gtrack-summary (approved 2026-11-08). Polling every 15 s (FR-12).
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { usePolledQuery } from "../../shared/api/polling";
import { errorMessage, t } from "../../shared/i18n";
import { ErrorAlert } from "../../shared/ui/ErrorAlert";
import { Pagination } from "../../shared/ui/Pagination";
import { downloadOverviewCsv, getOverview, listOverviewProjects, listOverviewTasks, type OverviewCounts, type OverviewTaskItem } from "./api";
import {
  DUE_PRESETS,
  NO_FILTERS,
  PRIORITIES,
  STATUSES,
  activeTile,
  applyTile,
  toggleDue,
  togglePriority,
  type SummaryFilters,
  type Tile,
} from "./filters";
import "./summary.css";

const TILES: readonly Tile[] = ["needs_review", "total", ...STATUSES];
const YMD = /^(\d{4})-(\d{2})-(\d{2})/;

/** A calendar date is re-ordered as text: no Date object, so no time zone (ADR-0007). */
function formatDate(value: string): string {
  const m = YMD.exec(value);
  return m === null ? value : `${m[3]}.${m[2]}.${m[1]}`;
}

/** Overdue for the mark: a past date, not finished; the server's "hot" carries the same today. */
function isOverdue(task: OverviewTaskItem, today: string): boolean {
  return task.due_date !== null && task.due_date < today && task.status !== "done";
}

/** Today in Europe/Moscow as YYYY-MM-DD (ADR-0007). */
function moscowToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(new Date());
}

function codeOf(e: unknown): string {
  const code = (e as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : "unknown";
}

function countOf(counts: OverviewCounts | undefined, tile: Tile): number | null {
  if (counts === undefined) return null;
  return tile === "needs_review" ? counts.needs_review : counts[tile];
}

function Tiles(props: { counts: OverviewCounts | undefined; filters: SummaryFilters; onTile: (t: Tile) => void }) {
  const active = activeTile(props.filters);
  return (
    <ul className="sum-tiles" aria-label={t("summary.tiles_label")}>
      {TILES.map((tile) => (
        <li key={tile}>
          <button
            type="button"
            data-tile={tile}
            className={tile === "needs_review" ? "sum-tile sum-tile--review" : "sum-tile"}
            aria-pressed={active === tile}
            onClick={() => props.onTile(tile)}
          >
            <span className="sum-label">{t(`summary.tile.${tile}`)}</span>
            <span className="sum-count">{countOf(props.counts, tile) ?? "—"}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function Filters(props: { filters: SummaryFilters; onChange: (f: SummaryFilters) => void }) {
  const { filters, onChange } = props;
  const baseId = useId();
  const projects = useQuery({
    queryKey: ["overview", "projects"],
    queryFn: () => listOverviewProjects(),
    staleTime: 60_000,
  });
  return (
    <form className="sum-filters" aria-label={t("summary.filters_label")} onSubmit={(e) => e.preventDefault()}>
      <div className="sum-filter">
        <label className="sum-flabel" htmlFor={`${baseId}-project`}>
          {t("summary.filter_project")}
        </label>
        <select
          id={`${baseId}-project`}
          name="project_id"
          value={filters.projectId ?? ""}
          onChange={(e) => onChange({ ...filters, projectId: e.target.value === "" ? null : e.target.value })}
        >
          <option value="">{t("summary.filter_project_all")}</option>
          {(projects.data?.items ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="sum-filter">
        <label className="sum-flabel" htmlFor={`${baseId}-status`}>
          {t("summary.filter_status")}
        </label>
        <select
          id={`${baseId}-status`}
          name="status"
          value={filters.status ?? ""}
          onChange={(e) =>
            onChange({
              ...filters,
              needsReview: false,
              status: e.target.value === "" ? null : (e.target.value as SummaryFilters["status"]),
            })
          }
        >
          <option value="">{t("summary.filter_status_all")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`summary.tile.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <fieldset className="sum-filter">
        <legend className="sum-flabel">{t("summary.filter_priority")}</legend>
        <div className="sum-checks">
          {PRIORITIES.map((p) => (
            <label key={p}>
              <input
                type="checkbox"
                name="priority"
                value={p}
                checked={filters.priorities.includes(p)}
                onChange={() => onChange(togglePriority(filters, p))}
              />
              {t(`tasks.priority.${p}`)}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="sum-filter sum-filter--wide">
        <legend className="sum-flabel">{t("summary.filter_due")}</legend>
        <div className="sum-presets">
          {DUE_PRESETS.map((d) => (
            <button
              key={d}
              type="button"
              data-due={d}
              aria-pressed={filters.due === d}
              onClick={() => onChange(toggleDue(filters, d))}
            >
              {t(`summary.due.${d}`)}
            </button>
          ))}
        </div>
      </fieldset>
    </form>
  );
}

function Due({ task, today }: { task: OverviewTaskItem; today: string }) {
  if (task.due_date === null) return <>{t("tasks.due_none")}</>;
  return (
    <>
      <time dateTime={task.due_date}>{formatDate(task.due_date)}</time>
      {isOverdue(task, today) ? ` · ${t("summary.overdue")}` : null}
    </>
  );
}

function Hot({ task }: { task: OverviewTaskItem }) {
  return task.hot ? <span className="sum-burn-tag">{t("summary.hot")}</span> : null;
}

function TaskRows({ items, today }: { items: OverviewTaskItem[]; today: string }) {
  return (
    <>
      <div className="sum-table-wrap">
        <table className="ui-table sum-table" aria-label={t("summary.title")}>
          <thead>
            <tr>
              <th scope="col">{t("tasks.col_project")}</th>
              <th scope="col">{t("tasks.col_title")}</th>
              <th scope="col">{t("tasks.col_status")}</th>
              <th scope="col">{t("tasks.col_priority")}</th>
              <th scope="col">{t("tasks.col_assignee")}</th>
              <th scope="col">{t("tasks.col_due")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((task) => (
              <tr key={task.id} data-task-id={task.id} data-hot={task.hot}>
                <td data-field="project">{task.project.name}</td>
                <td data-field="title">
                  <a href={`/tasks/${task.id}`}>{task.title}</a>
                  <Hot task={task} />
                </td>
                <td data-field="status">{t(`summary.tile.${task.status}`)}</td>
                <td data-field="priority">{t(`tasks.priority.${task.priority}`)}</td>
                <td data-field="assignee">{task.assignee?.login ?? t("tasks.assignee_none")}</td>
                <td data-field="due_date" data-overdue={isOverdue(task, today)}>
                  <Due task={task} today={today} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="sum-cards" aria-label={t("summary.title")}>
        {items.map((task) => (
          <li key={task.id} data-card-id={task.id}>
            <a className="c-title" href={`/tasks/${task.id}`}>
              {task.title}
            </a>
            <Hot task={task} />
            <span className="c-meta">
              {task.project.name} · {t(`summary.tile.${task.status}`)} · {t(`tasks.priority.${task.priority}`)}
            </span>
            <span className="c-meta" data-overdue={isOverdue(task, today)}>
              {task.assignee?.login ?? t("tasks.assignee_none")} · <Due task={task} today={today} />
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Saves a blob under a file name through a temporary link (no navigation, no new tab). */
function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function SummaryPage({ canExport = false }: { canExport?: boolean }) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [filters, setFilters] = useState<SummaryFilters>(NO_FILTERS);
  const [page, setPage] = useState(1);
  const change = (next: SummaryFilters) => {
    setFilters(next);
    setPage(1);
  };
  const counts = usePolledQuery({
    queryKey: ["overview", "counts"],
    queryFn: ({ headers, signal }) => getOverview({ headers, signal }),
  });
  const list = usePolledQuery({
    queryKey: ["overview", "tasks", { filters, page }],
    queryFn: ({ headers, signal }) => listOverviewTasks(filters, page, { headers, signal }),
  });
  const onExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const file = await downloadOverviewCsv(filters);
      saveFile(file.blob, file.filename);
    } catch (e) {
      setExportError(errorMessage(codeOf(e)));
    } finally {
      setExporting(false);
    }
  };
  const today = moscowToday();
  const empty = counts.data?.total === 0;
  const items = list.data?.items;
  return (
    <section className="ui-wide">
      <h1>{t("summary.title")}</h1>
      <ErrorAlert
        message={
          exportError ??
          (counts.isError ? errorMessage(codeOf(counts.error)) : list.isError ? errorMessage(codeOf(list.error)) : null)
        }
      />
      <Tiles counts={counts.data} filters={filters} onTile={(tile) => change(applyTile(filters, tile))} />
      {empty ? (
        <div className="sum-block" data-role="empty">
          <p>{t("summary.empty")}</p>
        </div>
      ) : (
        <>
          <Filters filters={filters} onChange={change} />
          {items === undefined ? (
            list.isPending ? (
              <p role="status">{t("admin.loading")}</p>
            ) : null
          ) : (
            <>
              <div className="sum-count-row">
                <p className="sum-count-note" role="status">
                  {t("summary.shown", { shown: items.length, total: list.data?.total ?? 0 })}
                </p>
                {canExport ? (
                  <div className="sum-csv">
                    <span id="sum-csv-note" className="sum-csv-note">
                      {t("summary.csv.note")}
                    </span>
                    <button
                      type="button"
                      className="ui-btn-secondary sum-csv-btn"
                      data-action="export-csv"
                      aria-describedby="sum-csv-note"
                      disabled={exporting}
                      onClick={() => void onExport()}
                    >
                      {exporting ? t("summary.csv.preparing") : t("summary.csv.button")}
                    </button>
                    {exporting ? (
                      <span role="status" className="sum-csv-note">
                        {t("summary.csv.preparing")}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
              {items.length > 0 ? <TaskRows items={items} today={today} /> : null}
              {page > 1 || (list.data?.has_next ?? false) ? (
                <Pagination page={page} hasNext={list.data?.has_next ?? false} busy={list.isPending} onPage={setPage} />
              ) : null}
            </>
          )}
        </>
      )}
    </section>
  );
}
