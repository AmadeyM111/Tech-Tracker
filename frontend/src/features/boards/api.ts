// Kanban board endpoints (T86). Every call goes through the shared application client and
// rejects with ApiError. `headers` carries the polling header (FR-59) on a polling tick.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type Board = components["schemas"]["Board"];
export type BoardColumn = components["schemas"]["BoardColumn"];
export type BoardCard = components["schemas"]["BoardCard"];
export type TaskMove = components["schemas"]["TaskMove"];

export interface ReadOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function getBoard(projectId: string, options: ReadOptions = {}): Promise<Board> {
  const { data } = await getAppClient().GET("/api/v1/projects/{project_id}/board", {
    params: { path: { project_id: projectId } },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw new ApiError(200, INVALID_RESPONSE, "invalid response body");
  return data;
}

/** Moves a card to a column place given by its neighbours (204, no body). */
export async function moveTask(taskId: string, body: TaskMove): Promise<void> {
  await getAppClient().POST("/api/v1/tasks/{task_id}/move", {
    params: { path: { task_id: taskId } },
    body,
  });
}

/** Creates a task from a board column: only the title is sent, the server fills in the rest (FR-18a). */
export async function createTask(projectId: string, title: string): Promise<{ id: string }> {
  const { data } = await getAppClient().POST("/api/v1/projects/{project_id}/tasks", {
    params: { path: { project_id: projectId } },
    // The schema marks `description` / `priority` as required only because they have server defaults.
    body: { title } as components["schemas"]["TaskCreate"],
  });
  if (data === undefined) throw new ApiError(201, INVALID_RESPONSE, "invalid response body");
  return data;
}
