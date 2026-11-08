// Summary endpoints (008/FR-2...FR-9) through the shared application client; reject with ApiError.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { ReadOptions } from "../tasks/api";
import type { SummaryFilters } from "./filters";

export type OverviewCounts = components["schemas"]["OverviewCountsOut"];
export type OverviewTaskPage = components["schemas"]["OverviewTaskPage"];
export type OverviewTaskItem = components["schemas"]["OverviewTaskItem"];

export const PAGE_SIZE = 50;

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function getOverview(options: ReadOptions = {}): Promise<OverviewCounts> {
  const { data } = await getAppClient().GET("/api/v1/me/overview", {
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function listOverviewTasks(
  filters: SummaryFilters,
  page: number,
  options: ReadOptions = {},
): Promise<OverviewTaskPage> {
  const query: {
    page: number;
    page_size: number;
    project_id?: string;
    status?: components["schemas"]["TaskStatus"];
    priority?: components["schemas"]["TaskPriority"][];
    due?: components["schemas"]["DuePreset"];
    needs_review?: boolean;
  } = { page, page_size: PAGE_SIZE };
  if (filters.projectId !== null) query.project_id = filters.projectId;
  if (filters.status !== null) query.status = filters.status;
  if (filters.priorities.length > 0) query.priority = [...filters.priorities];
  if (filters.due !== null) query.due = filters.due;
  if (filters.needsReview) query.needs_review = true;
  const { data } = await getAppClient().GET("/api/v1/me/overview/tasks", {
    params: { query },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}
