// Comment endpoints (T85). Every call goes through the shared application client and
// rejects with ApiError. `headers` carries the polling header (FR-59) on polling ticks.
import { ApiError, INVALID_RESPONSE, getAppClient } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import type { Page, PageParams } from "../admin/api";

export type Comment = components["schemas"]["Comment"];

export interface ReadOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function invalidBody(status: number): ApiError {
  return new ApiError(status, INVALID_RESPONSE, "invalid response body");
}

export async function listComments(
  taskId: string,
  p: PageParams,
  options: ReadOptions = {},
): Promise<Page<Comment>> {
  const query: { page: number; page_size?: number } = { page: p.page };
  if (p.pageSize !== undefined) query.page_size = p.pageSize;
  const { data } = await getAppClient().GET("/api/v1/tasks/{task_id}/comments", {
    params: { path: { task_id: taskId }, query },
    headers: options.headers,
    signal: options.signal,
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function createComment(taskId: string, body: string): Promise<Comment> {
  const { data } = await getAppClient().POST("/api/v1/tasks/{task_id}/comments", {
    params: { path: { task_id: taskId } },
    body: { body },
  });
  if (data === undefined) throw invalidBody(201);
  return data;
}

export async function updateComment(id: string, body: string): Promise<Comment> {
  const { data } = await getAppClient().PATCH("/api/v1/comments/{comment_id}", {
    params: { path: { comment_id: id } },
    body: { body },
  });
  if (data === undefined) throw invalidBody(200);
  return data;
}

export async function deleteComment(id: string): Promise<void> {
  await getAppClient().DELETE("/api/v1/comments/{comment_id}", {
    params: { path: { comment_id: id } },
  });
}
