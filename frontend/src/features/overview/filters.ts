// Summary filters (008/FR-4, FR-6, FR-7): status and due preset are single choice, priority is
// multi-select (Q-7). Due range «с / по» (024): excludes the preset (Q-1), either bound alone is
// allowed (Q-2). Pure helpers, no requests.
import type { components } from "../../shared/api/schema";

export type TaskStatus = components["schemas"]["TaskStatus"];
export type TaskPriority = components["schemas"]["TaskPriority"];
export type DuePreset = components["schemas"]["DuePreset"];

export const STATUSES: readonly TaskStatus[] = ["todo", "in_progress", "review", "done"];
export const PRIORITIES: readonly TaskPriority[] = ["low", "medium", "high"];
export const DUE_PRESETS: readonly DuePreset[] = ["overdue", "today", "tomorrow", "week", "none"];

export interface SummaryFilters {
  projectId: string | null;
  status: TaskStatus | null;
  priorities: readonly TaskPriority[];
  due: DuePreset | null;
  /** Calendar dates YYYY-MM-DD (Moscow), inclusive; null = bound not set (024). */
  dateFrom: string | null;
  dateTo: string | null;
  needsReview: boolean;
}

export const NO_FILTERS: SummaryFilters = {
  projectId: null,
  status: null,
  priorities: [],
  due: null,
  dateFrom: null,
  dateTo: null,
  needsReview: false,
};

/** Tile identifiers: "needs_review", "total" or a status (FR-2, FR-3). */
export type Tile = "needs_review" | "total" | TaskStatus;

/** A tile click opens the list with its filter; other filters stay (FR-4). */
export function applyTile(filters: SummaryFilters, tile: Tile): SummaryFilters {
  if (tile === "needs_review") return { ...filters, status: null, needsReview: true };
  if (tile === "total") return { ...filters, status: null, needsReview: false };
  return { ...filters, status: tile, needsReview: false };
}

/** The tile that matches the current filters, for aria-pressed. */
export function activeTile(filters: SummaryFilters): Tile {
  if (filters.needsReview) return "needs_review";
  return filters.status ?? "total";
}

/** Same priority twice is impossible; the order is the canonical one (stable query keys). */
export function togglePriority(filters: SummaryFilters, p: TaskPriority): SummaryFilters {
  const on = filters.priorities.includes(p);
  const next = PRIORITIES.filter((x) => (x === p ? !on : filters.priorities.includes(x)));
  return { ...filters, priorities: next };
}

/**
 * A pressed preset is released by the second click (single choice, FR-7). Choosing a preset
 * clears both range fields (024 FR-5, Q-1).
 */
export function toggleDue(filters: SummaryFilters, d: DuePreset): SummaryFilters {
  return { ...filters, due: filters.due === d ? null : d, dateFrom: null, dateTo: null };
}

export type RangeBound = "from" | "to";

/** Editing a range field releases the preset (024 FR-5, Q-1); an empty value clears the bound. */
export function setRangeBound(filters: SummaryFilters, bound: RangeBound, value: string): SummaryFilters {
  const next = value === "" ? null : value;
  return bound === "from"
    ? { ...filters, due: null, dateFrom: next }
    : { ...filters, due: null, dateTo: next };
}

/** «с» позже «по» (024 FR-6, Q-4): the request is not sent, the list keeps its previous state. */
export function rangeInvalid(filters: SummaryFilters): boolean {
  return filters.dateFrom !== null && filters.dateTo !== null && filters.dateFrom > filters.dateTo;
}
