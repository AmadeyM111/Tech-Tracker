// Task list and create endpoints (T83). Every call goes through the shared
// application client and rejects with ApiError. `headers` carries the polling
// header (FR-59) when the call comes from a polling tick; user actions pass none.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { Page, PageParams } from "../admin/api";

export type TaskListItem = components["schemas"]["TaskListItem"];
export type TaskDetail = components["schemas"]["TaskDetail"];
export type TaskStatus = components["schemas"]["TaskStatus"];
export type TaskPriority = components["schemas"]["TaskPriority"];

/** Body of the create request: an empty description / due date / assignee is simply not sent. */
export interface TaskCreate {
  title: string;
  priority: TaskPriority;
  description?: string;
  due_date?: string;
  assignee_id?: string;
}

export interface ProjectTasksParams extends PageParams {
  projectId: string;
  assigneeId?: string;
  status?: TaskStatus;
}

export interface ReadOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function listProjectTasks(
  p: ProjectTasksParams,
  options: ReadOptions = {},
): Promise<Page<TaskListItem>> {
  const query: {
    page: number;
    page_size?: number;
    assignee_id?: string;
    status?: TaskStatus;
  } = { page: p.page };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  if (p.assigneeId !== undefined) query.assignee_id = p.assigneeId;
  if (p.status !== undefined) query.status = p.status;
  const { data } = await getAppClient().GET("/api/v1/projects/{project_id}/tasks", {
    params: { path: { project_id: p.projectId }, query },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function listMyTasks(p: PageParams, options: ReadOptions = {}): Promise<Page<TaskListItem>> {
  const query: { page: number; page_size?: number } = { page: p.page };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  const { data } = await getAppClient().GET("/api/v1/me/tasks", {
    params: { query },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function createTask(projectId: string, body: TaskCreate): Promise<TaskDetail> {
  // The schema marks `description` as required only because it has a server default.
  const { data } = await getAppClient().POST("/api/v1/projects/{project_id}/tasks", {
    params: { path: { project_id: projectId } },
    body: body as components["schemas"]["TaskCreate"],
  });
  if (data === undefined) throw invalidBody(201);
  return data;
}

/** Body of the update request: only the keys present are changed; `null` clears a due date / assignee. */
export type TaskUpdate = components["schemas"]["TaskUpdate"];

/** Body of the subtask request: only the title is sent, the server fills in the rest (FR-20). */
export type SubtaskCreate = Pick<TaskCreate, "title"> & Partial<TaskCreate>;

export async function getTask(id: string, options: ReadOptions = {}): Promise<TaskDetail> {
  const { data } = await getAppClient().GET("/api/v1/tasks/{task_id}", {
    params: { path: { task_id: id } },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function updateTask(id: string, body: TaskUpdate): Promise<TaskDetail> {
  const { data } = await getAppClient().PATCH("/api/v1/tasks/{task_id}", {
    params: { path: { task_id: id } },
    body,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function deleteTask(id: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/tasks/{task_id}", {
    params: { path: { task_id: id } },
  });
}

export async function createSubtask(id: string, body: SubtaskCreate): Promise<TaskDetail> {
  // The schema marks `description` / `priority` as required only because they have server defaults.
  const { data } = await getAppClient().POST("/api/v1/tasks/{task_id}/subtasks", {
    params: { path: { task_id: id } },
    body: body as components["schemas"]["TaskCreate"],
  });
  if (data === undefined) throw invalidBody(201);
  return data;
}
